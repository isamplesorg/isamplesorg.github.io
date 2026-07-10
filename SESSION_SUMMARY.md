# Session Summary

## Session: 2026-07-03 — Eric/Andrea Explorer fixes shipped to prod; #311 place/date; John K showcase
**Directory**: /Users/raymondyee/C/src/iSamples/isamplesorg.github.io
**Trust Level**: high-risk (used R2 credentials via 1Password service-account token → uploaded to production `isamples-ry` bucket; merged 2 PRs to production isamples.org; posted public GitHub comments; browser automation against live sites)

---

### What Happened

Worked the open issues from Eric Kansa, Andrea Thomer, and John Kunze. Shipped several to production; one prototype awaiting John.

**Merged to production isamples.org (verified live, fresh browser context):**
- **PR #318** — Eric #295 (listings.json 404 → ship static empty-array `listings.json`), Andrea #311 (samples-table Material/Object type/Sampled feature columns + the pipeline fix for blank Place/Date), Andrea #312 (Download CSV button, 50k cap). Two Codex rounds (empty-array COALESCE, CSV `\r`+formula-injection); final LGTM.
- **PR #319** — deployed the #311 place/date fix to real data: rebuilt `samples_map_lite` from the live wide (verified byte-identical first), uploaded as **`isamples_202608_samples_map_lite_v3.parquet`** (NEW filename — never overwrite the immutable-cached `_v2`), pointed `lite_url` at it. Surfaced + fixed a latent `Array.isArray()` bug (see gotchas). Codex LGTM.

