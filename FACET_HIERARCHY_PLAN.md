# Facet hierarchy plan — tree display of facet values (#281 + #282)

Draft for Codex + RY review (2026-06-17). Issues:
- **#281** (ekansa): show facet hierarchy in a tree, first two levels unfolded, click to open deeper.
- **#282** (akthom): nested + alphabetical across all three concept vocabularies.
- **#276**: the counting-semantics fork this forces — single "first non-root" value vs **membership** ("anywhere in the path").

Treated as **one design**. This is the biggest explorer UI change since launch; it
rides on the #249 test net (PR1/PR2 merged; PR3 deployed; PR4a/PR4b/#285 in flight).

---

## 0. What I verified first (grounding — don't trust the folklore)

The Slack/issue framing was "the data already carries each sample's full vocab
ancestry, so the tree is in hand." **That is only half true** — verified against
code + the live 202608 data, not assumed:

1. **The facet UI is entirely flat today.** `explorer.qmd` `facetFilters` cell
   (L1783–1873) renders material/context/object_type as a flat checkbox list via
   `renderFilter()` (L1843), sorted by `count DESC` from `facet_summaries`. Source
   is hard-coded flat HTML (L659–690). No parent/child/tree/indent anywhere.
   `vocab_labels` is loaded only as `uri → pref_label` (no `broader`).

2. **`sample_facets_v3` is one row per `pid` with a SINGLE already-flattened URI
   per dimension.** `build_frontend_derived.py` picks the **first non-root**
   material concept per sample (`arg_min(ic.uri, ord)` over the wide array,
   excluding `MATERIAL_ROOT`, L86–96); context/object_type take array element
   `[1]` and their root-dropping is still deferred (L29–30, L114–115).

3. **The wide arrays are a SET of asserted concepts, NOT a clean ancestry path.**
   Real 202608 data — one sample's `p__has_material_category` resolves (in array
   order) to: `mineral`, `material` (root), `rock`. The canonical SKOS tree is
   `mineral → earthmaterial → material` and `rock → rockorsediment → earthmaterial
   → material`. So the array `{mineral, material, rock}` is **neither** a path
   **nor** a transitive closure (it's missing `earthmaterial` and `rockorsediment`,
   and spans two branches). Array-length distribution: len 1 = 6,233,867 samples,
   len 2 = 1,601, len 3 = 491,424.

   **Consequence:** full transitive ancestry must be **computed at build time** by
   walking `skos:broader` from each asserted concept to the root. We cannot read
   it straight off the array.

4. **The canonical tree IS available** — `build_vocab_labels.py` already fetches
   ~12 SKOS TTLs (core material/sampledfeature/objecttype + OpenContext, earthenv,
   biology extensions) but **drops** `skos:broader` from its output. The three
   core vocabularies are small and shallow:

   | vocab | concepts (core) | root | max depth | level-1 children |
   |---|---|---|---|---|
   | material | 21 | `material` | 3 | 7 |
   | sampledfeature | 20 | `anysampledfeature` | 3 | 4 |
   | objecttype | 20 | `materialsample` | 3 | 5 |

   Extension TTLs add more nodes under these roots, but the structure stays
   shallow. "First two levels unfolded" reveals most of each tree.

**Net:** the tree is *derivable* but not free. Two build-time additions are
needed — (a) emit the `broader` edges, (b) compute per-sample membership over the
ancestry. The UI then renders the tree and counts/filters via membership.

---

## 1. Two halves, two dependency profiles

| Half | What | Depends on #249 refactor? |
|---|---|---|
| **(a) Data/pipeline** | tree edges + membership-count derived files | **No** — pure backend; can start now |
| **(b) Tree UI** | tree rendering + membership filtering in `explorer.qmd` | **Yes** — touches the facet cells PR4b/#285 also touch |

So we break ground on **(a) immediately**; **(b)** lands after PR4a/PR4b/#285 merge.

---

## 2. Half (a) — data/pipeline (start now)

### 2.1 Emit the tree (`build_vocab_labels.py`)
Add a `broader` column (parent URI, nullable for roots) to `vocab_labels.parquet`,
read from `skos:broader` across **all** the TTLs already parsed. Optionally also a
`depth` (int, root = 0) and `scheme` (already present). Validation: every non-root
concept resolves to a root via `broader`; no cycles; every `facet_value` that
appears in the data has a tree node (flag orphans — these are the #161/#148-style
label-gap cousins).

