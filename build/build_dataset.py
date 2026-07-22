#!/usr/bin/env python3
"""Build the Audiala Open Places dataset (GeoJSON + CSV).

What this produces
------------------
`data/audiala-places.geojson` and `data/audiala-places.csv`: one row per
curated place that has a PUBLISHED guide on audiala.com. This is deliberately
NOT an exhaustive "all the world's monuments" dump — it only contains places
that passed Audiala's editorial pipeline (a generated, schema-validated guide
exists and is live on the site). Quality over quantity.

Inclusion rules (the quality bar)
---------------------------------
A Wikidata entity Q… is included iff ALL of:
  1. A published article row exists in koalai `articles`
     (`structured_content IS NOT NULL OR report IS NOT NULL`) — i.e. the
     place has a real guide page on audiala.com.
  2. `wikidata_id` matches `^Q[0-9]+$`.
  3. NOT classified `place_kind = 'non_tourism'` in `places` (hospitals,
     train stations, embassies… — see koalai pipeline/place_classification).
  4. Coordinates are known (some `places` row has non-null lat/lon in range).
  5. NOT an instance/subclass of a Wikidata exclusion class
     (diplomatic missions, Wikimedia list/disambiguation pages) — checked
     against the self-hosted QLever Wikidata endpoint.

Field derivation
----------------
- names        : koalai `translations` table (11 language columns), falling
                 back to the English article title.
- lat/lon      : best `places` row per QID (EN row preferred, then most
                 user ratings — mirrors batch_hugo_export.py `best_place`).
- country_iso2 : `places.raw->>'country_code'` (Geoapify) for the chosen row,
                 back-filled by per-country majority vote, then Wikidata
                 P297 via QLever for anything still missing.
- category     : Wikidata `P31/P279*` matched against a priority-ordered list
                 of tourism classes (castle before building, cathedral before
                 church, …); name-regex fallback; final fallback "attraction".
- fame signals : `places_page_rank.pr` (Wikidata PageRank, danker import) +
                 sitelink count (COUNT of schema:about triples on QLever).
- url_<lang>   : canonical audiala.com permalink, computed EXACTLY like the
                 site exporters (koalai_v2/publishing/markdown.py
                 `_get_permalink` / audiala-hugo/scripts/export_legacy_pages.py):
                   /{lang}/{country_slug}/{city_slug}/{place_slug}
                 where slugs come from the per-language article row (name,
                 city, country are localized per row), slugified with the
                 ported `slugify()` below (native scripts kept for
                 ja/zh/hi/ru), and the country slug resolved through the
                 vendored `country_translations.json`. A url_<lang> is only
                 emitted when a published article row exists in that language.

Reproducibility
---------------
    export AURORA_PASSWORD=…            # from koalai_v2/.env (never commit)
    python3 build/build_dataset.py      # defaults: localhost:5433 replica

Environment variables (all optional except AURORA_PASSWORD):
    DB_HOST (localhost) DB_PORT (5433) DB_USER (marco) DB_NAME (monuments)
    AURORA_PASSWORD / DB_PASSWORD       # database password
    QLEVER_URL (http://edelweiss:7001)  # self-hosted Wikidata QLever

Dependencies: psycopg2, requests, anyascii (pip install psycopg2-binary requests anyascii)

The script opens the database in a READ-ONLY transaction and never writes.

Provenance of ported logic
--------------------------
- slugify()                 ported from koalai_v2/core/utils.py (canonical impl)
- country slug resolution   ported from koalai_v2/publishing/translations.py
- country_translations.json vendored from koalai_v2/data/ (regenerate with
                            koalai_v2/scripts/refresh_country_translations.py)
- best-place selection      mirrors koalai_v2/scripts/batch_hugo_export.py
"""
import argparse
import collections
import csv
import json
import os
import random
import re
import sys
import time
import unicodedata
from pathlib import Path

import psycopg2
import psycopg2.extras
import requests
from anyascii import anyascii

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

LANGUAGES = ["en", "fr", "de", "es", "pt", "it", "hi", "zh", "cs", "ja", "ru"]
SITE_BASE = "https://audiala.com"

# ---------------------------------------------------------------------------
# slugify — ported verbatim from koalai_v2/core/utils.py
# ---------------------------------------------------------------------------
NATIVE_SCRIPT_LANGUAGES = frozenset({"ja", "zh", "hi", "ru", "ar"})


