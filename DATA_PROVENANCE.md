# iSamples Explorer — Data Provenance

How every parquet file the explorer uses is generated, from root to publish.
*Reviewed 2026-06-02 (CC, via codebase audit). Complements `SERIALIZATIONS.md` (format/schema reference); this file is the end-to-end build chain + the automation gaps.*

> **Load-bearing constraint:** the **root export cannot be regenerated.** It was produced from the iSamples Central Solr API (`central.isample.xyz`), **offline since Aug 2025**. The Zenodo-archived export is a **frozen root**. Any *new* data (e.g. concept URIs, thumbnails) therefore must come from a **per-source supplementary file merged into the base by `pid`** — the "sidecar" pattern (see Stage 3) — not from re-exporting.

## Pipeline DAG

```
Source collections (SESAR · OpenContext · GEOME · Smithsonian)
   │  iSamples Central Solr API  ── OFFLINE since Aug 2025 (cannot re-run) ──┐
   ▼                                                                         │
STAGE 0/1  export_client → JSONL → GeoParquet                               │ frozen
   → isamples_export_*_geo.parquet   (Export format; ~300MB, 6.7M; Zenodo doi:10.5281/zenodo.15278211)
   ▼
STAGE 2  pqg/pqg/sql_converter.py  (export → base PQG; 7-stage DuckDB SQL)
   →  narrow (…_narrow.parquet, ~844MB, 106M rows)   and   wide (…_wide.parquet, ~282MB, 20M rows)
   ▼
STAGE 3  sidecar/enrichment merge (LEFT JOIN by pid)        ← Eric's independently-maintained OC PQG (GCS)
   scripts/enrich_wide_with_oc_thumbnails.py  →  isamples_202604_wide.parquet (+47K thumbnails)
   ▼
STAGE 4  wide → frontend derived files  (mostly AD-HOC / not checked in — see gaps)
   → wide_h3 · h3_summary_res4/6/8 · samples_map_lite · sample_facets_v2 · facet_summaries · facet_cross_filter
   → vocab_labels  (scripts/build_vocab_labels.py — the one fully-scripted derived file; built from SKOS TTLs)
   ▼
STAGE 5  publish to R2 (bucket isamples-ry) + Cloudflare Worker (data.isamples.org, /current/ aliases)
   ▼
DuckDB-WASM in the browser (explorer.qmd; parquet URLs ~L767-781)
```

## Stages (script / command per step)

| Stage | Input → Output | How (file:line) | Automated? |
|---|---|---|---|
| **0/1 Export** | Solr API → `isamples_export_*_geo.parquet` | `export_client` `ExportClient.perform_full_download()` (`export_client.py:423-469`) → `write_geoparquet_from_json_lines()`; schema `SOURCE_COLUMNS` (`duckdb_utilities.py:9-42`, incl. `keywords: STRUCT(keyword VARCHAR)[]` — **text only, no URI**, L17) | ❌ API offline; **frozen** |
| **2 Base PQG** | export → `*_narrow.parquet` / `*_wide.parquet` | `pqg/pqg/sql_converter.py` `convert_isamples_sql(input, output, wide=…)` (CLI `python pqg/sql_converter.py in.parquet out.parquet [--wide]`); 7 stages, decomposes nested structs → nodes+edges; site dedupe by rounded lat/lon+label | ✅ scripted (exact prod invocation not recorded — gap) |
| **3 Sidecar merge** | base wide + Eric's OC PQG → `isamples_202604_wide.parquet` | `scripts/enrich_wide_with_oc_thumbnails.py` — `LEFT JOIN` OC `(pid, thumbnail_url)` into wide (`COALESCE`). **This is the precedent for merging ANY per-source supplement (incl. concept URIs) by pid.** Drift check: `scripts/check_oc_pqg_drift.py` (detects only; no mirror) | ⚠️ merge scripted; OC mirror + R2 upload manual |
| **4 Frontend derived** | wide → 7 explorer files | `vocab_labels.parquet` ← `scripts/build_vocab_labels.py` (SKOS TTLs via rdflib). **The other 6** (`wide_h3`, `h3_summary_res4/6/8`, `samples_map_lite`, `sample_facets_v2`, `facet_summaries`, `facet_cross_filter`) have **no checked-in build script** — query patterns live in notebooks / `SERIALIZATIONS.md` only | ❌ ad-hoc (1 of 7 scripted) |
| **5 Publish** | files → R2 + Worker | Worker `workers/data-isamples-org/src/index.js` (`wrangler deploy`); immutable cache for `isamples_\d{6}_*.parquet`; `/current/<flavor>.parquet` → 302 via `current/manifest.json`. Bucket `isamples-ry` | ⚠️ Worker scripted; **file upload + manifest update are manual** |