**Also written (docs) / posted:**
- `EXPLORER_QUERIES.md` (Eric #268 — plain-English explainer of which parquet files the Explorer queries).
- `ISSUE_313_GUIDANCE_2026-07-03.md` (Andrea #313 — bandwidth/browser guidance draft, NOT yet posted to the issue).
- Verified #278 (John K's original PID ask): search-by-PID half already shipped; charismatic-samples half is #142.

**John Kunze showcase thread (#142) — prototype only, NOT merged:**
- Front-page "charismatic samples": 2 of 4 (diamond, fish) are real specimens at their source repos but NOT in the iSamples aggregation; coral + askoi ARE in.
- **I twice wrongly called John's photos "stock/illustrative." They are real photos of real specimens** he/Saebs/Eric each personally sourced. Corrected on-thread ([#142 comment](https://github.com/isamplesorg/isamplesorg.github.io/issues/142#issuecomment-4878706706)).
- **PR #321** (branch `fix/142-showcase-honest-links`): keeps ALL John's images/links untouched, adds one line deep-linking the 2 in-collection samples into the Explorer (`/explorer.html#pid=<pid>&v=1`, both verified working live). Assigned to jkunze.
- **#320** filed: ingest the 2 missing specimens (SESAR diamond, Smithsonian fish) — separate data gap.

**Dropped:** PR-specific preview deploys (rossjrw/pr-preview-action). Codex + GitHub docs confirmed it can't work for this repo's fork-only PRs without either `pull_request_target` (security anti-pattern) or the "Send write tokens to fork PRs" repo setting (too broad). Branch deleted. Raymond said forget it.

---

### Safe to Carry Forward

**Gotchas / patterns (load-bearing):**
- **Arrow Vector ≠ Array**: DuckDB-WASM / Observable `DuckDBClient` returns `VARCHAR[]` columns as an Arrow `Vector` (iterable, has `.length`, but `Array.isArray()` is FALSE). Use `Array.from()` with a null-guard. This silently blanked `place_name` for years until #311 gave it real data. Helper: `formatPlaceName()` in `assets/js/explorer-utils.js` (unit-tested).
- **R2 immutable-cache rule**: `data.isamples.org/*.parquet` is served `Cache-Control: immutable, max-age=31536000`. NEVER overwrite a filename — always a new suffix (`_v3`, etc.). Overwriting leaves broken cached copies at CDN edges + browsers for up to a year.
- **10-min JS cache = false-positive stale errors**: `assets/js/*.js` on GitHub Pages has `Cache-Control: max-age=600`. Repeated same-session Playwright testing kept showing phantom `formatPlaceName is not a function` errors — pure browser cache staleness. **Always verify deploys with a FRESH isolated context** (`browser.newContext()` via `browser_run_code_unsafe`), never a reused tab.
- **Deploy cadence**: fork (`rdhyee`) preview via `gh workflow run "Render using Quarto and push to GH-pages" --ref <branch>` → verify `rdhyee.github.io/isamplesorg.github.io/...` → Codex review → PR to upstream `main` → merge (`--merge`, matches #317/#318 convention) → prod deploy fires on push to main (~5 min, includes Playwright smoke gate) → verify isamples.org.
- **R2 upload**: `op://Private/Cloudflare R2 Admin Token - All Buckets` (via `op run --env-file`), bucket `isamples-ry`. Script refuses to overwrite an existing key (immutable-cache safety). `cloudflare-r2` skill has the boto3 pattern.
- **#311 pipeline fix**: `place_name`/`result_time` are 100% NULL on MaterialSampleRecord directly; real values come via `Sample -produced_by-> SamplingEvent [-sampling_site-> SamplingSite]` traversal (in `build_frontend_derived.py`'s `samp` CTE). Deploying it requires a `samples_map_lite` rebuild + R2 upload (done: `_v3`).

**Files changed / created (all committed):**
- `explorer.qmd` (table columns, CSV export, `formatPlaceName`), `assets/js/explorer-utils.js` (+`formatPlaceName`), `scripts/build_frontend_derived.py` (traversal), `tests/test_frontend_derived.py` + `tests/unit/explorer-utils.test.mjs` (new tests), `_quarto.yml` + `listings.json`, `EXPLORER_QUERIES.md`, `ISSUE_313_GUIDANCE_2026-07-03.md`, `index.qmd` (#321 branch).

**Data artifacts:**
- Live R2: `isamples_202608_samples_map_lite_v3.parquet` (place/date fix, in prod). Local build: `/tmp/rebuild_311/` (ephemeral).

---

## External Content Processed

| Source | Type | Notes |
|--------|------|-------|
| GitHub issues/PRs #142/#278/#295/#311/#312/#313/#268 + comments | GitHub (Eric Kansa, Andrea Thomer, John Kunze) | Trusted collaborators; John corrected my "stock photos" error |
| Slack #technical thread | Slack | Andrea's positive feedback on the shipped fixes |
| Codex reviews (local `codex exec`) | AI reviewer | 3 review rounds across the PRs |
| n2t.net / doi.org PID resolution checks | web (curl HEAD) | Verifying showcase PIDs resolve |

No untrusted/anonymous web content fetched.

---

## Open Threads

- [ ] **John Kunze** to weigh in on PR #321 / #142 (deep-link the 2 in-collection showcase samples vs. leave all as source links). Assigned to him. Do NOT merge over his call.
- [ ] **#320** — ingest the 2 missing showcase specimens (SESAR diamond `IGSN:DIA0000YL`, Smithsonian fish) into the aggregation. Blocked on a fresher export (April-2025 export is frozen).
- [ ] **Andrea #313** — `ISSUE_313_GUIDANCE_2026-07-03.md` drafted but NOT posted to the issue; awaiting Raymond's OK to post.
- [ ] **Zenodo grant closeout** (from earlier session, still open): awaiting Raymond's creator-list/ORCID answer before building the deposition. Grant ends 2026-07-31.
- [ ] `index_alt.qmd` not synced with #321's change (deliberate — pending approval).

---

## Next Session Entry Point

> Start here: check if John Kunze replied on PR #321 / #142. If he wants the deep-link direction, merge #321 (it's already verified live-working) + sync `index_alt.qmd`. Separately, Zenodo creator-list is still the one blocking ask for the grant-closeout deposition (deadline 7/31).

---

## PREVIOUS Session: 2026-06-18 (evening) — #300 filtered clusters at world zoom
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