def slugify(text: str, language: str = None) -> str:
    """Convert text to URL-friendly slug (koalai canonical implementation)."""
    if not text:
        return ""

    if language and language in NATIVE_SCRIPT_LANGUAGES:
        slug = text.strip()
        slug = re.sub(r"[''`\"「」『』【】]", "", slug)
        slug = re.sub(r"[\s_・、。，．：；！？·]+", "-", slug)
        slug = "".join(
            c for c in slug
            if unicodedata.category(c)[0] in ("L", "M", "N") or c == "-"
        )
        slug = re.sub(r"-+", "-", slug).strip("-")
        return slug.lower()

    slug = anyascii(text.lower())
    slug = re.sub(r"[''`\"]", "", slug)
    slug = slug.replace(" ", "-").replace("_", "-").replace(".", "")
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


# ---------------------------------------------------------------------------
# Country canonicalization — ported from koalai_v2/publishing/translations.py
# ---------------------------------------------------------------------------
COUNTRY_WIKIDATA_IDS = {
    "Afghanistan": "Q889", "Albania": "Q222", "Algeria": "Q262", "Andorra": "Q228",
    "Angola": "Q916", "Antigua and Barbuda": "Q781", "Argentina": "Q414", "Armenia": "Q399",
    "Australia": "Q408", "Austria": "Q40", "Azerbaijan": "Q227", "Bahamas": "Q778",
    "Bahrain": "Q398", "Bangladesh": "Q902", "Barbados": "Q244", "Belarus": "Q184",
    "Belgium": "Q31", "Belize": "Q242", "Benin": "Q962", "Bhutan": "Q917",
    "Bolivia": "Q750", "Bosnia and Herzegovina": "Q225", "Botswana": "Q963", "Brazil": "Q155",
    "Brunei": "Q921", "Bulgaria": "Q219", "Burkina Faso": "Q965", "Burundi": "Q967",
    "Cambodia": "Q424", "Cameroon": "Q1009", "Canada": "Q16", "Cape Verde": "Q1011",
    "Central African Republic": "Q929", "Chad": "Q657", "Chile": "Q298", "China": "Q148",
    "Colombia": "Q739", "Comoros": "Q970", "Costa Rica": "Q800", "Croatia": "Q224",
    "Cuba": "Q241", "Cyprus": "Q229", "Czech Republic": "Q213",
    "Democratic Republic of the Congo": "Q974",
    "Denmark": "Q35", "Djibouti": "Q977", "Dominica": "Q784", "Dominican Republic": "Q786",
    "East Timor": "Q574", "Ecuador": "Q736", "Egypt": "Q79", "El Salvador": "Q792",
    "Equatorial Guinea": "Q983", "Eritrea": "Q986", "Estonia": "Q191", "Eswatini": "Q1050",
    "Ethiopia": "Q115", "Federated States of Micronesia": "Q702", "Fiji": "Q712",
    "Finland": "Q33",
    "France": "Q142", "Gabon": "Q1000", "Gambia": "Q1005", "Georgia": "Q230",
    "Germany": "Q183", "Ghana": "Q117", "Greece": "Q41", "Grenada": "Q769",
    "Guatemala": "Q774", "Guinea": "Q1006", "Guinea-Bissau": "Q1007", "Guyana": "Q734",
    "Haiti": "Q790", "Honduras": "Q783", "Hungary": "Q28", "Iceland": "Q189",
    "India": "Q668", "Indonesia": "Q252", "Iran": "Q794", "Iraq": "Q796",
    "Ireland": "Q27", "Israel": "Q801", "Italy": "Q38", "Ivory Coast": "Q1008",
    "Jamaica": "Q766", "Japan": "Q17", "Jordan": "Q810", "Kazakhstan": "Q232",
    "Kenya": "Q114", "Kiribati": "Q710", "Kuwait": "Q817", "Kyrgyzstan": "Q813",
    "Laos": "Q819", "Latvia": "Q211", "Lebanon": "Q822", "Lesotho": "Q1013",
    "Liberia": "Q1014", "Libya": "Q1016", "Liechtenstein": "Q347", "Lithuania": "Q37",
    "Luxembourg": "Q32", "Madagascar": "Q1019", "Malawi": "Q1020", "Malaysia": "Q833",
    "Maldives": "Q826", "Mali": "Q912", "Malta": "Q233", "Marshall Islands": "Q709",
    "Mauritania": "Q1025", "Mauritius": "Q1027", "Mexico": "Q96", "Moldova": "Q217",
    "Monaco": "Q235", "Mongolia": "Q711", "Montenegro": "Q236", "Morocco": "Q1028",
    "Mozambique": "Q1029", "Myanmar": "Q836", "Namibia": "Q1030", "Nauru": "Q697",
    "Nepal": "Q837", "Netherlands": "Q55", "New Zealand": "Q664", "Nicaragua": "Q811",
    "Niger": "Q1032", "Nigeria": "Q1033", "North Korea": "Q423", "North Macedonia": "Q221",
    "Norway": "Q20", "Oman": "Q842", "Pakistan": "Q843", "Palau": "Q695",
    "Palestine": "Q219060", "Panama": "Q804", "Papua New Guinea": "Q691", "Paraguay": "Q733",
    "Peru": "Q419", "Philippines": "Q928", "Poland": "Q36", "Portugal": "Q45",
    "Qatar": "Q846", "Republic of the Congo": "Q971", "Romania": "Q218", "Russia": "Q159",
    "Rwanda": "Q1037", "Saint Kitts and Nevis": "Q763", "Saint Lucia": "Q760",
    "Saint Vincent and the Grenadines": "Q757",
    "Samoa": "Q683", "San Marino": "Q238", "Sao Tome and Principe": "Q1039",
    "Saudi Arabia": "Q851",
    "Senegal": "Q1041", "Serbia": "Q403", "Seychelles": "Q1042", "Sierra Leone": "Q1044",
    "Singapore": "Q334", "Slovakia": "Q214", "Slovenia": "Q215", "Solomon Islands": "Q685",
    "Somalia": "Q1045", "South Africa": "Q258", "South Korea": "Q884", "South Sudan": "Q958",
    "Spain": "Q29", "Sri Lanka": "Q854", "Sudan": "Q1049", "Suriname": "Q730",
    "Sweden": "Q34", "Switzerland": "Q39", "Syria": "Q858", "Taiwan": "Q865",
    "Tajikistan": "Q863", "Tanzania": "Q924", "Thailand": "Q869", "Togo": "Q945",
    "Tonga": "Q678", "Trinidad and Tobago": "Q754", "Tunisia": "Q948", "Turkey": "Q43",
    "Turkmenistan": "Q874", "Tuvalu": "Q672", "Uganda": "Q1036", "Ukraine": "Q212",
    "United Arab Emirates": "Q878", "United Kingdom": "Q145", "United States": "Q30",
    "Uruguay": "Q77", "Uzbekistan": "Q265", "Vanuatu": "Q686", "Vatican City": "Q237",
    "Venezuela": "Q717", "Vietnam": "Q881", "Yemen": "Q805", "Zambia": "Q953",
    "Zimbabwe": "Q954",
}