### 2.2 Compute membership (`build_frontend_derived.py`)
New derived table, one row per (sample, concept-in-its-ancestry):
```
sample_facet_membership(pid, facet_type, concept_uri, depth)
```
For each sample and each dimension: take the asserted concept(s) from the wide
array, drop the bare root, and for each, walk `broader` to the root emitting a row
per ancestor (dedup per pid×concept). A sample tagged `{mineral, rock}` → membership
`{mineral, earthmaterial, rockorsediment, rock, material?}` (root-inclusion = open
question Q2). This is **membership semantics** (#276 "anywhere in the path").

Then hierarchical counts come from a GROUP BY on the membership table:
```
facet_tree_summaries(facet_type, concept_uri, parent_uri, depth, label, count)
  where count = COUNT(DISTINCT pid) with that concept in its membership set
```
**Counting invariant (Codex-corrected):** counts are a **distinct-pid UNION**, NOT
additive. `parent_count = COUNT(DISTINCT pid)` over (direct ∪ all descendants); the
only guaranteed relation is `parent_count >= every child_count`. Do **not** assert
`parent = direct + Σ children` — a `{mineral, rock}` sample lands under multiple
sibling branches, so children overlap. (Verified both directions on real data — see §7.)

**Universe must match the explorer (Codex):** build membership from the **located**
sample set (`samp_geo` — `MaterialSampleRecord` with geometry), the same universe the
map/table/existing facet_summaries use, or hierarchy counts will drift from every
other surface.

**URI form is first-class (Codex):** the SKOS TTLs use *un-versioned* URIs
(`.../material/anthropogenicmetal`) while the data uses *versioned* ones
(`.../material/1.0/rock`). `broader` edges MUST be emitted in the **data form** —
reuse the alias/version normalization `build_vocab_labels.py` already applies
(its data-form aliases exist for exactly this reason). Verified: a naive join is
0% match; with version-segment normalization it's correct (§7).

**SKOS is a DAG, not a tree (Codex):** 29 concepts across the loaded vocabularies
have multiple `skos:broader` parents. The validator must either pick a canonical
parent deterministically or define multi-parent rendering before UI work; don't
silently assume a single-parent tree.

### 2.3 Sizing / perf
Membership ≈ samples × avg ancestry depth. With depth ≤ 3–4 and most samples at
len 1, expect ~15–25M rows over 6.7M samples (vs `facets_v3` 6.7M rows). Store
sorted by `(facet_type, pid)` for the bbox-JOIN path; ZSTD. **Validate query
latency** (the explorer reads these over HTTP range requests) before committing to
the shape — mirror `profile_queries.py`. If the per-pid membership table is too
heavy for the viewport-scoped count JOIN, fall back to a precomputed
`facet_tree_cross_filter` cube (like today's `facet_cross_filter`).

### 2.4 Outputs, validator, publish
- New/changed files (versioned, **non-cutover** — publish alongside, don't
  overwrite prod): `…_facet_tree_summaries.parquet`, `…_sample_facet_membership.parquet`,
  `vocab_labels_*.parquet` (+`broader`).
- Extend `validate_frontend_derived.py`: tree integrity (single root per scheme,
  no cycles, parent counts ≥ child counts and = direct+Σchildren), membership grain
  (no dup pid×concept), label coverage.
- Ship as a **data-pipeline-only PR** (no `explorer.qmd`). Prove counts in a notebook
  / query log committed under the existing `*_SUMMARY` convention.

---

## 3. Half (b) — tree UI (after #249 PRs merge)

### 3.1 Rendering
Replace flat `renderFilter()` for material/context/object_type with a tree builder
fed by `facet_tree_summaries` (parent_uri + depth + label + count). Source stays
flat (no vocab tree). Behavior per #281/#282:
- Render the tree **nested + alphabetical** within each level (#282).
- **First two levels unfolded** (root's children + grandchildren); deeper nodes
  collapsed behind a disclosure control; click to expand (#281).
- Each node: checkbox + label + `(membership count)` in the existing
  `.facet-count[data-facet][data-value]` span shape so the count-update plumbing
  (`applyFacetCounts`, `.recomputing`) is reused unchanged.

### 3.2 Counts
`updateCrossFilteredCounts` reads membership counts instead of single-value counts.
Node count = its membership count under the current viewport + cross-filter + search.
Parent = direct + Σ descendants falls out of the membership GROUP BY.

### 3.3 Filtering semantics (the coherence contract)
Selecting a node filters to its **entire subtree** (membership): `facetFilterSQL`
changes from `material IN (…)` on `facets_v3` to `pid IN (SELECT pid FROM membership
WHERE concept_uri IN (selected nodes + their descendants))`. **Counts and the table
filter must share one expression** (the `FACETS_DESCRIPTION_EXPR` discipline from
the 202608 work / the #245 "facet == table" invariant), or legend and table drift.
- Parent/child checkbox interaction: selecting a parent selects its subtree
  (tri-state indeterminate for partial — **Q3**).

### 3.4 Interactions to respect
- `?material=` URL param (and friends) must accept tree nodes and round-trip
  (cf. facet-viewport `coherence` test).
- The #267 "active facet forces point mode" rule and the B1 viewport-scoped count
  path (moveStart `.recomputing` → moveEnd `refreshFacetCounts`) stay intact.
- Rides on the refactored facet code from #249 PR3 (`sql-builders.js`) — extend
  there, with `node --test` units for the new tree/membership SQL builders.

---

## 4. Sequencing & gate
1. **Now:** Half (a) — tree edges + membership + `facet_tree_summaries`, validator,
   latency probe, notebook proof. Data-pipeline PR; publish versioned files.
2. **After PR4a/PR4b/#285 merge:** Half (b) — tree UI + membership filtering, behind
   the smoke + characterization + new tree-specific Playwright specs (assert
   parent count = direct+Σchildren; selecting a parent filters the subtree; 2-levels
   unfolded; legend == table under a subtree selection). Codex per step.
3. Keep single-value `facets_v3` until (b) ships, then decide deprecate vs keep
   (Q1).

---

## 5. Open questions (for Codex + RY)
- **Q1 — migrate or coexist?** Does hierarchy fully replace the single-value
  `facets_v3` columns (filtering + counts move to membership), or do both ship?
  (Hierarchy needs membership for both; single-value can't express subtree filter.)
- **Q2 — root inclusion.** Does membership include the bare root (`material`,
  `anysampledfeature`, `materialsample`)? It's the "All" node; probably render it
  as the tree root label, not a selectable facet — confirm.
- **Q3 — parent selection UX.** Selecting a parent = select whole subtree, with a
  tri-state indeterminate when only some children are checked? Or parent is a pure
  filter (subtree) with no child checkboxes shown until expanded?
- **Q4 — multi-asserted leaves.** A sample tagged `{mineral, rock}` contributes to
  both branches' ancestries (union). Confirm that's the intended "membership"
  reading (vs picking one). #276 leans union.
- **Q5 — which dims first.** material is the #282 priority; sampledfeature +
  objecttype follow the same machinery; source never gets a tree. Ship all three
  trees at once or material-first?
- **Q6 — count perf.** Is the per-pid membership JOIN viable for viewport-scoped
  counts, or do we precompute a `facet_tree_cross_filter` cube? Decide from the
  2.3 latency probe.

---

## 6. First concrete step — DONE (proof-of-concept)
`scripts/poc_facet_hierarchy.py` builds the proof against the local 202608 wide +
the SKOS TTLs: merges `broader` edges (per-file parse — a combined-graph parse
silently drops material's edges), normalizes URIs to data form, computes the
ancestor closure + membership, and checks the invariants. Run:
`python scripts/poc_facet_hierarchy.py --wide <202608_wide.parquet> --ttls <dir>`.

## 7. PoC results (proven, material dimension, 202608)
- located samples = **6,026,242**; located-with-material = **5,829,436**;
  membership = **15,076,893** rows.
- **INVARIANT A — parent ≥ child: PASS** (counts monotonic down the tree).
- **INVARIANT B — root == located-with-material: PASS** (5,829,436 = 5,829,436;
  every located sample with a material concept reaches the root).
- **INVARIANT C — non-additive: confirmed** (earthmaterial distinct = 4,091,133 ≠
  Σ children = 2,028,538). Additive summing is wrong in both directions.
- Sane tree: material 5.83M → earthmaterial 4.09M → rockorsediment 852K → rock 794K;
  mineral 303K; organicmaterial 1.02M.
- **Gotchas surfaced & fixed:** (1) URI version-form mismatch (0% join → fixed by
  normalization); (2) rdflib drops material edges when many TTLs share one graph
  (parse per-file, merge dicts); (3) 29 multi-parent (DAG) concepts exist.

**Next:** wire this into `build_vocab_labels.py` (emit `broader`, data-form) +
`build_frontend_derived.py` (closure + membership + `facet_tree_summaries`, built
from `samp_geo`) + `validate_frontend_derived.py` (tree integrity, parent≥child,
DAG policy), behind a latency probe. Ship as the data-only PR (Half a). Then Half b.

## 8. Codex review — accepted corrections (2026-06-17, gpt-5.5)
Verdict: "directionally sound." Accepted: (1) distinct-pid-union invariant, not
additive [§2.2]; (2) build membership from the located universe [§2.2]; (3) URI-form
normalization is first-class [§2.2]; (4) DAG/multi-parent handling [§2.2]; (5) extract
a selected-facet **state model** (URL/checkbox/filter-SQL/cross-filter currently all
read the DOM directly) rather than just nested HTML [§3]; (6) put membership SQL in
`assets/js/sql-builders.js` with `node --test` units [§3]; (7) consider a
**closure table** (`concept_closure(ancestor, descendant, distance)` + asserted
projection) over a materialized membership file — benchmark both; (8) **ship
material-first** behind shared machinery [§5 Q5]; (9) parent UX = store the parent
URI + derive descendants, don't explode into the URL, tri-state indeterminate [§5 Q3].
