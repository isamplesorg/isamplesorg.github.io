# Explorer Selection URL State — Audit + Cluster Proposal

Companion to [`EXPLORER_STATE.md`](./EXPLORER_STATE.md). Audit of what selection state
the Explorer URL captures today, and a proposal for adding cluster-selection
state so a URL alone can replay "I clicked this dot and got these samples."

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

Three things make this harder than `pid`:

1. **Resolution-dependent**: a cluster at H3 res 4 doesn't exist as a unit at res 6; it splits into smaller clusters. Reload at a different camera altitude → different H3 resolution → no cluster matches.
2. **Filter-dependent**: cluster aggregation depends on the active `?sources=`, `?material=`, etc. filters at click time. Reload with different filters → different aggregation, even at the same resolution.
3. **Source-faceted**: the cluster's `dominant_source` is the *majority* source in that cell. With filters applied, the dominant source can flip.

So a URL that says "you clicked the cluster at (lat=33.27, lng=-86.24, res=4, source=SESAR)" is only meaningful if the URL *also* pins the resolution and filter state. Most of those filters are already URL-persisted (§1) — the missing pieces are the cluster identity itself and possibly the resolution if it isn't already implied by `#alt`.

Tangentially: the resolution chosen by the explorer at any camera altitude is governed by the `zoomWatcher` cell. As long as that mapping is stable, `#alt` *implicitly* pins the resolution, but encoding the resolution explicitly is more robust to future changes.

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

### Option B: single packed string

```
#cluster=SESAR:4:33.2706,-86.2375
```

| pro | con |
|---|---|
| One token; matches `#pid` ergonomically; format is documentable. | Custom parser; slightly less human-editable. |

### Option C: H3 cell index

```
#h3=841a067ffffffff&cluster_source=SESAR
```

| pro | con |
|---|---|
| H3 cell index is a canonical 15-char hex token uniquely identifying the cell at a given resolution; resolution is *embedded* in the index. Joins to the cluster row are exact, not delta-windowed. | Requires the explorer to compute or read the H3 index from the data. The current parquet schema has `center_lat`/`center_lng` but I haven't confirmed whether the H3 cell index is available — needs a quick parquet-schema check before committing to this. |

### Option D: unified `&sel=` field with type prefix

```
#sel=p:ark:/65665/abc           (sample)
#sel=c:SESAR:4:33.2706,-86.2375 (cluster)
```

| pro | con |
|---|---|
| One field for "what's selected"; uniform handler; future-proofs other selection types. | Migration cost: existing `&pid=` URLs in the wild stop working unless we keep both. Backwards-compat shim isn't free. |

---

## 4. Recommendation

**Option B (single packed `&cluster=` field), keeping `&pid=` as-is.**

Rationale:

- One new token, one new parser, mirrors the cluster's runtime identity 1:1. No data-pipeline change.
- No backwards-compat tax. URLs with `&pid=` keep working unchanged.
- Cluster + sample selections are mutually exclusive in the runtime (`selectedPid` is cleared on cluster click), so the URL having at most one of `&pid=` / `&cluster=` matches that.
- Option C (H3 cell index) is *cleaner long-term* but needs a parquet-schema check + a possible data-build change. Worth doing if the H3 index is already there; defer if not.

Concretely:

```js
// extend _globeState
viewer._globeState = {
  mode: 'cluster' | 'point',
  selectedPid: string | null,
  selectedCluster: { source, res, lat, lng } | null,  // NEW
};

// readHash() addition
cluster: parseCluster(params.get('cluster')),  // 'SESAR:4:33.2706,-86.2375' → object | null

// buildHash() addition
const sc = gs.selectedCluster;
if (sc) params.set('cluster', `${sc.source}:${sc.res}:${sc.lat.toFixed(4)},${sc.lng.toFixed(4)}`);

// cluster-click handler (:916-920)
v._globeState.selectedPid = null;
v._globeState.selectedCluster = { source: meta.source, res: meta.resolution, lat: meta.lat, lng: meta.lng };
history.pushState(null, '', buildHash(v));

// hashchange / boot hydration (`:1733`, `:2167`)
if (state.cluster) {
  // Re-fetch the same nearby-samples query the click handler runs (`:925-960`)
  // by reconstructing meta from the URL token and calling updateClusterCard / nearbyQuery.
  // Mutual exclusion: clear selectedPid.
}
```

Behavior on URL load:

1. `&cluster=...` present, no `&pid=`: re-run the cluster card + nearby-samples query at boot. If the camera altitude maps to a different H3 resolution than the cluster's, *don't* try to highlight a different cell — just populate the side panel from the URL's frozen cluster identity.
2. `&pid=` present, no `&cluster=`: existing behavior, no change.
3. Both present: prefer `&pid=` (sample mode wins; cluster URL is stale). Drop `&cluster=` from a `replaceState` to clean up.
4. Neither: blank selection (current behavior).

---

## 5. Open questions

1. **H3 cell index in parquet?** If `oc_isamples_pqg_wide.parquet` (or the lite pre-aggregated cluster parquet) already carries the H3 index per-row, switch to Option C and the encoding becomes `&h3=841a067ffffffff&cluster_source=SESAR`. Worth a one-off `DESCRIBE` query to find out. *Action: 5-min check before implementation.*
2. **Cross-resolution behavior on load.** If you share a `&cluster=...&alt=...` URL and the recipient's window is wider/narrower → the alt → resolution mapping might pick a different res. Should the URL load *force* the resolution to match the cluster's, or just populate the side-panel and let the camera dictate the visible H3 layer? *Recommendation: just populate the side panel; don't override camera. The shared-link receiver wanted to see your sample list, not necessarily your H3 grid.*
3. **Does the side panel need a "this cluster's view is no longer live" hint** when the recipient's camera/filters cause the on-globe cluster to differ from the URL one? *Defer; revisit after implementation if it confuses people.*
4. **Backwards compat for `&pid=`**: keep forever. Anyone who shared a sample-link in the wild today should not have it break.
5. **Schema bump**: should this trip `v=1` → `v=2` in the hash? Probably no — `&cluster=` is purely additive and old clients ignore it. Reserve the version bump for breaking changes.

---

## 6. Phasing

- **Phase 1** *(this proposal)*: ship `&cluster=` per Option B. ~30-line patch in `explorer.qmd`. Update `EXPLORER_STATE.md §2` table to add the row.
- **Phase 2** *(deferred)*: if Option C turns out to be free (H3 cell index in the parquet), migrate `&cluster=` to `&h3=` and keep a one-version compat shim that accepts both.
- **Phase 3** *(deferred, only if needed)*: unified `&sel=` field per Option D. Only worth doing if a third selection type (e.g., region/polygon) appears.

---

## 7. Acceptance for Phase 1

- [ ] `viewer._globeState.selectedCluster` field exists and is mutated by the cluster-click handler at `:916`.
- [ ] `buildHash()` writes `&cluster=` when `selectedCluster` is non-null.
- [ ] `readHash()` parses `&cluster=` into the same shape.
- [ ] Reloading a `&cluster=...` URL re-populates the side-panel cluster card + nearby-samples list with the same data the click would have produced.
- [ ] Sample-click clears `selectedCluster`; cluster-click clears `selectedPid`. Mutual exclusion preserved.
- [ ] `EXPLORER_STATE.md §2` table updated with the new row.
- [ ] One Playwright test: click cluster → verify URL contains `&cluster=` → reload → verify side panel re-populates.
