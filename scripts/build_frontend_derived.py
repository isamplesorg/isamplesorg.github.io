#!/usr/bin/env python3
"""Build the explorer's frontend-derived parquet files from a wide PQG parquet.

Deterministic, reproducible builder for the 6 ad-hoc Stage-4 derived files
(see DATA_PROVENANCE.md). Every run also writes a manifest (input + output
checksums, argv, git SHA, DuckDB + extension versions) so a build is
machine-identifiable and re-verifiable.

INPUT CONTRACT (enforced/handled):
  A wide PQG parquet with entity rows incl. MaterialSampleRecord +
  IdentifiedConcept. The `geometry` column may be **WKB BLOB** or DuckDB
  **GEOMETRY** — both are handled (detected at runtime). Concept references
  live in `p__has_{material,context,sample_object}_category` row-id arrays.

OUTPUTS (into --outdir, prefixed --tag):
  - {tag}_sample_facets_v2.parquet   pid, source, material, context, object_type, label, description (search-only; includes appended concept labels), place_name(VARCHAR)
  - {tag}_samples_map_lite.parquet   pid, label, source, latitude, longitude, place_name(VARCHAR[]), result_time, h3_res4(UBIGINT), h3_res6(UBIGINT), h3_res8(UBIGINT), h3_res8_hex
  - {tag}_h3_summary_res{4,6,8}.parquet  h3_cell(UBIGINT), sample_count(INT), center_lat, center_lng, dominant_source, source_count(INT), resolution(INT)
  - {tag}_facet_summaries.parquet    facet_type, facet_value, scheme, count
  - {tag}_facet_cross_filter.parquet filter_source/material/context/object_type, facet_type, facet_value, count
  - {tag}_wide_h3.parquet            wide + h3_res4/6/8  (large; built only on --only wide_h3)
  - {tag}_sample_facet_index.parquet pid, source, material_mask, context_mask, object_type_mask(BIGINT), build_id, schema_version(INT) — COMPLETE per-pid index over ALL located samples (incl. #306 no-membership pids, zero-masked); the multi-filter global-view count path (#304/#305) scans this
  - {tag}_manifest.json              provenance + per-output rowcount/schema/sha256

MATERIAL SELECTION (issue #265/#271): the broad SKOS root
`.../material/1.0/material` ("Material") can appear at ANY position in the
concept array; the old `[1]` pick surfaced it as a bogus facet value. We pick
the FIRST NON-ROOT concept (by array order); samples tagged ONLY at the root
get NULL material (excluded from the facet). This is NOT leaf/most-specific
selection — see DATA_PROVENANCE.md. context/object_type use the first array
element ([1]); their root-dropping is deferred (tracked in the pipeline epic).

Determinism: row order and all DISCRETE values are deterministic (ORDER BY on
every COPY; dominant_source ties broken by source name ASC; non-unique keys are
a hard error). Floating centroids (center_lat/lng) are rounded to 6 dp and are
display-only — not part of the reproducibility guarantee; pass --threads 1 for
bit-stable centroids across machines.

Usage:
  python scripts/build_frontend_derived.py --wide WIDE.parquet --outdir OUT --tag isamples_202606
  python scripts/build_frontend_derived.py --wide WIDE.parquet --outdir OUT --tag T --only sample_facets_v2,facet_summaries
"""
import argparse, hashlib, json, os, subprocess, sys, time
import duckdb

MATERIAL_ROOT = "https://w3id.org/isample/vocabulary/material/1.0/material"
FACET_DIMS = ["source", "material", "context", "object_type"]
# Hierarchical dims (#281/#282): wide array column + the dim's canonical SKOS
# root. The array carries each sample's SET of asserted IdentifiedConcept
# row_ids (general↔specific, no guaranteed order — FACET_HIERARCHY_PLAN.md §0).
# The root is dropped from "asserted" (re-added via closure) and is the single
# tree root per dim. source has no vocab tree. (Codex: drop ONLY these explicit
# roots, not every parentless concept — deprecated/parentless concepts must stay.)
DIM_ARRAY_COL = {
    "material": "p__has_material_category",
    "context": "p__has_context_category",
    "object_type": "p__has_sample_object_type",
}
DIM_ROOT = {
    "material": MATERIAL_ROOT,
    "context": "https://w3id.org/isample/vocabulary/sampledfeature/1.0/anysampledfeature",
    "object_type": "https://w3id.org/isample/vocabulary/materialsampleobjecttype/1.0/materialsample",
}
# the artifacts this script knows how to build (for --only/--skip validation)
ARTIFACTS = ["sample_facets_v2", "samples_map_lite", "h3_summaries",
             "facet_summaries", "facet_cross_filter", "wide_h3",
             "sample_facet_membership", "facet_tree_summaries",
             "facet_tree_cross_filter", "facet_node_bits", "sample_facet_masks",
             "sample_facet_index"]
# #293: max tree nodes per dim that fit in a signed BIGINT mask (bits 0..62).
# Live max is 22 (context); guard so a future vocab explosion fails loudly
# instead of silently overflowing a mask bit.
MASK_MAX_BITS = 63
# #305/#306: schema version for the complete per-pid facet index. Bump when the
# column set / semantics of sample_facet_index change so the explorer can refuse
# an index it doesn't understand instead of mis-reading it.
INDEX_SCHEMA_VERSION = 1

# Shared SQL expression for sample_facets_v2.description (#277 part 2).
# Appends space-joined concept labels (IC labels across all 4 concept dims)
# to the raw description so full-text search matches concept terms even when
# they don't appear in label/description/place_name.  description is
# SEARCH-ONLY in facets_v2 — display reads from the wide parquet.
# Used by build_sample_facets_v2 AND the validator's --wide semantic gate so
# they can never drift from each other.
FACETS_DESCRIPTION_EXPR = (
    "CASE"
    "  WHEN concept_labels IS NOT NULL AND TRIM(concept_labels) != ''"
    "  THEN COALESCE(description, '') || ' ' || concept_labels"
    "  ELSE description"
    " END"
)


