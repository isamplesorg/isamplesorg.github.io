# #313 — browser/bandwidth guidance (draft, post-#317 verification)

*Drafted 2026-07-03. This is the deliverable #313 actually asked for
("recommend what browser the explorer works best in", "recommended minimum
bandwidth") — written now because the prerequisite fix (#317) is confirmed
deployed as of today. Draft for Raymond's review before posting to #313 or
folding into `how-to-use.qmd`.*

## What changed since Andrea filed this

Andrea's original repro: two Material facets active at world zoom on Firefox
→ counts show `--` instead of numbers. Root cause (traced 2026-06-26,
`ISSUE_313_FINDINGS_2026-06-26.md`): the boot-time readiness check was
scanning ~20 MB of index data (`sample_facet_index` full-table distinct scan
+ a full coverage GROUP BY) before multi-filter counts would activate. On a
slow connection or a backgrounded tab, that took 20-80+ seconds; select a
2nd facet inside that window and you get the dash.

**PR #317 (merged 2026-07-01, R2 upload confirmed live today) fixes the two
biggest contributors:**
- The readiness check now reads a ~1 KB trusted manifest instead of
  scanning the 9.68 MB index file.
- The 9.67 MB mask-scan is decoupled from the readiness gate (runs after,
  not blocking it).

**Verified live on isamples.org just now** (Playwright): `window.__facetIndexStatus`
reads `"ready"`, and reproducing Andrea's exact scenario — two Material
facets active at world zoom — returns real counts (e.g. "Anthropogenic
environment (157,333)"), not dashes, for every Sampled Feature / Specimen
Type row checked. The dash bug, as originally reported, is fixed.

## What's still true (not fixed by #317, don't overclaim)

**DuckDB-WASM's range-request fallback (#190) is still open**, and it's not
Firefox-specific — I saw it fire in a Chromium session today too: every
parquet fetch, including the new ~1 KB manifest, logs `falling back to full
HTTP read for: ...`. Before #317 this meant full-HTTP-reading a combined
~20 MB of index+mask data on every load. After #317, the same fallback now
mostly applies to files that are KB-to-low-MB, so the fallback is far
cheaper even though it isn't fixed. Net effect: meaningfully better, but
"why does the network tab show full reads instead of range requests" is a
real, separate, still-open question (#190) — don't tell Andrea it's gone.

## Recommended guidance for Andrea (and how-to-use.qmd, pending Raymond's OK)

**Minimum bandwidth:** the boot-critical data (globe tiles + facet-ready
manifest) is now ~0.5-0.6 MB total (measured live today: 505 KB H3 tiles +
59 KB vocab labels + ~3 KB of small manifests). On a typical broadband or
LTE connection this is sub-second; even on a slow/throttled connection
(think old hotel wifi) it should resolve in single-digit seconds, not the
tens-of-seconds the pre-#317 dash bug required. The DuckDB engine itself
(a WASM module + worker script, roughly 1 MB combined per today's
measurement) is a one-time download your browser caches after the first
visit — it doesn't re-download on later visits or page navigations within
the site.

**Browser recommendation:** no browser is currently *broken* — the dash bug
reproduced on Firefox but the root cause (slow boot-time scan) was
connection-speed-dependent, not Firefox-specific, and #317's fix applies
equally to every browser. That said, Chrome/Chromium-based browsers remain
the most-tested path for this project (the CI smoke gate runs Chromium;
Firefox got one targeted spec in #317's P6, not full coverage). If you hit
something that looks Firefox-specific, it's still the least-covered browser
here — worth flagging which one you're on when filing.

**What to expect when clicking facets / spinning the globe:** brief loading
states are normal and intentional — the table dims and shows a spinner,
facet counts may briefly hold their previous value or show "Loading…"
rather than jump straight to a new number. A permanent dash that never
recovers, or a hard freeze, is not expected behavior post-#317 and is worth
a fresh bug report with browser + connection details.

## Suggested next step

Post a version of the "what changed" + "what's still true" sections above
as a comment on #313 (not closing it — #190 and the Firefox-coverage gap
are legitimate open follow-ups), and consider folding the "recommended
guidance" section into `how-to-use.qmd` as a short "Performance tips"
callout. Holding both for Raymond's sign-off before posting/publishing.
