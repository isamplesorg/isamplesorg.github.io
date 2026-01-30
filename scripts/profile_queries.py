#!/usr/bin/env python3
"""
Profile iSamples Cesium demo queries to identify optimization opportunities.

This script benchmarks the key queries used in the Cesium visualization:
1. Initial location load (all GeospatialCoordLocation records)
2. Point selection queries (samples at a location via JOINs)
3. Classification query (color-coding by type)

Run with: op run -- python scripts/profile_queries.py
"""

import time
import statistics
from dataclasses import dataclass
from typing import Optional
import duckdb

# Data sources
REMOTE_URL = "https://pub-a18234d962364c22a50c787b7ca09fa5.r2.dev/isamples_202601_wide.parquet"
LOCAL_PATH = "/tmp/isamples_202601_wide.parquet"

# Sample geocode PIDs for point selection tests (will be populated from data)
SAMPLE_GEOCODE_PIDS = []


@dataclass
class QueryResult:
    """Result of a single query benchmark."""
    name: str
    duration_ms: float
    row_count: int
    first_run: bool = False
    notes: str = ""


@dataclass
class BenchmarkSuite:
    """Collection of benchmark results."""
    source: str
    results: list[QueryResult]

    def summary(self) -> str:
        lines = [f"\n{'='*60}", f"Benchmark Results: {self.source}", "="*60]
        for r in self.results:
            marker = " (COLD)" if r.first_run else ""
            lines.append(f"  {r.name}{marker}: {r.duration_ms:.1f}ms ({r.row_count:,} rows)")
            if r.notes:
                lines.append(f"    → {r.notes}")
        return "\n".join(lines)


def time_query(con: duckdb.DuckDBPyConnection, query: str, params: list = None) -> tuple[float, int]:
    """Execute query and return (duration_ms, row_count)."""
    start = time.perf_counter()
    if params:
        result = con.execute(query, params).fetchall()
    else:
        result = con.execute(query).fetchall()
    duration_ms = (time.perf_counter() - start) * 1000
    return duration_ms, len(result)


def get_sample_geocode_pids(con: duckdb.DuckDBPyConnection, limit: int = 5) -> list[str]:
    """Get some sample geocode PIDs for testing point selection."""
    query = """
        SELECT pid FROM nodes
        WHERE otype = 'GeospatialCoordLocation'
        AND latitude IS NOT NULL
        LIMIT ?
    """
    result = con.execute(query, [limit]).fetchall()
    return [row[0] for row in result]


def benchmark_metadata(con: duckdb.DuckDBPyConnection, source: str) -> QueryResult:
    """Benchmark metadata-only query (column stats, row count)."""
    query = "SELECT COUNT(*) as total, COUNT(DISTINCT otype) as types FROM nodes"
    duration, _ = time_query(con, query)

    # Get actual counts
    result = con.execute(query).fetchone()
    total, types = result

    return QueryResult(
        name="Metadata (COUNT)",
        duration_ms=duration,
        row_count=total,
        notes=f"{types} distinct otypes"
    )


def benchmark_locations_query(con: duckdb.DuckDBPyConnection, cold: bool = False) -> QueryResult:
    """Benchmark the main locations query (biggest bottleneck)."""
    query = """
        SELECT DISTINCT pid, latitude, longitude
        FROM nodes
        WHERE otype = 'GeospatialCoordLocation'
          AND latitude IS NOT NULL
          AND longitude IS NOT NULL
    """
    duration, count = time_query(con, query)
    return QueryResult(
        name="Locations (all geocodes)",
        duration_ms=duration,
        row_count=count,
        first_run=cold,
        notes="Main initial load - renders as Cesium points"
    )


def benchmark_point_selection_direct(con: duckdb.DuckDBPyConnection, pid: str) -> QueryResult:
    """Benchmark direct location query (p__sample_location JOIN)."""
    query = """
        SELECT
            geo.latitude,
            geo.longitude,
            site.label AS sample_site_label,
            samp.pid AS sample_pid,
            samp.label AS sample_label
        FROM nodes AS geo
        JOIN nodes AS se ON (
            se.otype = 'SamplingEvent'
            AND list_contains(se.p__sample_location, geo.row_id)
        )
        JOIN nodes AS site ON (
            site.otype = 'SamplingSite'
            AND list_contains(se.p__sampling_site, site.row_id)
        )
        JOIN nodes AS samp ON (
            samp.otype = 'MaterialSampleRecord'
            AND list_contains(samp.p__produced_by, se.row_id)
        )
        WHERE geo.pid = ?
          AND geo.otype = 'GeospatialCoordLocation'
        LIMIT 100
    """
    duration, count = time_query(con, query, [pid])
    return QueryResult(
        name="Point selection (direct)",
        duration_ms=duration,
        row_count=count,
        notes=f"pid={pid[:30]}..."
    )