def log(msg, t0):
    print(f"[{time.time()-t0:6.1f}s] {msg}", flush=True)


def sha256_file(path, _bufsize=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_bufsize), b""):
            h.update(chunk)
    return h.hexdigest()


def geometry_expr(con, wide):
    """Return a SQL expression yielding a GEOMETRY from `s.geometry`, whether the
    column is stored as WKB BLOB or as DuckDB GEOMETRY. Fixes the silent
    BLOB-only contract (202604 wide = BLOB; 202601/Zenodo wides = GEOMETRY)."""
    rows = con.sql(f"DESCRIBE SELECT geometry FROM read_parquet('{wide}') LIMIT 0").fetchall()
    coltype = rows[0][1].upper() if rows else "BLOB"
    if coltype == "GEOMETRY":
        return "s.geometry"
    if coltype in ("BLOB", "WKB_BLOB", "VARBINARY"):
        return "ST_GeomFromWKB(s.geometry)"
    raise SystemExit(f"FATAL: unexpected geometry column type {coltype!r} in {wide}")


def build_base_tables(con, wide, t0):
    geom = geometry_expr(con, wide)
    con.execute(f"""
    -- ic: concept lookup for facet resolution and label aggregation.
    -- label is included so concept_labels can aggregate human-readable text
    -- directly from the wide without a second scan.
    CREATE OR REPLACE TEMP TABLE ic AS
      SELECT row_id, pid AS uri, label
      FROM read_parquet('{wide}') WHERE otype='IdentifiedConcept';

    -- material: FIRST NON-ROOT concept per sample. Decorrelated (unnest+join+
    -- arg_min by array ordinality) — NOT a correlated subquery and NOT a MAP
    -- cross-join (both of which blow up the planner on 20M rows).
    CREATE OR REPLACE TEMP TABLE mat AS
      WITH ex AS (
        SELECT s.pid AS pid, u.rid AS rid, u.ord AS ord
        FROM read_parquet('{wide}') s,
             UNNEST(s.p__has_material_category) WITH ORDINALITY AS u(rid, ord)
        WHERE s.otype='MaterialSampleRecord'
      )
      SELECT ex.pid, arg_min(ic.uri, ex.ord) AS material
      FROM ex JOIN ic ON ic.row_id = ex.rid
      WHERE ic.uri <> '{MATERIAL_ROOT}'
      GROUP BY ex.pid;

    -- concept_labels: one row per MSR pid; concept_labels is a space-joined
    -- string of all DISTINCT non-null IC labels referenced across
    -- p__has_material_category, p__has_sample_object_type,
    -- p__has_context_category, and p__keywords.  Appended (search-only) into
    -- sample_facets_v2.description so full-text searches like "pottery cyprus"
    -- match samples tagged with a pottery concept even if the word doesn't
    -- appear in their label/description/place_name.  facets_v2.description is
    -- SEARCH-ONLY; display always reads description from the wide parquet.
    CREATE OR REPLACE TEMP TABLE concept_labels AS
      WITH all_refs AS (
        SELECT s.pid, u.rid
        FROM read_parquet('{wide}') s, UNNEST(s.p__has_material_category) AS u(rid)
        WHERE s.otype='MaterialSampleRecord'
        UNION ALL
        SELECT s.pid, u.rid
        FROM read_parquet('{wide}') s, UNNEST(s.p__has_sample_object_type) AS u(rid)
        WHERE s.otype='MaterialSampleRecord'
        UNION ALL
        SELECT s.pid, u.rid
        FROM read_parquet('{wide}') s, UNNEST(s.p__has_context_category) AS u(rid)
        WHERE s.otype='MaterialSampleRecord'
        UNION ALL
        SELECT s.pid, u.rid
        FROM read_parquet('{wide}') s, UNNEST(s.p__keywords) AS u(rid)
        WHERE s.otype='MaterialSampleRecord'
      )
      SELECT r.pid,
             string_agg(DISTINCT ic.label, ' ' ORDER BY ic.label) AS concept_labels
      FROM all_refs r
      JOIN ic ON ic.row_id = r.rid
      WHERE ic.label IS NOT NULL AND TRIM(ic.label) != ''
      GROUP BY r.pid;

    -- one row per MaterialSampleRecord; all concept resolution via JOINs (decorrelated).
    CREATE OR REPLACE TEMP TABLE samp AS
      SELECT
        s.pid,
        s.n                              AS source,
        s.label,
        s.description,
        s.place_name,                    -- VARCHAR[]
        s.result_time,
        ROUND(ST_Y({geom}), 6)           AS latitude,
        ROUND(ST_X({geom}), 6)           AS longitude,
        mat.material                     AS material,
        ctx.uri                          AS context,
        obj.uri                          AS object_type,
        cl.concept_labels                AS concept_labels
      FROM read_parquet('{wide}') s
      LEFT JOIN mat ON mat.pid = s.pid
      LEFT JOIN ic AS ctx ON ctx.row_id = s.p__has_context_category[1]
      LEFT JOIN ic AS obj ON obj.row_id = s.p__has_sample_object_type[1]
      LEFT JOIN concept_labels cl ON cl.pid = s.pid
      WHERE s.otype='MaterialSampleRecord';

    CREATE OR REPLACE TEMP TABLE samp_geo AS
      SELECT *,
             h3_latlng_to_cell(latitude, longitude, 4) AS h3_res4,
             h3_latlng_to_cell(latitude, longitude, 6) AS h3_res6,
             h3_latlng_to_cell(latitude, longitude, 8) AS h3_res8
      FROM samp WHERE latitude IS NOT NULL AND longitude IS NOT NULL;
    """)
    n_samp = con.sql("SELECT COUNT(*) FROM samp").fetchone()[0]
    n_geo = con.sql("SELECT COUNT(*) FROM samp_geo").fetchone()[0]
    n_dup = con.sql("SELECT COUNT(*) FROM (SELECT pid FROM samp_geo GROUP BY pid HAVING COUNT(*)>1)").fetchone()[0]
    n_icdup = con.sql("SELECT COUNT(*) FROM (SELECT row_id FROM ic GROUP BY row_id HAVING COUNT(*)>1)").fetchone()[0]
    # #305/#306 (Codex): the GROUP BY...HAVING COUNT>1 dup check above collapses all
    # NULL pids into ONE group, so a SINGLE NULL pid slips through — yet a NULL pid
    # breaks every pid join (joins drop it) and is silently absent from the coverage
    # fingerprint. Reject it explicitly.
    n_null = con.sql("SELECT COUNT(*) FROM samp_geo WHERE pid IS NULL").fetchone()[0]
    log(f"samp={n_samp:,}  samp_geo={n_geo:,}  duplicate_pids={n_dup:,}  "
        f"null_pids={n_null:,}  duplicate_concept_row_ids={n_icdup:,}", t0)
    if n_dup or n_icdup or n_null:
        # HARD fail (Codex): non-unique/NULL keys make the output grain wrong (inflated
        # facet counts, ambiguous joins, non-total ORDER BY pid). Abort before writing.
        raise SystemExit(
            f"FATAL: non-unique/NULL keys — duplicate_pids={n_dup}, null_pids={n_null}, "
            f"duplicate_concept_row_ids={n_icdup}. "
            f"Output grain/joins would be wrong; refusing to write.")


