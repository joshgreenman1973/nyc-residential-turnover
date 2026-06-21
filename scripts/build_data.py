#!/usr/bin/env python3
"""
Build NYC residential-turnover data: pull ACS 5-year tract estimates,
aggregate to 2020 Neighborhood Tabulation Areas (NTAs), compute turnover
metrics, and merge into shoreline-clipped NTA geometry.

Sources
-------
- U.S. Census Bureau ACS 5-year (2020-2024), tract level
    B25038  Tenure by Year Householder Moved Into Unit  (primary)
    B07003  Geographic Mobility in the Past Year by Sex (secondary / annual churn)
- NYC DCP 2020 Census Tract -> NTA equivalency  (Socrata hm78-6dwm)
- NYC DCP 2020 NTA boundaries, shoreline-clipped (Socrata 9nt8-h7nd)

Output: docs/data.geojson  (one feature per residential NTA, metrics in properties)
        docs/meta.json      (citywide context + generation metadata)
"""
import json, sys, os, math, urllib.request, urllib.parse

KEY = os.environ.get("CENSUS_API_KEY")
if not KEY:
    sys.exit("Set CENSUS_API_KEY (free key from https://api.census.gov/data/key_signup.html)")
VINTAGE = "2024"          # ACS 5-year endpoint year (covers 2020-2024)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(HERE, "docs")
COUNTIES = {  # FIPS -> borough
    "005": "Bronx", "047": "Brooklyn", "061": "Manhattan",
    "081": "Queens", "085": "Staten Island",
}

# ACS variables we need (estimate E + margin M)
B25038 = {
    "tot": "001", "own": "002", "own_2023": "003", "own_2020_22": "004",
    "rent": "009", "rent_2023": "010", "rent_2020_22": "011",
}
B07003 = {"pop1yr": "001", "same_house": "004"}

def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "nyc-turnover/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)

def acs_call(table, codes, county):
    cols = []
    for c in codes.values():
        cols += [f"{table}_{c}E", f"{table}_{c}M"]
    get = ",".join(["NAME"] + cols)
    url = (f"https://api.census.gov/data/{VINTAGE}/acs/acs5?get={get}"
           f"&for=tract:*&in=state:36%20county:{county}&key={KEY}")
    rows = fetch_json(url)
    head = rows[0]
    out = {}
    for row in rows[1:]:
        rec = dict(zip(head, row))
        geoid = rec["state"] + rec["county"] + rec["tract"]
        out[geoid] = rec
    return out

def num(x):
    """ACS estimates: negatives / None are jam/missing -> 0."""
    try:
        v = float(x)
        return v if v >= 0 else 0.0
    except (TypeError, ValueError):
        return 0.0

def moe(x):
    """Margin of error; ACS uses negative codes for 'not applicable'. Treat as 0."""
    try:
        v = float(x)
        return v if v >= 0 else 0.0
    except (TypeError, ValueError):
        return 0.0

