# Plan — #305 Facet-count correctness & coherence (counts beyond the single-filter cube)

**Status:** plan of record · **Authors:** Claude + Codex (joint, 2026-06-19) · **Tracks:** #305 (meta), #304 (live bug), #306 (data bug), #276 (semantics), #230, #286

## Problem

At the global/zoomed-out view, facet **counts** only cross-filter for a **single** active
filter (served by the precomputed `facet_tree_cross_filter` cube via `effectiveSingleFilter()`,
`explorer.qmd:3374`). With **2+ active selections** the cube is skipped and tree-dim counts
revert to the **unfiltered baseline** (`explorer.qmd:3557-3562`) — deliberately, to avoid a
~39M-row `sample_facet_membership` GROUP BY that stalls DuckDB-WASM. So the **map is correctly
filtered** (#299 bitmask) but the **count numbers are wrong** for multi-filter at world view.
Zoomed-in is already correct (live membership path, `explorer.qmd:3564-3598`). Reported by
Eric in #304 (e.g. *Material: Anthropogenic* + *Specimen Type: Artifact*).

## Core idea — count per node FROM the bitmasks (no membership scan)

For a count dimension D over a qualifying pid set Q:

```sql
SELECT nb.concept_uri AS value, COUNT(*) AS count
FROM <complete_facet_index> s
JOIN read_parquet('${node_bits_url}') nb ON nb.facet_type = '<D>'
  AND (s.<D>_mask & (1::BIGINT << nb.bit_index)) <> 0
WHERE <AND of the OTHER active dims' mask predicates> <source> <viewport> <search>
GROUP BY nb.concept_uri
```

- Masks are **one row per pid** → `COUNT(*)` == `COUNT(DISTINCT pid)` (do **not** add `COUNT(DISTINCT)` — wasted work).
- Membership encodes **ancestor closure** → child bit ⇒ parent bit, so **parent ≥ child** holds for free.
- The bitwise join is against `facet_node_bits` (≤63 rows/dim), not the 39M-row membership table.

**Cross-filter semantics (confirmed correct):** OR among selected nodes *within* a dimension;
AND *across* dimensions; **omit the target dimension's own predicate** (exclude-self), matching
the UI contract (`explorer.qmd:3305`) and the existing cube (`build_frontend_derived.py:460`).
Special case: **zero selected sources** ⇒ impossible filter for tree targets, but the source
dimension's own histogram must still exclude source and stay constrained by the three trees.

## Feasibility (Codex native DuckDB benchmarks, real 6M-pid data)

| Query | Time |
|---|---|
| One unfiltered 22-node histogram | ~0.17s |
| All three tree dims via one 56-node join | ~0.69s |
| Eric's Material+Specimen-Type → context histogram | ~0.02s |
| Embedded source predicate/group | ~0.014s |
| `facets_v3` semi-join (rejected approach) | ~0.145s |

Strongly supports feasibility. **Worst case ≈ 6M × 56 = ~336M cheap bit-tests**, not merely a
6M-row scan → **WASM cold+warm benchmarking remains a hard release gate** (the app has documented
DuckDB-WASM concurrency/deadlock sensitivity).

## Source handling

Add `source` as a plain **VARCHAR** column to a **new complete per-pid index** (source is
exclusive, not multi-valued → a mask is wrong; a `facets_v3` semi-join adds a second 6M-row
read + hash join). New schema:

```
pid · source · material_mask · context_mask · object_type_mask · build_id · schema_version
```

## Data-correctness prerequisite (#306)

The current `sample_facet_masks` is built from `membership`, so it **omits ~29,917 located
samples** with coordinates but no tree membership (`facets_v3` = 6,026,242 vs masks = 5,996,325).
The new index must start from **`samp_geo`**, LEFT JOIN masks, and emit **zero masks** for
no-membership pids. Tracked as **#306** (must land in Phase 1).

## Honesty rule (non-negotiable)

**Never fall back to the unfiltered baseline when filters are active** — that is exactly the
#304 bug. `applyFacetCounts(..., null)` means baseline (`explorer.qmd:1381`). On any
miss/error under active filters, show **"—" / "unavailable" / stale styling / hidden counts** —
never authoritative-looking baseline numbers. Apply all dimension maps **atomically after one
stale-guard check** (`facetCountsReqId`); never partially repaint dimensions.

## Phased plan

### Phase 1 — Artifact + semantic foundation
- Build the complete per-pid index above. Start from `samp_geo`; include zero-mask pids (#306).
- Add `source` VARCHAR; extend the build **fingerprint** to cover the pid/source universe
  (today it fingerprints membership only → would go stale silently once source/coverage change).
- AI-free validator: pid completeness vs `facets_v3`; source equality; node-bit coverage;
  mask ≡ membership for pids that have membership; build_id consistency.
- **Publish under a new immutable filename/tag — do NOT overwrite the cached `202608` artifact.**
- Ratify the count contract (#276) as **membership / "anywhere in tree"** — already the shipped
  semantics, so this is confirmation, not a redesign.

### Phase 2 — Fix #304 at global view
- Generalized **direct-control filter snapshot** (today's `describeCrossFilters()` zeroes tree
  selections at global view — the root cause). Generalize `effectiveSingleFilter()` to all selections.
- Route **multi-filter / full-tree-mode / global / no-search** counts through one mask-index
  histogram query (the `tree_counts ∪ source_counts` shape).
- Keep the single-filter cube as a **pure optimization**, not a required semantic path.
- Apply dimension maps atomically after the stale check. On failure → unavailable, **not** baseline.
- **Benchmark cold + warm DuckDB-WASM** across empty / narrow / broad / all-pid qualifying sets;
  set a concrete interaction budget before release.

### Phase 3 — Extend (not premature unification)
- Add **viewport** support (identical padded bbox, `VIEWPORT_PAD_FACTOR = 0.3`).
- Add **search** via `search_pids`.
- Characterization-test the new path against the existing membership path; **then** retire the
  membership count implementation. (Immediate unification would balloon the first fix into
  viewport + search + flat-mode + stale-update refactoring — defer.)

### Phase 4 — Verification + cleanup
- Unit-test predicate generation (exclude-self, zero-source states).
- Data validator gates from Phase 1, run in CI.
- Playwright: Eric's exact URL, multi-value-in-one-dim, source+tree, impossible combos,
  global↔viewport transitions, superseded requests.
- Remove the misleading active-filter baseline fallback everywhere.
- Codex adversarial review; staging verify on real R2 data; deploy smoke gate.

## Constraints / landmines
- **63-bit ceiling:** current dims are 19 / 22 / 15 nodes — ample headroom. Keep the build
  hard-fail; design a future multiword schema but **do not implement now**.
- **Flat / mixed render mode:** keep the mask path gated OFF (subtree-membership semantics are
  wrong for a flat dim) — defer to existing paths, as the cube already does.
- **Immutable data:** new tag/filename; never overwrite a cached artifact.

## Top 3 risks
1. **WASM latency / connection starvation** — credible SQL, unmeasured in-browser; ~336M bit-tests worst case.
2. **Stale / incomplete index generations** — #306 missing pids + membership-only build_id; mixed cached generations → convincing-but-false counts.
3. **Honesty & state-transition failures** — baseline-as-truth fallback + async camera transitions unless results applied atomically.

---
*Joint plan: Claude (code trace, drafting) + Codex (native benchmarks, source design, #306 discovery, honesty rule, phasing). 2026-06-19.*
