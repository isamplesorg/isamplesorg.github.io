---
title: "iSamples Data Serializations"
subtitle: "A catalog of the parquet files that back the iSamples query substrate"
author: "iSamples team"
date: today
toc: true
categories: [data, architecture, parquet]
---

## 1. Purpose and scope

iSamples has roughly a dozen parquet files in circulation at any given
moment — each with a specific role, a specific upstream parent, and a
specific set of downstream consumers (the web Explorer, the Python
reference notebook, the progressive globe, the PQG conformance work).
Some are primary archival products; others are derived aggregates
or caches; still others are source-specific variants published
outside the `data.isamples.org` namespace.

This document is a **catalog**, not an ingestion guide: it tells you
what each file is, where it came from, who consumes it, and where in
the spec tree to look for its normative definition. For how to *build*
these files, see the scripts in
[`scripts/`](https://github.com/isamplesorg/isamplesorg.github.io/tree/main/scripts)
and the converters in
[`pqg/`](https://github.com/isamplesorg/pqg). For how to *query* them,
see [`query-spec.qmd`](query-spec.qmd). For how to *cite* them, see
the Zenodo deposition plan.

All sizes and row counts below were verified by DuckDB `DESCRIBE` +
`COUNT(*)` against `https://data.isamples.org/` on 2026-04-24.

## 2. The derivation DAG

```
Zenodo export (doi:10.5281/zenodo.15278211, ~300 MB, 6.7 M samples)
  │   sample-centric, nested STRUCTs (PQG "export" format)
  │
  └─► isamples_202512_narrow.parquet  (820 MB, 101 M rows)
        │   graph-normalized, nodes + _edge_ rows (PQG "narrow")
        │
        └─► isamples_202601_wide.parquet  (278 MB, 20.7 M rows)
              │   entity-centric, p__* relationship arrays (PQG "wide")
              │
              ├─► isamples_202604_wide.parquet  (292 MB, 20.7 M rows)
              │     = 202601 wide + ~47 K OpenContext thumbnails
              │     (see scripts/enrich_wide_with_oc_thumbnails.py)
              │
              ├─► isamples_202601_wide_h3.parquet  (292 MB, 20.7 M)
              │     = wide + h3_res4 / h3_res6 / h3_res8 columns
              │
              ├─► isamples_202601_samples_map_lite.parquet  (60 MB, 6.0 M)
              │     display projection for map points
              │
              ├─► isamples_202601_sample_facets_v2.parquet  (63 MB, 6.0 M)
              │     pid → facet-URI strings for multi-dim filtering
              │
              ├─► isamples_202601_facet_summaries.parquet  (2 KB, 56 rows)
              │     baseline (facet_type, facet_value, count) tuples
              │
              ├─► isamples_202601_facet_cross_filter.parquet  (6 KB, 526 rows)
              │     single-active-filter cross cache
              │
              └─► isamples_202601_h3_summary_res{4,6,8}.parquet
                    geospatial aggregates for the progressive globe
                    (38 K / 112 K / 176 K cells)

Source-specific variants (parallel to the substrate, not derived from it):

oc_isamples_pqg.parquet        (GCS, 11.8 M, narrow, OC-only)
oc_isamples_pqg_wide.parquet   (GCS,  2.5 M, wide,   OC-only)
  └─► serve as upstream for OpenContext thumbnails folded into 202604 wide
```

Arrows indicate derivation, not containment. Every file in the left
column can be rebuilt from its parent by a script in
`isamples-python/` or `isamplesorg.github.io/scripts/`.

## 3. Catalog

### Tier: source of truth

| File | Role | Size | Rows | Upstream | Consumers | Spec |
|---|---|---:|---:|---|---|---|
| `zenodo.15278211` export | Aggregated Zenodo export (all 4 sources, sample-centric, nested) | ~300 MB | 6.7 M | SESAR + OpenContext + GEOME + Smithsonian ingestion | PQG converters (narrow, wide) | PQG §3.3 (export format) |

### Tier: graph normalization

| File | Role | Size | Rows | Upstream | Consumers | Spec |
|---|---|---:|---:|---|---|---|
| `isamples_202512_narrow.parquet` | Graph-normalized with explicit `_edge_` rows; canonical archival form | 820 MB | 101.4 M | Zenodo export | Graph traversals, PQG tutorials, narrow→wide converter, Zenodo archive | PQG §3.1, §4.2 |
| `isamples_202601_wide.parquet` | Entity-centric, relationships as `p__*` arrays; primary analytic substrate | 278 MB | 20.7 M | narrow | Search Explorer, Python notebook, facet/h3/lite derivations | PQG §3.2, §4.5 |
| `isamples_202604_wide.parquet` | 202601 wide + ~47 K OC thumbnails folded in | 292 MB | 20.7 M | 202601 wide + `oc_isamples_pqg.parquet` | `current/wide.parquet` alias points here | PQG §3.2 |

### Tier: derived aggregates (progressive globe / H3)

| File | Role | Size | Rows | Upstream | Consumers | Spec |
|---|---|---:|---:|---|---|---|
| `isamples_202601_wide_h3.parquet` | Wide with `h3_res{4,6,8}` BIGINT columns pre-joined | 292 MB | 20.7 M | wide | Deep-Dive Analysis tutorial (H3 filtering without join) | QUERY_SPEC §2.4 |
| `isamples_202601_h3_summary_res4.parquet` | Continental tier: `(h3_cell, sample_count, center_lat, center_lng, dominant_source, source_count, resolution)` | 580 KB | 38 K | wide_h3 | Interactive Explorer globe (zoomed out), Python Explorer H3 tier mode | QUERY_SPEC §2.4 |
| `isamples_202601_h3_summary_res6.parquet` | Regional tier | 1.6 MB | 112 K | wide_h3 | Interactive Explorer globe (mid zoom) | QUERY_SPEC §2.4 |
| `isamples_202601_h3_summary_res8.parquet` | Neighborhood tier | 2.4 MB | 176 K | wide_h3 | Interactive Explorer globe (close zoom) | QUERY_SPEC §2.4 |

### Tier: display projections

| File | Role | Size | Rows | Upstream | Consumers | Spec |
|---|---|---:|---:|---|---|---|
| `isamples_202601_samples_map_lite.parquet` | Minimum map projection; only `MaterialSampleRecord` rows with coordinates | 60 MB | 6.0 M | wide (filtered) | Interactive Explorer point-level rendering below ~120 km altitude | QUERY_SPEC §4.1 |

### Tier: facet caches

| File | Role | Size | Rows | Upstream | Consumers | Spec |
|---|---|---:|---:|---|---|---|
| `isamples_202601_sample_facets_v2.parquet` | `(pid, source, material, context, object_type, label, description, place_name)`; URI-string facets per sample | 63 MB | 6.0 M | wide | Search Explorer multi-dim facet filtering | QUERY_SPEC §3.3, §5.1 |
| `isamples_202601_facet_summaries.parquet` | Baseline `(facet_type, facet_value, scheme, count)` | 2 KB | 56 | wide | Every tutorial (instant initial facet counts) | QUERY_SPEC §3.3 tier 1 |
| `isamples_202601_facet_cross_filter.parquet` | Pre-computed counts for single-filter cross-facet queries | 6 KB | 526 | wide | Search Explorer cross-filter UI | QUERY_SPEC §3.3 tier 2a |

### Tier: source-specific variants (not part of the substrate)

| File | Role | Size | Rows | Upstream | Consumers | Spec |
|---|---|---:|---:|---|---|---|
| `oc_isamples_pqg.parquet` (GCS) | OpenContext-only narrow; carries `thumbnail_url` values absent from the aggregated export | ~1.8 GB | 11.8 M | OpenContext ETL (Eric Kansa) | `scripts/enrich_wide_with_oc_thumbnails.py` → 202604 wide; PQG development | PQG §3.1 |
| `oc_isamples_pqg_wide.parquet` (GCS) | OpenContext-only wide | ~600 MB | 2.5 M | OC narrow | OC-specific analyses, PQG benchmarks | PQG §3.2 |

**No OpenContext sidecar file exists yet.** Per the sidecar-pattern plan
(Raymond endorsed 2026-04-17), thumbnails are currently merged directly
into `isamples_202604_wide.parquet` rather than joined at query time
from a sidecar. A future `isamples_202601_oc_sidecar.parquet` (keyed on
`pid`, with `thumbnail_url`, `is_public`, `license`, `media_url`,
`harvested_at`) is planned — see
`project_isamples_sidecar_pattern.md`.

## 4. Per-file detail

URL convention: each file is available at
`https://data.isamples.org/<filename>` (versioned, 1-yr immutable cache)
and, where applicable, at `https://data.isamples.org/current/<alias>`
(302 redirect, 5-min cache). Examples below use the versioned URL; swap
for the alias when you want "latest."

### 4.1 Zenodo export (source of truth)

- **Role**: The raw aggregated Zenodo export — all four sources, sample-centric, nested STRUCTs.
- **DOI**: `10.5281/zenodo.15278211`
- **Headline schema** (PQG export, 19 cols): `sample_identifier`, `label`, `description`, `produced_by {sampling_site {sample_location {latitude, longitude, ...}}}`, etc.
- **Query pattern**: one row per sample; no JOINs needed for basic queries.
- **DuckDB**: download the parquet from Zenodo, then
  `SELECT * FROM read_parquet('isamples_export_*.parquet') LIMIT 10`.

### 4.2 `isamples_202512_narrow.parquet`

- **Role**: PQG narrow format — the canonical, lossless graph-normalized representation.
- **Headline schema** (40 cols): `row_id, pid, otype, s, p, o, n, altids, geometry, ...entity-specific columns...`. Edges are rows with `otype='_edge_'` and populated `s/p/o`.
- **Query pattern**: multi-hop JOIN via `_edge_` rows (see PQG §2.2).
- **DuckDB**:
  ```sql
  SELECT COUNT(*) FROM read_parquet('https://data.isamples.org/isamples_202512_narrow.parquet')
  WHERE otype = 'MaterialSampleRecord';
  ```

### 4.3 `isamples_202601_wide.parquet`

- **Role**: PQG wide format — primary analytic substrate for Explorer + notebook.
- **Headline schema** (49 cols): same core columns as narrow, plus `p__produced_by`, `p__sample_location`, `p__sampling_site`, `p__site_location`, `p__responsibility`, `p__registrant`, `p__has_material_category`, `p__has_context_category`, `p__has_sample_object_type`, `p__keywords`, `p__curation`, `p__related_resource` — each an `INT32[]` of target `row_id`s.
- **Query pattern**: entity-centric; relationships via array-element JOIN (see PQG §3.2).
- **DuckDB**:
  ```sql
  SELECT source, COUNT(*) FROM read_parquet('https://data.isamples.org/isamples_202601_wide.parquet')
  WHERE otype = 'MaterialSampleRecord' GROUP BY 1 ORDER BY 2 DESC;
  ```

### 4.4 `isamples_202604_wide.parquet`

- **Role**: 202601 wide enriched with ~47 K OpenContext thumbnails. `current/wide.parquet` 302-redirects here.
- **Headline schema**: identical to 202601 wide (49 cols). Only the `thumbnail_url` column on OC `MaterialSampleRecord` rows is populated differently.
- **Query pattern**: drop-in replacement for 202601 wide; use `current/wide.parquet` unless you need a pinned version.
- **DuckDB**:
  ```sql
  SELECT COUNT(*) FROM read_parquet('https://data.isamples.org/current/wide.parquet')
  WHERE thumbnail_url IS NOT NULL;
  ```

### 4.5 `isamples_202601_wide_h3.parquet`

- **Role**: Wide with H3 indices pre-joined, so H3 predicates don't need a join.
- **Headline schema** (52 cols): wide columns + `h3_res4`, `h3_res6`, `h3_res8` (BIGINT).
- **Query pattern**: direct H3-cell filtering without an H3 UDF.
- **DuckDB**:
  ```sql
  SELECT COUNT(*) FROM read_parquet('https://data.isamples.org/isamples_202601_wide_h3.parquet')
  WHERE h3_res6 = 604932829406232575;
  ```

### 4.6 `isamples_202601_h3_summary_res{4,6,8}.parquet`

- **Role**: Zoom-adaptive aggregates that back the Cesium progressive globe and the Python Explorer's "H3 tier" rendering mode.
- **Headline schema** (7 cols, identical across resolutions): `h3_cell` (BIGINT), `sample_count` (INT), `center_lat`, `center_lng` (DOUBLE), `dominant_source` (VARCHAR), `source_count` (INT), `resolution` (INT).
- **Query pattern**: fetch the right resolution for the current zoom; no join needed.
- **DuckDB**:
  ```sql
  SELECT * FROM read_parquet('https://data.isamples.org/isamples_202601_h3_summary_res6.parquet')
  ORDER BY sample_count DESC LIMIT 20;
  ```

### 4.7 `isamples_202601_samples_map_lite.parquet`

- **Role**: Display projection for point-level map rendering. Contains only `MaterialSampleRecord` rows with valid coordinates.
- **Headline schema** (9 cols): `pid, label, source, latitude, longitude, place_name, result_time, h3_res8, h3_res8_hex`. **No `description`** — it's in wide only.
- **Query pattern**: the Explorer reads this directly when altitude drops below the point-render threshold.
- **DuckDB**:
  ```sql
  SELECT source, COUNT(*) FROM read_parquet('https://data.isamples.org/isamples_202601_samples_map_lite.parquet')
  WHERE latitude BETWEEN 32 AND 42 GROUP BY 1;
  ```

### 4.8 `isamples_202601_sample_facets_v2.parquet`

- **Role**: Cross-dimension facet filtering — one row per sample, facets expanded as arrays of URI strings.
- **Headline schema** (8 cols): `pid, source, material, context, object_type, label, description, place_name`. `material`/`context`/`object_type` are string arrays of controlled-vocabulary URIs.
- **Query pattern**: `WHERE list_has_any(material, ['<uri>', ...])` for multi-select facets.
- **DuckDB**:
  ```sql
  SELECT pid FROM read_parquet('https://data.isamples.org/isamples_202601_sample_facets_v2.parquet')
  WHERE 'https://w3id.org/isample/vocabulary/material/rock' = ANY(material) LIMIT 10;
  ```

### 4.9 `isamples_202601_facet_summaries.parquet`

- **Role**: Baseline (no-filter) facet counts. Loaded by every tutorial at startup.
- **Headline schema** (4 cols, 56 rows): `facet_type` (source|material|context|object_type), `facet_value`, `scheme`, `count`.
- **Query pattern**: sort by `count DESC` to render a top-N facet list.
- **DuckDB**:
  ```sql
  SELECT * FROM read_parquet('https://data.isamples.org/isamples_202601_facet_summaries.parquet')
  WHERE facet_type = 'material' ORDER BY count DESC;
  ```

### 4.10 `isamples_202601_facet_cross_filter.parquet`

- **Role**: Cross-facet counts for the single-active-filter case (QUERY_SPEC §3.3 tier 2a). Avoids recomputing when one facet dimension is active.
- **Headline schema** (7 cols, 526 rows): `filter_source, filter_material, filter_context, filter_object_type, facet_type, facet_value, count`. Exactly one `filter_*` column is non-NULL per row.
- **Query pattern**: lookup by the active filter to get counts for the remaining dimensions.
- **DuckDB**:
  ```sql
  SELECT facet_type, facet_value, count FROM read_parquet('https://data.isamples.org/isamples_202601_facet_cross_filter.parquet')
  WHERE filter_source = 'SESAR' ORDER BY facet_type, count DESC;
  ```

### 4.11 `oc_isamples_pqg.parquet` and `oc_isamples_pqg_wide.parquet` (OC variants)

- **Role**: OpenContext-specific PQG files maintained by Eric Kansa. Hosted at
  `https://storage.googleapis.com/opencontext-parquet/`, **not** under
  `data.isamples.org`. They are not part of the cross-source substrate —
  they carry OC-internal detail (notably `thumbnail_url`) that the
  aggregated Zenodo export drops.
- **Headline schema**: PQG narrow (40 cols) and wide (47 cols). OC wide has slightly fewer `p__*` columns than the unified wide — this is schema drift, not semantically meaningful for standard queries.
- **Consumer**: `scripts/enrich_wide_with_oc_thumbnails.py` uses OC narrow to fill thumbnails into 202604 unified wide. Also used directly in PQG benchmark work.
- **Future**: these become the prototype upstream for per-source sidecars (see §3, bottom row).

## 5. URL convention

All substrate files live under `https://data.isamples.org/` — a
Cloudflare Worker fronting an R2 bucket. The Worker provides:

- **Versioned URLs** `https://data.isamples.org/isamples_<YYYYMM>_<variant>.parquet`
  — 1-year immutable cache. Safe to pin in papers, Zenodo manifests,
  reproducibility notebooks.
- **Alias URLs** `https://data.isamples.org/current/<alias>` — 302
  redirect with 5-min cache; always resolves to the latest snapshot.
  Use for "always fresh" consumers. Currently
  `current/wide.parquet → isamples_202604_wide.parquet`.

**Never reference the raw
`pub-a18234d962364c22a50c787b7ca09fa5.r2.dev/...` URL.** It bypasses
the Worker and defeats both the alias layer and the Cache-Control
headers that DuckDB-WASM relies on for HTTP range requests.

OpenContext-specific variants live at
`https://storage.googleapis.com/opencontext-parquet/` and are
maintained outside this convention.

## 6. Relationship to other documents

- **[`query-spec.qmd`](query-spec.qmd)** §5.1 — the DuckDB binding table,
  which maps query-spec dimensions (`source`, `material`, `bbox`, `h3`,
  `time`, `text`) to the specific parquet files above. This catalog
  says *what* the files are; the query spec says *which dimension*
  each file serves.
- **`ZENODO_DEPOSITION_PLAN.md`** (in the monorepo root) — specifies
  which subset of these files are archived in each Zenodo deposition.
  The 202601 deposition bundles the 10 R2-served files plus a
  `MANIFEST.json` and `README.md`. Source-specific OC variants and
  the raw Zenodo export are **not** part of the substrate deposition.
- **[`pqg/docs/PQG_SPECIFICATION.md`](https://github.com/isamplesorg/pqg/blob/main/docs/PQG_SPECIFICATION.md)** — defines the three canonical formats
  (export, narrow, wide) whose schemas the primary files conform to.
  §3.5 is the normative section.
- **`pqg/docs/conformance_matrix.md`** (planned) — will document, for
  each file above, exactly which clauses of the PQG spec it satisfies
  (required columns, allowed `otype` values, edge-type constraints,
  etc.). This catalog is the prose companion; the conformance matrix
  will be the machine-checkable companion.
- **`project_isamples_sidecar_pattern.md`** (memory) — planning for
  per-source sidecars that would sit alongside the unified wide file
  rather than being folded in at build time (as OC thumbnails
  currently are). When that lands, it adds a new tier to §3.

---

*Last updated: 2026-04-24 by iSamples team. Row counts and sizes
verified by DuckDB against `https://data.isamples.org/` on the same
date.*
