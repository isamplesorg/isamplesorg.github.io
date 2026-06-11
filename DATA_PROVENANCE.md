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
STAGE 3  sidecar/enrichment merges (LEFT JOIN by pid)       ← Eric's independently-maintained OC PQG (GCS)
   3a scripts/enrich_wide_with_oc_thumbnails.py  →  isamples_202604_wide.parquet (+47K thumbnails)
   3b scripts/enrich_wide_with_oc_concepts.py    →  isamples_202606_wide.parquet (#272: OC material/
      object-type concepts REPLACE the frozen export's for OC pids — OC wins unconditionally;
      gate: scripts/validate_oc_concept_enrichment.py)
   ▼
STAGE 4  wide → frontend derived files  (NOW SCRIPTED: scripts/build_frontend_derived.py)
   → wide_h3 · h3_summary_res4/6/8 · samples_map_lite · sample_facets_v2 · facet_summaries · facet_cross_filter
   → vocab_labels  (scripts/build_vocab_labels.py — built separately from SKOS TTLs)
   → {tag}_manifest.json  (build identity: input+output sha256, argv, git SHA, DuckDB/extension versions)
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
| **3a Sidecar: thumbnails** | base wide + Eric's OC PQG → `isamples_202604_wide.parquet` | `scripts/enrich_wide_with_oc_thumbnails.py` — `LEFT JOIN` OC `(pid, thumbnail_url)` into wide (`COALESCE`). Drift check: `scripts/check_oc_pqg_drift.py` (detects only; no mirror) | ⚠️ merge scripted; OC mirror + R2 upload manual |
| **3b Sidecar: OC concepts (#272)** | 3a wide + Eric's OC **wide** → `isamples_202606_wide.parquet` | `scripts/enrich_wide_with_oc_concepts.py` — REPLACES `p__has_material_category` / `p__has_sample_object_type` for OC pids with OC's ordered concept lists (**OC wins unconditionally** — RY decision 2026-06-10, #272); mints `IdentifiedConcept` rows for URIs the frozen export never had (e.g. `otheranthropogenicmaterial`, the #260 fix); deterministic; emits `.manifest.json`. Independent gate: `scripts/validate_oc_concept_enrichment.py` (re-derives from inputs; non-overlay rows must be byte-identical). Scope: overlay only — ~75K OC records absent from the frozen export are NOT ingested (follow-up); `p__has_context_category` untouched (follow-up). | ✅ merge + gate scripted (`make all-272`); R2 upload manual |
| **4 Frontend derived** | wide → 7 explorer files | The 6 map/facet files (`wide_h3`, `h3_summary_res4/6/8`, `samples_map_lite`, `sample_facets_v2`, `facet_summaries`, `facet_cross_filter`) ← **`scripts/build_frontend_derived.py`** (deterministic; geometry-agnostic; emits a manifest). `vocab_labels.parquet` ← `scripts/build_vocab_labels.py` (SKOS TTLs). Gated by `scripts/validate_frontend_derived.py` (algebraic + `--wide` semantic re-derivation) + `tests/test_frontend_derived.py` (fixtures, CI). | ✅ scripted; facet/map files semantic-tested; wide_h3 column-smoke-tested |
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

## Stage 4 builder contract (`scripts/build_frontend_derived.py`)

- **Geometry-agnostic input.** The `geometry` column may be **WKB BLOB** (e.g. `isamples_202604_wide`) or DuckDB **GEOMETRY** (e.g. `isamples_202601_wide`, the Zenodo wide). The builder detects the type at runtime — earlier ad-hoc SQL assumed BLOB and threw `BinderException` on GEOMETRY wides.
- **Material selection (#265/#271).** `material` = the **first NON-ROOT** concept in `p__has_material_category` (the root `.../material/1.0/material` "Material" can sit at any array position). Samples tagged only at the root get `NULL` material (excluded from the facet). This is **NOT leaf/most-specific** selection — the arrays are not clean SKOS paths. `context`/`object_type` use `[1]`; their root-dropping is deferred.
- **Determinism.** Every COPY has `ORDER BY`; `dominant_source` ties break on source name (ASC); center lat/lng rounded to 6 dp.
- **Reproducibility & build identity.** Each run writes `{tag}_manifest.json` (input + per-output sha256, argv, git SHA, DuckDB + extension versions). DuckDB pinned in `scripts/requirements.txt`.
- **Tested.** `tests/test_frontend_derived.py` (fixtures, CI via `.github/workflows/pipeline-tests.yml`) + `scripts/validate_frontend_derived.py` (algebraic: `facet_summaries == GROUP BY sample_facets_v2`, `facet_cross_filter == conditional GROUP BY`, `facets.pid == map_lite.pid`, pid uniqueness, H3 sums). `make test` / `make all`.

## Documentation / automation gaps (remaining)

- ⚠️ **The deployed `202601` derived files are NOT reproducible** from any available wide. A rebuild yields **528,983** root-material rows (pre-#271); the deployed `sample_facets_v2` has **346,768** — so the live files came from a different/unrecorded Stage-4 process, *and* the data has since rolled (wide is now `202604`). Treat a fresh `build_frontend_derived.py` run as the new source of truth, not as a bit-for-bit reproduction of the deployed files.
- **Version skew:** the deployed derived files are `202601` while the wide they should derive from is `202604` (the popup reads `202604`). Rebuilding from `202604` resolves it (tracked in the pipeline epic).
- **No R2 upload automation** — file upload to bucket `isamples-ry` + `current/manifest.json` update are manual `wrangler`/dashboard steps.
- **No OC mirror script** — `check_oc_pqg_drift.py` detects GCS↔R2 drift but doesn't perform the mirror.
- **Stage-2 prod invocation** that produced `zenodo_narrow_2025-12-12` / `zenodo_wide_2026-01-09` from the Zenodo export is still unrecorded (dedupe options unknown).
- **`SERIALIZATIONS.md:80`** claims every file "can be rebuilt by a script" — now true for the Stage-4 files; still aspirational for Stage-2.
- **Sidecar spec** is in Obsidian only, not version-controlled with the code.

## Key files
- `export_client/isamples_export_client/duckdb_utilities.py` — export schema (keywords narrowing @ L17)
- `pqg/pqg/sql_converter.py` — export→PQG engine; `pqg/docs/PQG_SPECIFICATION.md` — format spec
- `isamplesorg.github.io/scripts/enrich_wide_with_oc_thumbnails.py` — the sidecar-merge precedent
- `isamplesorg.github.io/scripts/build_vocab_labels.py` — the one scripted derived file
- `isamplesorg.github.io/scripts/check_oc_pqg_drift.py` — OC drift check
- `isamplesorg.github.io/workers/data-isamples-org/{src/index.js,wrangler.toml}` — Worker + R2 config
- `isamplesorg.github.io/SERIALIZATIONS.md` — format/schema reference (DAG companion to this file)
