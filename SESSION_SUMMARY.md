# iSamples Website Session Summary
**Date**: 2025-12-10
**Status**: Recovery session - resumed after interrupted session, confirmed cleanup plan NOT executed

---

## Quick Context

Session was interrupted before /wrap. Recovered context from SESSION_SUMMARY.md and dev-journal. Confirmed that the extensive repo cleanup plan was documented but NOT executed - `archive/` directory doesn't exist yet.

Previous session (Dec 9) completed query performance profiling. This session was brief - just recovery and status check.

---

## Accomplished

### Dec 10 (This Session)
- **Session Recovery**: Recovered context from interrupted session via /resume
- **Status Verification**: Confirmed `archive/` dir not created, cleanup plan not executed
- **Uncommitted Changes Identified**: Found staged changes in 3 repos (website, python, export_client)

### Dec 9 (Previous Session)
- **Query Profiler Created**: `scripts/profile_queries.py` - benchmarks all key Cesium queries
- **Performance Baseline Established**: Remote R2 parquet query times measured
- **Bottlenecks Identified**: `list_contains()` JOINs and full-table scans are the culprits
- **Optimization Strategy Defined**: Two-tier data architecture with pre-computed artifacts
- **Repo Inventory Documented**: Full assessment of 14 repos with cleanup recommendations

---

## Key Findings (Dec 9 Profiling)

| Query | Time | Verdict |
|-------|------|---------|
| Locations (cold) | 3,875ms | Too slow for initial load |
| Locations (warm) | 1,598ms | Still slow even cached |
| Point selection (direct) | 4,341ms | Unacceptable for click |
| Point selection (site-mediated) | 578ms | Borderline |
| Entity counts | 158ms | Fast enough |
| Classification | SKIPPED | Machine-killer (minutes+, GB memory) |

**Root Causes:**
1. **Locations**: Scanning 19.5M rows for 5.98M geocodes, returning 47 columns when 3 needed
2. **Point selection**: `list_contains()` on arrays requires full table scan - no index
3. **Classification**: LEFT JOINs with `list_contains()` = exponential complexity

---

## Generated Files

| File | Description | Keep/Regenerate |
|------|-------------|-----------------|
| `scripts/profile_queries.py` | Query benchmarking tool | Keep |
| `/tmp/query_profile_results.txt` | Latest profiling output | Regenerate |

### From Previous Session (Dec 6)
| File | Description | Keep/Regenerate |
|------|-------------|-----------------|
| `/tmp/zenodo_narrow_strict.parquet` | Narrow PQG (709MB) | Keep - on R2 |
| `/tmp/zenodo_wide_strict.parquet` | Wide PQG (242MB) | Keep - on R2 |
| `~/.claude/skills/gemini/SKILL.md` | Gemini skill doc | Keep |

---

## Public URLs

- **Wide**: `https://pub-a18234d962364c22a50c787b7ca09fa5.r2.dev/isamples_202512_wide.parquet`
- **Narrow**: `https://pub-a18234d962364c22a50c787b7ca09fa5.r2.dev/isamples_202512_narrow.parquet`

---

## Next Steps (Prioritized)

### 0. Eric/Andrea Wrap-Up Plan (Dec 2025)

**From Eric's email (confirmed Dec 10) - three-part plan:**

#### Part 1: Archive Full PQG Export to Zenodo
- Use PostgreSQL dump Dave can recover
- Create comprehensive iSamples Central PQG export
- Archive to Zenodo for preservation

#### Part 2: Simplified Parquet for Frontend (HIGH PRIORITY)
Requirements for parquet-powered iSamples Central:

| Feature | Implementation Notes |
|---------|---------------------|
| **Global Cesium map** | Use H3 geohash (https://h3geo.org/) to aggregate locations for fast rendering |
| **Faceted filtering** | Facets with counts: object type, material type, collection |
| **Map updates on filter** | Filtering facets should update world map dynamically |
| **Click → sample table** | Point click shows sample records (like OpenContext demo) |
| **Links to source** | Sample results link back to home collections |
| **Full-text search** | Search updates world map (stretch goal?) |

**Key insight from Eric**: May need even MORE denormalized parquet than "PQG wide" - specifically designed for these UI needs.

#### Part 3: Visual Enhancements (Nice to have)
- Most records lack thumbnails
- Use collection logos as stand-ins
- Use NounProject icons (Eric has account) for sample object types
- Icons from: https://isamples.org/models/generated/vocabularies/material_sample_object_type.html

---

### 1. Create Optimized Intermediary Artifacts (High priority, Medium risk)

**Aligns with Eric's Part 2 - simplified parquet for frontend**

**Recommended artifacts:**

1. **`locations_h3.parquet`** (~1-5MB) - NEW based on Eric's suggestion
   - H3 hexagonal aggregation at multiple resolutions
   - h3_index, count, representative_lat, representative_lon
   - For fast initial map render with clustering

2. **`locations_summary.parquet`** (~5-10MB)
   - Pre-filtered: pid, latitude, longitude, location_type
   - Only 5.98M rows × 4 columns
   - Target: <500ms initial load

3. **`facets_precomputed.parquet`** (~1MB) - NEW for Eric's faceting
   - Pre-aggregated counts by: object_type, material_type, collection
   - Enables instant facet rendering

4. **`location_samples_lookup.parquet`** (~50MB?)
   - Pre-computed: geo_pid → [sample_pids, sample_labels, source_url]
   - Eliminates `list_contains()` JOINs at query time
   - Target: <100ms point selection

5. Keep full wide parquet for detail drill-down only

### 2. Page Consolidation (Low risk)
- Merge `parquet_cesium_wide.qmd` and `parquet_cesium_isamples_wide.qmd`
- Update to use optimized artifacts

### 3. Public-Facing UI (Medium risk)
- Consider React SPA for production quality
- Features: Search, filter by source, map exploration, export
- Add collection logos/NounProject icons per Eric's suggestion

### 4. Schema Enforcement (Low risk)
- Normalize `sample_identifier_col` → `sample_identifier`
- Add column order tests

### 5. Deprecate iSamples Central API References (Medium priority, Low risk)

**Goal**: Pivot fully to parquet workflows while preserving API code for potential future revival.

**Strategy - "Soft Deprecation"**:
- Don't delete API client code - move to `_legacy/` or mark with deprecation warnings
- Update all tutorials/examples to use parquet-first patterns
- Add clear banners/callouts: "iSamples Central API is offline - using parquet archive"
- Keep API code importable but not in default examples

**Repositories affected**:
| Repo | Action |
|------|--------|
| `isamples-python` | Mark `IsbClient`, `IsbClient2`, `ISamplesBulkHandler` as deprecated; keep in codebase |
| `isamplesorg.github.io` | Remove/archive API-dependent tutorials; focus on parquet demos |
| `pqg` | Already parquet-native - no changes needed |

**Code preservation pattern**:
```python
# In isamples-python/src/isamples_client/isbclient.py
import warnings

class IsbClient:
    """
    DEPRECATED: iSamples Central API is offline as of 2025.
    Use parquet workflows instead - see examples/basic/geoparquet.ipynb

    This class is preserved for potential future API revival.
    """
    def __init__(self, ...):
        warnings.warn(
            "IsbClient is deprecated - iSamples Central API offline. "
            "Use parquet workflows: examples/basic/geoparquet.ipynb",
            DeprecationWarning,
            stacklevel=2
        )
        ...
```

**Documentation updates**:
- README.md: Lead with parquet, mention API as "archived"
- CLAUDE.md: Already notes API offline - strengthen language
- Tutorials: Archive API-dependent ones, create new parquet-only versions

**Parquet format focus** (per Eric's direction):
- PQG narrow format: Full fidelity, archival
- PQG wide format: Query-optimized, entity-centric
- Frontend-optimized: H3 aggregated, pre-computed facets (new)

### 6. Repository Cleanup & Organization (Low priority, Low risk)

**Inventory completed Dec 9, 2025** - Assessment of all iSamples repos:

#### Active Repositories (keep as-is)
| Repo | Last Commit | 6-Mo Commits | Size | Notes |
|------|-------------|--------------|------|-------|
| `isamplesorg.github.io` | Dec 6 | 71 | 1.4G | Primary website, Cesium demos |
| `isamples-python` | Dec 4 | 30 | 997M | Python client, Jupyter examples |
| `pqg` | Dec 6 | 21 | 18G | Property graph framework |

#### Maintained (keep, minimal changes expected)
| Repo | Last Commit | Notes |
|------|-------------|-------|
| `export_client` | Dec 5 | CLI for batch downloads |
| `isamplesorg-metadata` | Nov 14 | LinkML schemas, vocabularies |

#### Legacy/Archive (candidates for `archive/` subdirectory)
| Repo | Last Commit | Size | Notes |
|------|-------------|------|-------|
| `isamples_inabox` | Feb 2023 | 19M | Original server (PostgreSQL/Solr/FastAPI) |
| `isamples_docker` | Mar 2022 | 340M | Docker deployment - obsolete |
| `isamples_docker_upstream` | Mar 2023 | 357M | Docker mirror - obsolete |
| `isamples-ansible` | Mar 2023 | 381M | Ansible deployment - obsolete |
| `noid-generation` | Oct 2023 | 168M | NOID identifier tool |
| `noid-1` | Oct 2021 | 372K | Original NOID Python port |
| `noidy` | Apr 2023 | 284K | NOID variant |
| `pynoid` | Apr 2023 | 192K | NOID alternative |
| `ezid` | May 2023 | 93M | EZID identifier service |
| `ezid-client-tools` | Jun 2023 | 1.6M | EZID client tools |
| `opencontext_rdhyee` | Mar 2023 | 373M | Exploratory OC work |

#### Root-Level Files to Clean Up
**Keep (essential docs):**
- `CLAUDE.md`, `SESSION_SUMMARY.md` - Active guidance
- `EDGE_TYPE_FLOW.md`, `PQG_LEARNING_GUIDE.md` - Valuable reference

**Archive/Delete (Oct 2025 scratch files):**
- `test_*.py`, `test_*.js` - Exploratory test scripts
- `*_output.txt` - Test outputs (regenerable)
- `find_pkap_geos.py`, `investigate_path1.py` - One-off scripts
- `package.json`, `node_modules/` - Minimal npm setup (not needed)
- `GEMINI.md` - Empty placeholder
- `IMPLEMENTATION_SUMMARY.md`, `BILLING_UPDATE.md`, `QUERY_COMPARISON.md`, `AGENTS.md` - Possibly stale

**Suggested cleanup action:**
```bash
cd /Users/raymondyee/C/src/iSamples
mkdir -p archive
mv isamples_inabox isamples_docker isamples_docker_upstream isamples-ansible archive/
mv noid-generation noid-1 noidy pynoid ezid ezid-client-tools archive/
mv opencontext_rdhyee archive/
# Consider: rm -rf node_modules package.json package-lock.json
```

**Space recovery potential:** ~1.7GB from archiving legacy repos

---

## Active File Analysis (Per-Repo Cleanup Plans)

### 1. `isamplesorg.github.io` (1.4G total, 20M git)

**Most Active Files (commits since Jun 2025):**
| File | Commits | Status |
|------|---------|--------|
| `tutorials/parquet_cesium.qmd` | 27 | ACTIVE - main Cesium demo |
| `_quarto.yml` | 9 | Config |
| `tutorials/zenodo_isamples_analysis.qmd` | 7 | ACTIVE |
| `index.qmd` | 6 | Homepage |
| `tutorials/parquet_cesium_wide.qmd` | 2 | ACTIVE - wide format demo |
| `tutorials/parquet_cesium_isamples_wide.qmd` | 1 | ACTIVE - full iSamples demo |

**Space Hogs:**
- `assets/oc_isamples_pqg.parquet` - **691MB** (duplicated in docs/assets!)
- `docs/assets/` - 695MB (duplicate of assets/)

**Cleanup Opportunities:**
```bash
# Remove duplicate parquet (use R2 URL instead)
rm assets/oc_isamples_pqg.parquet
# Or add to .gitignore and reference R2 URL in tutorials
```

**Files to consider archiving:**
- `PERFORMANCE_OPTIMIZATION_PLAN.md`, `OPTIMIZATION_SUMMARY.md`, `LAZY_LOADING_IMPLEMENTATION.md` - One-off planning docs

---

### 2. `isamples-python` (997M total)

**Most Active Files:**
| File | Commits | Status |
|------|---------|--------|
| `examples/basic/oc_parquet_analysis_enhanced.ipynb` | 13 | ACTIVE |
| `examples/basic/geoparquet.ipynb` | 5 | ACTIVE - main parquet demo |
| `examples/basic/isample-archive.ipynb` | 4 | ACTIVE |
| `README.md`, `CLAUDE.md`, `pyproject.toml` | 4 each | Config/docs |
| `src/isamples_client/isbclient.py` | 1 | API client (TO DEPRECATE) |

**Space Hogs:**
- `examples/basic/oc_isamples_pqg.parquet` - **691MB**
- `examples/basic/oc_isamples_pqg_wide.parquet` - **275MB**

**Cleanup Opportunities:**
```bash
# Add parquet files to .gitignore, document R2 URLs instead
echo "*.parquet" >> .gitignore
# Or keep one canonical copy and symlink
```

**Files to consider archiving:**
- `PQG_INTEGRATION_PLAN.md`, `ISAMPLES_MODEL_ACTION_PLAN.md` - Planning docs (may be stale)
- `examples/spatial/` - Check if still relevant
- Multiple `*_output.txt` files

---

### 3. `pqg` (18G total - **NEEDS ATTENTION**)

**Most Active Files:**
| File | Commits | Status |
|------|---------|--------|
| `pqg/sql_converter.py` | 8 | ACTIVE - core converter |
| `pqg/pqg_singletable.py` | 4 | ACTIVE - main implementation |
| `README.md` | 4 | Docs |
| `pqg/typed_edges.py` | 2 | ACTIVE - typed edge support |
| `pqg/schemas/*.py` | 2 each | ACTIVE - schema validation |

**Space Hogs (CRITICAL):**
- `.git/` - **17GB** (likely large parquet commits in history)
- `.venv/` - 690MB (normal for DuckDB/PyArrow)

**Cleanup Opportunities:**
```bash
# Check git history for large files
git rev-list --objects --all | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' | sort -k3 -n -r | head -20

# Consider: git filter-repo to remove large parquet files from history
# Or: fresh clone without history
```

**Root cause investigation needed:** Why is .git 17GB? Likely committed large parquet files that were later removed.

---

### 4. `export_client` (58M total - clean)

**Most Active Files:**
| File | Commits | Status |
|------|---------|--------|
| `isamples_export_client/pqg_converter.py` | 4 | ACTIVE |
| `README.md` | 2 | Docs |

**Status:** Clean, well-organized. No cleanup needed.

---

### 5. `isamplesorg-metadata` (83M total - stable)

**Most Active Files:**
| File | Commits | Status |
|------|---------|--------|
| `src/docs/*.md` | 1 each | Documentation updates |

**Status:** Foundational schema repo. Stable. No cleanup needed.

---

## Priority Cleanup Actions

### Immediate (High impact, low risk)
1. **pqg .git cleanup** - 17GB is excessive. Investigate and consider `git filter-repo` or fresh clone
2. **Remove duplicate parquets** - `assets/oc_isamples_pqg.parquet` duplicated in website repo

### Short-term (Medium impact)
3. **Add `.gitignore` for parquet** - Reference R2 URLs instead of committing 691MB files
4. **Archive planning docs** - Move stale `*_PLAN.md` files to `archive/` in each repo

### When convenient (Low priority)
5. **Clean root-level scratch files** - Test scripts, output files in `/Users/raymondyee/C/src/iSamples/`

---

## Technical Notes

### Profiler Usage
```bash
# Safe mode (skips classification query)
~/.pyenv/versions/myenv/bin/python scripts/profile_queries.py --remote-only

# Full mode (WARNING: high memory/CPU)
~/.pyenv/versions/myenv/bin/python scripts/profile_queries.py --full

# Local only (if file downloaded)
curl -o /tmp/isamples_202512_wide.parquet https://pub-a18234d962364c22a50c787b7ca09fa5.r2.dev/isamples_202512_wide.parquet
~/.pyenv/versions/myenv/bin/python scripts/profile_queries.py --local-only
```

### Credentials & Tools
- **R2 Credentials**: Stored in 1Password, use `op run --env-file=...` pattern
- **Gemini CLI**: `/opt/homebrew/bin/gemini`
- **Codex CLI**: `/opt/homebrew/bin/codex exec "prompt" -o /tmp/output.txt`

---

## Blockers / Decisions Needed

1. **Artifact storage**: Upload optimized parquet files to R2? Or generate on-demand?
2. **Pre-compute strategy**: Run classification once during ETL vs compute lazily?
3. **Location type**: Should `location_type` be pre-computed (blue/purple/orange classification)?

---

## Resume Checklist

1. Read this SESSION_SUMMARY.md
2. Review profiling results: `/tmp/query_profile_results.txt`
3. Next action: Create `locations_summary.parquet` generation script
4. Public URLs above are live and working

---

**Last Updated**: 2025-12-09 by Claude Code (Opus 4.5)
**Repository**: isamplesorg.github.io (fork at rdhyee/isamplesorg.github.io)
**Focus**: Query performance optimization, intermediary artifact design
**Next Action**: Generate optimized parquet artifacts
**Session Status**: IN PROGRESS