_COUNTRY_ALIASES = {
    "people's republic of china": "China",
    "peoples republic of china": "China",
    "amerikahezhongguo": "United States",
    "united states of america": "United States",
    "bhart": "India",
    "itaria": "Italy",
    "germaniya": "Germany",
    "saudovskaya araviya": "Saudi Arabia",
    "hong kong": "China",
    "united-kingdom": "United Kingdom",
    "czechia": "Czech Republic",
    "aland islands": "Finland",
    "cina": "China",
    "indie": "India",
    "indo": "Indonesia",
    "italien": "Italy",
    "italia": "Italy",
    "italie": "Italy",
    "giappone": "Japan",
    "viêt nam": "Vietnam",
    "viet nam": "Vietnam",
    "vietname": "Vietnam",
    "вьетнам": "Vietnam",
    "वियतनाम": "Vietnam",
    "ベトナム": "Vietnam",
    "越南": "Vietnam",
    "việt nam": "Vietnam",
}

# Display-only country normalization for the country_en / country_iso2 COLUMNS.
# Deliberately NOT merged into _COUNTRY_ALIASES: the site's URL exporter does
# not know these aliases either, so folding them into slug resolution would
# produce URLs that differ from the live site (e.g. articles stored with
# country "Türkiye" are published under /en/turkiye/…, and /en/turkey/… is a
# 410). URL derivation must stay byte-identical with the exporters.
DISPLAY_COUNTRY_ALIASES = {
    "türkiye": "Turkey",
    "奥地利": "Austria",   # simplified-Chinese variant seen in a few EN rows
}

# Known test/QA rows present in the production DB (invalid Wikidata ids —
# real QIDs never have leading zeros; also excluded by the SQL regex below).
_country_translations: dict | None = None
_reverse_country_map: dict | None = None


def _load_country_translations() -> dict:
    global _country_translations
    if _country_translations is None:
        with open(HERE / "country_translations.json", encoding="utf-8") as f:
            _country_translations = json.load(f)
    return _country_translations


def _build_reverse_country_map() -> dict:
    global _reverse_country_map
    if _reverse_country_map is not None:
        return _reverse_country_map
    m = {en.lower(): en for en in COUNTRY_WIKIDATA_IDS}
    for en, translations in _load_country_translations().items():
        if en not in COUNTRY_WIKIDATA_IDS:
            continue
        for translated in translations.values():
            if isinstance(translated, str) and translated:
                m.setdefault(translated.lower(), en)
    for alias, en in _COUNTRY_ALIASES.items():
        m.setdefault(alias, en)
    _reverse_country_map = m
    return m


