# Audiala Places — a curated, multilingual open dataset of travel POIs

**33,148 places** across **93 countries** and **~1,200 cities**, each with a
Wikidata QID, coordinates, names in **11 languages**, a type/category slug,
fame signals, and a link to a published travel guide on
[audiala.com](https://audiala.com) in each language. Guides are produced by a
research → drafting → schema-validation → fact-check pipeline
([how we make our guides](https://audiala.com/about/editorial-process/)); we
do not claim a human reads every page.

- `data/audiala-places.geojson` — GeoJSON `FeatureCollection` (55.3 MB)
- `data/audiala-places.csv` — same rows, flat CSV (40.5 MB)
- `build/build_dataset.py` — the reproducible build script

**License: [CC BY 4.0](LICENSE)** · **Attribution required:**
*"Data by Audiala — [audiala.com](https://audiala.com)"* (see
[Attribution](#attribution)).

---

## What this is (and is not)

This is the set of places for which Audiala has **published an editorial
travel guide**. Every row corresponds to a live guide page on audiala.com —
that published-article requirement *is* the curation filter. It is a
quality bar, not a completeness claim.

This is **not** "all the world's monuments", "every castle in Europe", or a
Wikidata dump. If you need an exhaustive universe of POIs, query Wikidata or
OpenStreetMap directly. What this dataset adds over those sources is:

1. a **curation signal** — each entry cleared an editorial generation +
   schema-validation pipeline and is live as a full guide;
2. **consistent multilingual naming** (11 languages) per place;
3. **stable guide URLs per language** for deep-linking;
4. pre-joined **fame signals** (Wikidata PageRank + sitelink counts) for
   ranking.

## Schema

| Column | Description |
|---|---|
| `wikidata_id` | Wikidata QID (`Q…`) — primary key, one row per entity |
| `name_en` … `name_ru` | Place name in en, fr, de, es, pt, it, hi, zh, cs, ja, ru (native script; falls back to the English name when no translation exists — 99.8–99.9 % have native translations) |
| `latitude`, `longitude` | WGS84 decimal degrees (GeoJSON: `Point` geometry, `[lon, lat]`) |
| `country_iso2` | ISO 3166-1 alpha-2 country code |
| `country_en` | English country name (canonicalized) |
| `city_en` | English city name the guide is filed under |
| `category` | Type slug from a 50-value controlled vocabulary (`castle`, `museum`, `church`, `bridge`, …) — see [Category](#category) |
| `article_tier` | `structured` (new rich guide format) or `legacy` (earlier guide format) |
| `wikidata_pagerank` | Wikidata PageRank score ([danker](https://danker.s3.amazonaws.com/index.html) all-wiki links run); present for 83 % of rows |
| `sitelinks` | Number of Wikimedia project pages linked to the entity (proxy for cross-language notability); present for ~100 % of rows |
| `url_en` … `url_ru` | Canonical audiala.com guide URL in each language (native-script paths for hi/zh/ja/ru); emitted only when a guide is published in that language (≥ 99.9 % per language) |

## Methodology

Built by `build/build_dataset.py` (read-only SQL against Audiala's content
database + SPARQL against a self-hosted Wikidata [QLever] endpoint):

1. **Selection** — every Wikidata entity with a published Audiala article
   (structured or legacy guide), excluding: entities classified
   `non_tourism` by Audiala's place-classification pipeline (hospitals,
   train stations, offices, …), entities without usable coordinates, and
   entities whose Wikidata classification disqualifies them (diplomatic
   missions, Wikimedia list/disambiguation pages, and articles mistakenly
   keyed to a *person's* QID — 188 rows dropped in this build).
2. **Names** — Audiala's `translations` table (one column per language),
   English fallback.
3. **Coordinates** — best place record per QID (English-language record
   preferred, then highest review count).
4. **Category** — Wikidata `P31/P279*` matched against a priority-ordered
   list of ~50 tourism classes (most specific wins: *castle* before
   *building*, *cathedral* before *church*); name-pattern fallback; final
   fallback `attraction`.
5. **Fame signals** — Wikidata PageRank (danker import) joined from the
   content DB; sitelink counts from the Wikidata snapshot.
6. **URLs** — recomputed with the exact permalink logic of the site's page
   exporters (same slugification, including native-script slugs and
   per-language country slugs), so dataset URLs match the live site.

**QA on this build:** GeoJSON parses; CSV row count = GeoJSON feature count =
33,148; coordinates validated in range; 330 random URLs across all 11
languages returned **99.7 % HTTP 200** (1 × 410 tombstoned page).

## Row counts (build of 2026-07-22)

| Metric | Value |
|---|---|
| Places (rows) | 33,148 |
| Countries | 93 |
| Distinct (country, city) pairs | 1,204 |
| Languages | 11 |
| Native-name coverage | 99.8–99.9 % per language |
| Guide-URL coverage | 99.9–100 % per language |
| `structured` tier | 451 |
| `legacy` tier | 32,697 |
| With Wikidata PageRank | 83.2 % |
| With sitelink count | ~100 % |

Top countries: US 4,150 · Italy 4,053 · France 2,299 · Germany 2,081 ·
Spain 2,077 · UK 1,467 · India 1,204 · Poland 877 · Canada 815 · Brazil 804.

### Category

50 slugs. Distribution: building 5,408 · museum 4,422 · attraction 3,013 ·
statue 2,214 · church 2,074 · monument 1,523 · theatre 1,381 · palace 1,141 ·
square 1,065 · fortification 915 · stadium 839 · park 833 · bridge 751 ·
archaeological-site 678 · temple 523 · locality 514 · garden 479 · mosque 461 ·
cathedral 454 · library 425 · monastery 408 · castle 403 · cemetery 361 ·
tower 356 · neighbourhood 280 · university 249 · opera-house 213 · town 212 ·
zoo 177 · botanical-garden 170 · synagogue 167 · village 152 · canal 120 ·
street 82 · lighthouse 78 · amusement-park 76 · religious-site 65 ·
restaurant 59 · island 55 · lake 52 · cave 52 · mountain 46 · beach 44 ·
shinto-shrine 29 · ship 27 · memorial 26 · city-gate 23 · waterfall 21 ·
market 20 · fountain 12.

## Sample — 20 highest-sitelink entries (non-settlement categories)

| QID | Name (en) | Name (ja) | Category | City | CC | Sitelinks | PageRank |
|---|---|---|---|---|---|---|---|
| Q85 | [Cairo](https://audiala.com/en/egypt/cairo-governorate/cairo) | カイロ | archaeological-site | Cairo Governorate | EG | 259 | 1349.7 |
| Q12501 | [Great Wall of China](https://audiala.com/en/china/beijing/great-wall-of-china) | 万里の長城 | fortification | Beijing | CN | 193 | 142.6 |
| Q243 | [Eiffel Tower](https://audiala.com/en/france/paris/eiffel-tower) | エッフェル塔 | tower | Paris | FR | 189 | 225.2 |
| Q9141 | [Taj Mahal](https://audiala.com/en/india/agra/taj-mahal) | タージ・マハル | monument | Agra | IN | 180 | 94.8 |
| Q478595 | [Tan Son Nhat International Airport](https://audiala.com/en/vietnam/ho-chi-minh-city/tan-son-nhat-international-airport) | タンソンニャット国際空港 | building | Ho Chi Minh City | VN | 170 | 15.5 |
| Q19675 | [Louvre Museum](https://audiala.com/en/france/paris/louvre-museum) | ルーヴル美術館 | museum | Paris | FR | 165 | 460.8 |
| Q9202 | [Statue of Liberty](https://audiala.com/en/united-states/new-york-city/statue-of-liberty) | 自由の女神像 | statue | New York City | US | 156 | 142.1 |
| Q12506 | [Hagia Sophia](https://audiala.com/en/turkey/istanbul/hagia-sophia) | アヤソフィア | mosque | Istanbul | TR | 150 | 132.5 |
| Q676203 | [Machu Picchu](https://audiala.com/en/peru/machu-picchu/machu-picchu) | マチュ・ピチュ | archaeological-site | Machu Picchu | PE | 147 | 63.0 |
| Q10285 | [Colosseum](https://audiala.com/en/italy/rome/colosseum) | コロッセオ | museum | Rome | IT | 146 | 129.8 |
| Q35525 | [White House](https://audiala.com/en/united-states/washington/white-house) | ホワイトハウス | palace | Washington | US | 143 | 485.0 |
| Q5086 | [Berlin Wall](https://audiala.com/en/germany/berlin/berliner-mauer) | ベルリンの壁 | fortification | Berlin | DE | 141 | 303.6 |
| Q12495 | [Burj Khalifa](https://audiala.com/en/united-arab-emirates/dubai/burj-khalifa) | ブルジュ・ハリーファ | building | Dubai | AE | 140 | 49.6 |
| Q34221 | [Niagara Falls](https://audiala.com/en/canada/niagara-falls/niagara-falls) | ナイアガラの滝 | waterfall | Niagara Falls | CA | 135 | 93.9 |
| Q10288 | [Parthenon](https://audiala.com/en/greece/athens/parthenon) | パルテノン神殿 | temple | Athens | GR | 133 | 141.1 |
| Q41180 | [La Marseillaise](https://audiala.com/en/france/marseille/la-marseillaise) | ラ・マルセイエーズ | attraction | Marseille | FR | 124 | 141.1 |
| Q2981 | [Notre-Dame de Paris](https://audiala.com/en/france/paris/notre-dame-de-paris) | ノートルダム大聖堂 | cathedral | Paris | FR | 124 | 172.4 |
| Q37200 | [Great Pyramid of Giza](https://audiala.com/en/egypt/giza-governorate/great-pyramid-of-giza) | ギザの大ピラミッド | archaeological-site | Giza Governorate | EG | 123 | 66.1 |
| Q23402 | [Musée d'Orsay](https://audiala.com/en/france/paris/musee-dorsay) | オルセー美術館 | museum | Paris | FR | 123 | 146.5 |
| Q16990 | [Mount Etna](https://audiala.com/en/italy/zafferana-etnea/mount-etna) | エトナ火山 | mountain | Zafferana Etnea | IT | 123 | 98.4 |

Warts on display (deliberately — see next section): Q85 is Cairo itself
carrying an `archaeological-site` P31 path; Q41180 resolves to the anthem
*La Marseillaise* rather than the Marseille monument depicting it. Both are
QID-mapping artifacts in the long tail.

## Known coverage limits

Read this before building on the data. The dataset is honest about what it
is; please don't present it as something it isn't.

- **Not exhaustive — by design.** This is *places Audiala has published
  guides for*, nothing more. There are millions of tourism POIs in Wikidata
  and OSM that are absent here. Absence of a place means nothing except that
  we haven't published its guide yet.
- **Coverage is skewed.** 93 countries, but heavily weighted toward the US,
  Western Europe, and India. Many countries have a handful of rows; large
  parts of Africa, Central Asia, and Oceania are thin or absent. Within
  covered countries, coverage clusters around ~1,200 cities.
- **Selection reflects publishing history, not importance.** What got a
  guide first depended on Audiala's city rollout order and demand signals,
  not on any objective notability ranking.
- **Category is best-effort.** ~87 % of rows are typed from Wikidata
  `P31/P279*`; the rest fall back to name patterns or the generic
  `attraction`. `building` (5,408 rows) is a weak class. Treat `category`
  as a convenience facet, not ground truth.
- **QID mapping has a long tail of imperfection.** This build removed 188
  detectable mis-mappings (articles keyed to person QIDs, embassies,
  Wikimedia list pages), but subtler cases remain (see the sample table's
  warts). If you find one, please report it.
- **URL liveness ≈ 99.7 %,** measured on a 330-URL random sample at build
  time. Guides are occasionally re-curated; retired pages return HTTP 410.
- **Fame signals are snapshots.** PageRank comes from a danker run imported
  into our DB; sitelink counts from our self-hosted Wikidata snapshot. Both
  drift as Wikidata evolves, and PageRank is missing for ~17 % of rows.
- **Coordinates are operational, not surveyed.** They originate from
  commercial/open geocoding lineage (Google/Geoapify/OSM) selected per
  place; expect occasional imprecision.

## Rebuilding

```bash
pip install psycopg2-binary requests anyascii
export AURORA_PASSWORD=…   # Audiala content-DB credential (internal)
python3 build/build_dataset.py            # writes data/ (93 s typical)
python3 build/build_dataset.py --help     # options: --limit, --check-urls, --no-qlever
```

The build requires read access to Audiala's internal content database and
(optionally, for sitelinks/typing/exclusions) the self-hosted Wikidata
QLever endpoint — so third parties cannot rebuild it, but the script
documents every derivation decision and is the single source of truth for
how the files were produced.

## Attribution

This dataset is licensed under
[Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).
You may share and adapt it, including commercially, **provided you credit
Audiala**. Required attribution:

> Data by Audiala — [audiala.com](https://audiala.com)

For a map or app, a visible "Data by Audiala" link satisfies this; for a
derived dataset or paper, cite the dataset name and link to audiala.com.

## Update cadence

Initial release, 2026-07-25. The build is fully scripted, so refreshes are
cheap; expect periodic updates as coverage grows. Published on
[GitHub](https://github.com/audiala/open-data) and
[Hugging Face](https://huggingface.co/datasets/audiala/audiala-places).
