# CANONICAL.md — which data files are real, and which are accidental history

*Created 2026-07-23 (grant closing week) to answer: "can we simplify our stable of
supplementary parquet files?" Answer: the **live set is already minimal** — the
accumulation is superseded versions and orphan snapshots around it. This file
names the canonical set and documents every non-canonical survivor so the
accident is neutralized even where files remain on the bucket.*

**Companion:** the machine-readable release manifest
(`tools/build_release_manifest.py` → `isamples_202608_release_manifest.json`)
enumerates the same canonical set with sizes/checksums; the Explorer cross-checks
it at boot (#334 v0). A file absent from the manifest is non-canonical **by
definition**.

## 1. The canonical (live) set — 202608

Exactly what production `explorer.qmd` loads, all under `https://data.isamples.org/`:

| File | Role (plain English) |
|---|---|
| `isamples_202608_wide.parquet` | Full sample detail, one row per entity — everything derives from this |
| `isamples_202608_samples_map_lite_v3.parquet` | Slim map/table columns (coords, label, place, date, h3 cells) |
| `isamples_202608_sample_facets_v4.parquet` | Per-sample facet URIs + search-text blob (the `?fts=off` scan target) |
| `isamples_202608_h3_summary_res{4,6,8}.parquet` | Pre-counted globe clusters at 3 zoom tiers |
| `isamples_202608_facet_summaries.parquet` | Facet checkbox counts, no filters active |
| `isamples_202608_facet_cross_filter.parquet` | Facet counts under single cross-filter |
| `isamples_202608_facet_tree_summaries.parquet` | Hierarchical (tree) facet counts |
| `isamples_202608_facet_tree_cross_filter.parquet` | Tree facet counts under cross-filter |
| `isamples_202608_sample_facet_membership.parquet` | Sample↔facet-tree membership |
| `isamples_202608_sample_facet_masks.parquet` | Bitmask substrate for multi-filter counts |
| `isamples_202608_facet_node_bits.parquet` | Facet-node bit assignments for the masks |
| `isamples_202608_sample_facet_index.parquet` | Per-sample facet index (multi-filter fast path) |
| `isamples_202608_sample_facet_index_meta.parquet` | ~1 KB trusted manifest for the above (#313/#317 boot-race fix) |
| `vocab_labels_202608.parquet` | URI → human label (539 entries; verified complete 2026-07-22) |
| `isamples_202608_search_index_v1/` | Sharded FTS index — the default search since 2026-07-17. Runtime loads: `build_stats.json`, `hot_tokens.json`, `shard_sizes.json`, `hot_topk.parquet`, + 256 base token shards and ~591 hot-token sub-files (852 objects total incl. sidecars; base inventory in `shard_sizes.json`, totals in `build_stats.json`); `df.parquet` is offline-only |

The ~9-file facet family looks baroque but is load-bearing: it is the price of
fast multi-filter counts with no server. See `EXPLORER_QUERIES.md` for how each
is queried and `DATA_PROVENANCE.md` for how each is built.

## 2. Superseded versions (still served; do not use)

Each suffix bump was a real fix that left its predecessor in place — the #326
incident ("two sibling files silently diverged in vintage") is what happens when
nothing marks the old ones dead. That marking is this table.

| Superseded file | Replaced by | Why (the bump's fix) |
|---|---|---|
| `isamples_202608_sample_facets_v2.parquet` | `_v3` | concept labels folded into search text (#277; v2 introduced in `10fd415`, bumped in `8a6ebf5`) |
| `isamples_202608_sample_facets_v3.parquet` | `_v4` | place_name folded into search text (#326, `7e900a0`) — **the file whose staleness caused the #326 bug** |
| `isamples_202608_samples_map_lite.parquet` | `_v2` | h3_res4/res6 columns for filtered clusters (#300, `1715142`) |
| `isamples_202608_samples_map_lite_v2.parquet` | `_v3` | corrected place_name + Array.isArray fix (#311, `3f2f20a`) |

**Policy going forward:** a suffix bump MUST add a row here and regenerate the
release manifest in the same change. (The manifest makes violations visible at
boot; this table makes them legible to humans.)

## 3. Snapshot generations (who serves whom)

| Generation | Status |
|---|---|
| `isamples_202512_*` | Narrow only — **archival** (in the Zenodo deposit; there is no 202601 narrow — known label mismatch, documented in the deposit README) |
| `isamples_202601_*` | **Archival** — the coherent snapshot in Zenodo draft 21288719 |
| `isamples_202604_*` | **NOT orphan — backs the stable `/current/wide.parquet` alias** used by data.qmd and multiple tutorials (see SERIALIZATIONS.md). Must NOT be moved until the alias is repointed and consumers audited |
| `isamples_202606_*` | Pipeline intermediate (the #272 OC-concept-enriched wide that fed 202608 — see DATA_PROVENANCE.md step 3b). Not loaded by anything at runtime; safe to attic post-grant, lineage documented |
| `isamples_202608_*` | **Live** (production Explorer) |

## 4. Conveniences (not load-bearing; fine to keep, labeled)

| File | Note |
|---|---|
| `isamples_202601_wide_h3.parquet` | Analyst convenience (wide + precomputed H3 cells). In the Zenodo deposit; NOT loaded by the Explorer |
| `*.csv` twins of lite/H3 (~640 MB) | Convenience exports; parquet is authoritative; excluded from Zenodo by design |

## 5. Post-grant simplification options (deliberately NOT done in-grant)

1. Move §2's superseded versions and the 202606 pipeline intermediate to an `/attic/` prefix on R2 (don't delete — old
   notebooks/links may reference them). Needs R2 write credentials.
2. Collapse the facet family only alongside a real pipeline rework — the current
   9 files trade storage (cheap) for browser CPU (scarce); collapsing them is an
   engineering project, not cleanup.
3. If a fresher export ever lands (#320), cut ONE coherent generation and retire
   202608 wholesale via the manifest.
<!-- cc:2026.07.23 -->