def main():
    os.makedirs(DOCS, exist_ok=True)

    # 1. crosswalk: geoid -> nta
    print("Fetching tract->NTA crosswalk...", file=sys.stderr)
    xwalk = {}
    url = ("https://data.cityofnewyork.us/resource/hm78-6dwm.json"
           "?$select=geoid,ntacode,ntatype,ntaname,boroname&$limit=5000")
    for r in fetch_json(url):
        xwalk[r["geoid"]] = r

    # 2. ACS data per county, both tables
    print("Fetching ACS tract estimates...", file=sys.stderr)
    acs = {}
    for fips in COUNTIES:
        a = acs_call("B25038", B25038, fips)
        b = acs_call("B07003", B07003, fips)
        for g, rec in a.items():
            rec.update(b.get(g, {}))
            acs[g] = rec

    # 3. aggregate tracts -> NTA
    ntas = {}
    unmatched = 0
    for geoid, rec in acs.items():
        x = xwalk.get(geoid)
        if not x:
            unmatched += 1
            continue
        code = x["ntacode"]
        n = ntas.setdefault(code, {
            "nta": code, "name": x["ntaname"], "boro": x.get("boroname", ""),
            "ntatype": x["ntatype"],
            # estimate sums
            "tot": 0.0, "own": 0.0, "own_rec": 0.0,
            "rent": 0.0, "rent_rec": 0.0,
            "pop1yr": 0.0, "same_house": 0.0,
            # margin sum-of-squares accumulators
            "m_tot": 0.0, "m_own": 0.0, "m_own_rec": 0.0,
            "m_rent": 0.0, "m_rent_rec": 0.0,
            "m_pop1yr": 0.0, "m_same": 0.0,
        })
        e = lambda c: num(rec.get(f"B25038_{c}E"))
        m = lambda c: moe(rec.get(f"B25038_{c}M"))
        n["tot"] += e("001"); n["m_tot"] += m("001")**2
        n["own"] += e("002"); n["m_own"] += m("002")**2
        n["rent"] += e("009"); n["m_rent"] += m("009")**2
        own_rec = e("003") + e("004")
        rent_rec = e("010") + e("011")
        n["own_rec"] += own_rec
        n["rent_rec"] += rent_rec
        n["m_own_rec"] += m("003")**2 + m("004")**2
        n["m_rent_rec"] += m("010")**2 + m("011")**2
        n["pop1yr"] += num(rec.get("B07003_001E")); n["m_pop1yr"] += moe(rec.get("B07003_001M"))**2
        n["same_house"] += num(rec.get("B07003_004E")); n["m_same"] += moe(rec.get("B07003_004M"))**2

    print(f"  tracts matched: {len(acs)-unmatched}, unmatched: {unmatched}", file=sys.stderr)

    # 4. compute metrics per NTA
    def ratio_moe(num_e, num_m2, den_e, den_m2):
        """ACS proportion MOE in percentage points. num_m2/den_m2 are sums of squares."""
        if den_e <= 0:
            return None
        p = num_e / den_e
        num_m = math.sqrt(num_m2)
        den_m = math.sqrt(den_m2)
        under = num_m**2 - (p**2) * den_m**2
        if under < 0:  # fall back to ratio MOE formula
            under = num_m**2 + (p**2) * den_m**2
        return round(100.0 * math.sqrt(under) / den_e, 1)

    metrics = {}
    for code, n in ntas.items():
        if n["ntatype"] != "0":   # residential only
            continue
        if n["tot"] < 1:
            continue
        all_rec = n["own_rec"] + n["rent_rec"]
        m_all_rec2 = n["m_own_rec"] + n["m_rent_rec"]
        moved = max(0.0, n["pop1yr"] - n["same_house"])
        # moved-in-past-year MOE: derived = pop - same_house -> combine in quadrature
        m_moved2 = n["m_pop1yr"] + n["m_same"]

        rec = {
            "nta": code, "name": n["name"], "boro": n["boro"],
            "households": int(round(n["tot"])),
            "owner_hh": int(round(n["own"])),
            "renter_hh": int(round(n["rent"])),
            # turnover = share who moved in 2020 or later (~last 5 yrs)
            "turnover_all": round(100.0 * all_rec / n["tot"], 1) if n["tot"] else None,
            "turnover_own": round(100.0 * n["own_rec"] / n["own"], 1) if n["own"] else None,
            "turnover_rent": round(100.0 * n["rent_rec"] / n["rent"], 1) if n["rent"] else None,
            # annual churn = share who lived elsewhere 1 year ago
            "churn_annual": round(100.0 * moved / n["pop1yr"], 1) if n["pop1yr"] else None,
            "owner_share": round(100.0 * n["own"] / n["tot"], 1) if n["tot"] else None,
            # margins of error (pct points)
            "moe_all": ratio_moe(all_rec, m_all_rec2, n["tot"], n["m_tot"]),
            "moe_own": ratio_moe(n["own_rec"], n["m_own_rec"], n["own"], n["m_own"]),
            "moe_rent": ratio_moe(n["rent_rec"], n["m_rent_rec"], n["rent"], n["m_rent"]),
            "moe_churn": ratio_moe(moved, m_moved2, n["pop1yr"], n["m_pop1yr"]),
        }
        metrics[code] = rec

    print(f"  residential NTAs with metrics: {len(metrics)}", file=sys.stderr)

    # 5. NTA geometry (shoreline-clipped), merge metrics
    print("Fetching NTA geometry...", file=sys.stderr)
    gj = fetch_json("https://data.cityofnewyork.us/resource/9nt8-h7nd.geojson?$limit=2000")
    feats = []
    for f in gj["features"]:
        p = f.get("properties", {})
        code = p.get("nta2020")
        mrec = metrics.get(code)
        if not mrec:
            continue   # drop non-residential / no-data polygons
        f["properties"] = mrec
        feats.append(f)
    out = {"type": "FeatureCollection", "features": feats}
    with open(os.path.join(DOCS, "data.geojson"), "w") as fh:
        json.dump(out, fh)
    print(f"  geometry features written: {len(feats)}", file=sys.stderr)

    # 6. citywide context + meta
    tot_hh = sum(n["tot"] for n in ntas.values())
    tot_rec = sum(n["own_rec"] + n["rent_rec"] for n in ntas.values())
    tot_own = sum(n["own"] for n in ntas.values())
    tot_own_rec = sum(n["own_rec"] for n in ntas.values())
    tot_rent = sum(n["rent"] for n in ntas.values())
    tot_rent_rec = sum(n["rent_rec"] for n in ntas.values())
    tot_pop1yr = sum(n["pop1yr"] for n in ntas.values())
    tot_same = sum(n["same_house"] for n in ntas.values())
    vals = [m for m in metrics.values() if m["turnover_all"] is not None]
    top = sorted(vals, key=lambda x: -x["turnover_all"])[:10]
    bot = sorted(vals, key=lambda x: x["turnover_all"])[:10]
    meta = {
        "vintage": "ACS 2020-2024 5-year estimates",
        "generated_for": VINTAGE,
        "n_neighborhoods": len(metrics),
        "city": {
            "turnover_all": round(100*tot_rec/tot_hh, 1),
            "turnover_own": round(100*tot_own_rec/tot_own, 1),
            "turnover_rent": round(100*tot_rent_rec/tot_rent, 1),
            "churn_annual": round(100*(tot_pop1yr-tot_same)/tot_pop1yr, 1),
            "households": int(round(tot_hh)),
        },
        "top10": [{"name": t["name"], "boro": t["boro"], "v": t["turnover_all"]} for t in top],
        "bottom10": [{"name": t["name"], "boro": t["boro"], "v": t["turnover_all"]} for t in bot],
    }
    with open(os.path.join(DOCS, "meta.json"), "w") as fh:
        json.dump(meta, fh, indent=2)
    print("Done. Citywide turnover (moved in 2020+): "
          f"all {meta['city']['turnover_all']}%, "
          f"owners {meta['city']['turnover_own']}%, "
          f"renters {meta['city']['turnover_rent']}%", file=sys.stderr)

if __name__ == "__main__":
    main()
