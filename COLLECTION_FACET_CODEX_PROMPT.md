# Codex prompt — Option A: first-class `collection` facet in the iSamples explorer

> Paste the block below into Codex (run from `~/C/src/iSamples/isamplesorg.github.io`,
> which has `AGENTS.md`; the repo root has `.codex/config.toml` with Playwright MCP).
> Tracks issue isamplesorg/isamplesorg.github.io#243. Plan-first with a sign-off gate.

---

```
GOAL
Add a first-class "collection" dimension to the iSamples interactive explorer
(explorer.qmd) so users can filter samples to a named collection — e.g. the
OpenContext project "PKAP Survey Area" — and layer the existing material /
context / object_type facets on top. Full background, data analysis, and the
two-phase plan are in issue #243.

DO THIS IN TWO STAGES. Stage 1: produce a written implementation plan and STOP
for my sign-off. Stage 2 (only after I approve): implement.

=== KEY DESIGN FACTS (already verified — do not re-derive) ===
- A "collection" is the `label` of a SamplingSite entity. It is NOT on the
  MaterialSampleRecord rows; it is reached by traversal:
    MaterialSampleRecord.p__produced_by[1] -> SamplingEvent
    SamplingEvent.p__sampling_site[1]       -> SamplingSite.label
  (All within the wide parquet; `otype` column distinguishes entity types.)
- Cardinality: ~60,268 distinct SamplingSite labels; only ~1.63M of 6.35M
  samples have a site (sparse facet, mostly OpenContext). PKAP = 15,446 samples.
- Doing this traversal LIVE in DuckDB-WASM per interaction is NOT viable (it is
  the array-join pattern profiled as the in-browser bottleneck). MUST precompute.
- Data is served from https://data.isamples.org/ (Cloudflare Worker -> R2).
  NEVER reference raw pub-*.r2.dev URLs.

=== HOW FACETS WORK TODAY (anchors in explorer.qmd) ===
- Parquet URL constants: R2_BASE (:683), wide_url=/current/wide.parquet (:690),
  facets_url=…sample_facets_v2.parquet (:692), facet_summaries_url (:693),
  cross_filter_url (:695), vocab_labels_url (:698), lite_url (:687),
  h3_res{4,6,8}_url (:684-686).
- The facet filter predicate (:942):
    AND pid IN (SELECT DISTINCT pid FROM read_parquet('${facets_url}')
                WHERE <conds>)
  i.e. per-sample facet values live in sample_facets_v2.parquet, keyed by pid.
- Facet checkbox lists + counts are rendered by renderFilter(...) (:~1792) from
  facet_summaries (value -> count); cross-filtered counts use facet_cross_filter.
- material/context/object_type values are vocabulary URIs labeled via
  vocab_labels.parquet. NOTE: a collection's "value" is a SamplingSite identity
  (site_id) labeled from the NEW collections dimension below — NOT a vocab URI.
- URL/state contract is normative in EXPLORER_STATE.md. The four query params
  today are search, sources, material, context, object_type (+ search_scope).
  A new `collection` param must follow the SAME lifecycle as `material`:
  applyQueryToFacetFilters (hydrate), handleFacetFilterChange ->
  writeQueryState() (write-back), cross-filter count recompute, param removed
  when empty. Honor the Quarto `?q=` collision note (use `collection`, not `q`).
- Cluster-mode honesty: H3 summary parquets only carry dominant_source, so
  material/context/object_type filters do NOT affect zoomed-out clusters (the
  #facetNote). A `collection` facet inherits this unless collection is also
  added to the H3 summaries — call this out; do not silently break the note.

=== STEP 0 (do first, report findings) ===
Locate the build pipeline that PRODUCES the supplementary parquets
(sample_facets_v2, samples_map_lite, h3_summary_res{4,6,8}, facet_summaries,
facet_cross_filter) and uploads them to R2. They are NOT in this repo's
scripts/. Search the sibling repos and data dirs:
  ~/C/src/iSamples/{isamples-python,pqg,isamplesorg.github.io-duckdb-spike}
  ~/Data/iSample/  (esp. pqg_refining/)
and any notebooks. Also read workers/data-isamples-org/README.md for the R2
serving/versioning layer. Report exactly how each file is built and uploaded,
or state that a build path must be created from scratch.

=== STAGE 1 DELIVERABLE: a written plan covering ===
1. Build: a new script (e.g. scripts/build_collections.py) that, from
   /current/wide.parquet, computes per-sample (pid -> site_id, site_label) via
   the traversal, and emits:
     a) collections.parquet  — dimension, ~60K rows:
        site_id, label, source, n_samples, centroid_lat, centroid_lng,
        bbox(min/max lat/lng). Powers the "search the long tail" half of the UX
        and the Featured-Collections presets (collections.qmd).
     b) an added `site_id` (+ maybe site_label) column on sample_facets_v2
        (regenerate as v3 if v2's builder is unavailable; keep pid as the key so
        the :942 predicate extends with one more AND condition).
     c) collection rows in facet_summaries (site_id -> count) so the checkbox
        list + counts render via the existing machinery. Decide whether to add
        collection to facet_cross_filter now or defer (note the consequence).
   Define a stable site_id (hash of label, or the SamplingSite pid). Specify
   versioned filenames + the /current alias, consistent with existing files.
2. Explorer wiring (explorer.qmd), mirroring `material` exactly:
   - new collection facet container + a `?collection=` URL param on the
     EXPLORER_STATE.md lifecycle.
   - DUAL UX (my decision): top-N collections (>= a sample-count threshold) as
     checkboxes reusing renderFilter; PLUS a type-to-search input over
     collections.parquet for the long tail (60K). Specify how a search-selected
     collection becomes an active filter value alongside the checkboxes.
   - extend the :942 predicate (or facets subquery) with the collection
     condition; ensure cross-filter counts and #facetNote stay correct.
3. data.qmd + collections.qmd updates: document collections.parquet; once the
   facet exists, upgrade the Featured-Collections preset links from
   geographic-only to a real &collection=<site_id> filter.
4. Test plan: extend tests/ (pytest + Playwright). At minimum a Playwright check
   that ?collection=<PKAP site_id> yields the PKAP sample set and that layering
   ?material=… narrows it; reproducible DuckDB snippets for the counts.
5. Risks / migration: snapshot-version coupling (site_id stability across
   rebuilds), the sparse-facet UX for non-collection sources, cluster-mode
   honesty, and file-size deltas.

=== CONSTRAINTS ===
- Read AGENTS.md, ../CLAUDE.md, EXPLORER_STATE.md before planning.
- explorer.qmd is ~3,500 lines of working OJS/JS — make INCREMENTAL, additive
  changes mirroring existing facet code; do not refactor working paths.
- Quarto OJS gotcha: cells use `name = value`, NOT top-level const/let/var.
- Static site, no hot reload: note where `quarto preview` + browser refresh is
  needed to verify.
- Verify against https://data.isamples.org/ only; never raw pub-*.r2.dev.
- STOP after the Stage 1 plan and wait for my approval before writing code.
```
