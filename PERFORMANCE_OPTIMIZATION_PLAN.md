# Performance Optimization Plan: Cesium Tutorial

**Date**: 2025-10-31
**Issue**: Page loading is VERY SLOW
**Root Cause Analysis**: Multiple compounding factors

---

## 🎯 Performance Bottlenecks Identified

### 1. **Initial Page Load: `locations` Query** ⚠️ CRITICAL BOTTLENECK

**Location**: `parquet_cesium.qmd` lines 131-157

**Current Behavior**:
```sql
WITH geo_classification AS (
    SELECT
        geo.pid, geo.latitude, geo.longitude,
        MAX(CASE WHEN e.p = 'sample_location' THEN 1 ELSE 0 END) as is_sample_location,
        MAX(CASE WHEN e.p = 'site_location' THEN 1 ELSE 0 END) as is_site_location
    FROM nodes geo
    JOIN nodes e ON (geo.row_id = e.o[1])
    WHERE geo.otype = 'GeospatialCoordLocation'
    GROUP BY geo.pid, geo.latitude, geo.longitude
)
SELECT * FROM geo_classification
```

**Why It's Slow**:
- Self-join of `nodes` table with itself on **array element match** (`e.o[1]`)
- Scans ALL GeospatialCoordLocation nodes (likely thousands)
- GROUP BY with aggregation (MAX + CASE) for classification
- Runs BEFORE user can interact with page
- DuckDB-WASM must load relevant parquet chunks via HTTP

**Estimated Impact**: 🔴 **80% of perceived slowness**

---

### 2. **Click-Triggered Queries: 6 Self-Joins Each** ⚠️ MEDIUM BOTTLENECK