def build_sample_facets_v2(con, out):
    # description is SEARCH-ONLY in sample_facets_v2: the explorer reads
    # description for display from the wide parquet (self-join on pid), never
    # from facets_v2.  We append the space-joined concept labels of every
    # IdentifiedConcept referenced by this sample (p__has_material_category,
    # p__has_sample_object_type, p__has_context_category, p__keywords) so that
    # full-text searches like "pottery cyprus" match samples tagged with a pottery
    # concept even when the word doesn't appear in label/description/place_name.
    # The wide's IdentifiedConcept.label is used directly (covers minted keyword
    # concepts such as British Museum thesaurus terms that are absent from
    # vocab_labels.parquet). See issue #277 part 2.
    con.execute(f"""COPY (
        SELECT pid, source, material, context, object_type, label,
               {FACETS_DESCRIPTION_EXPR} AS description,
               place_name::VARCHAR AS place_name
        FROM samp_geo ORDER BY pid
    ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)""")


def build_samples_map_lite(con, out):
    # h3_res4/h3_res6 (#300): the browser aggregates filtered clusters on the
    # fly off this file (GROUP BY the res-appropriate h3 column + the #293 mask
    # predicate) so a broad facet filter at world zoom renders as fast filtered
    # clusters instead of capped raw points. They dictionary-compress well (far
    # fewer distinct values than res8), so the size delta is small. h3_res8 was
    # already present (point-mode selected-cell lookups).
    con.execute(f"""COPY (
        SELECT pid, label, source, latitude, longitude, place_name, result_time,
               h3_res4::UBIGINT AS h3_res4,
               h3_res6::UBIGINT AS h3_res6,
               h3_res8::UBIGINT AS h3_res8,
               h3_h3_to_string(h3_res8) AS h3_res8_hex
        FROM samp_geo ORDER BY pid
    ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)""")


def build_h3_summary(con, out, res):
    col = f"h3_res{res}"
    # deterministic dominant_source: max sample count, ties broken by source name ASC.
    con.execute(f"""COPY (
        WITH sc AS (
            SELECT {col} AS cell, source, COUNT(*) AS c
            FROM samp_geo WHERE {col} IS NOT NULL GROUP BY {col}, source
        ),
        dom AS (
            SELECT cell, source AS dominant_source,
                   ROW_NUMBER() OVER (PARTITION BY cell ORDER BY c DESC, source ASC) AS rn
            FROM sc
        ),
        agg AS (
            SELECT {col} AS cell, COUNT(*) AS sample_count,
                   ROUND(AVG(latitude), 6) AS center_lat,
                   ROUND(AVG(longitude), 6) AS center_lng,
                   COUNT(DISTINCT source) AS source_count
            FROM samp_geo WHERE {col} IS NOT NULL GROUP BY {col}
        )
        SELECT agg.cell::UBIGINT          AS h3_cell,
               agg.sample_count::INTEGER  AS sample_count,
               agg.center_lat, agg.center_lng,
               dom.dominant_source,
               agg.source_count::INTEGER  AS source_count,
               {res}::INTEGER             AS resolution
        FROM agg JOIN dom ON dom.cell = agg.cell AND dom.rn = 1
        ORDER BY h3_cell
    ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)""")


def build_facet_summaries(con, out):
    union = " UNION ALL ".join(
        f"SELECT '{d}' AS facet_type, {d} AS facet_value FROM samp_geo WHERE NULLIF(TRIM({d}), '') IS NOT NULL"
        for d in FACET_DIMS)
    con.execute(f"""COPY (
        SELECT facet_type, facet_value, NULL::INTEGER AS scheme, COUNT(*) AS count
        FROM ({union})
        GROUP BY facet_type, facet_value
        ORDER BY facet_type, facet_value
    ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)""")