def resolve_canonical_country(country: str) -> str:
    if not country:
        return ""
    if country in COUNTRY_WIKIDATA_IDS:
        return country
    return _build_reverse_country_map().get(country.lower(), country)


def get_country_slug(country_name_any: str, language: str = "en") -> str:
    """Canonical localized country slug — ported from
    koalai_v2/publishing/translations.py::get_country_translation."""
    if not country_name_any:
        return ""
    canonical_en = resolve_canonical_country(country_name_any)
    if language == "en":
        return slugify(canonical_en, language="en")
    entry = _load_country_translations().get(canonical_en)
    if isinstance(entry, dict):
        translated = entry.get(language)
        if isinstance(translated, str) and translated:
            return slugify(translated, language=language)
    return slugify(country_name_any, language=language)


def build_permalink(lang: str, country: str, city: str, name: str, qid: str) -> str:
    """Mirror of koalai_v2/publishing/markdown.py::_get_permalink."""
    country_slug = get_country_slug(country or "unknown", lang)
    city_slug = slugify(city or "unknown", language=lang)
    place_slug = slugify(name or "", language=lang)
    if not place_slug:
        place_slug = (qid or "unknown").lower()
    return f"{lang}/{country_slug}/{city_slug}/{place_slug}"


# ---------------------------------------------------------------------------
# Wikidata type classification (priority-ordered: first match wins)
# ---------------------------------------------------------------------------
TYPE_ROOTS: list[tuple[str, str]] = [
    ("Q23413", "castle"),
    ("Q57821", "fortification"),
    ("Q16560", "palace"),
    ("Q2977", "cathedral"),
    ("Q44613", "monastery"),
    ("Q16970", "church"),
    ("Q32815", "mosque"),
    ("Q34627", "synagogue"),
    ("Q845945", "shinto-shrine"),
    ("Q44539", "temple"),
    ("Q1007870", "museum"),        # art gallery
    ("Q33506", "museum"),
    ("Q839954", "archaeological-site"),
    ("Q860861", "statue"),         # sculpture
    ("Q4989906", "monument"),
    ("Q5003624", "memorial"),
    ("Q483453", "fountain"),
    ("Q12280", "bridge"),
    ("Q39715", "lighthouse"),
    ("Q12518", "tower"),
    ("Q82117", "city-gate"),
    ("Q174782", "square"),
    ("Q167346", "botanical-garden"),
    ("Q43501", "zoo"),
    ("Q2281788", "aquarium"),
    ("Q194195", "amusement-park"),
    ("Q1107656", "garden"),
    ("Q22698", "park"),
    ("Q39614", "cemetery"),
    ("Q153562", "opera-house"),
    ("Q24354", "theatre"),
    ("Q7075", "library"),
    ("Q483110", "stadium"),
    ("Q330284", "market"),
    ("Q11707", "restaurant"),
    ("Q40080", "beach"),
    ("Q35509", "cave"),
    ("Q34038", "waterfall"),
    ("Q23397", "lake"),
    ("Q8502", "mountain"),
    ("Q23442", "island"),
    ("Q12284", "canal"),
    ("Q79007", "street"),
    ("Q3918", "university"),
    ("Q11446", "ship"),
    ("Q123705", "neighbourhood"),
    ("Q532", "village"),
    ("Q515", "town"),          # place articles keyed to a town/city QID
    ("Q15284", "town"),        # municipalities/communes
    ("Q486972", "locality"),   # human settlement catch-all
    ("Q24398318", "religious-site"),
    ("Q41176", "building"),
    ("Q570116", "attraction"),
]
TYPE_PRIORITY = {qid: i for i, (qid, _) in enumerate(TYPE_ROOTS)}
TYPE_SLUG = dict(TYPE_ROOTS)

# Rows whose Wikidata classification proves they are not travel POIs are DROPPED.
EXCLUDE_ROOTS = {
    "Q213283": "diplomatic mission (embassy/consulate)",
    "Q13406463": "Wikimedia list article",
    "Q4167410": "Wikimedia disambiguation page",
    # Statue/memorial articles occasionally keyed to the QID of the PERSON
    # depicted (e.g. Q8007 Franklin D. Roosevelt for a Buenos Aires monument).
    # A human is never a place — drop rather than publish a wrong QID mapping.
    "Q5": "human (article keyed to person QID, not the monument)",
}

