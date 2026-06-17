# PR4 plan — URL/state single-writer boundary (#208)

Draft for Codex review (2026-06-15). Continues the #249 strangler refactor.
PR1–PR3 (smoke gate, characterization tests, pure-module extraction) are
merged to upstream and live on isamples.org. This plan covers the next
documented stage: #208 "centralize URL writers, collapse dual mode."

Method unchanged: extract along seams, behind the green smoke +
characterization gate, Codex review per step, behavior-neutral.

---

## 1. Current state (verified against `explorer.qmd` @ be79a82)

#208 has three sub-smells. **Smell 2 is already resolved** — do not redo it:

| #208 sub-step | Status | Evidence |
|---|---|---|
| Smell 2 — collapse dual `mode` | ✅ DONE | `viewer._globeState.mode` is the sole store; `getMode()`/`setExplorerMode()` exist at L2368-2369; the only other `mode` token is a local `const mode = getMode()` (L2684). No closure-private `mode` variable remains. |
| Smell 1a — single URL-write boundary | ❌ TODO | **13** `history.{replace,push}State` sites; **11** write `buildHash(viewer)` (hash), 2 write `url` (query string, owned by `writeQueryState`). |
| Smell 1b — unify `camera.changed` + `moveEnd` via `reconcileCameraState` | ❌ TODO | Two listeners with overlapping duties + the sub-`percentageChanged` "URL updates but stats don't" gap; also the #262 heatmap→zoom-out cluster-restore bug. |

### The 11 hash-write sites (Smell 1a migration surface) — Codex-corrected 2026-06-15