def build_facet_cross_filter(con, out):
    # baseline (all filter_* NULL) + single-dimension filters. NOTE: the shape
    # (incl. baseline rows + self-dimension rows) matches what the deployed
    # explorer reads; see SERIALIZATIONS.md for the exact contract. Determinism
    # via ORDER BY.
    selects = []
    for fd in FACET_DIMS:
        selects.append(
            f"SELECT NULL::VARCHAR AS filter_source, NULL::VARCHAR AS filter_material, "
            f"NULL::VARCHAR AS filter_context, NULL::VARCHAR AS filter_object_type, "
            f"'{fd}' AS facet_type, {fd} AS facet_value, COUNT(*) AS count "
            f"FROM samp_geo WHERE NULLIF(TRIM({fd}), '') IS NOT NULL GROUP BY {fd}")
    for filt in FACET_DIMS:
        for fd in FACET_DIMS:
            cols = ", ".join(
                (f"{filt} AS filter_{c}" if c == filt else f"NULL::VARCHAR AS filter_{c}")
                for c in FACET_DIMS)
            selects.append(
                f"SELECT {cols}, '{fd}' AS facet_type, {fd} AS facet_value, COUNT(*) AS count "
                f"FROM samp_geo WHERE NULLIF(TRIM({filt}), '') IS NOT NULL AND NULLIF(TRIM({fd}), '') IS NOT NULL GROUP BY {filt}, {fd}")
    con.execute(f"""COPY (
        SELECT filter_source, filter_material, filter_context, filter_object_type,
               facet_type, facet_value, count
        FROM ({' UNION ALL '.join(selects)})
        ORDER BY filter_source, filter_material, filter_context, filter_object_type, facet_type, facet_value
    ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)""")


def build_wide_h3(con, wide, out):
    geom = geometry_expr(con, wide).replace("s.geometry", "geometry")
    con.execute(f"""COPY (
        SELECT *,
          CASE WHEN geometry IS NOT NULL THEN h3_latlng_to_cell(ST_Y({geom}), ST_X({geom}), 4) END AS h3_res4,
          CASE WHEN geometry IS NOT NULL THEN h3_latlng_to_cell(ST_Y({geom}), ST_X({geom}), 6) END AS h3_res6,
          CASE WHEN geometry IS NOT NULL THEN h3_latlng_to_cell(ST_Y({geom}), ST_X({geom}), 8) END AS h3_res8
        FROM read_parquet('{wide}') ORDER BY pid
    ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)""")


def build_concept_membership(con, wide, vocab_labels, t0):
    """Build the hierarchy temp tables (#281/#282/#276) from vocab_labels' data-form
    `broader` edges + the wide concept arrays, over the LOCATED universe (samp_geo)
    so counts match the map/table. Creates: concept_tree, concept_closure, roots,
    asserted, membership. See FACET_HIERARCHY_PLAN.md §2."""
    # concept_tree: data-form (uri, canonical primary parent, depth-from-root).
    # vocab_labels already aliases broader into data form, so this joins to the
    # data-form concept URIs the wide arrays resolve to.
    con.execute(f"""
    CREATE OR REPLACE TEMP TABLE vl_edges AS
      SELECT DISTINCT uri, broader AS parent_uri
      FROM read_parquet('{vocab_labels}') WHERE uri_form='data_v1';
    CREATE OR REPLACE TEMP TABLE concept_tree AS
      WITH RECURSIVE depths AS (
        SELECT uri, parent_uri, 0 AS depth FROM vl_edges WHERE parent_uri IS NULL
        UNION ALL
        SELECT e.uri, e.parent_uri, d.depth + 1
        FROM vl_edges e JOIN depths d ON e.parent_uri = d.uri
      )
      SELECT uri, ANY_VALUE(parent_uri) AS parent_uri, MIN(depth) AS depth
      FROM depths GROUP BY uri;
    -- transitive ancestor closure (self at distance 0)
    CREATE OR REPLACE TEMP TABLE concept_closure AS
      WITH RECURSIVE clo AS (
        SELECT uri AS descendant, uri AS ancestor, 0 AS distance FROM concept_tree
        UNION ALL
        SELECT c.descendant, t.parent_uri AS ancestor, c.distance + 1
        FROM clo c JOIN concept_tree t ON t.uri = c.ancestor
        -- Cycle guard (Codex r2): the SKOS projection is acyclic today, but cap
        -- depth so a future bad vocab (a broader cycle) can't recurse forever.
        -- 64 >> any real concept depth (live max is 3).
        WHERE t.parent_uri IS NOT NULL AND c.distance < 64
      )
      SELECT DISTINCT descendant, ancestor, distance FROM clo;
    """)
    # node_dim: assign each tree concept to the dim whose canonical root it reaches
    # via the closure. This both (a) restricts the hierarchy to each dim's real
    # tree and (b) keeps exactly one root per dim — deprecated/parentless concepts
    # that don't reach a dim root are NOT treated as roots (Codex HIGH-1).
    dim_root_vals = ", ".join(f"('{dim}', '{root}')" for dim, root in DIM_ROOT.items())
    con.execute(f"""
    CREATE OR REPLACE TEMP TABLE dim_root(facet_type VARCHAR, root_uri VARCHAR);
    INSERT INTO dim_root VALUES {dim_root_vals};
    CREATE OR REPLACE TEMP TABLE node_dim AS
      SELECT DISTINCT c.descendant AS uri, r.facet_type
      FROM concept_closure c JOIN dim_root r ON r.root_uri = c.ancestor;
    """)
    # asserted: every located sample's concept(s) per hierarchical dim, from the
    # FULL wide array (not the flattened first-non-root value), dropping ONLY that
    # dim's explicit root.
    union = " UNION ALL ".join(
        f"""SELECT DISTINCT sg.pid, '{dim}' AS facet_type, ic.uri AS concept
            FROM samp_geo sg
            JOIN read_parquet('{wide}') s ON s.pid = sg.pid,
                 UNNEST(s.{col}) AS u(rid)
            JOIN ic ON ic.row_id = u.rid
            WHERE ic.uri <> '{DIM_ROOT[dim]}'"""
        for dim, col in DIM_ARRAY_COL.items())
    con.execute(f"CREATE OR REPLACE TEMP TABLE asserted AS {union};")
    # membership: each asserted concept expanded to its ancestor closure, RESTRICTED
    # to ancestors in the SAME dim's canonical tree. Membership semantics (#276): a
    # sample counts under every node on the path(s) of every concept it asserts.
    # Asserted concepts that don't reach their dim root (label gaps #148/#161, or
    # the un-linked specimentype scheme) produce no rows → EXCLUDED from the
    # hierarchy (flat facet_summaries still counts them) and reported below.
    con.execute("""
    CREATE OR REPLACE TEMP TABLE membership AS
      SELECT DISTINCT a.pid, a.facet_type, c.ancestor AS concept_uri
      FROM asserted a
      JOIN concept_closure c ON c.descendant = a.concept
      JOIN node_dim nd ON nd.uri = c.ancestor AND nd.facet_type = a.facet_type;
    """)
    n_tree = con.sql("SELECT COUNT(*) FROM concept_tree").fetchone()[0]
    n_mem = con.sql("SELECT COUNT(*) FROM membership").fetchone()[0]
    # Excluded = distinct (dim, concept) asserted that never reach the dim root.
    excl = con.sql("""
        SELECT a.facet_type, COUNT(DISTINCT a.concept) AS n
        FROM asserted a
        WHERE NOT EXISTS (
          SELECT 1 FROM concept_closure c JOIN node_dim nd
            ON nd.uri = c.ancestor AND nd.facet_type = a.facet_type
          WHERE c.descendant = a.concept)
        GROUP BY a.facet_type ORDER BY a.facet_type""").fetchall()
    log(f"concept_tree={n_tree:,}  membership={n_mem:,}", t0)
    if excl:
        detail = ", ".join(f"{ft}={n}" for ft, n in excl)
        log(f"NOTE: concepts EXCLUDED from hierarchy (no path to dim root; label "
            f"gaps #148/#161 / un-linked schemes — flat facet_summaries still counts them): {detail}", t0)