# Name-based fallback when Wikidata yields no type match (ordered).
NAME_TYPE_PATTERNS: list[tuple[str, str]] = [
    (r"castle|château|chateau|schloss|\bburg\b|castello|castillo|hrad|kasteel", "castle"),
    (r"cathedral|cathédrale|kathedrale|catedral|cattedrale|\bdom\b", "cathedral"),
    (r"abbey|monastery|abbaye|kloster|monastero|monasterio|convent", "monastery"),
    (r"church|église|eglise|kirche|iglesia|chiesa|basilica|basilique|chapel|chapelle|kaple", "church"),
    (r"mosque|mosquée|moschee|mezquita", "mosque"),
    (r"synagogue|synagoga", "synagogue"),
    (r"temple|templo|tempio", "temple"),
    (r"museum|musée|musee|museo|muzeum|galerie|gallery", "museum"),
    (r"palace|palais|palazzo|palacio|palác", "palace"),
    (r"fountain|fontaine|fontana|fuente|brunnen", "fountain"),
    (r"bridge|pont\b|brücke|brucke|ponte|puente|most\b", "bridge"),
    (r"lighthouse|phare|faro|leuchtturm", "lighthouse"),
    (r"tower|tour\b|turm|torre|věž", "tower"),
    (r"statue|statua", "statue"),
    (r"memorial|mémorial", "memorial"),
    (r"monument", "monument"),
    (r"theatre|theater|théâtre|teatro|divadlo", "theatre"),
    (r"opera|opéra", "opera-house"),
    (r"library|bibliothèque|biblioteca|bibliothek|knihovna", "library"),
    (r"cemetery|cimetière|cimitero|cementerio|friedhof|hřbitov", "cemetery"),
    (r"market|marché|marche|mercado|mercato|markt|bazaar", "market"),
    (r"square|plaza|piazza|platz|náměstí|place\b", "square"),
    (r"garden|jardin|giardino|jardín|garten|zahrada", "garden"),
    (r"park\b|parc\b|parque|parco", "park"),
    (r"beach|plage|playa|praia|spiaggia", "beach"),
    (r"gate\b|porte\b|porta\b|puerta\b|\btor\b|brána", "city-gate"),
    (r"aquarium", "aquarium"),
    (r"zoo\b", "zoo"),
    (r"stadium|stade|stadion|estadio", "stadium"),
    (r"university|université|universidad|università|universität", "university"),
]
NAME_TYPE_COMPILED = [(re.compile(p, re.IGNORECASE), slug) for p, slug in NAME_TYPE_PATTERNS]


def classify_by_name(name: str) -> str:
    for rx, slug in NAME_TYPE_COMPILED:
        if rx.search(name or ""):
            return slug
    return "attraction"


# ---------------------------------------------------------------------------
# QLever SPARQL helpers
# ---------------------------------------------------------------------------
SPARQL_HEADERS = {
    "Content-Type": "application/sparql-query",
    "Accept": "application/sparql-results+json",
    "User-Agent": "audiala-open-data/1.0 (https://audiala.com)",
}
PREFIXES = (
    "PREFIX wd: <http://www.wikidata.org/entity/> "
    "PREFIX wdt: <http://www.wikidata.org/prop/direct/> "
    "PREFIX schema: <http://schema.org/> "
)


def sparql(endpoint: str, query: str, retries: int = 3) -> list[dict]:
    for attempt in range(retries):
        try:
            r = requests.post(endpoint, data=PREFIXES + query,
                              headers=SPARQL_HEADERS, timeout=180)
            r.raise_for_status()
            return r.json()["results"]["bindings"]
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))
    return []


def _qid_of(binding_value: dict) -> str:
    return binding_value["value"].rsplit("/", 1)[1]