| Line | Verb | Gate today | Caller / intent | writeGlobeHash call |
|---|---|---|---|---|
| 1594 | push | **none** | map **sample-click** selection | `{replace:false, force:true}` |
| 1654 | push | **none** | map **cluster-click** selection | `{replace:false, force:true}` |
| 2059 | replace | **none** (bypasses suppress by design, L2055) | table row-click selection | `{force:true}` |
| 2698 | push | `pushHistory!==false` only (NOT suppress-gated) | `enterPointMode` | keep caller guard; `{replace:false, force:true}` |
| 2710 | push | `pushHistory!==false` only (NOT suppress-gated) | `exitPointMode` | keep caller guard; `{replace:false, force:true}` |
| 3525 | replace | **none** | source-filter invalidates selected H3 | `{force:true}` |
| 3548 | replace | **none** | source-filter invalidates selected pid | `{force:true}` |
| 3680 | replace | `if (!_suppressHashWrite)` | camera.changed EARLY write (#201 Bug A) | `{}` (gated default) |
| 3757 | replace | `if (!_suppressHashWrite)` | camera.changed LATE write | `{}` (gated default) |
| 3823 | replace | `if (!_suppressHashWrite)` | moveEnd backstop write (#204) | `{}` (gated default) |
| 4044 | replace | **none** | **Share button** pre-copy hash refresh | `{force:true}` |

**Only 3 sites (3680/3757/3823) are actually `_suppressHashWrite`-gated.** The
other 8 are ungated today and MUST migrate with `force:true` to stay
behavior-neutral — default-gating them (my original error) would change behavior.

Two non-hash writes stay out of scope (query string): `writeQueryState()` body
(L940-943) and `persistSearchScope()` (L4105-4111, preserves the existing hash).
**Correction:** L4044 is the Share button (a hash write, in scope); L4111 is
`persistSearchScope` (query string, out of scope) — the reverse of the original
draft.

`_suppressHashWrite` lifecycle: set true at boot (L1506), cleared at L5176;
toggled around the hashchange deep-link apply (L3955/3973). Read by exactly 3
hash writers (3679/3756/3822).

### ⚠️ The one judgment call: 2698/2710 during boot (Q2)

`enterPointMode` CAN fire in the suppressed boot window (camera.changed →
`tryEnterPointModeIfNeeded()` at L3705 → `enterPointMode(undefined)` → pushes at
L2698), even though boot reconciliation "should not add history" (L5197).
**PR4a decision: preserve current behavior exactly** (`force:true` when
`pushHistory!==false`) — keep the refactor pure. Whether boot should suppress
those pushes is a *separate, tested bugfix*, filed as follow-up, NOT folded into
PR4a (per "preserve working code patterns").

---

## 2. PR4a — `writeGlobeHash()` boundary (LOW risk, high clarity)

### Design

A single top-level function (sibling to `buildHash`), the only place that
writes the hash:

```js
// replace: true (default) → history.replaceState; false → pushState
// force:   true → write even when _suppressHashWrite is set (selection path)
function writeGlobeHash(viewer, { replace = true, force = false } = {}) {
    if (viewer._suppressHashWrite && !force) return;
    const hash = buildHash(viewer);
    if (replace) history.replaceState(null, '', hash);
    else         history.pushState(null, '', hash);
}
```

This bakes the `_suppressHashWrite` gate into ONE place instead of repeating
`if (!viewer._suppressHashWrite)` at 4 sites and silently omitting it at 5.

### Migration

Drive entirely off the **Codex-corrected table in §1** (the `writeGlobeHash call`
column is the per-site spec). Summary: 3 gated-default sites (3680/3757/3823),
8 `force:true` sites (everything else), `replace:false` for the 4 push sites
(1594/1654/2698/2710), `replace` for the rest. enter/exitPointMode keep their
`pushHistory!==false` caller guard.

### Behavior-neutrality argument

Each migrated site produces the identical `history` call for identical state,
because the per-site `force`/`replace` flags reproduce today's exact gate (now
verified line-by-line by Codex). The only sites reading `_suppressHashWrite`
today are 3680/3757/3823 → they alone use the gated default; all others were
already ungated and use `force:true`.

### Verification
- `git diff` shows only call-site swaps + one new function; `buildHash`
  unchanged.
- Characterization (d1 `?search=`, d2 `&pid=`) + `url-roundtrip.spec.js`
  (the existing deep deep-link spec) exercise push vs replace and the
  suppress gate. Run both manually (live parquet) + smoke on the PR.
- Add a focused Playwright assertion: after a row-click, `history.length`
  increases (push) and `#pid=` is in the URL; after a small pan, the URL
  updates without a new history entry (replace). (Optional — the existing
  url-roundtrip spec may already cover the round-trip.)

---

## 3. PR4b — `reconcileCameraState(reason)` (HIGH risk — recommend caution)

### Why it's risky

`camera.changed` (L3666, debounced 600ms + `percentageChanged=0.1`) and
`moveEnd` (L3821, every settled move) overlap but are NOT redundant. Between
them they encode hard-won fixes for **#190, #193, #201, #204, #221, #234
(A1/B1/C3), #237, #240, #262**. Specifically they differ in:

- **URL write timing**: camera.changed writes EARLY (before awaits, #201 Bug A)
  AND late; moveEnd writes once. A naive merge could drop the early write.
- **Mode transitions + resolution reload** live only in camera.changed (with
  the #193 "chase" gates on `applied`).
- **Facet counts / heatmap** (#237/#240 stale-guards) live only in moveEnd.
- **Point-mode exit backstop** (#221 round 2) lives only in moveEnd.
- **Debounce**: camera.changed coalesces 600ms; moveEnd is immediate.

`reason`-tagged unification (`'changed' | 'moveEnd'`) is feasible but every
branch above must be preserved exactly. This is the opposite of PR3's
mechanical safety.

### Recommended shape (if we proceed)

Do NOT merge the two handlers wholesale. Instead:
1. Extract the **shared settled-camera tail** both already run — the URL write
   (now `writeGlobeHash`) + the cluster "Samples in View" stat update — into a
   small `reconcileSettledCamera(viewer)` and call it from both. This closes
   the #204 sub-threshold-URL gap minimally without touching mode/resolution
   logic.
2. Leave mode-transition + resolution-reload in camera.changed and
   facet/heatmap/point-exit in moveEnd as-is.
3. Treat #262 (heatmap→zoom-out cluster restore) as a SEPARATE targeted fix
   with its own characterization test, NOT folded into a big merge.

### Open recommendation
**Split confirmed: PR4a and PR4b are separate PRs.** PR4a is a clean win and
should land first and alone. PR4b's value (#208 smell 1b + #262) is real but
its risk profile argues for the minimal `reconcileSettledCamera` tail above
rather than the full handler merge Codex originally sketched. Flag for Codex:
is the minimal-tail extraction enough to claim #208 smell 1b, or does the
acceptance criterion ("shared settled-camera reconciliation entry point")
require the full merge? (Q3)

---

## 4. Codec extraction question (Q4)

The roadmap's PR4 title is "URL/state **codecs** + boundary." `readHash` is
already a module (PR3). `buildHash` is nearly pure — it reads
`viewer.camera`, `viewer._globeState`, and the `#heatmapToggle` DOM checkbox.
Options:
- (a) Leave `buildHash` in the qmd (it's the encode half; the DOM read makes
  it not cleanly pure). Ship only `writeGlobeHash` this PR.
- (b) Extract `buildHash(viewer, { heatmapOn })` to `explorer-utils.js` with
  the DOM read hoisted to the caller, unit-test the encode. More surface, more
  value for #164's state-contract-in-code goal.

Lean (a) for PR4a to keep it tiny; revisit (b) only if Codex thinks the codec
pairing (readHash already extracted) is worth completing now.

---

## 5. Sequencing & gate

1. **PR4a** — `writeGlobeHash` + migrate 11 sites. Behavior-neutral.
   Gate: smoke + characterization (d1/d2) + url-roundtrip, Codex review.
2. **PR4b** — `reconcileSettledCamera` minimal tail (+ optional #262 fix as a
   tracked sibling). Separate PR, separate Codex review, extra deep specs.
3. Defer the full camera-handler merge and the Vite/TS question (post-PR5,
   per #249).

Per-seam freeze only (not page-wide): while PR4a is open, avoid other edits to
the 11 listed write sites.

---

## 6. Questions for Codex — ANSWERED (Codex gpt-5.5, 2026-06-15)
- **Q1**: 1594/1654 are map-click selections (not boot); they ignore suppress
  today → preserve via `force:true`. ✅
- **Q2**: Yes — enter/exitPointMode CAN fire during the suppressed boot window
  (L3705→L2809→L2698). So preserve current behavior with `force:true`-when-
  `pushHistory!==false`; treat boot-push suppression as a separate tested
  bugfix, not part of PR4a. ✅ (see §1 judgment-call box)
- **Q3**: Full handler merge NOT required. Minimal shared-tail extraction
  (hash write + cluster "Samples in View" stat) satisfies #208 smell 1b. ✅
- **Q4**: Defer `buildHash` extraction (it reads `#heatmapToggle` DOM at L1186;
  needs a signature change + encoder tests). ✅
- **Q5**: Yes — corrected: 3525/3548 ungated (not gated); 4044 = Share button
  (in scope); 4111 = persistSearchScope (query string, out of scope); no
  hashchange-internal buildHash write exists; row-click = replace, map = push.
  All folded into the §1 table. ✅

**Codex verdict:** agrees with the 2-PR split and with avoiding the full camera
merge; required §1 to be corrected before PR4a (done above). Plan is now
implementation-ready for PR4a.