def build_sample_facet_membership(con, out):
    con.execute(f"""COPY (
        SELECT m.pid, m.facet_type, m.concept_uri, t.depth
        FROM membership m JOIN concept_tree t ON t.uri = m.concept_uri
        ORDER BY m.facet_type, m.pid, m.concept_uri
    ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)""")


def build_facet_tree_summaries(con, out):
    # Hierarchical counts: COUNT(DISTINCT pid) per node (membership = direct ∪
    # descendants). NOT additive — a sample under two sibling branches counts
    # once at each and once at their shared ancestor (FACET_HIERARCHY_PLAN.md §2.2).
    con.execute(f"""COPY (
        SELECT m.facet_type, m.concept_uri, t.parent_uri, t.depth,
               COUNT(DISTINCT m.pid) AS count
        FROM membership m JOIN concept_tree t ON t.uri = m.concept_uri
        GROUP BY m.facet_type, m.concept_uri, t.parent_uri, t.depth
        ORDER BY m.facet_type, count DESC, m.concept_uri
    ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)""")


def build_facet_tree_cross_filter(con, out):
    # #290/#293: single-active-filter cross-filter COUNT cube spanning the 3 SKOS
    # trees (material/context/object_type — keyed by concept_uri, subtree semantics
    # via `membership`) AND the flat `source` dim. For every single active filter
    # (one node/value in ONE dim) it precomputes COUNT(DISTINCT pid) for every
    # OTHER dim's node/value, plus a baseline (no filter). This is the precomputed
    # answer to the live tree-count membership self-scan that hits the DuckDB-WASM
    # data-scale wall at global view (38.9M-row membership). Tiny output (~1k rows).
    #
    # Schema MIRRORS facet_cross_filter so the explorer reads it identically:
    #   filter_source/material/context/object_type, facet_type, facet_value, count
    # The filter dim is encoded in its filter_<dim> column (concept_uri for trees,
    # source string for source); the target dim in facet_type/facet_value. A row is
    # the cross-filtered count of target value GIVEN the single filter. Counts are
    # GLOBAL (no viewport) — the explorer uses this only at/near global view, exactly
    # like the flat cube. Determinism via COUNT(DISTINCT) + full-key ORDER BY.
    #
    # NOTE: this DELIBERATELY excludes same-dim pairs (t.dim <> f.dim) — the explorer
    # never cross-filters a dim by its own selection (it shows all of a dim's nodes).
    # It also excludes flat→flat pairs the existing facet_cross_filter already covers;
    # here every row has a tree dim on at least one side (source has only one flat dim).
    con.execute(f"""COPY (
      WITH xf AS (
        SELECT pid, facet_type AS dim, concept_uri AS value FROM membership
        UNION ALL
        SELECT pid, 'source' AS dim, source AS value
        FROM samp_geo WHERE NULLIF(TRIM(source), '') IS NOT NULL
      ),
      single AS (
        SELECT f.dim AS fdim, f.value AS fval,
               t.dim AS facet_type, t.value AS facet_value,
               COUNT(DISTINCT t.pid) AS count
        FROM xf f JOIN xf t ON t.pid = f.pid AND t.dim <> f.dim
        GROUP BY 1, 2, 3, 4
      ),
      base AS (
        SELECT NULL::VARCHAR AS fdim, NULL::VARCHAR AS fval,
               dim AS facet_type, value AS facet_value, COUNT(DISTINCT pid) AS count
        FROM xf GROUP BY dim, value
      ),
      allrows AS (SELECT * FROM single UNION ALL SELECT * FROM base)
      SELECT
        CASE WHEN fdim = 'source'      THEN fval END AS filter_source,
        CASE WHEN fdim = 'material'    THEN fval END AS filter_material,
        CASE WHEN fdim = 'context'     THEN fval END AS filter_context,
        CASE WHEN fdim = 'object_type' THEN fval END AS filter_object_type,
        facet_type, facet_value, count
      FROM allrows
      ORDER BY filter_source, filter_material, filter_context, filter_object_type,
               facet_type, facet_value
    ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)""")


