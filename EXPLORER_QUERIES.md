# How the Interactive Explorer queries data (plain-English walkthrough)

*Written for Eric (#268: "where's the SQL and what parquet files are getting
queried"). This is a guided tour, not the full reference — for the exhaustive
file-by-file schema catalog see `SERIALIZATIONS.md`, and for how those files
get built from the raw export see `DATA_PROVENANCE.md`.*

## The one-sentence version

There is no server and no database. The Explorer is a static webpage
(`explorer.qmd`, compiled to `explorer.html`) that runs a real SQL engine
**inside your browser tab** (DuckDB-WASM) and points it at plain `.parquet`
files sitting on a public URL. Every "query" is your browser fetching just
the byte-ranges of a file it needs and running SQL against them locally — no
request ever goes to an iSamples server.

## Where the files live

Every file is served from `https://data.isamples.org/<filename>.parquet` —
that's a Cloudflare Worker in front of a storage bucket, not a database
server. You can open any of these URLs directly, or point DuckDB at them
(see "Try it yourself" below). The Explorer picks the current filenames in
one place, `explorer.qmd` around **line 800-864**, e.g.:

```js
lite_url    = `${R2_BASE}/isamples_202608_samples_map_lite_v2.parquet`   // map points + table
wide_url    = `${R2_BASE}/isamples_202608_wide.parquet`                  // full sample detail
facets_url  = `${R2_BASE}/isamples_202608_sample_facets_v3.parquet`      // material/context/object_type + search text
h3_res4_url = `${R2_BASE}/isamples_202608_h3_summary_res4.parquet`       // pre-counted globe dots (world zoom)
```

| File | Plain-English role | Roughly how big |
|---|---|---|
| `..._wide.parquet` | Full detail for every sample (one row each) — everything else is derived from this | ~280 MB |
| `..._samples_map_lite_v2.parquet` | Slim version with just what the map/table need: coords, label, place, date | ~50-60 MB |
| `..._sample_facets_v3.parquet` | One row per sample: material/context(sampled feature)/object_type as plain URIs, plus a search-text blob | ~60 MB |
| `..._h3_summary_res{4,6,8}.parquet` | Pre-counted dots for the globe at 3 zoom tiers (continent / region / neighborhood), so zooming out never counts 6M rows live | tiny–few MB |
| `..._facet_summaries.parquet`, `..._facet_cross_filter.parquet`, `..._facet_tree_*.parquet` | Pre-computed facet-checkbox counts at various levels of "how many filters are active" — the whole point of these is to avoid a live COUNT over millions of rows | KB–tens of MB |
| `..._sample_facet_masks.parquet`, `..._sample_facet_index.parquet` | Bitmask tricks so 2+ facet filters at once are still fast (see `SERIALIZATIONS.md` §4.12 if you want the gory detail) | ~10 MB each |
| `vocab_labels_*.parquet` | URI → human-readable label lookup (e.g. `.../material/1.0/rock` → "Rock") | ~60 KB |

*Full list with exact schemas: `SERIALIZATIONS.md`. This table is the subset
that matters for "what happens when I click around the Explorer."*

## What happens when you...

### ...load the page

The globe draws immediately from `h3_res4_url` — one query, pre-aggregated,
instant:

```sql
SELECT h3_cell, sample_count, center_lat, center_lng, dominant_source
FROM read_parquet('h3_summary_res4.parquet')
```
*(`explorer.qmd` — the `phase1` cell, ~line 2209.)* This is why the globe
never feels like it's "loading 6 million points" — it's loading ~38,000
pre-counted hexagon summaries instead.

### ...zoom in

As you zoom past a threshold, the Explorer swaps to res6, then res8 H3
tiles (same idea, finer hexagons), and eventually to individual points from
`samples_map_lite_v2.parquet` once there are few enough in view to draw
directly.

### ...click a facet checkbox (Material / Sampled Feature / Object Type / Source)

Two things happen. First, the map/table re-query with an added `WHERE`
clause built from your selection (`facetFilterSQL()` in `explorer.qmd`).
Second, the OTHER facets' counts need to update ("if I also filtered by
SESAR, how many rocks would there be") — that's the expensive part, and it's
answered by pre-computed cross-filter tables (`facet_cross_filter`,
`facet_tree_cross_filter`) rather than a live scan, *unless* you have 2+
filters active at world zoom, in which case a bitmask index
(`sample_facet_masks` + `facet_node_bits`) does a fast columnar AND/OR
instead of scanning the full membership table. This part has had the most
engineering attention (issues #290/#293/#304/#305/#306) because it's the
slowest possible query shape — "count matches under an arbitrary combination
of filters" doesn't pre-aggregate cleanly.

### ...search for text

Search runs `ILIKE`-style matching against `sample_facets_v3.parquet`'s
description column (which has vocabulary-concept labels appended at build
time, so a search for "pottery" also matches samples only tagged with a
pottery *concept*, not just the word):

```sql
SELECT pid, label, source, place_name FROM read_parquet('sample_facets_v3.parquet')
WHERE description ILIKE '%pottery%'
```
*(`buildSearchFilter()`, `explorer.qmd` ~line 5370-5415.)* Matching pids are
staged into a table (`search_pids`) that every other query — map, table,
facet counts — then filters against, so search composes with facets instead
of being a separate mode.

### ...view the Samples table

The table pages through `samples_map_lite_v2.parquet` (coords/label/place/
date) and, as of #311, joins in `sample_facets_v3.parquet` for
material/object type/sampled feature — one query per page (default page
size), not the whole result set:

```sql
WITH page AS (
    SELECT pid, label, source, latitude, longitude, place_name, result_time
    FROM read_parquet('samples_map_lite_v2.parquet')
    WHERE <your active filters>
    ORDER BY pid LIMIT 50 OFFSET 0
)
SELECT page.*, f.material, f.context, f.object_type
FROM page LEFT JOIN read_parquet('sample_facets_v3.parquet') AS f ON f.pid = page.pid
```
*(`loadPage()`, `explorer.qmd` ~line 2755-2775.)* "Download CSV" (#312) runs
the same shape without the `LIMIT`/`OFFSET` (capped at 50,000 rows so an
unfiltered world-zoom export can't hang the tab).

### ...click a sample point

One `wide.parquet` self-join to pull the full detail row plus its material/
object-type concept labels (`explorer.qmd` ~line 2114-2135):

```sql
SELECT s.description, s.thumbnail_url, mat_lbl.pref_label AS material_label, obj_lbl.pref_label AS object_type_label
FROM read_parquet('wide.parquet') s
LEFT JOIN read_parquet('wide.parquet') mat ON mat.row_id = s.p__has_material_category[1]
LEFT JOIN read_parquet('vocab_labels.parquet') mat_lbl ON mat_lbl.uri = mat.pid
WHERE s.pid = '<clicked pid>'
```
This is the one query that reads from `wide.parquet` on click (everything
above deliberately avoids touching the 280 MB wide file until you actually
need full detail on one sample).

## Try it yourself

You don't need the browser — any of this works from the DuckDB CLI or
`isamples-python`, against the exact same public URLs the Explorer uses:

```sql
-- how many samples per source, right now, live off the public URL
SELECT n AS source, COUNT(*)
FROM read_parquet('https://data.isamples.org/isamples_202608_wide.parquet')
WHERE otype = 'MaterialSampleRecord'
GROUP BY n ORDER BY 2 DESC;

-- same "pottery" search the Explorer runs
SELECT pid, label, source
FROM read_parquet('https://data.isamples.org/isamples_202608_sample_facets_v3.parquet')
WHERE description ILIKE '%pottery%'
LIMIT 20;
```

DuckDB only fetches the byte ranges it needs (via HTTP range requests), so
this is fast even though the files are hundreds of MB — you're not
downloading the whole thing to run a filtered query.

## Where to go deeper

- **`SERIALIZATIONS.md`** — every file, full schema, exact row/byte counts, the URL convention (versioned vs `/current/` alias).
- **`DATA_PROVENANCE.md`** — how `wide.parquet` itself gets built from the frozen Zenodo export, and the sidecar-enrichment pattern Eric's OpenContext PQG feeds into.
- **`query-spec.qmd`** — the dimension-to-file binding table (source/material/bbox/h3/time/text → which file answers each).
- **`scripts/build_frontend_derived.py`** — the actual SQL that produces every file in the table above, if you want the ground truth rather than my paraphrase of it.

---
*Written 2026-07 in response to #268. If something above doesn't match what
you're actually seeing when you click around, that's a bug in this doc (or a
real bug) — file it.*