def fetch_wikidata_signals(endpoint: str, qids: list[str], batch_size: int = 500):
    """Return (sitelinks: {qid: int}, type_matches: {qid: best_slug},
    excluded: {qid: reason}) via batched QLever queries."""
    sitelinks: dict[str, int] = {}
    best: dict[str, int] = {}   # qid -> best (lowest) priority index
    excluded: dict[str, str] = {}
    root_values = " ".join(f"wd:{q}" for q, _ in TYPE_ROOTS)
    excl_values = " ".join(f"wd:{q}" for q in EXCLUDE_ROOTS)
    n_batches = (len(qids) + batch_size - 1) // batch_size
    for i in range(0, len(qids), batch_size):
        batch = qids[i:i + batch_size]
        values = " ".join(f"wd:{q}" for q in batch)
        # 1. sitelink counts (schema:about triples ≈ wikibase:sitelinks)
        rows = sparql(endpoint,
                      f"SELECT ?item (COUNT(?a) AS ?n) WHERE {{ VALUES ?item {{ {values} }} "
                      f"?a schema:about ?item }} GROUP BY ?item")
        for b in rows:
            sitelinks[_qid_of(b["item"])] = int(b["n"]["value"])
        # 2. tourism type classification
        rows = sparql(endpoint,
                      f"SELECT DISTINCT ?item ?root WHERE {{ VALUES ?item {{ {values} }} "
                      f"VALUES ?root {{ {root_values} }} ?item wdt:P31/wdt:P279* ?root }}")
        for b in rows:
            qid, root = _qid_of(b["item"]), _qid_of(b["root"])
            p = TYPE_PRIORITY[root]
            if qid not in best or p < best[qid]:
                best[qid] = p
        # 3. exclusion classes
        rows = sparql(endpoint,
                      f"SELECT DISTINCT ?item ?root WHERE {{ VALUES ?item {{ {values} }} "
                      f"VALUES ?root {{ {excl_values} }} ?item wdt:P31/wdt:P279* ?root }}")
        for b in rows:
            excluded[_qid_of(b["item"])] = EXCLUDE_ROOTS[_qid_of(b["root"])]
        done = i // batch_size + 1
        if done % 10 == 0 or done == n_batches:
            print(f"  qlever: batch {done}/{n_batches}", flush=True)
    type_slug = {qid: TYPE_ROOTS[p][1] for qid, p in best.items()}
    return sitelinks, type_slug, excluded


def fetch_iso2_from_wikidata(endpoint: str, country_qids: list[str]) -> dict[str, str]:
    """{country_qid: ISO2} via Wikidata P297."""
    if not country_qids:
        return {}
    values = " ".join(f"wd:{q}" for q in country_qids)
    rows = sparql(endpoint,
                  f"SELECT ?c ?iso WHERE {{ VALUES ?c {{ {values} }} ?c wdt:P297 ?iso }}")
    return {_qid_of(b["c"]): b["iso"]["value"].upper() for b in rows}


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def connect_db():
    password = os.getenv("AURORA_PASSWORD") or os.getenv("DB_PASSWORD")
    if not password:
        sys.exit("ERROR: set AURORA_PASSWORD (or DB_PASSWORD) in the environment")
    conn = psycopg2.connect(
        dbname=os.getenv("DB_NAME", "monuments"),
        user=os.getenv("DB_USER", "marco"),
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5433"),
        password=password,
        connect_timeout=15,
        options="-c default_transaction_read_only=on",
    )
    # NOTE: no autocommit — named (server-side) cursors need a transaction;
    # the session is forced read-only via default_transaction_read_only.
    return conn


CORE_SQL = """
SELECT a.wikidata_id, a.name, a.city, a.country,
       EXISTS (SELECT 1 FROM articles ax
               WHERE ax.wikidata_id = a.wikidata_id
                 AND ax.structured_content IS NOT NULL) AS has_structured,
       bp.latitude, bp.longitude, bp.city_en, bp.country_en, bp.country_code,
       ppr.pr AS pagerank
FROM articles a
LEFT JOIN LATERAL (
    SELECT p.latitude, p.longitude, p.city_en, p.country_en,
           UPPER(p.raw->>'country_code') AS country_code
    FROM places p
    WHERE p.wikidata_id = a.wikidata_id
      AND p.latitude IS NOT NULL AND p.longitude IS NOT NULL
      AND p.latitude BETWEEN -90 AND 90 AND p.longitude BETWEEN -180 AND 180
    ORDER BY (p.lang = 'en') DESC, p.user_ratings_total DESC NULLS LAST, p.id
    LIMIT 1
) bp ON TRUE
LEFT JOIN places_page_rank ppr ON ppr.wikidata_id = a.wikidata_id
WHERE a.language = 'en'
  AND (a.structured_content IS NOT NULL OR a.report IS NOT NULL)
  AND a.wikidata_id ~ '^Q[1-9][0-9]*$'
  AND NOT EXISTS (SELECT 1 FROM places p2
                  WHERE p2.wikidata_id = a.wikidata_id
                    AND p2.place_kind = 'non_tourism')
"""

PER_LANG_SQL = """
SELECT wikidata_id, language, name, city, country
FROM articles
WHERE (structured_content IS NOT NULL OR report IS NOT NULL)
  AND wikidata_id ~ '^Q[1-9][0-9]*$'
"""