# --- generation fingerprints (#293, #305/#306) -----------------------------
# The per-row token expressions are module constants so the VALIDATOR can
# recompute the exact same fingerprint independently from the written sibling
# files (membership, sample_facets_v2) and assert the index's build_id — i.e.
# the builder is not the sole authority on the index's generation identity.
# chr(31) (US) separates fields. A NULL source is encoded with a distinct
# sentinel byte so NULL and '' can never collide (Codex #5).
MEMBERSHIP_TOKEN_EXPR = "pid || chr(31) || facet_type || chr(31) || concept_uri"
COVERAGE_TOKEN_EXPR = ("pid || chr(31) || CASE WHEN source IS NULL THEN chr(0) ELSE chr(1) END "
                       "|| chr(31) || COALESCE(source, '')")


def _fingerprint(con, relation, token_expr):
    # Order-independent generation fingerprint over `relation`. Combines THREE
    # order-independent accumulators — XOR, SUM (HUGEINT, no overflow), and COUNT —
    # of per-row hashes. XOR alone cancels identical rows and is vulnerable to a
    # 2-row swap; SUM+COUNT defeat that. NOT a cryptographic digest: this defends
    # against accidental drift / stale generations, not an adversary who engineers a
    # multi-row hash collision. Grain is unique (validated), so the trio is stable.
    x, s, n = con.sql(
        f"SELECT COALESCE(bit_xor(hash({token_expr})), 0), "
        f"       COALESCE(SUM(hash({token_expr})::HUGEINT), 0), COUNT(*) "
        f"FROM {relation}").fetchone()
    return f"{x}_{s}_{n}"


def membership_build_id(con):
    # #293 (Codex P1, r2): a fingerprint of the FULL membership generation — not
    # just the node set. Both node_bits (positional bit assignment) and masks are
    # pure functions of `membership`, so hashing membership content captures every
    # change that would alter either artifact (new/dropped pids, re-mapped concepts,
    # AND node-set changes). Embedding this id in both lets the explorer refuse the
    # mask path unless the two are from the SAME generation (guards a stale-cached
    # masks file).
    #
    # FORMAT IS A DEPLOYED CONTRACT (#305): the live facet_node_bits / sample_facet_masks
    # (202608) carry this id as a BARE bit_xor decimal, and the explorer's facetIndexReady
    # preflight matches the index's membership-half against the DEPLOYED node_bits.build_id.
    # So this MUST stay the plain order-independent XOR — do NOT switch it to the
    # _fingerprint trio (that would change the string and break generation-matching
    # against every already-published artifact). membership grain is unique per
    # (pid,facet_type,concept_uri) — validated — so no XOR cancellation. The richer
    # trio is reserved for coverage_build_id, which is a NEW id with no compat constraint.
    return con.sql(
        f"SELECT CAST(COALESCE(bit_xor(hash({MEMBERSHIP_TOKEN_EXPR})), 0) AS VARCHAR) FROM membership"
    ).fetchone()[0]


def coverage_build_id(con):
    # #305/#306: fingerprint of the COMPLETE per-pid universe the index covers —
    # the (pid, source) pairs over the LOCATED set (samp_geo), independent of tree
    # membership. membership_build_id() alone is blind to this: an index built from
    # the SAME membership but a changed source value or a changed located-pid set
    # (exactly the #306 class of drift — located pids with no membership) would carry
    # an identical membership id and go stale SILENTLY. NULL vs '' source are encoded
    # distinctly (sentinel byte) so a NULL↔'' flip changes the fingerprint.
    return _fingerprint(con, "samp_geo", COVERAGE_TOKEN_EXPR)


def index_build_id(con):
    # #305/#306: the index's generation identity = "<membership_id>:<coverage_id>".
    # The two halves are deliberately separable so the explorer can BOTH:
    #   1. gate the mask-bit interpretation by matching the membership half against
    #      facet_node_bits.build_id (the bit assignment is a pure function of
    #      membership — the index masks are only meaningful under the SAME node_bits
    #      generation), and
    #   2. detect coverage/source drift via the coverage half (would otherwise be
    #      invisible to a membership-only id).
    # FORMATS DIFFER BY DESIGN: membership half is the BARE bit_xor decimal (the
    # deployed node_bits/masks contract — see membership_build_id), coverage half is
    # the richer "<xor>_<sum>_<count>" trio (a new id). ':' appears in neither half
    # (decimals + underscores only), so split(':', 1) is unambiguous.
    return f"{membership_build_id(con)}:{coverage_build_id(con)}"


def build_facet_node_bits(con, out, build_id):
    # #293: authoritative concept_uri -> bit_index assignment per tree dim. The
    # explorer loads this to turn a node selection into a bitmask and filter
    # sample_facet_masks with a cheap columnar bitwise predicate (replacing the
    # 39M-row membership GROUP BY that hits the DuckDB-WASM data-scale wall on
    # broad multi-tree selections). bit_index is 0-based, DETERMINISTIC (dense
    # rank over distinct concept_uri per facet_type, ordered by URI). The mask
    # builder below uses the SAME assignment so they can never drift. We HARD-fail
    # if any dim exceeds MASK_MAX_BITS (a signed-BIGINT mask can't hold it).
    over = con.sql("""
        SELECT facet_type, MAX(bit_index)+1 AS n FROM (
          SELECT facet_type, concept_uri,
                 (ROW_NUMBER() OVER (PARTITION BY facet_type ORDER BY concept_uri) - 1) AS bit_index
          FROM (SELECT DISTINCT facet_type, concept_uri FROM membership)
        ) GROUP BY facet_type HAVING MAX(bit_index)+1 > ?""", params=[MASK_MAX_BITS]).fetchall()
    if over:
        raise SystemExit(f"FATAL: tree dim(s) exceed {MASK_MAX_BITS} nodes — bitmask overflow: {over}")
    con.execute(f"""COPY (
        SELECT facet_type, concept_uri,
               (ROW_NUMBER() OVER (PARTITION BY facet_type ORDER BY concept_uri) - 1)::INTEGER AS bit_index,
               '{build_id}' AS build_id
        FROM (SELECT DISTINCT facet_type, concept_uri FROM membership)
        ORDER BY facet_type, concept_uri
    ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)""")


