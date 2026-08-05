# Coherence audit — "can the Explorer show a confidently wrong number?"

**Date:** 2026-08-04 (grant closeout)
**Audited:** `explorer.qmd` (7,531 lines) at branch `fix/340-facet-counts-honest-under-search`,
HEAD `2622d48`, based on `upstream/main` `9687fbf`. Plus `assets/js/explorer-utils.js` and the
governing docs.
**Method:** static code reading (Claude), then an adversarial second pass (Codex) instructed to
prove each finding wrong or unreachable. Disagreements are recorded below rather than smoothed over.
**Status:** READ-ONLY. No code was changed. Nothing here is implemented.

---

## Plain English: what this audit is about

Issue #340 looked like "the search filter isn't applied to the facet counts." It wasn't that.

The real shape was: **the recalculation started, never finished, and nobody noticed** — because
while a recalculation is in flight the numbers only go slightly grey. The *text doesn't change*.
So the previous, now-wrong numbers sit on screen looking completely normal, indefinitely. No error,
no spinner, no blank.

That is a nasty failure mode: the UI is most convincing exactly when it is most wrong.

This audit asked one question of **every number the Explorer displays**:

> **What happens if the thing meant to replace this number never returns?**

If the answer is "the old value stays up, unmarked or marked only by a colour change," that's a
finding.

**Headline result:** the #340 fix is sound, but it removed *one trigger* rather than the *hazard
class*. The same structural gap exists on other paths, and there is no enforced rule preventing it
from recurring. Two further surfaces can display flatly false numbers today.

---

## Status — what was fixed the same day

A follow-up closeout patch (`fix/coherence-honesty-closeout`, Codex-approved after one blocking
round) implemented four findings. **Everything else in this document remains open.**

| Finding | Action taken |
|---|---|
| **F3** | Legacy per-dim `catch` now paints `markFacetCountsUnavailable([d.key])` instead of the unfiltered baseline. Closes PLAN_305 Phase 4's explicit item for this site. |
| **F5** | Point mode no longer reports the 5,000 render cap as the true in-view total when the COUNT query fails — stats show `—`, phase text says the total is unavailable, and the debug/console diagnostics say "unknown" too. |
| **M2** | `reconcileSettledCamera()` now repaints the always-visible phase message — **but only behind a freshness guard** (`!loading && computeTargetMode(alt)==='cluster' && currentRes===targetRes && _clusterFilterSig===desiredClusterSig()`). The guard also now gates the stats repaint, closing the `_clusterFilterSig` blindness noted in F4. |
| **Structural (partial)** | `markFacetCountsRecomputing()` now arms a 400 ms timer that swaps unsettled counts to `(Loading…)`. "In flight" is no longer signalled by opacity alone — the mechanism that made #340 invisible. |

**A caution recorded from that patch's review.** The first M2 attempt had *no* freshness guard and
would have let a stale cluster cache overwrite an honest "Loading H3…" or "Failed to load…" with a
green settled count — reintroducing this exact failure class while fixing it. It was caught in
adversarial review, not by tests. Treat any "just repaint the number here" change in this file as
guilty until proven fresh.

### Known-open, deliberately deferred (grant closeout)

1. **Legacy per-dimension atomicity** — successful legacy count queries still repaint independently,
   so a mixed-generation view is possible for up to the 400 ms window (F3 detail).
