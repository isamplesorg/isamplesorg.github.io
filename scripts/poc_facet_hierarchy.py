#!/usr/bin/env python3
"""Proof-of-concept for the facet hierarchy plan (#281/#282/#276) — Half (a).

De-risks the data/pipeline half BEFORE touching build_vocab_labels.py /
build_frontend_derived.py: derive the concept tree from SKOS `broader`, compute
per-sample membership over the ancestry, aggregate hierarchical counts, and check
the invariants. See FACET_HIERARCHY_PLAN.md §6/§7.

Material dimension only (the #282 priority); the same machinery generalizes to
context (sampledfeature) and object_type.

Gotchas this encodes (all surfaced empirically):
  1. URI form: SKOS TTLs use un-versioned URIs (.../material/rock) but the data
     uses versioned ones (.../material/1.0/rock). We normalize by stripping the
     /X.Y/ version segment so the ancestry join matches. (Production reuses
     build_vocab_labels.py's alias/version logic instead.)
  2. rdflib drops material's broader edges when many TTLs are parsed into ONE
     graph — parse each TTL into its own graph and merge the dicts.
  3. SKOS is a DAG: some concepts have multiple skos:broader parents.

Counting invariant (Codex-corrected): counts are a distinct-pid UNION, NOT
additive. parent_count = COUNT(DISTINCT pid over direct ∪ descendants); only
parent_count >= every child_count is guaranteed.

Usage:
  python scripts/poc_facet_hierarchy.py --wide /path/202608_wide.parquet \
      --ttls /path/to/ttl_dir
"""
import argparse
import glob
import re

import duckdb
import rdflib
from rdflib.namespace import SKOS

VERSION_SEG = re.compile(r"/\d+\.\d+(?=/)")  # the "/1.0" version path segment
MATERIAL_ROOT_NORM = "https://w3id.org/isample/vocabulary/material/material"


def norm(uri):
    """Strip the version segment so TTL (un-versioned) and data (versioned) URIs join."""
    return VERSION_SEG.sub("", uri) if uri else uri


def load_broader(ttl_dir):
    """Merge skos:broader across all TTLs. Parse each file into its OWN graph —
    a single shared graph silently drops material's edges."""
    broader, multi = {}, {}
    for f in sorted(glob.glob(f"{ttl_dir}/*.ttl")):
        g = rdflib.Graph().parse(f, format="turtle")
        for s, _, o in g.triples((None, SKOS.broader, None)):
            cs, co = norm(str(s)), norm(str(o))
            broader.setdefault(cs, co)
            multi.setdefault(cs, set()).add(co)
    dag = {k: v for k, v in multi.items() if len(v) > 1}
    return broader, dag


def ancestor_closure(broader):
    """Return [(descendant, ancestor, distance)] including self at distance 0."""
    def chain(u):
        out, seen, cur, d = [(u, 0)], {u}, u, 0
        while cur in broader and broader[cur] not in seen:
            cur = broader[cur]; d += 1; out.append((cur, d)); seen.add(cur)
        return out
    concepts = set(broader) | set(broader.values())
    return [(c, a, d) for c in concepts for (a, d) in chain(c)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wide", required=True, help="202608 wide parquet")
    ap.add_argument("--ttls", required=True, help="dir of SKOS .ttl vocab files")
    args = ap.parse_args()

    broader, dag = load_broader(args.ttls)
    print(f"broader edges: {len(broader)}   multi-parent (DAG) concepts: {len(dag)}")
    closure = ancestor_closure(broader)

    con = duckdb.connect()
    con.create_function("norm", norm, ["VARCHAR"], "VARCHAR")
    con.execute("CREATE TABLE closure(descendant VARCHAR, ancestor VARCHAR, distance INT)")
    con.executemany("INSERT INTO closure VALUES (?,?,?)", closure)
    con.execute("CREATE TABLE parent(child VARCHAR, parent VARCHAR)")
    con.executemany("INSERT INTO parent VALUES (?,?)", list(broader.items()))

    w = args.wide
    con.execute(f"""
    CREATE TEMP TABLE ic AS
      SELECT row_id, pid AS uri FROM read_parquet('{w}') WHERE otype='IdentifiedConcept';
    -- LOCATED universe = the explorer's universe (samp_geo): MaterialSampleRecord w/ geometry
    CREATE TEMP TABLE located AS
      SELECT pid FROM read_parquet('{w}') WHERE otype='MaterialSampleRecord' AND geometry IS NOT NULL;
    CREATE TEMP TABLE asserted AS
      SELECT DISTINCT s.pid, norm(ic.uri) AS concept
      FROM read_parquet('{w}') s JOIN located l ON l.pid = s.pid,
           UNNEST(s.p__has_material_category) AS u(rid) JOIN ic ON ic.row_id = u.rid
      WHERE s.otype='MaterialSampleRecord' AND norm(ic.uri) <> '{MATERIAL_ROOT_NORM}';
    CREATE TEMP TABLE membership AS
      SELECT DISTINCT a.pid, c.ancestor AS concept
      FROM asserted a JOIN closure c ON c.descendant = a.concept;
    CREATE TEMP TABLE tree_counts AS
      SELECT concept, COUNT(DISTINCT pid) AS cnt FROM membership GROUP BY concept;
    """)

    n_loc = con.sql("SELECT COUNT(*) FROM located").fetchone()[0]
    n_wm = con.sql("SELECT COUNT(DISTINCT pid) FROM asserted").fetchone()[0]
    n_mem = con.sql("SELECT COUNT(*) FROM membership").fetchone()[0]
    print(f"located={n_loc:,}  located-with-material={n_wm:,}  membership rows={n_mem:,}")

    bad = con.sql("""
        SELECT p.parent, p.child, pc.cnt, cc.cnt FROM parent p
        JOIN tree_counts pc ON pc.concept=p.parent
        JOIN tree_counts cc ON cc.concept=p.child WHERE cc.cnt > pc.cnt""").fetchall()
    print(f"INVARIANT A (parent>=child): {'PASS' if not bad else 'FAIL ' + str(bad[:3])}")

    root = con.sql(f"SELECT cnt FROM tree_counts WHERE concept='{MATERIAL_ROOT_NORM}'").fetchone()
    root = root[0] if root else 0
    print(f"INVARIANT B (root==located-with-material): root={root:,} expected={n_wm:,} "
          f"{'PASS' if root == n_wm else 'DIFF'}")

    tail = lambda u: u.rsplit("/", 1)[-1]
    print("\n=== material membership counts (located samples) ===")
    for c, cnt in con.sql(
        "SELECT concept, cnt FROM tree_counts WHERE concept LIKE '%/material/%' "
        "ORDER BY cnt DESC LIMIT 14").fetchall():
        p = broader.get(c)
        print(f"  {cnt:>10,}  {tail(c):26s} (parent: {tail(p) if p else 'ROOT'})")


if __name__ == "__main__":
    main()