def build_sample_facet_masks(con, out, build_id):
    # #293: one row per located pid that has ANY tree membership; a BIGINT mask
    # per tree dim where bit (1<<bit_index) is set iff the pid is a member of that
    # node (membership already encodes the ancestor closure, so a parent node's
    # bit is set for the whole subtree). The explorer filters with
    #   (material_mask & <selected>) <> 0 AND (context_mask & <selected>) <> 0 ...
    # which is set-identical to the membership pid-subquery but a single columnar
    # scan (no 39M-row scan, no GROUP BY pid). bit assignment == build_facet_node_bits.
    con.execute(f"""COPY (
        WITH nb AS (
          SELECT facet_type, concept_uri,
                 (1::BIGINT << (ROW_NUMBER() OVER (PARTITION BY facet_type ORDER BY concept_uri) - 1)) AS bitval
          FROM (SELECT DISTINCT facet_type, concept_uri FROM membership)
        )
        SELECT m.pid,
          COALESCE(bit_or(CASE WHEN m.facet_type='material'    THEN nb.bitval END), 0)::BIGINT AS material_mask,
          COALESCE(bit_or(CASE WHEN m.facet_type='context'     THEN nb.bitval END), 0)::BIGINT AS context_mask,
          COALESCE(bit_or(CASE WHEN m.facet_type='object_type' THEN nb.bitval END), 0)::BIGINT AS object_type_mask,
          '{build_id}' AS build_id
        FROM membership m JOIN nb ON nb.facet_type=m.facet_type AND nb.concept_uri=m.concept_uri
        GROUP BY m.pid
        ORDER BY m.pid
    ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)""")


def build_sample_facet_index(con, out, build_id):
    # #305/#306: the COMPLETE per-pid facet index — one row for EVERY located
    # sample (samp_geo), not only those with tree membership. This is the artifact
    # the multi-filter global-view count path (#304) scans: it must be able to count
    # over the whole located universe, including samples that carry NO tree concept.
    #
    # WHY this exists separately from sample_facet_masks: masks is built FROM
    # `membership`, so it silently OMITS located samples with no membership row
    # (~29,917 in the 202608 generation — #306). Counting/ filtering off masks alone
    # undercounts the located universe. Here we start from samp_geo (the authoritative
    # located set), LEFT JOIN the same membership-derived masks, and emit a ZERO mask
    # for no-membership pids (a zero mask matches no node bit → contributes 0 to every
    # tree facet, which is correct: the sample is in no subtree — but it IS still a
    # located sample and still counts toward `source` and the located total).
    #
    # `source` is a plain VARCHAR (source is exclusive, not multi-valued — a mask
    # would be wrong, a facets_v3 semi-join would add a second 6M-row read). The
    # mask columns are bit-identical to sample_facet_masks for pids that have
    # membership (validated). bit assignment == build_facet_node_bits / masks.
    con.execute(f"""COPY (
        WITH nb AS (
          SELECT facet_type, concept_uri,
                 (1::BIGINT << (ROW_NUMBER() OVER (PARTITION BY facet_type ORDER BY concept_uri) - 1)) AS bitval
          FROM (SELECT DISTINCT facet_type, concept_uri FROM membership)
        ),
        masks AS (
          SELECT m.pid,
            COALESCE(bit_or(CASE WHEN m.facet_type='material'    THEN nb.bitval END), 0)::BIGINT AS material_mask,
            COALESCE(bit_or(CASE WHEN m.facet_type='context'     THEN nb.bitval END), 0)::BIGINT AS context_mask,
            COALESCE(bit_or(CASE WHEN m.facet_type='object_type' THEN nb.bitval END), 0)::BIGINT AS object_type_mask
          FROM membership m JOIN nb ON nb.facet_type=m.facet_type AND nb.concept_uri=m.concept_uri
          GROUP BY m.pid
        )
        SELECT sg.pid,
               sg.source::VARCHAR                       AS source,
               COALESCE(mk.material_mask, 0)::BIGINT     AS material_mask,
               COALESCE(mk.context_mask, 0)::BIGINT      AS context_mask,
               COALESCE(mk.object_type_mask, 0)::BIGINT  AS object_type_mask,
               '{build_id}' AS build_id,
               {INDEX_SCHEMA_VERSION}::INTEGER AS schema_version
        FROM samp_geo sg LEFT JOIN masks mk ON mk.pid = sg.pid
        ORDER BY sg.pid
    ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)""")


def file_meta(con, path):
    n = con.sql(f"SELECT COUNT(*) FROM read_parquet('{path}')").fetchone()[0]
    schema = [(r[0], r[1]) for r in con.sql(f"DESCRIBE SELECT * FROM read_parquet('{path}')").fetchall()]
    return {"rows": n, "schema": schema, "bytes": os.path.getsize(path), "sha256": sha256_file(path)}