## The sidecar/enrichment pattern (how new data gets in)

Because the export is frozen, new per-source data is added by **merging a supplementary parquet keyed by `pid` into the base wide** — exactly what the thumbnail enrichment does:

```sql
-- scripts/enrich_wide_with_oc_thumbnails.py (core)
CREATE TEMP TABLE oc_thumbs AS
  SELECT DISTINCT pid, thumbnail_url FROM read_parquet('<eric_oc_pqg>') WHERE thumbnail_url IS NOT NULL;
COPY (SELECT p.* REPLACE (COALESCE(oc.thumbnail_url, p.thumbnail_url) AS thumbnail_url)
      FROM read_parquet('<base_wide>') p LEFT JOIN oc_thumbs oc ON p.pid = oc.pid)
  TO '<out>' (FORMAT PARQUET, COMPRESSION ZSTD);
```

Eric Kansa maintains OpenContext PQG **independently** on GCS (`storage.googleapis.com/opencontext-parquet/oc_isamples_pqg.parquet`), so it can carry data the frozen iSamples export lacks. This is the channel for **#263** (external concept URIs): Eric's OC PQG carries them → merged into wide by pid → flows to the derived files. *(Sidecar design endorsed 2026-04-17; the spec `project_isamples_sidecar_pattern.md` lives in the Obsidian vault, not a repo — gap.)*

## Documentation / automation gaps

- **6 of 7 frontend derived files have no checked-in build script** (`wide_h3`, the three `h3_summary_res*`, `samples_map_lite`, `sample_facets_v2`, `facet_summaries`, `facet_cross_filter`). Query patterns exist in notebooks + `SERIALIZATIONS.md §4` but not as runnable COPY-TO scripts. `pqg add-h3` / `pqg facet-summaries` are named in the dev journal (Mar 2026) but **absent from `pqg/__main__.py`**.
- **No R2 upload automation** — file upload to bucket `isamples-ry` + `current/manifest.json` update are manual `wrangler`/dashboard steps.
- **No OC mirror script** — `check_oc_pqg_drift.py` detects GCS↔R2 drift but doesn't perform the mirror.
- **Exact prod invocation** that produced `zenodo_narrow_2025-12-12` / `zenodo_wide_2026-01-09` from the Zenodo export is not recorded (dedupe options unknown).
- **No Makefile / CI / post-render hook** rebuilds derived files when wide changes — every post-Stage-2 step is manual.
- **`SERIALIZATIONS.md:80`** claims every file "can be rebuilt by a script" — aspirational; true for ~4 of 10 files.
- **Sidecar spec** is in Obsidian only, not version-controlled with the code.

## Key files
- `export_client/isamples_export_client/duckdb_utilities.py` — export schema (keywords narrowing @ L17)
- `pqg/pqg/sql_converter.py` — export→PQG engine; `pqg/docs/PQG_SPECIFICATION.md` — format spec
- `isamplesorg.github.io/scripts/enrich_wide_with_oc_thumbnails.py` — the sidecar-merge precedent
- `isamplesorg.github.io/scripts/build_vocab_labels.py` — the one scripted derived file
- `isamplesorg.github.io/scripts/check_oc_pqg_drift.py` — OC drift check
- `isamplesorg.github.io/workers/data-isamples-org/{src/index.js,wrangler.toml}` — Worker + R2 config
- `isamplesorg.github.io/SERIALIZATIONS.md` — format/schema reference (DAG companion to this file)
