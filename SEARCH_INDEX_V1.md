# Search Index v1 Contract

> **Amendment 2026-07-10** (first full-corpus build, #170): two changes to
> §1's v1 minimum, discovered empirically. (1) **`keywords` is pulled
> forward from the v2 list** into `concept.label`'s sources; (2) URI
> dereferencing falls back to **the concept's own `label` column in the
> wide** before the URI tail. Rationale: as originally written, v1 indexed
> ZERO results for the benchmark's own example query `pottery Cyprus` —
> "Pottery" is not a concept in the 537-entry curated vocabulary; it
> reaches samples only as an OpenContext *keyword* concept whose label
> lives on the IdentifiedConcept row. The interim ILIKE search already
> covers keyword-concept labels (via `build_frontend_derived.py`'s
> appended `concept_labels`), so v1-as-written was a recall REGRESSION
> and an automatic #172 NO-GO. Resolution order is now:
> `vocab_labels.pref_label` → `IdentifiedConcept.label` → URI tail
> (with the missing-label counter tracking the last case only).

Doc-only contract for the iSamples Explorer's full-text search substrate.
Closes [#169](https://github.com/isamplesorg/isamplesorg.github.io/issues/169);
inputs are consumed by the offline builder ([#170](https://github.com/isamplesorg/isamplesorg.github.io/issues/170)),
the browser query prototype ([#171](https://github.com/isamplesorg/isamplesorg.github.io/issues/171)),
and the GO/NO-GO gate ([#172](https://github.com/isamplesorg/isamplesorg.github.io/issues/172)).

Companion to [`EXPLORER_STATE.md`](./EXPLORER_STATE.md): that doc pins the
*UI surface* contract (option C — side-panel + result-pin overlay); this
doc pins the *search backend* contract. The two are intentionally
orthogonal.

> **v1 ≠ destination.** v1 is a learning lap, not the finish line.
> The substrate format admits content-only expansion to v1.5 (sampling
> event/site fields) and v2 (Solr `searchText` parity) without schema
> migration. Section 1 names every expansion vector; budgets in §7
> apply to v1 content; v2 expansion gets a measurement-driven re-budget,
> not a renegotiation of v1 numbers.

---

## 1. Sample search document projection

The substrate is **not** "tokenize these parquet columns." It is "tokenize
a *sample-centric document* whose text fragments are joined across the
property graph and tagged by their entity origin." Each sample (`pid`)
has a logical document of weighted text fragments. Build-time joins
materialize the projection; tokens are tagged with the **virtual field
name** (entity dot field), not the source parquet column.

### v1 minimum (the projection that ships first)

| virtual field         | source                                                              | rationale                                                  |
|-----------------------|---------------------------------------------------------------------|------------------------------------------------------------|
| `sample.label`        | `MaterialSampleRecord.label` (~6.68M coverage)                      | canonical title; near-universal                            |
| `sample.description`  | `MaterialSampleRecord.description` (~1.61M ≈ 24%)                   | sparse but high-signal where present                       |
| `sample.place_name`   | `samples_map_lite.parquet.place_name[]` (~2.21M)                    | already proven valuable in current ILIKE search            |
| `concept.label`       | `material` / `context` / `object_type` / **`keywords`** concept refs, resolved `vocab_labels.pref_label` → `IdentifiedConcept.label` → URI tail (2026-07-10 amendment — see header note) | **load-bearing**: facet URIs are near-universal but raw URIs are useless to FTS; dereferenced labels make `ceramic`, `basalt`, `bone`, `marine` work — and the keyword-concept labels are the ONLY path by which `pottery` reaches samples |

A sample whose `material` URI is `<…>/Pottery` gets a row
`{token: 'pottery', pid: …, field: 'concept.label', tf: 1, …}`. One row
per sample per facet URI per token after tokenization.

### v1.5 expansion (additive — no schema change)

| virtual field                       | source (Solr equivalent)                                  |
|-------------------------------------|-----------------------------------------------------------|
| `event.label`                       | `producedBy_label` (~1.92M)                               |
| `event.description`                 | `producedBy_description` (~5.54M ≈ 83%)                   |
| `event.has_feature_of_interest`     | `producedBy_hasFeatureOfInterest` (~6.35M ≈ 95%)          |
| `event.sampling_purpose`            | `producedBy_samplingPurpose` (~262K)                      |
| `site.label`                        | `producedBy_samplingSite_label` (~190K)                   |
| `site.description`                  | `producedBy_samplingSite_description` (~172K)             |
| `site.place_name`                   | `producedBy_samplingSite_placeName[]` (~336K)             |

### v2 / Solr `searchText` parity (named, not built)

| virtual field            | source                                                |
|--------------------------|-------------------------------------------------------|
| `agent.name`             | registrant + responsibility agents                    |
| `curation.label`         | `curation_label`                                      |
| `curation.description`   | `curation_description`                                |
| `curation.location`      | `curation_location`                                   |
| ~~`keywords`~~           | **moved into v1** (2026-07-10 amendment — header note) |
| `source`                 | `source` enum (low value as FTS — facet UI suffices)  |

---

## 2. Tokenizer (build-time)

- Lowercase ASCII via `String.prototype.toLowerCase()` / Python `str.lower()`.
- Unicode NFKC normalization.
- Diacritic stripping via NFD + combining-mark removal.
- Whitespace split, punctuation stripped, length filter (`1 ≤ len ≤ 64`).
- **No stemming.** Honest limitation; document in UI copy.
- **Index every token, including stopwords.** Stopword handling is
  query-time, not build-time (§3) — keeps substrate flexible for future
  phrase queries.
- **Parallel implementations**: JS for browser query, Python for offline
  build. Shared regression test set (≥ 30 strings, including diacritics,
  mixed case, hyphenation, IGSN ids, archaeological place names).
  CI fails on Python ↔ JS divergence.

---

## 3. Query-time policy (distinct from build-time)

A separate axis from §2 — same tokenizer, but with additional query-only
filtering applied to the user input *before* combining tokens.

- **Tokenize the user input** with the same tokenizer used at build
  (lowercase + NFKC + diacritic strip + whitespace split + length
  filter). Round-trip invariant must hold.
- **Drop English stopwords** from the bag-of-words AND. Curated list:
  `a`, `an`, `the`, `of`, `from`, `for`, `to`, `in`, `on`, `at`, `is`,
  `was`, `with`, `and`, `or`. Small, conservative, no language detection.
  Rationale: a query like `pottery from Cyprus` should not require `from`
  to match. Build-time skipping would lose phrase-query potential;
  query-time skipping is reversible policy.
- **AND-combine the surviving tokens.** Empty surviving set ⇒ controlled
  empty state with helpful copy ("All terms in your query are common
  words. Add a more specific term to search.") — never a full-corpus
  dump or an error.
- **Non-fetchable hot (common-term) tokens** (§6): after stopword
  removal, manifest tokens with `fetchable: false` are ALSO dropped
  from the AND when at least one other token survives — the UI must
  disclose exactly which terms were ignored. If ALL surviving tokens
  are non-fetchable-hot, rank via `hot_topk.parquet` (§6). Fetchable
  hot tokens participate in the AND normally (their sub-files fit the
  budget). #172's benchmark quantifies the semantic cost (dropped-term
  recall, multi-common top-K intersection empty-rate).
- **No query-language syntax in v1.** No quoted phrases, no
  field-prefix operators, no booleans, no negation, no wildcards, no
  fuzzy. Documented v2 path: phrase quoting first (cheap and
  high-value), then field-prefix and negation.

---

## 4. Substrate row schema

Two parquet outputs per data version.

**Token-row substrate** (the partitioned inverted index):

```
{
  token:      VARCHAR    -- normalized token
  pid:        VARCHAR    -- sample primary id
  field:      VARCHAR    -- virtual field: 'sample.label' | 'sample.description'
                         --   | 'sample.place_name' | 'concept.label'
                         --   | (future: 'event.*' | 'site.*' | 'agent.*' …)
  tf:         USMALLINT  -- term frequency in this (pid, field) pair
  doc_len:    USMALLINT  -- token count of (pid, field) for BM25 length norm
}
```

**Sidecar `df.parquet`** (global per-token document frequency):

```
{
  token:  VARCHAR
  df:     UINTEGER  -- documents (pid × field) containing this token
}
```

Field weights are **query-side code**, not substrate data. Adding a
v1.5 / v2 field is a build-pipeline scope change, not a schema migration.

---

## 5. Ranking

BM25, fixed `k1 = 1.2`, `b = 0.75`. DF and `doc_len` from the substrate.
Field weights live in query code:

| field                | weight |
|----------------------|--------|
| `sample.label`       | 3.0    |
| `concept.label`      | 2.5    |
| `sample.place_name`  | 2.0    |
| `sample.description` | 1.0    |

Final result rank per `pid` = sum across `(pid, field)` BM25 contributions
weighted by field weight. Top-K = 50 (matches the result-pin overlay cap
in `EXPLORER_STATE.md` §6).

---

## 6. Partition shape

*(Amended 2026-07-10 with the concrete mechanics from #170's full-corpus
builds — the original text predates the discovery manifest.)*

- Hash-partition by token: `fnv1a32(utf8(token)) % N` base shards
  (`shard_000.parquet` … zero-padded). FNV-1a-32 is normative — the
  browser reader (#171) must compute it in JS.
- Per-shard byte cap: **≤ 5 MB** parquet FILE bytes (stricter than
  uncompressed — file bytes are what a browser transfers).
- **Hot-token rule** (token-level, not shard-level): a token whose
  postings alone would exceed the cap is REMOVED from its base shard and
  written to `hot/<key>_p{0..M-1}.parquet`, where `<key>` is the token's
  fnv1a32 hex (suffixed `-1`, `-2`… on the rare 32-bit collision) and M
  is sized so each sub-file fits the cap (verified after writing;
  re-split at 2×M until compliant). Whether a hot token's postings are
  fetched at query time is decided by the two-tier rule below;
  NON-fetchable hot postings exist for offline analysis and the #172
  oracle only (Codex round-2 finding, 2026-07-10; tiering round-3/4).
- **Two-tier hot-token query rule** (the reconciliation, refined per
  round-3 review): hotness is a STORAGE property; selectivity is
  semantic, and the manifest records both. Each hot entry carries
  `total_bytes` and `fetchable` (= total_bytes ≤ cap).
  - **Fetchable hot** (e.g. 'island', ~82K postings, ~2.5 MB total):
    the reader fetches ALL its `hot/` sub-files and treats the token
    exactly like a normal AND term — still within the cold budget.
  - **Non-fetchable hot** (true common terms — 'sample', 'material',
    millions of postings): NEVER fetched. Mixed with ≥1 selective term
    → dropped from the AND (UI discloses exactly which terms were
    ignored). All-common queries rank via **`hot_topk.parquet`** — a
    build-time sidecar holding each hot token's static single-token
    BM25 top-500 **per-pid summed, field-weighted per §5** (single
    small file, cap-checked). Multi-common AND intersects top-K lists
    (documented approximation; #172 benchmarks the empty-rate).
- **Discovery manifest `hot_tokens.json`** ships beside the shards:
  `{cap_bytes, query_policy, topk_k, topk_bytes, tokens: {token: {key,
  sub_files, postings, total_bytes, fetchable}}}`. Reader algorithm:
  token in manifest → two-tier rule above; otherwise → fetch
  `shard_{fnv1a32(token) % N}.parquet`.
- **`shard_sizes.json`** (sidecar): file byte size of every base shard,
  so the reader can compute a query's expected transfer BEFORE fetching
  (per-query budgeting + the benchmark's bytes-transferred metric are
  computed from it, not guessed).
- Near-hot skew guard: after writing each base shard, its heaviest
  tokens are promoted to `hot/` until the file fits the cap.
- Number of top-level shards (`N`): **256** (64 proved too few — ~9 MB
  base shards on the 202608 corpus); recorded in `build_stats.json`.

---

## 7. Budgets

These are **contract**. The GO/NO-GO gate (#172) is mechanical against
this table.

| metric                                          | target           |
|-------------------------------------------------|------------------|
| cold first search (P50 over the §9 benchmark)   | ≤ 2 s            |
| warm repeat-same-query search                   | ≤ 500 ms         |
| warm new-query-after-warm-up search             | ≤ 500 ms         |
| filter-composed cold search                     | ≤ 3 s            |
| bytes transferred cold (P50 over the §9 benchmark) | ≤ 5 MB        |
| bytes transferred warm                          | ≤ 1 MB per query |

**What is guaranteed vs measured** (round-4 honesty pass): the BUILD
enforces a per-FILE invariant — every base shard, hot sub-file, and the
`hot_topk` sidecar is ≤ cap (5 MiB). A query's cold transfer is the SUM
of its tokens' files: bounded by `n_selective_tokens × cap` (+ one
sidecar read for common terms), NOT by a flat 5 MB for arbitrarily long
queries — a 4-term query can legitimately fetch ~9 MB worst-case. The
budget row above is therefore defined over the §9 canonical benchmark
(realistic 1–3 term queries) at P50, which is what the #172 gate
mechanically evaluates; per-query expected transfer is computable
up-front from `shard_sizes.json` + the manifest, and the benchmark
records actual bytes per query. Row-group pruning under HTTP range
requests (when #190's fallback doesn't fire) reduces real transfer
below file sizes; budgets do NOT assume it.

**"Warm" disambiguation** (resolves [#174](https://github.com/isamplesorg/isamplesorg.github.io/issues/174)):

- *Warm-repeat-same-query*: same query, second invocation, same page.
  Measures end-to-end cache + render path.
- *Warm-new-query-after-warm-up*: different query, after parquet
  metadata is already cached. Measures query execution after the
  substrate file is warm.

Both are reported by the benchmark; the budget targets above apply to both.

Numeric thresholds for quality gates (top-K overlap percentages) are
calibrated **after** [#167](https://github.com/isamplesorg/isamplesorg.github.io/issues/167) baseline lands and the prototype runs;
they do not appear in this doc as fixed numbers. The contract requires
the *shape* of the gate (top-3 vs hand-labeled, top-10 vs hand-labeled,
top-10 vs DuckDB FTS oracle, plus the hard-fail invariants in §9), not
the specific percentages.

---

## 8. Versioning

- URL pattern: `https://data.isamples.org/isamples_YYYYMM_search_index_v1/<shard>.parquet`
  with `hot/<key>_pN.parquet` sub-files and sidecars `df.parquet`,
  `hot_tokens.json` (§6), and `build_stats.json` (§10).
- Explorer pins to a specific `YYYYMM` so a dataset rebuild can't
  break a deployed site mid-flight.
- Index version is tied to data version. v1.x format bumps require
  URL-path bump (`_v1` → `_v2`).

---

## 9. Curated benchmark + quality gate

- File: `tests/search_benchmark.json`.
- 12-15 queries, hand-labeled top-10 by Raymond. Must include:
  - **bare-text queries** (`pottery`, `basalt`)
  - **multi-term** (`pottery Cyprus`)
  - **stopword-heavy** (`pottery from Cyprus`) — verifies §3 query-time
    stopword policy
  - **concept-only queries** (`ceramic`, `bone`, `mammal`) — verifies
    dereferenced concept labels work; **fails loudly** if v1 ships
    without concept labels
  - **diacritic** (`Çatalhöyük`)
  - **no-hit** (`xyzzyqqqplugh`)
  - **filter-composed cases** (source-only, source + material) with
    hand-labeled expected filtered top-K (per #172 hard-fail
    invariant)
- The gate is hard, not advisory:
  - top-3 overlap vs hand-labeled set ≥ TBD%
  - top-10 overlap vs hand-labeled set ≥ TBD%
  - top-10 overlap vs DuckDB FTS local oracle (#171 §5) ≥ TBD%
  - **zero concept-only benchmark queries return empty**
  - **zero stopword-heavy queries return empty**
  - **all hard-fail invariants in [#172](https://github.com/isamplesorg/isamplesorg.github.io/issues/172) pass**

---

## 10. Build-stats artifact (contract requirement)

The v1 substrate build pipeline ([#170](https://github.com/isamplesorg/isamplesorg.github.io/issues/170)) MUST emit
`build_stats.json` alongside the partitioned token-row parquets:

```json
{
  "data_version": "isamples_YYYYMM",
  "built_at_utc": "YYYY-MM-DDTHH:MM:SSZ",
  "total_samples": <int>,
  "fields": {
    "sample.label":       { "samples_with_field": <int>, "total_tokens": <int>, "avg_doc_len": <float> },
    "sample.description": { ... },
    "sample.place_name":  { ... },
    "concept.label":      { ... }
  },
  "concept_label_uri_resolution": {
    "material_resolved": <fraction>, "material_missing_pref": <fraction>,
    "context_resolved":  <fraction>, "context_missing_pref":  <fraction>,
    "object_type_resolved": <fraction>, "object_type_missing_pref": <fraction>
  },
  "shard_count": <int>,
  "shard_max_size_mb": <float>,
  "total_bytes_uncompressed": <int>,
  "build_seconds": <float>,
  "top_df_tokens": [ ["the", <int>], ["of", <int>], ... ]
}
```

This contract item exists so this doc and the builder cannot drift —
every release of the substrate carries empirical coverage data, not
narrative claims.

---

## 11. Out of scope (v1)

- Solr-parity field set (§1 v2 expansion path; not implemented).
- Stemming (English-specific, hurts non-English content; v2+ if at all).
- Query-language syntax: quoted phrases, field operators, booleans,
  negation, wildcards, fuzzy matching, ranges, boosts.
- Hosted-search backend (a permanent contingency triggered by either
  GO/NO-GO failure in #172 OR v2+ requirements that exceed what a
  static substrate can deliver — see [#171 §7](https://github.com/isamplesorg/isamplesorg.github.io/issues/171)).
