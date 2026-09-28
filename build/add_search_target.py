#!/usr/bin/env python3
"""Add the `search_impressions_decile` ML target to the Audiala Places dataset.

The target answers one question per place: how often did its audiala.com
guide pages appear in Google Web search results (impressions), relative to
every other place in the dataset? It is derived from Audiala's private Google Search Console bulk
export and published only as a relative decile, never as raw volumes.

Definition
----------
- Window: a fixed date range of Google Search Console *Web* impressions
  (the range is recorded in the README and in `--window-label`).
- Per place: impressions summed over all of its `url_<lang>` pages, after
  folding `#fragment` URLs and slug redirects into the canonical page (the
  same canonicalization as audiala-hugo/scripts/ctr_deficit_panel.py).
- `search_impressions_decile`: 0 when the place had no impressions in the window;
  otherwise 1 (lowest) to 10 (highest), by rank among places with at least
  one impression. Ties are broken by rank order, so deciles are equal-sized.

Clicks, CTR and ranking position are deliberately not published.

Input GSC JSON: {"<lang>/<country>/<city>/<place>": {"impressions": int, ...}}
as produced by `fetch_bq_pages` + `canonicalize_pages` in the SEO panel script.

Usage:
    python3 build/add_search_target.py --gsc-json PATH --window-label 2026-07-03..2026-09-25
"""
import argparse
import csv
import json
import unicodedata
from pathlib import Path
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
LANGUAGES = ["en", "fr", "de", "es", "pt", "it", "hi", "zh", "cs", "ja", "ru"]
SITE_BASE = "https://audiala.com/"
TARGET = "search_impressions_decile"
LEGACY_TARGETS = {"search_demand_decile"}


def url_key(url: str) -> str:
    path = url[len(SITE_BASE):] if url.startswith(SITE_BASE) else url
    return unicodedata.normalize("NFC", unquote(path)).strip("/")


def gsc_key(path: str) -> str:
    return unicodedata.normalize("NFC", unquote(path)).strip("/")


def deciles(values: dict[str, int]) -> dict[str, int]:
    """0 for zero impressions; 1..10 equal-sized rank buckets among the rest."""
    out = {k: 0 for k, v in values.items() if v <= 0}
    ranked = sorted((k for k, v in values.items() if v > 0), key=lambda k: values[k])
    n = len(ranked)
    for i, k in enumerate(ranked):
        out[k] = min(10, i * 10 // n + 1)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--gsc-json", required=True)
    ap.add_argument("--window-label", required=True)
    ap.add_argument("--data-dir", default=str(REPO_ROOT / "data"))
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    gsc = {gsc_key(k): int(v.get("impressions") or 0)
           for k, v in json.load(open(args.gsc_json, encoding="utf-8")).items()}

    csv_path = data_dir / "audiala-places.csv"
    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields = [c for c in reader.fieldnames if c != TARGET and c not in LEGACY_TARGETS]
        rows = list(reader)

    demand = {}
    matched_pages = 0
    for r in rows:
        total = 0
        for lang in LANGUAGES:
            u = r.get(f"url_{lang}")
            if u:
                imp = gsc.get(url_key(u), 0)
                matched_pages += imp > 0
                total += imp
        demand[r["wikidata_id"]] = total
    dec = deciles(demand)

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields + [TARGET])
        w.writeheader()
        for r in rows:
            r[TARGET] = dec[r["wikidata_id"]]
            w.writerow({k: r[k] for k in fields + [TARGET]})

    geo_path = data_dir / "audiala-places.geojson"
    geo = json.load(open(geo_path, encoding="utf-8"))
    for feat in geo["features"]:
        qid = feat["properties"]["wikidata_id"]
        for legacy in LEGACY_TARGETS:
            feat["properties"].pop(legacy, None)
        feat["properties"][TARGET] = dec.get(qid, 0)
    with open(geo_path, "w", encoding="utf-8") as f:
        json.dump(geo, f, ensure_ascii=False, separators=(",", ":"))

    nonzero = sum(1 for v in demand.values() if v > 0)
    print(f"window {args.window_label}: {len(rows)} places, {nonzero} with impressions "
          f"({nonzero / len(rows):.1%}), {matched_pages} language pages matched")
    counts = {d: sum(1 for v in dec.values() if v == d) for d in range(11)}
    print("decile counts:", counts)


if __name__ == "__main__":
    main()
