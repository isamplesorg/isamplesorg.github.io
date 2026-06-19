# Session Summary

## Session: 2026-06-18 (evening) — #300 filtered clusters at world zoom
**Directory**: /Users/raymondyee/C/src/iSamples/isamplesorg.github.io
**Trust Level**: medium (local Playwright + DuckDB; downloaded 3 R2 artifacts read-only; no prod writes, no secrets)

---

## What Happened
Implemented **issue #300** — when a facet filter is active at world zoom, render a
filtered H3-cluster view instead of forcing slow capped point mode (#267). Plus a
prerequisite behavior-neutral refactor (PR4c).

### Shipped to PRs
- **PR4c (#301, OPEN)** — `refactor/208-computeTargetMode`: extracted
  `filtersForcePoint()` + `computeTargetMode()` (centralize the point/cluster mode
  decision that was duplicated at 4 sites). Behavior-neutral; Codex-approved;
  unit 13/13 + characterization green. **Should merge before the #300 PR.**

### #300 work (branch `feat/300-filtered-clusters`, stacked on PR4c — NOT yet PR'd)
Commits:
- `837e877` build: add `h3_res4`/`h3_res6` to `samples_map_lite` (+validator/tests 23/23)
- `ffe904d` C1 infra: filter-aware `loadRes`, `filteredClustersReady` preflight, semantic cluster sig
- `f558c31` C2 activation: facets → filtered clusters above EXIT_POINT_ALT
- `8c9f2c4` C3 coherence: deep-link/boot restore, filtered click hydration, facet note
- `3891aaf` Codex round-2: P0 (missed `_urlHasFacets` boot force-point block) + 7 P1s
- `b6f32e7` **boot-deadlock fix** + verification spec
- `d4c0280` Codex serialization-review fixes (remove lossy `!loading` guards, dedup)

---

## Safe to Carry Forward

### Key decisions / discoveries
- **THE hard bug**: filtered clusters never loaded at world zoom because the heavy
  `filteredClusterSQL` query, issued during boot's concurrent query storm,
  **deadlocked DuckDB-WASM** (non-threaded MVP build). Identical query runs in
  ~2.5s once idle; even 2 concurrent post-boot queries are fine. **Fix: serialize
  all `db.query` through a FIFO chain** in the `db` cell (single point; all 45
  data calls use `db.query`, verified). Without it the feature is invisible.
- Feature **gates on `filteredClustersReady`** (lite has res4/res6) AND
  `window.__nodeBits` (masks fast-path). If absent → `computeTargetMode` keeps
  pre-#300 point-mode behavior. **So the #300 code PR can merge BEFORE the data
  republish — feature stays dormant until the lite is updated.**
- H3 cells don't strictly nest: `h3_latlng_to_cell(...,4)` ≠ parent of
  `...(...,8)`. The build computes each res independently; the local lite regen
  (`scripts/regen_lite_res46.py`) matches by validating against the shipped h3
  summaries (exact), not by parent-consistency.
- Codex reviewed 3× (design, implementation, serialization) — all findings fixed.

### Verification (local, `dev_server.py` on :8099 serving res46 lite, explorer on :5860)
- `tests/playwright/filtered-clusters-300.spec.js` [data]: broad facet
  (`anyanthropogenicmaterial`) at world zoom → `_clusterFilterSig` kind:filtered,
  cluster mode (not point), 81 res4 cells, **count conservation** (cluster sum ==
  masks-backed `COUNT(*)`); zoom-in → point. **2 passed.**
- Offline: `filteredClusterSQL` sums == direct filtered counts at every res.
- Regression (explorer-characterization + url-roundtrip, production data, feature
  dormant): confirms serialization didn't break boot. The `(e)` facet-hydration
  test is a known cold-cache flake (unrelated; passes warm).

### New data artifact (validated, NOT yet uploaded)
- `~/Data/iSample/pqg_refining/staged_202608/isamples_202608_samples_map_lite_res46.parquet`
  (48 MB; res4/res6 added; reproduces shipped h3 summaries exactly).

---

## Open Threads / Next Session Entry Point

> **Start here:** #300 is implemented + verified locally; both PR4c and #300 are
> green. RY chose: **merge #301 first, then open #300**, and activate via a
> **versioned `_v2` lite filename**. Coordinated rollout sequence:
>
> 1. **RY merges PR4c #301** (neutral refactor; green + Codex-approved).
> 2. **CC rebases** `feat/300-filtered-clusters` onto the merged `upstream/main`,
>    adds the **`lite_url` → `isamples_202608_samples_map_lite_v2.parquet`** change
>    (+ a local serve-dir symlink so the verify spec still passes), pushes, opens
>    the **#300 PR**. (`diag-300.spec.js` already deleted; keep
>    `filtered-clusters-300.spec.js`.)
> 3. **RY uploads** the staged `_v2` lite to R2 bucket `isamples-ry` (Touch ID):
>    `~/Data/iSample/pqg_refining/staged_202608/isamples_202608_samples_map_lite_v2.parquet`
>    (48 MB, res4/res6/res8). **MUST happen before merging #300** — `lite_url`
>    points at `_v2`, so a missing `_v2` would 404 the explorer's lite entirely.
> 4. **RY merges #300** → feature live (filtered clusters activate immediately,
>    since `_v2` carries res4/res6).
>
> Watch-item: the `db.query` serialization (boot-deadlock fix) ships to all users
> and makes boot queries sequential. Local boot is fast; measure real-network boot
> latency during review. Fallback if too slow: defer only the heavy filtered query
> until the connection is idle (keep other queries concurrent).

### Deferred / known
- `(e)` characterization test is cold-cache flaky (environmental, not #300).
- `listings.json` 404 = Quarto issue #295 (benign, pre-existing).
- Serialization caveat: a query that never settles would stall the whole queue
  (documented in the `db` cell). No such caller today.

---

## Session History
| Date | Trust | Summary |
|------|------|---------|
| 2026-06-18 pm | medium | #300 filtered clusters: build+C1/C2/C3+Codex×3+boot-deadlock fix; verified local; PR4c #301 open |
| 2026-06-18 am | high-risk | Shipped #290 cube + #293 masks to prod (#298/#299); Tiered Cache; filed #300 |