def benchmark_point_selection_site_mediated(con: duckdb.DuckDBPyConnection, pid: str) -> QueryResult:
    """Benchmark site-mediated location query (p__site_location JOIN)."""
    query = """
        SELECT
            geo.latitude,
            geo.longitude,
            site.label AS sample_site_label,
            samp.pid AS sample_pid,
            samp.label AS sample_label
        FROM nodes AS geo
        JOIN nodes AS site ON (
            site.otype = 'SamplingSite'
            AND list_contains(site.p__site_location, geo.row_id)
        )
        JOIN nodes AS se ON (
            se.otype = 'SamplingEvent'
            AND list_contains(se.p__sampling_site, site.row_id)
        )
        JOIN nodes AS samp ON (
            samp.otype = 'MaterialSampleRecord'
            AND list_contains(samp.p__produced_by, se.row_id)
        )
        WHERE geo.pid = ?
          AND geo.otype = 'GeospatialCoordLocation'
        LIMIT 100
    """
    duration, count = time_query(con, query, [pid])
    return QueryResult(
        name="Point selection (site-mediated)",
        duration_ms=duration,
        row_count=count,
        notes=f"pid={pid[:30]}..."
    )


def benchmark_classification(con: duckdb.DuckDBPyConnection) -> QueryResult:
    """Benchmark the classification query (color-coding by type)."""
    query = """
        WITH geo_classification AS (
            SELECT
                geo.pid,
                MAX(CASE WHEN se.row_id IS NOT NULL THEN 1 ELSE 0 END) as is_sample_location,
                MAX(CASE WHEN site.row_id IS NOT NULL THEN 1 ELSE 0 END) as is_site_location
            FROM nodes geo
            LEFT JOIN nodes se ON (
                se.otype = 'SamplingEvent'
                AND list_contains(se.p__sample_location, geo.row_id)
            )
            LEFT JOIN nodes site ON (
                site.otype = 'SamplingSite'
                AND list_contains(site.p__site_location, geo.row_id)
            )
            WHERE geo.otype = 'GeospatialCoordLocation'
            GROUP BY geo.pid
        )
        SELECT
            pid,
            CASE
                WHEN is_sample_location = 1 AND is_site_location = 1 THEN 'both'
                WHEN is_sample_location = 1 THEN 'sample_location_only'
                WHEN is_site_location = 1 THEN 'site_location_only'
            END as location_type
        FROM geo_classification
    """
    duration, count = time_query(con, query)
    return QueryResult(
        name="Classification (color-coding)",
        duration_ms=duration,
        row_count=count,
        notes="LEFT JOIN with list_contains - very expensive!"
    )


def benchmark_entity_counts(con: duckdb.DuckDBPyConnection) -> QueryResult:
    """Benchmark entity type breakdown."""
    query = """
        SELECT otype, COUNT(*) as cnt
        FROM nodes
        GROUP BY otype
        ORDER BY cnt DESC
    """
    duration, count = time_query(con, query)
    return QueryResult(
        name="Entity counts by type",
        duration_ms=duration,
        row_count=count,
        notes="Useful for dashboard stats"
    )


def benchmark_source_counts(con: duckdb.DuckDBPyConnection) -> QueryResult:
    """Benchmark source breakdown (if source column exists)."""
    # Check if we have a source-like column
    query = """
        SELECT
            COALESCE(
                CASE
                    WHEN pid LIKE 'igsn:%' THEN 'SESAR'
                    WHEN pid LIKE 'ark:/28722/k2%' THEN 'OpenContext'
                    WHEN pid LIKE '%geome%' THEN 'GEOME'
                    WHEN pid LIKE '%smithsonian%' THEN 'Smithsonian'
                    ELSE 'Other'
                END,
                'Unknown'
            ) as source,
            COUNT(*) as cnt
        FROM nodes
        WHERE otype = 'MaterialSampleRecord'
        GROUP BY source
        ORDER BY cnt DESC
    """
    duration, count = time_query(con, query)
    return QueryResult(
        name="Source breakdown",
        duration_ms=duration,
        row_count=count,
        notes="Inferred from PID patterns"
    )