**Three Queries** (Eric's, Path 1, Path 2) all follow this pattern:

```sql
FROM nodes AS geo
JOIN nodes AS rel_se ON (rel_se.p = 'sample_location' AND list_contains(rel_se.o, geo.row_id))
JOIN nodes AS se ON (rel_se.s = se.row_id AND se.otype = 'SamplingEvent')
JOIN nodes AS rel_site ON (se.row_id = rel_site.s AND rel_site.p = 'sampling_site')
JOIN nodes AS site ON (rel_site.o[1] = site.row_id AND site.otype = 'SamplingSite')
JOIN nodes AS rel_samp ON (rel_samp.p = 'produced_by' AND list_contains(rel_samp.o, se.row_id))
JOIN nodes AS samp ON (rel_samp.s = samp.row_id AND samp.otype = 'MaterialSampleRecord')
WHERE geo.pid = ?
```

**Why It's Slow**:
- **6 self-joins** on the same `nodes` table
- **2 uses of `list_contains()`** for backward edge traversal (array scans)
- **Multi-hop graph traversal** (5 hops: geo → event → site → event → sample)
- Repeated for EACH clicked point

**Estimated Impact**: 🟡 **15% of perceived slowness** (only after click)

---

### 3. **Remote Parquet Loading** 🌐 FUNDAMENTAL CONSTRAINT

**Data Source**: `https://storage.googleapis.com/isamplesorg/data/oc_isamples_pqg.parquet`

**Why It's Inherently Slower**:
- HTTP range requests for parquet chunks
- Network latency (Google Cloud Storage → browser)
- DuckDB-WASM must parse and cache chunks
- No local indexes or materialized views

**Estimated Impact**: 🟠 **5% of perceived slowness** (well-optimized by DuckDB already)

---

## 🛠️ Optimization Strategies

### Strategy A: **Materialized View / Pre-Aggregated Geocode Index** 🌟 HIGHEST ROI

**Approach**: Pre-compute the `locations` query result into a separate lightweight parquet file

**Implementation**:
1. **Server-side preprocessing**:
   ```python
   # Run ONCE when oc_isamples_pqg.parquet updates
   import duckdb
   con = duckdb.connect()
   con.execute("""
       COPY (
           WITH geo_classification AS (
               SELECT
                   geo.pid, geo.latitude, geo.longitude,
                   MAX(CASE WHEN e.p = 'sample_location' THEN 1 ELSE 0 END) as is_sample_location,
                   MAX(CASE WHEN e.p = 'site_location' THEN 1 ELSE 0 END) as is_site_location
               FROM read_parquet('oc_isamples_pqg.parquet') geo
               JOIN read_parquet('oc_isamples_pqg.parquet') e ON (geo.row_id = e.o[1])
               WHERE geo.otype = 'GeospatialCoordLocation'
               GROUP BY geo.pid, geo.latitude, geo.longitude
           )
           SELECT * FROM geo_classification
       ) TO 'oc_geocodes_classified.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)
   """)
   ```

2. **Client-side usage**:
   ```javascript
   locations = {
       const query = `SELECT * FROM read_parquet('${geocodes_parquet_path}')`;
       const data = await loadData(query, [], "loading_1", "locations");
       // ... render points
   }
   ```

**Expected Speedup**: ⚡ **10-50x faster** initial load (from 5-10 seconds → <1 second)

**Tradeoffs**:
- ✅ Massive performance win
- ✅ Simple to implement
- ✅ No query rewrite needed
- ⚠️ Adds one more file to maintain (~50KB vs 700MB main file)
- ⚠️ Must regenerate when main parquet updates

---

### Strategy B: **Lazy Loading / Progressive Enhancement** 🎨 UX IMPROVEMENT

**Approach**: Let user interact with page BEFORE geocodes finish loading

**Implementation**:
1. Show Cesium globe immediately (already works)
2. Display loading indicator: "Loading 1,234 geocodes..."
3. Render points in batches as they arrive (chunked processing)
4. Enable search box immediately (independent of point rendering)

**Code Pattern**:
```javascript
locations = {
    const query = `...`; // existing query
    const data = await loadData(query, [], "loading_1", "locations");

    // Render in chunks of 500 to keep UI responsive
    const CHUNK_SIZE = 500;
    for (let i = 0; i < data.length; i += CHUNK_SIZE) {
        const chunk = data.slice(i, i + CHUNK_SIZE);
        for (const row of chunk) {
            // ... add points
        }
        // Yield to browser between chunks
        await new Promise(resolve => setTimeout(resolve, 0));
    }
    return data;
}
```

**Expected Improvement**: ⚡ **Perceived performance 3-5x better** (page feels interactive sooner)

**Tradeoffs**:
- ✅ Better UX without query changes
- ✅ Works with existing slow query
- ⚠️ More complex rendering logic
- ⚠️ Doesn't solve fundamental slowness

---

### Strategy C: **Denormalized Edge Indexes** 🗄️ FUNDAMENTAL RESTRUCTURE

**Approach**: Pre-build reverse lookup tables for common traversals

**Implementation**:
1. **Create separate index tables**:
   ```sql
   -- geo_to_events.parquet
   SELECT e.o[1] as geo_row_id, e.s as event_row_id, e.p as edge_type
   FROM nodes e
   WHERE e.p IN ('sample_location', 'site_location')

   -- event_to_samples.parquet
   SELECT rel.o[1] as event_row_id, rel.s as sample_row_id
   FROM nodes rel
   WHERE rel.p = 'produced_by'
   ```

2. **Rewrite queries to use indexes**:
   ```sql
   SELECT samp.*, geo.latitude, geo.longitude
   FROM read_parquet('samples.parquet') samp
   JOIN read_parquet('event_to_samples.parquet') idx1 ON (samp.row_id = idx1.sample_row_id)
   JOIN read_parquet('geo_to_events.parquet') idx2 ON (idx1.event_row_id = idx2.event_row_id)
   JOIN read_parquet('geocodes.parquet') geo ON (idx2.geo_row_id = geo.row_id)
   WHERE geo.pid = ?
   ```

**Expected Speedup**: ⚡ **5-10x faster** queries (from 1-2 seconds → 200-400ms)

**Tradeoffs**:
- ✅ Eliminates `list_contains()` array scans
- ✅ Reduces self-joins (separate tables = better indexes)
- ⚠️ **Major refactor**: Changes data model
- ⚠️ Breaks compatibility with existing notebooks
- ⚠️ More complex build pipeline

---

### Strategy D: **SQL Query Micro-Optimizations** 🔬 INCREMENTAL GAINS

**Approach**: Rewrite queries to help DuckDB optimizer

**Techniques**:

1. **Push down filters earlier**:
   ```sql
   -- BEFORE: Filter at end
   FROM nodes AS geo
   JOIN nodes AS rel_se ON (...)
   WHERE geo.pid = ?

   -- AFTER: Filter geo first
   FROM (SELECT * FROM nodes WHERE otype = 'GeospatialCoordLocation' AND pid = ?) AS geo
   JOIN nodes AS rel_se ON (...)
   ```

2. **Replace `list_contains()` with EXISTS subqueries** (if DuckDB optimizes better):
   ```sql
   -- BEFORE
   JOIN nodes AS rel_se ON (list_contains(rel_se.o, geo.row_id))

   -- AFTER (test if faster)
   JOIN nodes AS rel_se ON (geo.row_id = ANY(rel_se.o))
   ```

3. **Eliminate redundant JOINs**:
   - All 3 queries join to `site` just for `site.label` and `site.pid`
   - If not needed for filtering, could be a separate follow-up query

**Expected Speedup**: ⚡ **1.2-2x faster** (marginal gains)

**Tradeoffs**:
- ✅ No data model changes
- ✅ Easy to A/B test
- ⚠️ May not work due to DuckDB-WASM query planner limitations

---

## 📊 Recommended Prioritization

### Phase 1: **Quick Wins** (1-2 hours) 🟢

**Goal**: Make page feel 3-5x faster without major refactoring

1. ✅ **Implement Strategy B** (Lazy Loading)
   - Show "Loading X geocodes..." progress indicator
   - Render points in batches (500 at a time)
   - Enable search box before points finish loading

2. ✅ **Add telemetry** to understand actual timings
   ```javascript
   console.time('locations_query');
   const data = await loadData(query, ...);
   console.timeEnd('locations_query');
   ```

**Expected User Experience**:
- Page interactive in 1-2 seconds (vs 5-10 seconds)
- Visual feedback (progress bar)
- Can search for specific geocode immediately

---

### Phase 2: **Structural Optimization** (4-6 hours) 🟡

**Goal**: Achieve 10-50x speedup on initial load

1. ✅ **Implement Strategy A** (Materialized Geocode Index)
   - Create `oc_geocodes_classified.parquet` (~50KB)
   - Update GitHub Actions workflow to regenerate on data updates
   - Test with DuckDB-WASM in browser

2. ✅ **A/B Test Strategy D** (SQL Micro-Optimizations)
   - Try filter push-down
   - Measure actual impact (may be negligible)

**Expected User Experience**:
- Initial load: <1 second for geocode points
- First click query: Still 1-2 seconds (acceptable)

---

### Phase 3: **Deep Optimization** (2-3 days) 🔴 ONLY IF NEEDED

**Goal**: Achieve 5-10x speedup on click-triggered queries

1. ⚠️ **Evaluate Strategy C** (Denormalized Indexes)
   - Prototype with subset of data
   - Measure actual gains in DuckDB-WASM
   - Assess maintenance burden

2. ⚠️ **Consider alternative architectures**:
   - Pre-compute ALL common queries → static JSON files
   - Client-side caching (IndexedDB for query results)
   - WebAssembly-based custom graph traversal (if DuckDB still too slow)

**Only pursue if**: Phase 2 gains aren't sufficient for user needs

---

## 🧪 Measurement Plan

**Before optimization**:
```javascript
// Add to parquet_cesium.qmd
performance.mark('page-start');

locations = {
    performance.mark('locations-start');
    const data = await loadData(query, [], "loading_1", "locations");
    performance.mark('locations-end');
    performance.measure('locations-query', 'locations-start', 'locations-end');
    console.log(performance.getEntriesByName('locations-query')[0].duration + 'ms');
    return data;
}

// After first click
async function get_samples_1(pid) {
    performance.mark('samples1-start');
    const result = await loadData(q, [pid], "loading_s1", "samples_1");
    performance.mark('samples1-end');
    performance.measure('samples1-query', 'samples1-start', 'samples1-end');
    console.log(performance.getEntriesByName('samples1-query')[0].duration + 'ms');
    return result ?? [];
}
```

**Metrics to Track**:
- Initial page load time (to interactive)
- `locations` query execution time
- First click response time (each of 3 queries)
- Data transfer size (Network tab)
- Memory usage (Performance tab)

---

## 🤔 Fundamental Questions

### Q: "To what degree is this about SQL query efficiency?"

**A**: **~15% of the problem for initial load, ~80% for click queries**

- Initial load: The `locations` query is inherently expensive (self-join + GROUP BY on all geocodes), BUT could be **10-50x faster** with pre-aggregation (Strategy A)
- Click queries: The 6 self-joins are unavoidable given the property graph model, BUT could be **5-10x faster** with denormalized indexes (Strategy C)

### Q: "To what degree are we stuck because of self-joins?"

**A**: **We're only stuck if we insist on querying the raw property graph**

**The property graph model REQUIRES self-joins** because:
- All nodes and edges in ONE table (`nodes`)
- Graph traversal = multiple joins to the same table
- No escape without changing data model

**However, we have options**:
1. ✅ **Pre-aggregate common queries** (Strategy A) - avoids re-computing on every page load
2. ✅ **Denormalize hot paths** (Strategy C) - trades storage for query speed
3. ✅ **Cache results client-side** - only run expensive queries once per browser session
4. ⚠️ **Abandon property graph for query layer** - keep it for data ingestion, but publish separate optimized query tables

**The self-joins are NOT the problem**. The problem is:
- Running expensive aggregations on EVERY page load (fixable with Strategy A)
- No indexes on array-valued columns (`list_contains` scans) (fixable with Strategy C)
- No query result caching (fixable with client-side storage)

---

## 📋 Decision Points

**Before proceeding, clarify**:

1. **What's the user's pain threshold?**
   - Is 2 seconds initial load acceptable? (Then do Phase 1 only)
   - Need <1 second? (Then do Phase 2)
   - Need instant? (Then need Phase 3 or architectural rethink)

2. **What's the maintenance budget?**
   - Phase 1: Zero maintenance (just code changes)
   - Phase 2: Low maintenance (regenerate one small parquet file)
   - Phase 3: High maintenance (multiple derived tables, complex build pipeline)

3. **How often does source data update?**
   - Daily: Phase 2 is fine (automated regeneration)
   - Hourly: Phase 3 may be problematic (cache invalidation complexity)
   - Weekly: Even manual regeneration works

4. **What's the priority: initial load or click response?**
   - If initial load is the main complaint: **Focus on Strategy A**
   - If click queries are the main complaint: **Focus on Strategy C**

---

## 🎬 Next Steps

**Immediate Action** (recommend): Start with Phase 1 to get quick wins

1. Add performance telemetry to quantify actual bottlenecks
2. Implement lazy loading + progress indicators
3. Measure improvement
4. Re-assess if Phase 2 is needed

**Optional**: Prototype Strategy A (materialized geocode index) in parallel to see if it's worth pursuing

Let me know which direction you want to explore!