TRANSLATIONS_SQL = """
SELECT wikidata_id, en, fr, de, es, pt, it, hi, zh, cs, ja, ru
FROM translations
WHERE wikidata_id = ANY(%s)
"""


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Build the Audiala Open Places dataset")
    ap.add_argument("--out-dir", default=str(REPO_ROOT / "data"))
    ap.add_argument("--qlever-url", default=os.getenv("QLEVER_URL", "http://edelweiss:7001"))
    ap.add_argument("--no-qlever", action="store_true",
                    help="Skip QLever (no sitelinks, name-regex categories, no exclusion pass)")
    ap.add_argument("--batch-size", type=int, default=500)
    ap.add_argument("--limit", type=int, default=None, help="Cap rows (smoke test)")
    ap.add_argument("--check-urls", type=int, default=0,
                    help="HEAD-check N random url_en values against audiala.com")
    args = ap.parse_args()
    t0 = time.time()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("1/6 querying core rows (published EN articles + best place + pagerank)...")
    conn = connect_db()
    cur = conn.cursor(name="core", cursor_factory=psycopg2.extras.RealDictCursor)
    cur.itersize = 5000
    cur.execute(CORE_SQL + (f" LIMIT {int(args.limit)}" if args.limit else ""))
    core: dict[str, dict] = {}
    dropped_no_coords = 0
    for r in cur:
        if r["latitude"] is None or r["longitude"] is None:
            dropped_no_coords += 1
            continue
        core[r["wikidata_id"]] = dict(r)
    cur.close()
    print(f"    {len(core)} places with coordinates ({dropped_no_coords} dropped: no coords)")

    qids = sorted(core, key=lambda q: int(q[1:]))

    print("2/6 querying translations (11 languages)...")
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(TRANSLATIONS_SQL, (qids,))
    translations = {r["wikidata_id"]: r for r in cur.fetchall()}
    cur.close()
    print(f"    {len(translations)} translation rows")

    print("3/6 querying per-language article rows for URL derivation...")
    cur = conn.cursor(name="perlang", cursor_factory=psycopg2.extras.RealDictCursor)
    cur.itersize = 20000
    cur.execute(PER_LANG_SQL)
    urls: dict[str, dict[str, str]] = collections.defaultdict(dict)
    for r in cur:
        qid, lang = r["wikidata_id"], r["language"]
        if qid not in core or lang not in LANGUAGES:
            continue
        permalink = build_permalink(lang, r["country"], r["city"], r["name"], qid)
        # Canonical site URLs carry NO trailing slash (trailing-slash 301s away).
        urls[qid][lang] = f"{SITE_BASE}/{permalink}"
    cur.close()
    conn.close()
    print(f"    URLs computed for {len(urls)} places")

    sitelinks: dict[str, int] = {}
    wd_types: dict[str, str] = {}
    excluded: dict[str, str] = {}
    iso2_by_country_qid: dict[str, str] = {}
    if not args.no_qlever:
        print(f"4/6 QLever ({args.qlever_url}): sitelinks + P31/P279* types + exclusions...")
        sitelinks, wd_types, excluded = fetch_wikidata_signals(
            args.qlever_url, qids, args.batch_size)
        print(f"    sitelinks for {len(sitelinks)}, wikidata-typed {len(wd_types)}, "
              f"excluded {len(excluded)}")
        iso2_by_country_qid = fetch_iso2_from_wikidata(
            args.qlever_url, sorted(set(COUNTRY_WIKIDATA_IDS.values())))
    else:
        print("4/6 skipped (--no-qlever)")

    for qid, reason in excluded.items():
        core.pop(qid, None)
    if excluded:
        reasons = collections.Counter(excluded.values())
        for reason, n in reasons.most_common():
            print(f"    dropped {n}: {reason}")
    qids = [q for q in qids if q in core]

    print("5/6 assembling rows...")
    # ISO2 pass 1: majority vote of Geoapify country_code per canonical country
    votes: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for qid in qids:
        r = core[qid]
        canonical = resolve_canonical_country(r["country"] or r["country_en"] or "")
        canonical = DISPLAY_COUNTRY_ALIASES.get(canonical.lower(), canonical)
        r["_canonical_country"] = canonical
        cc = r["country_code"]
        if cc and len(cc) == 2:
            votes[canonical][cc] += 1
    iso2_majority = {c: v.most_common(1)[0][0] for c, v in votes.items() if v}

    rows = []
    lang_url_counts = collections.Counter()
    lang_name_native = collections.Counter()
    for qid in qids:
        r = core[qid]
        tr = translations.get(qid) or {}
        canonical = r["_canonical_country"]
        name_en = tr.get("en") or r["name"] or ""
        iso2 = r["country_code"] if (r["country_code"] and len(r["country_code"]) == 2) \
            else iso2_majority.get(canonical, "")
        if not iso2:
            cqid = COUNTRY_WIKIDATA_IDS.get(canonical)
            iso2 = iso2_by_country_qid.get(cqid, "") if cqid else ""
        category = wd_types.get(qid) or classify_by_name(name_en)
        row = {
            "wikidata_id": qid,
            "latitude": round(float(r["latitude"]), 6),
            "longitude": round(float(r["longitude"]), 6),
            "country_iso2": iso2,
            "country_en": canonical or (r["country"] or ""),
            "city_en": r["city"] or r["city_en"] or "",
            "category": category,
            "article_tier": "structured" if r["has_structured"] else "legacy",
            "wikidata_pagerank": round(float(r["pagerank"]), 9) if r["pagerank"] is not None else "",
            "sitelinks": sitelinks.get(qid, ""),
        }
        for lang in LANGUAGES:
            v = tr.get(lang)
            if v:
                lang_name_native[lang] += 1
            row[f"name_{lang}"] = v or name_en
        for lang in LANGUAGES:
            u = urls.get(qid, {}).get(lang, "")
            row[f"url_{lang}"] = u
            if u:
                lang_url_counts[lang] += 1
        rows.append(row)

    rows.sort(key=lambda r: (r["country_iso2"], r["city_en"], r["wikidata_id"]))

    print("6/6 writing CSV + GeoJSON...")
    fieldnames = (["wikidata_id"]
                  + [f"name_{lang}" for lang in LANGUAGES]
                  + ["latitude", "longitude", "country_iso2", "country_en", "city_en",
                     "category", "article_tier", "wikidata_pagerank", "sitelinks"]
                  + [f"url_{lang}" for lang in LANGUAGES])
    csv_path = out_dir / "audiala-places.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    features = []
    for r in rows:
        props = {k: v for k, v in r.items()
                 if k not in ("latitude", "longitude") and v != ""}
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point",
                         "coordinates": [r["longitude"], r["latitude"]]},
            "properties": props,
        })
    geojson = {
        "type": "FeatureCollection",
        "name": "audiala-places",
        "attribution": "Data by Audiala — https://audiala.com (CC BY 4.0)",
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "features": features,
    }
    geojson_path = out_dir / "audiala-places.geojson"
    with open(geojson_path, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False, separators=(",", ":"))

    # ------------------------------------------------------------------
    # Validation + summary
    # ------------------------------------------------------------------
    with open(geojson_path, encoding="utf-8") as f:
        parsed = json.load(f)
    assert parsed["type"] == "FeatureCollection"
    assert len(parsed["features"]) == len(rows), "GeoJSON/CSV row mismatch"
    with open(csv_path, encoding="utf-8") as f:
        csv_rows = sum(1 for _ in csv.reader(f)) - 1
    assert csv_rows == len(rows), f"CSV rows {csv_rows} != {len(rows)}"
    for feat in random.sample(parsed["features"], min(50, len(parsed["features"]))):
        lon, lat = feat["geometry"]["coordinates"]
        assert -90 <= lat <= 90 and -180 <= lon <= 180

    print(f"\nOK — {len(rows)} places")
    print(f"  {csv_path} ({csv_path.stat().st_size/1e6:.1f} MB)")
    print(f"  {geojson_path} ({geojson_path.stat().st_size/1e6:.1f} MB)")
    print(f"  elapsed {time.time()-t0:.0f}s")
    print("\nLanguage coverage (native translated name / guide URL):")
    for lang in LANGUAGES:
        print(f"  {lang}: names {100*lang_name_native[lang]/len(rows):5.1f}%  "
              f"urls {100*lang_url_counts[lang]/len(rows):5.1f}%")
    cats = collections.Counter(r["category"] for r in rows)
    print("\nTop categories:")
    for c, n in cats.most_common(15):
        print(f"  {c}: {n}")
    tiers = collections.Counter(r["article_tier"] for r in rows)
    print(f"\nTiers: {dict(tiers)}")
    ctry = collections.Counter(r["country_en"] for r in rows)
    print(f"Countries: {len(ctry)} — top: "
          + ", ".join(f"{c} {n}" for c, n in ctry.most_common(10)))
    no_iso = sum(1 for r in rows if not r["country_iso2"])
    print(f"Rows without ISO2: {no_iso}")

    if args.check_urls:
        print(f"\nHEAD-checking {args.check_urls} random EN URLs...")
        ok = bad = 0
        for r in random.sample(rows, min(args.check_urls, len(rows))):
            u = r["url_en"]
            try:
                resp = requests.head(u, timeout=15, allow_redirects=False)
                status = resp.status_code
            except Exception as e:
                status = f"ERR {e}"
            good = status == 200
            ok += good
            bad += not good
            print(f"  [{status}] {u}")
        print(f"  {ok} ok / {bad} not-200")


if __name__ == "__main__":
    main()
