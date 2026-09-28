---
license: cc-by-4.0
pretty_name: Audiala Places — Curated Multilingual Travel POIs
language:
  - en
  - fr
  - de
  - es
  - pt
  - it
  - hi
  - zh
  - cs
  - ja
  - ru
tags:
  - travel
  - tourism
  - poi
  - wikidata
  - multilingual
  - geospatial
  - tabular
  - benchmark
task_categories:
  - tabular-classification
  - tabular-regression
size_categories:
  - 10K<n<100K
configs:
  - config_name: default
    data_files:
      - split: train
        path: data/audiala-places.csv
---

# Audiala Places — Curated Multilingual Travel POIs

33,289 travel points of interest across 93 countries, each with a Wikidata
QID, WGS84 coordinates, names in 11 languages, a type/category slug, fame
signals (Wikidata PageRank + sitelink count), a link to a published travel
guide on [audiala.com](https://audiala.com) in each of the 11 languages, and
an ML target: `search_impressions_decile`, how visible each place's guides
are in Google Search.

**The curation filter is editorial:** a place is included if and only if
Audiala has published a full travel guide for it. This dataset is
deliberately **not exhaustive** — it is a quality-bar dataset, not an
"every POI in the world" dump.

## Dataset structure

One row per Wikidata entity. Provided as CSV (flat columns) and GeoJSON
(`FeatureCollection` of `Point` features with the same properties).

| Field | Type | Description |
|---|---|---|
| `wikidata_id` | string | Wikidata QID, primary key |
| `name_en` … `name_ru` | string | Name in en, fr, de, es, pt, it, hi, zh, cs, ja, ru (native script; English fallback for the ~0.2 % without a translation) |
| `latitude`, `longitude` | float | WGS84 decimal degrees |
| `country_iso2` | string | ISO 3166-1 alpha-2 |
| `country_en` | string | English country name |
| `city_en` | string | English city name |
| `category` | string | One of 50 type slugs (`castle`, `museum`, `church`, `bridge`, `square`, …), derived from Wikidata `P31/P279*` with name-pattern fallback |
| `article_tier` | string | `structured` (rich guide format) or `legacy` |
| `wikidata_pagerank` | float | Wikidata PageRank (danker all-wiki run); empty for ~17 % of rows |
| `sitelinks` | int | Count of Wikimedia project pages linked to the entity |
| `url_en` … `url_ru` | string | Canonical audiala.com guide URL per language (native-script paths for hi/zh/ja/ru) |
| `search_impressions_decile` | int | **ML target.** Google Web impressions of the place's guide pages (11 languages summed, 2026-07-03 → 2026-09-25) as a relative decile: `0` = none (177 rows), `1` lowest … `10` highest (~3,311 rows each) |

## ML task: predict search visibility

Given open facts about a travel place, predict how often its guide pages
appear in Google Search. The target mixes real search demand with how well
Audiala's pages rank, so it measures search visibility, not a place's global
popularity. It is ordinal: use Spearman or quadratic weighted kappa, and hold
out whole cities or countries to test generalization.

**Baseline** (gradient-boosted trees on sitelinks, PageRank, category,
country, coordinates, article tier and number of language URLs; 5-fold CV):
Spearman **0.49**, exact decile **13.6 %** (chance ≈ 9 %), within ±1
**40.6 %**. Sitelinks alone reach Spearman 0.45. The multilingual names and
geography are largely untapped. Raw impressions, clicks, CTR and positions
are not published.

## Intended uses

- Tabular ML benchmark: predict `search_impressions_decile` from open features.
- Ranking / recommending travel destinations (fame signals included).
- Multilingual POI name lookup keyed by Wikidata QID.
- Map layers of curated (guide-backed) attractions.
- Joining editorial travel content to Wikidata/OSM entities.

## Limitations

- **Not exhaustive.** Coverage = Audiala's published-guide catalog; skewed
  toward the US, Western Europe, and India, clustered around ~1,360 cities.
  Absence means "no guide yet", not "not notable".
- **Category is best-effort** (~87 % Wikidata-typed, rest heuristic;
  `building` and `attraction` are weak classes).
- A **small long tail of QID mis-mappings** may remain (207 detectable ones
  were removed at build time). Reports welcome.
- Guide URLs were 100 % live (HTTP 200) on a 300-URL random sample at
  build time (2026-09-28); retired pages return 410.
- The search target covers one summer window (2026-07-03 → 2026-09-25), so
  seasonal places are skewed.
- Fame signals are snapshots and drift as Wikidata evolves.

## License and attribution

Licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Required attribution: **"Data by Audiala — [audiala.com](https://audiala.com)"**.

## Citation

```
@misc{audiala-places-2026,
  title  = {Audiala Places: Curated Multilingual Travel POIs},
  author = {{Audiala}},
  year   = {2026},
  url    = {https://audiala.com},
  note   = {CC BY 4.0}
}
```