2. **Comprehensive pre-await invalidation** — the source/facet handlers still do awaited globe work
   *before* `refreshFacetCounts()`, and the mask/cube paths still await before any invalidation. A
   hang *before* invalidation therefore still strands unmarked numbers (F2's missed stranding point,
   F8's ordering hole). **This is the single most valuable remaining fix**, and it is what would turn
   the honesty rule into an actual invariant.
3. **No regression test for the 400 ms timer** — should assert: an animated move produces
   `(Loading…)` after the grace period; stale `.zero` clears; settlement restores numeric text; a
   superseded request cannot repaint a newer generation. Flagged as the worthwhile first follow-up.
4. Everything in the findings table below not listed as fixed above — notably **M1** (selected
   card / Nearby Samples), **F11** (search-results snapshot), **F4** (stats panel invalidation),
   **F7**, **F12**, and the static-prose numeric drift.

---

## Findings

Severity: **HIGH** = can show a confidently wrong number indefinitely with no signal.
**MEDIUM** = can show stale/false values under specific but real conditions, or signals only subtly.
**LOW** = terminates honestly.

| # | Surface | Severity | Reachability | One-line |
|---|---------|----------|--------------|----------|
| F2 | Facet counts, non-search triggers | **HIGH** | Medium (needs hung/slow query) | Mask-index and cube paths await with no in-flight text change and no timeout |
| F3 | Facet counts, legacy error path | **HIGH** | Medium (needs a query error) | `catch` paints the *unfiltered global baseline* under active filters; plus non-atomic partial repaint |
| M1 | Selected cluster/sample card + "Nearby Samples (N)" | **MED/HIGH** | Medium | Old card survives filter changes and even terminal lookup failures |
| F5 | Point mode "Samples in View" | **MEDIUM** | Low-Med (dense view + failed COUNT) | Reports the 5,000 cap as if it were the true total |
| F7 | Facet counts, mixed tree/flat mode | **MEDIUM** | Low, but **persistent + deterministic** | One failed tree render ⇒ baseline shown while a tree filter is active |
| F11 | Search results list + heading `(50)` | **MEDIUM** | High (any facet toggle during search) | Snapshot of a previous filter state, with nothing on screen saying so |
| M2 | `#phaseMsg` cluster count | **MEDIUM** | Medium | After exiting point mode, a pan can leave a previous viewport's count in permanently visible text |
| F4 | Stats panel | **MEDIUM** | Low (collapsed by default) | No in-flight or unavailable state exists at all |
| F8 | Samples table meta + pager | **LOW→MED** | Low-Med | Honest *once refresh starts*; a hang before it starts strands everything unmarked |
| F12 | In-map card detail | **LOW** | Medium | Renders "Not Provided" when the lookup *failed* |
| F9 | Search results status line | **LOW** | — | Terminates honestly |
| F10 | Heatmap status | **LOW** | — | Terminates honestly; the model to copy |
| F1 | Facet counts under search | **FIXED** | — | The #340 calibration case; now terminates in real text |

---

## Detail

### F1 — Facet counts under active search — FIXED (calibration case)

`refreshFacetCounts()` (`explorer.qmd:4439-4467`) bails to `markFacetCountsUnavailable()` whenever
`searchIsActive()`, both before arming the debounce (4457-4460) and re-checked at fire time (4465).
The bail happens *after* `++facetCountsReqId`, so a late-settling older query cannot overwrite the
dash. The three search producers (5982-5987, 6028-6029, 6188-6194) call it the moment
`__searchFilter.active` flips true. All three terminal painters change **text** (1577-1647).

Both reviewers agree. Note precisely what was achieved: **honesty by disabling search-aware counts,
not by making their recomputation reliable.** Residual risk LOW.

### F2 — HIGH — Non-search count paths: no in-flight text change, no timeout

The `#340` hazard class survives for every trigger that isn't a search.

- The mask-index query awaits `db.query()` at **4172-4179**, invoked at **4275-4279** — *before* the
  only slow-path `markFacetCountsRecomputing()` call at **4307**.
- A viewport pan is marked only by class styling at **5366-5370** — the exact class-only,
  text-unchanged marking #340 proved insufficient.
- There is **no timeout** on the await. A hang means no terminal paint ever happens.

*Codex corrections adopted:*
- The global single-filter **cube** path (4248-4252) has the same defect, awaiting at 4037-4041
  before any visible invalidation. The draft framed this as specific to the heavy UNION ALL
  histogram; a first single-filter toggle at global view normally takes the cube instead.
- **Earlier stranding point the draft missed:** the source and facet handlers don't call
  `refreshFacetCounts()` until *after* unrelated globe work (source 4962-4979; facet 5100-5101).
  If that earlier load hangs, the count replacement **never even begins** and the old text stays
  completely unmarked. This is worse than the draft's framing, because no invalidation happens at all.

*Honest limit:* evidence that the non-search queries actually hang is **circumstantial**. #340 proves
a hang is possible in this stack (search-constrained variant), and the viewport variant shares the
`JOIN samples_map_lite` shape — but no non-search hang was observed. HIGH is assigned for the
**invariant failure**, not a demonstrated incident.

### F3 — HIGH — Legacy error path paints the unfiltered baseline under active filters

`explorer.qmd:4429-4434`, in the per-dimension legacy path:

```js
catch (err) { ... applyFacetCounts(d.key, null) }
```

`null` means *paint `viewer._baselineCounts`* — the unfiltered global numbers. Reachable when a
viewport request falls through the index path (4275-4293) and a per-dim query throws (e.g. a
transient range-request failure). The repaint clears `.recomputing`, so the wrong number looks
settled.

This directly violates PLAN_305's non-negotiable Honesty rule, and Phase 4's item *"remove the
misleading active-filter baseline fallback everywhere"* remains open.

*Codex correction adopted:* the draft was too absolute. Under exclude-self semantics the **active
dimension's own** baseline can legitimately be correct; it's the *other* dimensions, constrained by
that filter, that go wrong.

*Codex addition adopted — a second violation the draft missed:* successful legacy queries repaint
**independently** (4357-4428). If three dimensions settle and one hangs, the UI shows a
**mixed-generation partial repaint** — numbers from two different filter states side by side —
contrary to PLAN_305's atomicity requirement (lines 70-76).

### M1 — MEDIUM/HIGH — Selected cluster/sample card and "Nearby Samples (N)" *(missed by the draft; found by Codex)*

The strongest entirely-missed surface. The side card shows cluster count, H3 resolution and
coordinates (1748-1759), sample coordinates (1770-1784), and the list heading `Nearby Samples (N)`
(1939-1947).

Two ways old numbers get stranded:
1. Source/facet changes revalidate the selected cluster only *after* globe reconciliation and another
   async lookup (4962-5004, 5100-5124). A hang leaves the prior filter's card and list unmarked.
2. Hash navigation waits for a new PID/H3 lookup **without first clearing or loading-marking the old
   card** (5685-5725). Worse: PID failure only logs (5712-5714), and an empty result only hides the
   *in-map* card (5707-5710) — so the old **side** card can survive even a terminal failure.

I verified these line references against the code and concur.

### F5 — MEDIUM — Point mode reports the render cap as the true total

`loadViewportSamples` (3715-3735): when `POINT_BUDGET` (5,000) is hit, a follow-up COUNT computes the
real total. If that COUNT **throws**, the code proceeds with `totalCount = data.length` and
`capReached = false`. Lines 3746-3750 then assert 5,000 is the in-view total and that 5,000
"individual samples" were loaded — when the truth could be 10-100× higher.

Both reviewers confirm. Requires a dense viewport *and* a failed COUNT, but the resulting statement is
unequivocally false and indistinguishable from a genuine 5,000. Same bug shape as the one #206 fixed
for the no-failure case.

### F7 — MEDIUM — Mixed tree/flat mode shows baseline under an active tree filter

If `FACET_TREE` is on but one tree fails to render (flat fallback), `TREE_DIM_KEYS.every(treeActive)`
is false (1230-1236), so both all-tree gates are skipped (4248-4249, 4275).
`describeCrossFilters()` zeroes tree-dim selections at global view (3944-3964), so the baseline
early-return (4302-4304) paints unfiltered numbers while a tree filter is genuinely active.

*Codex correction adopted — severity raised.* The draft called this "transient." It isn't:
`renderTreeFacet()` has **no retry** after its flat fallback (2693-2704), so the mixed state persists
for the whole session or until cell re-evaluation. Reachability is low, but **once reached the wrong
counts are deterministic**, not a race.

### F11 — MEDIUM — Search results list and heading are a stale snapshot with no visible label

*Codex correction adopted — the draft rated this LOW and excused it as "by design."*

The search list is computed with the source/facet predicates current at the time (6530-6531) and
paints numeric status and heading counts (6711-6724). Later source/facet changes deliberately leave
those values untouched (6776-6785). So `#searchResults` can keep showing "50 of N" and the heading
`(50)` while both describe a **previous** filter combination.

Codex's argument, which I accept: *a code comment is not user-visible disclosure.* By the audit's own
stated rule this is a deterministic finding, not a documentation note. It is also the **most
reachable** item in this audit — any facet toggle during an active search triggers it.

### M2 — MEDIUM — `#phaseMsg` retains a previous viewport's cluster count *(missed by the draft)*

`exitPointMode()` paints "N clusters in view" (3854). Later cluster-mode camera moves call
`reconcileSettledCamera()`, which updates the stats panel but **not** `#phaseMsg` (5220-5234,
5384-5390). So after exiting point mode, the next ordinary pan can leave a stale count in the
*permanently visible* phase message. Verified.

### F4 — MEDIUM — Stats panel has no not-current state at all

`updateStats()` (1721-1728) only ever writes final values; nothing marks the panel in-flight or
unavailable. `loadRes()` and `loadViewportSamples()` change only `#phaseMsg` on start/failure
(3523-3529, 3599-3605, 3672, 3754-3758). Off-globe early returns (3655-3670) update neither.
`reconcileSettledCamera()` blindly counts the current cache (5220-5229) **without checking
`_clusterFilterSig`**, so it can count a facet-blind cache while a filtered reload is in flight.

Mitigation: the panel is collapsed by default (710-721), which lowers exposure but does not repair
the invariant.

### F8 — LOW→MEDIUM — Samples table: honest internally, but not end-to-end

*Codex correction adopted — the draft claimed "honest by construction"; that's false end-to-end.*

Internally the table is exemplary: `setMetaLoading` changes text + spinner and clears the stale pager
(2849-2857); failure sentinels at 2870-2877 and 3220-3228; rows dimmed with `aria-busy`; `Next`
disabled while `totalRows` is unknown.

But search changes `await reconcileGlobeForFilters()` **before** calling
`window.refreshSamplesTable?.()` (5147-5161). If that reconciliation hangs, the table refresh never
starts — old meta, pager totals and rows stay undimmed and unmarked indefinitely. Search clearing has
the same ordering. Same root shape as F2's missed stranding point.

### F12 — LOW — "Not Provided" is claimed when the lookup failed

`populateInMapCardDetail(null)` maps missing fields to "Not Provided" (1899-1910); the query catch
paths pass `null` (2465-2469, 3042-3047, 5614-5618). So a *failed lookup* is reported to the user as
*data absence*.

*Codex correction adopted:* the draft called this a one-word fix. It isn't — `null` currently
conflates "no matching detail row," "field absent," and "query failed." A genuine fix needs an
explicit error state.

### F9 / F10 — LOW — These terminate honestly

**F9 (search status line):** all terminal paths guarded by `_searchSeq`; superseded searches don't
paint because the newer search owns the text (6656-6659, 6891-6918, 6929-6947). A hung build leaves
explicit "Building search filter…" text. A failed follow-up COUNT retains "50+" — honest
under-disclosure.

**F10 (heatmap):** the model the rest of the file should copy. Status painted *before* the query
(4657-4660); success paints the real count (4776); **failure paints unavailable AND removes the stale
imagery** (4777-4802) so status and overlay can't disagree; tolerance-skip restores the truthful count
(4846-4858); `moveStart` paints a waiting status (5380). A hang leaves explicit loading text.

### F6 — Withdrawn as a finding (kept as a robustness note)

The draft flagged that `moveStart` invalidates and class-marks (5366-5370) with recovery depending
entirely on `moveEnd` (5384-5396). Codex could not identify any reachable unpaired-`moveStart` path —
all camera movement goes through Cesium, with no manual emission or cancellation path that omits
`moveEnd`. **I accept the downgrade.** Keep as a fragility note only; promote only if runtime evidence
ever shows an unpaired event.

---

## Is the honesty rule an invariant? No.

It is **call-site discipline**, not structure. Facet counts have three terminal painters plus one
class-only marker; the table has ad-hoc `setMeta`/`setMetaLoading`; the heatmap has
`setHeatmapStatus`; the stats panel has no not-current state whatsoever. Every new code path has to
*remember* to terminate. #340 happened precisely because one didn't — and F2/F8/M1 show others that
still don't.

There is even precedent for the fix inside this very file: the `explorer-busy` watchdog (4905-4936)
force-clears a stuck busy cursor after 120s because "a HUNG promise would never reach that finally."
That reasoning was never applied to the *numbers*.

### Recommended structural change (describe only — NOT implemented)

The draft proposed a per-surface **watchdog timer**. **Codex argued this is the wrong mechanism, and
I find its argument more convincing.** Recording both, since this is the audit's main judgement call:

- *Draft position:* arm a timer on `beginUpdate(surfaceId)`, clear on `settle(surfaceId)`; if it
  fires first, force the surface to its not-current state. ~20 lines for facet counts.
- *Codex position (adopted):* a watchdog enforces "loading must eventually end," which is a
  **stronger and different** requirement than honesty. Honesty only needs invalid data to *stop
  looking current immediately*. A permanently visible "Loading…" is already accepted as honest
  elsewhere in this audit. Critically, **a watchdog doesn't help when work hangs before
  `beginUpdate()` is ever called** — which is exactly F2's missed stranding point and F8's ordering
  hole. It also doesn't cancel the underlying DuckDB query, so it can hide the UI symptom while the
  shared connection stays occupied.

**The invariant belongs at input invalidation, not on a timer attached to selected query paths:**

1. At every semantic invalidation — filter, search, mode, viewport, selection — **synchronously**
   replace affected numeric text with a visible loading/unavailable sentinel, *before any `await`*.
2. Commit real values only under the surface's existing generation guard.
3. On rejection, paint unavailable — **never** baseline.
4. Add a timeout only if the product separately requires that loading must terminate.

Minimum coherent change for facet counts specifically:
- Make `markFacetCountsRecomputing()` **replace text** (e.g. `(Loading…)`) and clear stale `.zero`,
  so "in flight" is never conveyed by opacity alone.
- Invoke that invalidation at the **start** of source/facet changes, before globe reconciliation.
- Invoke it synchronously for every non-search `refreshFacetCounts()`, covering cube, mask and legacy
  routing.
- Replace the legacy `catch`'s baseline with unavailable, and buffer legacy results for one **atomic**
  repaint.

---

## Documentation drift

| Doc | Issue | Verdict |
|---|---|---|
| `EXPLORER_STATE.md:132` | Says `window.refreshSamplesTable` is "not used by other cells; safe to keep or remove" — **false**: installed at 3387, called at 5161. Following the doc would silently break search→table refresh. | Confirmed |
| `EXPLORER_STATE.md:98` | The `.recomputing` row is semantically incomplete — omits `markFacetCountsUnavailable()` clearing it, `markFacetCountsPending()` adding it, the `count-unavailable` class, and that terminal states now change text. | Confirmed |
| `EXPLORER_STATE.md` §3 | Says each degraded dimension "behaves fully flat" — the mixed-mode routing (F7) disproves this at global view. | Confirmed |
| `EXPLORER_STATE.md` §3/§4 stale line refs | Draft said these lack a staleness warning. **Wrong** — there is a global warning at lines 15-24, and §7 has its own at 668-673. Stale refs are maintenance debt, not undisclosed. | Draft corrected |
| `PLAN_305_facet_counts.md` | Closeout note (107-132) is accurate. Phase 4 remains **materially open**: F3 is a live baseline fallback, the legacy path repaints non-atomically, and mixed mode retains another baseline route. | Confirmed |
| `A1_SCOPING.md:41-46` | Instructs a search semi-join in both count paths — no longer the contract after #340. Draft overstated it as asserting shipped behavior (it's plainly a scoping doc), but it still needs a short superseded-note. | Partly corrected |
| Static Explorer prose (~7526) | Worse than "unverified" — it's **wrong**. Manifest gives res4 505,651 B (not 580 KB), res6 1,322,875 B (not 1.6 MB), res8 2,009,510 B (not 2.5 MB). And "4 parquet files" is false: the runtime manifest check enumerates 16 core objects + 4 search-index objects (933-944). Cluster row counts (38K/112K/176K) remain unverified — the manifest doesn't carry them. | Escalated |

---

## What we did NOT check — limits of this audit

Be aware of these before treating the findings table as complete.

- **No runtime verification.** Every finding here is from reading code. The only live evidence is
  inherited from the #340 fix session (60/60 elements stuck in `.recomputing`). None of F2-F12 or
  M1/M2 was reproduced in a browser. Reachability ratings are **inferred**, not measured.
- **Non-search hangs are unproven.** F2's severity rests on a structural gap plus one demonstrated
  hang in the search variant. No non-search hang was observed.
- **The #340 stall was never localized.** We did not diagnose *where* the search-constrained query
  gets stuck; PLAN_305 defers this deliberately. So we cannot say which other paths inherit the same
  root cause.
- **DuckDB-WASM cancellation/timeout semantics were not investigated.** This matters: any fix that
  only repaints the UI leaves the shared connection occupied.
- **Only `explorer.qmd` was audited.** Other site pages that display numbers — the guided tour,
  `data.qmd`, tutorials — were out of scope.
- **No pixel/visual verification.** We checked what the code writes, not what a user actually
  perceives; a "subtle" marking may be more or less visible in practice than assumed.
- **Two reviewers, one codebase.** Claude and Codex both read statically and can share blind spots.
  M1 and M2 were missed entirely by the first pass and only surfaced under adversarial review —
  which is itself evidence that a third pass would likely find more.

---

*Audit: Claude (Fable) draft → Codex adversarial review → reconciled by Claude. Disagreements are
recorded inline with both positions. Produced during grant closeout as a handoff artifact; nothing
here was implemented.*
