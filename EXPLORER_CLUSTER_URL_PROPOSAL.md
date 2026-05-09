# Explorer Selection URL State — Audit + Cluster Proposal

Companion to [`EXPLORER_STATE.md`](./EXPLORER_STATE.md). Audit of what selection state
the Explorer URL captures today, and a proposal for adding cluster-selection
state so a URL alone can replay "I clicked this dot and got these samples."

**Recommendation (revised after Codex review)**: encode cluster selection as `&h3=<cell>` in the URL hash, using the H3 cell index that the explorer already SELECTs from the parquet (`explorer.qmd:973`, `:1316`). Exact key join, no lossy lat/lng tuple, no data-pipeline change.

All file:line references are against `explorer.qmd` at commit `e0043c8`
(post-#180 polish PR).

---

## 1. Audit: what's URL-persisted vs in-memory only

### Already URL-persisted

These already round-trip through the URL today; no work needed.

| State | URL token | Notes |
|---|---|---|
| Camera position | `#lat`, `#lng`, `#alt`, `#heading`, `#pitch` | Hash; debounced 600 ms; `EXPLORER_STATE.md §2`. |
| Mode (cluster vs point) | `#mode=point` (absent ⇒ cluster) | Hash. Pushed on `enter/exitPointMode`. |
| **Selected sample** | **`#pid=<urlencoded>`** | Hash. `selectedPid` written by sample-click (`:892`), cleared by cluster-click (`:919`). Round-trips through `readHash` → `_globeState.selectedPid` → `updateSampleCard()` + lazy `wide_url` description fetch (`:1813`, `:2167`). |
| Search query | `?search=` | Query-string. `EXPLORER_STATE.md §1`. |
| Search scope | `?search_scope=area\|world` | Query-string. From PR #179. |
| View mode (globe/table) | `?view=table` (absent ⇒ globe) | Query-string. |
| Source filter (4 source toggles) | `?sources=CSV` | Query-string. |
| Material / Sampled Feature / Specimen Type facet filters | `?material=`, `?context=`, `?object_type=` | Query-string. CSV of full URIs. |

**Sample selection is solved.** A URL like
`#v=1&lat=33.27&lng=-86.24&alt=311435&pid=ark%3A%2F65665%2F...&mode=point` drops a
collaborator at the exact dot you clicked, with the side-panel sample card
populated.

### NOT URL-persisted (in-memory only)

| State | Where it lives | Lost on reload? |
|---|---|---|
| **Selected cluster** | `updateClusterCard()` writes the cluster card DOM only; `selectedPid` is *cleared* on cluster click (`:919`) | ✓ |
| Nearby-samples panel (post-cluster-click result) | `samplesSection` DOM, populated from a `delta`-window query (`:925-960`) | ✓ — derivable from cluster identity if we had it |
| Sample card detail (description) | `samplesSection` / sample-card DOM | ✗ — refetched on `pid` reload via `wide_url` |
| Table page index | `let page = 0` closure in `tableView` (`:1080`) | ✓ — known intentional gap (`EXPLORER_STATE.md §1`, `#163` item 6) |
| Hover label text | `viewer.pointLabel` | ✗ ephemeral by design |
| Globe canvas zoom-watcher transient state | `viewer._clusterData`, `_clusterTotal`, `_baselineCounts` | ✗ derived from filters + camera |

The **selected cluster** is the only meaningful selection-state gap.

---

## 2. The cluster identity problem

A clicked cluster's runtime identity (`:891`):

```js
{ count, source: row.dominant_source, lat: row.center_lat, lng: row.center_lng, resolution: 4 }
```

Two things make this harder than `pid` (revised after Codex review of v1):

1. **Resolution-dependent**: a cluster at H3 res 4 doesn't exist as a unit at res 6; it splits into smaller cells. Reload at a different camera altitude → different H3 resolution → no cluster matches.
2. **Source-filter-dependent only**: cluster aggregation depends on the active `?sources=` filter. The H3 summary parquets explicitly carry only `dominant_source` — the cluster code at `explorer.qmd:1706-1710` documents that `material` / `context` / `object_type` filters **cannot** affect cluster counts, only sample-level views. So cluster identity is reproducible if `?sources=` is pinned.

The H3 cell index is **canonical**: a single 15-character hex value (e.g. `841a067ffffffff`) that uniquely identifies a cell at a specific resolution. The resolution is *embedded* in the index — no separate field needed. The explorer's H3 summary queries (`explorer.qmd:973`, `:1316`) already SELECT `h3_cell`; the cluster `.id` object simply doesn't carry it forward. **The "is the H3 index available?" open question (v1 doc OQ1) is answered: yes, no data-pipeline change required.**

So a URL that says "you clicked H3 cell `841a067ffffffff`" plus the existing `?sources=` filter state fully reproduces the cluster the user saw — no lat/lng drift, no resolution param, exact join into the parquet row.

---

## 3. Encoding options

Four candidate URL representations for cluster selection, with the `&pid=`
slot generalized.

### Option A: separate cluster fields

```
#cluster_lat=33.2706&cluster_lng=-86.2375&cluster_res=4&cluster_source=SESAR
```

| pro | con |
|---|---|
| Mirrors the runtime `id` shape; trivial round-trip; greppable. | Four params; bloats hash; collisions risk if other features want `&cluster_*`. |

### Option B: single packed lat/lng tuple — REJECTED

```
#cluster=SESAR:4:33.2706,-86.2375
```

| pro | con |
|---|---|
| One token; matches `#pid` ergonomically; format is documentable. | **Lossy** — relies on lat/lng comparison rather than exact key join. The H3 cell index is already in the runtime data (see Option C); this option throws it away for no reason. Custom parser; coordinate rounding could miss the row. |

### Option C: H3 cell index — RECOMMENDED

```
#h3=841a067ffffffff
```

| pro | con |
|---|---|
| H3 cell index is a canonical 15-char hex token uniquely identifying the cell at a specific resolution; resolution is *embedded* in the index. Joins to the cluster row are exact (`WHERE h3_cell = ?`), not delta-windowed. The `?sources=` filter (already URL-persisted) covers source-state reproducibility. | None significant — the index is already SELECTed at `explorer.qmd:973` and `:1316`; only the cluster `.id` object needs to carry it. |

**Note**: `dominant_source` does *not* need to be in the URL. It's a *derived* attribute of the cluster row, looked up by `h3_cell` at hydration time. The source-filter state (`?sources=`) is what matters for reproducing the same aggregation.

### Option A: separate cluster fields

(see above)

### Option D: unified `&sel=` field with type prefix

```
#sel=p:ark:/65665/abc      (sample)
#sel=c:841a067ffffffff     (cluster, h3-form)
```

| pro | con |
|---|---|
| One field for "what's selected"; uniform handler; future-proofs other selection types. | Migration cost: existing `&pid=` URLs in the wild stop working unless we keep both. Backwards-compat shim isn't free. |

---

## 4. Recommendation

**Option C (`&h3=<cell>`), keeping `&pid=` as-is.**

Revised from v1 of this doc after Codex review confirmed `h3_cell` is already in the H3 summary parquets (queried at `explorer.qmd:973` and `:1316`) — the cluster `.id` just doesn't carry it forward.

Rationale:

- **Exact lookup, not lossy**: `WHERE h3_cell = '<cell>'` is a primary-key join. The lat/lng-tuple alternative (Option B) requires `WHERE` + range comparison and is fragile to coordinate rounding.
- **Single token**: 15 hex chars; resolution implicit; no parser beyond `params.get('h3')`.
- **No data-pipeline change**: just thread `h3_cell` into the runtime `id` object at the two `add()` sites.
- **No backwards-compat tax**: `&pid=` URLs keep working unchanged.
- **Cluster + sample mutual exclusion** matches the runtime invariant (`selectedPid` is cleared on cluster click).

Concretely:

```js
// 1. Carry h3_cell into the runtime id (explorer.qmd:987 and :1331)
viewer.h3Points.add({
    id: { h3_cell: row.h3_cell, count, source: row.dominant_source,
          lat: row.center_lat, lng: row.center_lng, resolution: 4 },
    ...
});

// 2. Extend _globeState (explorer.qmd:821)
viewer._globeState = {
  mode: 'cluster' | 'point',
  selectedPid: string | null,
  selectedH3: string | null,  // NEW — the h3_cell hex string
};

// 3. readHash() addition (:615)
h3: params.get('h3') || null,

// 4. buildHash() addition (:629)
const gs = v._globeState;
if (gs.selectedH3) params.set('h3', gs.selectedH3);

// 5. Cluster-click handler (:916-920)
v._globeState.selectedPid = null;
v._globeState.selectedH3 = meta.h3_cell;
history.pushState(null, '', buildHash(v));

// 6. Hash hydration (:1733, :2167)
if (state.h3) {
  // Reconstruct cluster meta with: SELECT * FROM read_parquet(...) WHERE h3_cell = ?
  // Then call updateClusterCard(meta) + the nearby-samples query at :925-960.
  // Mutual exclusion: clear selectedPid.
}
```

Behavior on URL load:

1. `&h3=...` present, no `&pid=`: query the parquet for that cell, populate side panel + nearby-samples list. Camera/H3-resolution layer left as-is — see OQ2.
2. `&pid=` present, no `&h3=`: existing behavior, no change.
3. Both present: prefer `&pid=` (sample mode wins; cluster URL is stale). Drop `&h3=` via `replaceState` to clean up.
4. Neither: blank selection (current behavior).

---

## 5. Open questions

1. ~~**H3 cell index in parquet?**~~ **Answered**: yes. `h3_cell` is already SELECTed at `explorer.qmd:973` (phase1) and `:1316` (loadRes); only the cluster `.id` object needs to carry it forward.
2. **Cross-resolution behavior on load.** If you share `&h3=<cell>&alt=...` and the recipient's window altitude maps to a different H3 resolution than the cell's, should the URL load *force* the resolution to match the cell's, or just populate the side-panel and leave the visible H3 layer alone? *Recommendation: populate the side panel only. The shared-link receiver wanted to see your sample list, not necessarily your grid.*
3. **Does the side panel need a "this cluster's view is no longer live" hint** when the recipient's camera/filters cause the on-globe rendering to differ from the URL one? *Defer; revisit after implementation if it confuses people.*
4. **Backwards compat for `&pid=`**: keep forever. Existing sample-share links must not break.
5. **Schema bump**: should this trip `v=1` → `v=2` in the hash? Probably no — `&h3=` is purely additive and old clients ignore unknown params. Reserve the version bump for breaking changes.

---

## 6. Phasing

- **Phase 1** *(this proposal)*: ship `&h3=<cell>` per Option C. ~25-line patch in `explorer.qmd` (carry `h3_cell` through the runtime `id`; extend `_globeState`, `readHash`, `buildHash`, cluster-click handler, hash hydration). Update `EXPLORER_STATE.md §2` table to add the row.
- **Phase 2** *(only if needed)*: unified `&sel=` field per Option D. Worth doing only if a third selection type (e.g., region/polygon) appears.

The previous Phase 2 (compat shim from `&cluster=` to `&h3=`) is dropped — by going straight to Option C we never ship the lossy intermediate form.

---

## 7. Acceptance for Phase 1

- [ ] `h3_cell` carried through the runtime cluster `id` at both `add()` sites (`:987`, `:1331`).
- [ ] `viewer._globeState.selectedH3` field exists and is mutated by the cluster-click handler at `:916`.
- [ ] `buildHash()` writes `&h3=` when `selectedH3` is non-null.
- [ ] `readHash()` parses `&h3=` as a hex string.
- [ ] Reloading a `&h3=<cell>` URL re-populates the side-panel cluster card + nearby-samples list with the same data the click would have produced (exact `WHERE h3_cell = ?` join).
- [ ] Sample-click clears `selectedH3`; cluster-click clears `selectedPid`. Mutual exclusion preserved.
- [ ] `EXPLORER_STATE.md §2` table updated with the new row.
- [ ] One Playwright test: click cluster → verify URL contains `&h3=` → reload → verify side panel re-populates.