def run_benchmark_suite(source_path: str, source_name: str) -> BenchmarkSuite:
    """Run full benchmark suite against a data source."""
    print(f"\nConnecting to: {source_name}")
    print(f"  Path: {source_path[:80]}...")

    con = duckdb.connect()

    # Create view
    print("  Creating view...")
    start = time.perf_counter()
    con.execute(f"CREATE VIEW nodes AS SELECT * FROM read_parquet('{source_path}')")
    view_time = (time.perf_counter() - start) * 1000
    print(f"  View created in {view_time:.1f}ms")

    results = []

    # 1. Metadata (cold)
    print("  Running metadata query...")
    results.append(benchmark_metadata(con, source_name))

    # 2. Entity counts
    print("  Running entity counts...")
    results.append(benchmark_entity_counts(con))

    # 3. Source breakdown
    print("  Running source breakdown...")
    results.append(benchmark_source_counts(con))

    # 4. Locations query (cold)
    print("  Running locations query (cold)...")
    results.append(benchmark_locations_query(con, cold=True))

    # 5. Locations query (warm - cached)
    print("  Running locations query (warm)...")
    results.append(benchmark_locations_query(con, cold=False))

    # Get sample PIDs for point selection tests
    print("  Getting sample geocode PIDs...")
    sample_pids = get_sample_geocode_pids(con, limit=3)

    if sample_pids:
        # 6. Point selection (direct)
        print("  Running point selection (direct)...")
        results.append(benchmark_point_selection_direct(con, sample_pids[0]))

        # 7. Point selection (site-mediated)
        print("  Running point selection (site-mediated)...")
        results.append(benchmark_point_selection_site_mediated(con, sample_pids[0]))

    # 8. Classification (expensive!)
    print("  Running classification query (this may take a while)...")
    results.append(benchmark_classification(con))

    con.close()
    return BenchmarkSuite(source=source_name, results=results)


def analyze_optimization_opportunities(suite: BenchmarkSuite) -> str:
    """Analyze results and suggest optimizations."""
    lines = ["\n" + "="*60, "OPTIMIZATION ANALYSIS", "="*60]

    # Find the slowest queries
    sorted_results = sorted(suite.results, key=lambda r: r.duration_ms, reverse=True)

    lines.append("\nSlowest queries (candidates for optimization):")
    for i, r in enumerate(sorted_results[:3], 1):
        lines.append(f"  {i}. {r.name}: {r.duration_ms:.1f}ms")

    # Specific recommendations
    lines.append("\nRECOMMENDATIONS:")

    # Check locations query
    locations = next((r for r in suite.results if "Locations" in r.name and r.first_run), None)
    if locations and locations.duration_ms > 2000:
        lines.append(f"""
1. PRE-COMPUTE LOCATIONS PARQUET
   Current: {locations.duration_ms:.0f}ms for {locations.row_count:,} rows

   Create a dedicated `locations.parquet` with just:
   - pid, latitude, longitude (for Cesium rendering)
   - Pre-filtered to non-null coordinates

   Expected improvement: ~10x (load 3 columns vs 47)
""")

    # Check classification query
    classification = next((r for r in suite.results if "Classification" in r.name), None)
    if classification and classification.duration_ms > 5000:
        lines.append(f"""
2. PRE-COMPUTE CLASSIFICATION
   Current: {classification.duration_ms:.0f}ms

   The `list_contains()` JOINs are expensive. Pre-compute:
   - `locations_classified.parquet`: pid, lat, lon, location_type
   - Run classification once during ETL, not in browser

   Expected improvement: Classification becomes a simple lookup
""")

    # Check point selection
    point_direct = next((r for r in suite.results if "Point selection (direct)" in r.name), None)
    if point_direct and point_direct.duration_ms > 500:
        lines.append(f"""
3. INDEX FOR POINT SELECTION
   Current: {point_direct.duration_ms:.0f}ms per point click

   Options:
   a) Pre-compute sample-to-location mapping table
   b) Create DuckDB persistent database with indexes
   c) Use row_id indexes instead of list_contains() scans

   Target: <100ms for point selection
""")

    lines.append("""
4. TWO-TIER DATA STRATEGY
   Tier 1 (Initial Load): locations_summary.parquet (~5MB)
   - Just pid, lat, lon for rendering points
   - Optional: pre-computed counts, categories

   Tier 2 (On-Demand): Full wide parquet for drill-down
   - Only fetched when user clicks a point
   - HTTP range requests for specific rows
""")

    return "\n".join(lines)


