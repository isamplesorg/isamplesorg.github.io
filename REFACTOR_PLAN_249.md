# Draft comment for isamplesorg/isamplesorg.github.io#249

> Paste-ready draft for the refactor-window plan. Edit freely — written
> 2026-06-12 alongside the PR that wires the e2e gate (PR 1 below).

---

## Refactor window: concrete PR sequence

Following up on the 2026-06-05 update above: here is the staged plan for
the refactor window, structured so every stage lands behind a green
browser-level gate and no stage requires a big-bang diff. The method is
still Option C (strangler / extract-along-seams); what's new is the
explicit sequencing and the regression gate that goes in *first*.

### PR 1 — CI safety net (this is the only infrastructure PR)

Wire the existing Playwright browser specs into CI before anything in
`explorer.qmd` moves:

- New workflow `explorer-e2e.yml`: renders `explorer.qmd` with Quarto,
  serves `docs/` with the repo's range-capable `dev_server.py`, runs a
  headless-Chromium **smoke set** on every PR that touches the explorer
  (page boots with no uncaught/OJS-cell errors, Cesium canvas draws at
  non-zero size, facet sidebar renders, search box present).
- The smoke set deliberately does **not** wait on parquet loads from
  data.isamples.org, so slow data can't flake the gate. The deeper
  data-dependent specs (facet viewport, URL round-trip, heatmap, search
  counts) stay runnable on demand via `workflow_dispatch` with a spec
  filter, and locally per `tests/README.md`.
- This complements (doesn't replace) the pre-deploy DuckDB-liveness gate
  already in `quarto-pages.yml` / `tests/test_smoke.py`: that one guards
  *deploys to production*; this one guards *PRs*, which is where refactor
  regressions need to be caught.

**Gate rule for every PR below: the smoke set must stay green, and any
stage that touches a seam covered by a deeper spec runs that spec
manually before merge.**

### PR 2 — characterization tests around the seams we're about to cut

Cheap, compounding (step 1 of the 2026-06-05 plan): turn the recent
symptom reports into specs *before* moving code — #260 (detail-card
material/category), #265 (facet label provenance), #267 (facet selection
drives the map; partially latched already), back/forward + deep-link
round-trip (#239's divergence case). #266 is already covered by the
updated `explorer-map-overlay.spec.js` assertion. These are
characterization tests: they pin current *intended* behavior, not new
features.

### PR 3 — extract pure logic into `assets/js/` ES modules (lowest risk)

The step the original analysis sized at ~500 lines, near-zero risk: SQL
builders (`facetFilterSQL`, `sourceFilterSQL`, `textSearchWhere`/`Score`),
hash codec (`readHash`/`buildHash`), bbox math (`paddedViewportBounds`/
`viewerBboxSQL`), card renderers, escapers. The explorer already imports
`assets/js/source-palette.js` at runtime, so the mechanism is proven.
Pure functions become unit-testable outside the browser; this PR also
directly answers #268's "where does the SQL live?" — the answer becomes a
file path instead of a line range in a 5.4k-line qmd. Includes the
parquet-URL registry / plain-English query doc from the 2026-06-05 plan.

### PR 4 — URL/state codecs + single-writer boundary (#208)

Extract the state codecs (search params, hash state, selection, heatmap,
source/facet selections — the `EXPLORER_STATE.md` inventory), then land
#208's two fixes on top of the now-isolated codec: collapse the dual
`mode` state to `viewer._globeState.mode` as single source of truth, and
funnel the ~8 URL writers through `writeGlobeHash` / `setExplorerMode` /
`reconcileCameraState`. This is the stage that de-risks every future
"interactive state diverges from cold-reload state" bug (#239, #262).

### PR 5 — split controllers out of `zoomWatcher`, one seam at a time

The god-closure (~2,200 lines) gets carved along its already-namespaced
seams, heatmap first (`viewer._heatmap*` state is already hoisted —
the seam the original analysis rated highest-risk, so it goes last among
extractions but first among controllers since its state is cleanest),
then facet panel, samples table, search panel, map mode/rendering.
Each seam = one PR, each behind the gate plus the relevant deep spec.
#189's selection controller (`selectSample`/`selectCluster`/
`clearSelection`) joins this stage **only if** its YAGNI trigger has
fired by then — per that issue, it stays filed until a selection feature
or recurrence forces it.

### Explicitly deferred

- The "should this become a Vite/TS app embedded in Quarto?" question
  (open question 1 in the issue body) — decide *after* PR 5, when the
  module boundaries make the cost visible. Not a prerequisite for any
  stage above.
- #234's filter-semantics direction (A1+B1+C3/C2) is *feature* work, not
  refactor work — but PR 3/PR 4 are sequenced so that when #234
  implementation starts, search/facet predicates and URL state are
  already modules it can build on instead of more closure growth.
- No UI redesign, no data-substrate changes, no Quarto replacement
  (non-goals from the 2026-06-05 comment stand).

### Coordination

While PRs 3–5 are open, feature work in `explorer.qmd` freezes only on
the seam being moved (answer to open question 2: per-seam freeze, not a
page-wide freeze). `EXPLORER_STATE.md` gains a module-boundary section as
each extraction lands (open question 3: yes, same doc).