def git_sha():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"],
                                       cwd=os.path.dirname(os.path.abspath(__file__)),
                                       stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wide", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--tag", required=True, help="output prefix, e.g. isamples_202606 (no stale default)")
    ap.add_argument("--only", default="", help=f"comma list of: {','.join(ARTIFACTS)}")
    ap.add_argument("--skip", default="", help="comma list of the same names to skip")
    ap.add_argument("--vocab-labels", default="",
                    help="vocab_labels parquet (with `broader`, data_v1 rows) — "
                         "required for sample_facet_membership / facet_tree_summaries (#281/#282)")
    ap.add_argument("--no-manifest", action="store_true", help="skip writing {tag}_manifest.json")
    ap.add_argument("--threads", type=int, default=0,
                    help="DuckDB thread count; set 1 for bit-stable floating centroids (slower)")
    args = ap.parse_args()

    only = set(filter(None, args.only.split(",")))
    skip = set(filter(None, args.skip.split(",")))
    bad = (only | skip) - set(ARTIFACTS)
    if bad:  # Codex #3: fail loudly on typos instead of silently building nothing
        sys.exit(f"FATAL: unknown --only/--skip name(s): {sorted(bad)}. Known: {ARTIFACTS}")
    want = lambda name: (not only or name in only) and name not in skip
    os.makedirs(args.outdir, exist_ok=True)

    t0 = time.time()
    con = duckdb.connect()
    if args.threads:
        con.execute(f"PRAGMA threads={args.threads}")
    con.execute("INSTALL h3 FROM community; LOAD h3; INSTALL spatial; LOAD spatial;")
    log("building base sample tables…", t0)
    build_base_tables(con, args.wide, t0)

    p = lambda name: os.path.join(args.outdir, f"{args.tag}_{name}.parquet")
    produced = []
    def emit(name, fn):
        if want(name):
            fn(p(name)); produced.append(p(name)); log(f"{name} ✓", t0)

    emit("sample_facets_v2", lambda o: build_sample_facets_v2(con, o))
    emit("facet_summaries", lambda o: build_facet_summaries(con, o))
    emit("facet_cross_filter", lambda o: build_facet_cross_filter(con, o))
    emit("samples_map_lite", lambda o: build_samples_map_lite(con, o))
    if want("h3_summaries"):
        for res in (4, 6, 8):
            build_h3_summary(con, p(f"h3_summary_res{res}"), res); produced.append(p(f"h3_summary_res{res}"))
        log("h3_summary_res{4,6,8} ✓", t0)
    emit("wide_h3", lambda o: build_wide_h3(con, args.wide, o))

    # Hierarchy artifacts (#281/#282) — need vocab_labels for the SKOS tree.
    HIER_ARTIFACTS = {"sample_facet_membership", "facet_tree_summaries",
                      "facet_tree_cross_filter", "facet_node_bits", "sample_facet_masks",
                      "sample_facet_index"}
    if any(want(a) for a in HIER_ARTIFACTS):
        if not args.vocab_labels:
            # Fail loud if the user EXPLICITLY asked for a hierarchy artifact
            # (Codex) — silently skipping an explicit --only target is wrong.
            explicit = only & HIER_ARTIFACTS
            if explicit:
                sys.exit(f"FATAL: --only {sorted(explicit)} requires --vocab-labels <vocab_labels.parquet>")
            log("SKIP hierarchy artifacts: pass --vocab-labels <vocab_labels.parquet>", t0)
        else:
            build_concept_membership(con, args.wide, args.vocab_labels, t0)
            # The mask fast-path bundle = {membership, node_bits, masks?, index}.
            # sample_facet_masks AND sample_facet_index store raw mask bits that are
            # uninterpretable without facet_node_bits, and that the validator can only
            # gate by re-deriving from sample_facet_membership. So whenever masks or
            # index is requested, FORCE-emit membership + node_bits too (even under
            # `--only sample_facet_index`) — otherwise the build ships an artifact its
            # own validator must reject (Codex #4 / r3). force_dep() builds a not-wanted
            # artifact exactly once and records it for the manifest.
            need_fastpath = want("facet_node_bits") or want("sample_facet_masks") or want("sample_facet_index")
            force_deps = want("sample_facet_masks") or want("sample_facet_index")
            def force_dep(name, fn):
                if want(name):
                    emit(name, fn)
                elif p(name) not in produced:
                    fn(p(name)); produced.append(p(name)); log(f"{name} ✓ (auto-paired with masks/index)", t0)

            if force_deps:
                force_dep("sample_facet_membership", lambda o: build_sample_facet_membership(con, o))
            else:
                emit("sample_facet_membership", lambda o: build_sample_facet_membership(con, o))
            emit("facet_tree_summaries", lambda o: build_facet_tree_summaries(con, o))
            # #290/#293 cross-filter cube — needs membership (above) + samp_geo (source).
            emit("facet_tree_cross_filter", lambda o: build_facet_tree_cross_filter(con, o))
            # #293 bitmask filter artifacts — needs membership (above). node_bits and
            # masks share a node-set build_id so the explorer only uses the mask path
            # when the two are from the same generation (Codex P1).
            if need_fastpath:
                _bid = membership_build_id(con)
                if force_deps:
                    force_dep("facet_node_bits", lambda o: build_facet_node_bits(con, o, _bid))
                else:
                    emit("facet_node_bits", lambda o: build_facet_node_bits(con, o, _bid))
                emit("sample_facet_masks", lambda o: build_sample_facet_masks(con, o, _bid))
                # #305/#306: complete per-pid index (every located pid + source,
                # zero-mask for no-membership pids). Its build_id embeds the SAME
                # membership id as node_bits (mask-bit interpretation gate) PLUS a
                # coverage id over samp_geo's (pid, source) universe (staleness gate).
                emit("sample_facet_index", lambda o: build_sample_facet_index(con, o, index_build_id(con)))

    if not args.no_manifest:
        log("hashing inputs/outputs for manifest…", t0)
        exts = {r[0]: r[1] for r in con.sql(
            "SELECT extension_name, extension_version FROM duckdb_extensions() WHERE installed").fetchall()}
        manifest = {
            "tag": args.tag,
            "argv": sys.argv,
            "git_sha": git_sha(),
            "duckdb_version": duckdb.__version__,
            "extensions": exts,
            "input": {"path": args.wide,
                      "bytes": (os.path.getsize(args.wide) if os.path.exists(args.wide) else None),
                      "sha256": (sha256_file(args.wide) if os.path.exists(args.wide) else "remote/unhashed")},
            "outputs": {os.path.basename(f): file_meta(con, f) for f in produced},
        }
        mpath = p("manifest").replace(".parquet", ".json")
        with open(mpath, "w") as fh:
            json.dump(manifest, fh, indent=2)
        log(f"manifest → {mpath}", t0)

    log("done", t0)


if __name__ == "__main__":
    main()