def run_benchmark_suite_safe(source_path: str, source_name: str, skip_expensive: bool = True) -> BenchmarkSuite:
    """Run benchmark suite, optionally skipping expensive queries."""
    print(f"\nConnecting to: {source_name}")
    print(f"  Path: {source_path[:80]}...")

    con = duckdb.connect()

    # Create view
    print("  Creating view...")
    start = time.perf_counter()
    con.execute(f"CREATE VIEW nodes AS SELECT * FROM read_parquet('{source_path}')")
    view_time = (time.perf_counter() - start) * 1000
    print(f"  View created in {view_time:.1f}ms")

    results = []

    # 1. Metadata (cold)
    print("  Running metadata query...")
    results.append(benchmark_metadata(con, source_name))

    # 2. Entity counts
    print("  Running entity counts...")
    results.append(benchmark_entity_counts(con))

    # 3. Source breakdown
    print("  Running source breakdown...")
    results.append(benchmark_source_counts(con))

    # 4. Locations query (cold)
    print("  Running locations query (cold)...")
    results.append(benchmark_locations_query(con, cold=True))

    # 5. Locations query (warm - cached)
    print("  Running locations query (warm)...")
    results.append(benchmark_locations_query(con, cold=False))

    # Get sample PIDs for point selection tests
    print("  Getting sample geocode PIDs...")
    sample_pids = get_sample_geocode_pids(con, limit=3)

    if sample_pids:
        # 6. Point selection (direct)
        print("  Running point selection (direct)...")
        results.append(benchmark_point_selection_direct(con, sample_pids[0]))

        # 7. Point selection (site-mediated)
        print("  Running point selection (site-mediated)...")
        results.append(benchmark_point_selection_site_mediated(con, sample_pids[0]))

    # 8. Classification (expensive!) - skip by default
    if not skip_expensive:
        print("  Running classification query (WARNING: this is very expensive!)...")
        results.append(benchmark_classification(con))
    else:
        print("  SKIPPING classification query (use --full to include)")
        results.append(QueryResult(
            name="Classification (SKIPPED)",
            duration_ms=0,
            row_count=0,
            notes="Skipped - known to be very expensive (minutes+, high memory)"
        ))

    con.close()
    return BenchmarkSuite(source=source_name, results=results)


def main():
    import os
    import argparse

    parser = argparse.ArgumentParser(description="Profile iSamples Cesium demo queries")
    parser.add_argument("--full", action="store_true", help="Include expensive classification query (WARNING: high CPU/memory)")
    parser.add_argument("--local-only", action="store_true", help="Only test local file (skip remote)")
    parser.add_argument("--remote-only", action="store_true", help="Only test remote file (skip local)")
    args = parser.parse_args()

    print("="*60)
    print("iSamples Query Performance Profiler")
    print("="*60)

    if args.full:
        print("\n⚠️  WARNING: --full mode includes classification query")
        print("   This query can take MINUTES and use GIGABYTES of memory!")
        print("   Press Ctrl+C within 5 seconds to cancel...")
        try:
            time.sleep(5)
        except KeyboardInterrupt:
            print("\nCancelled.")
            return

    skip_expensive = not args.full

    # Check if local file exists
    local_exists = os.path.exists(LOCAL_PATH)

    remote_suite = None
    local_suite = None

    # Test remote (the production scenario)
    if not args.local_only:
        print("\n[1/2] Benchmarking REMOTE source (R2)...")
        try:
            remote_suite = run_benchmark_suite_safe(REMOTE_URL, "Remote (R2)", skip_expensive)
            print(remote_suite.summary())
        except Exception as e:
            print(f"  ERROR: {e}")

    # Test local if available
    if not args.remote_only:
        if local_exists:
            print("\n[2/2] Benchmarking LOCAL source...")
            try:
                local_suite = run_benchmark_suite_safe(LOCAL_PATH, "Local File", skip_expensive)
                print(local_suite.summary())
            except Exception as e:
                print(f"  ERROR: {e}")
        else:
            print(f"\n[2/2] Skipping local benchmark - file not found: {LOCAL_PATH}")
            print(f"      Download with: curl -o {LOCAL_PATH} {REMOTE_URL}")

    # Analysis
    suite_to_analyze = local_suite or remote_suite
    if suite_to_analyze:
        print(analyze_optimization_opportunities(suite_to_analyze))

    print("\n" + "="*60)
    print("Profiling complete!")
    print("="*60)


if __name__ == "__main__":
    main()
