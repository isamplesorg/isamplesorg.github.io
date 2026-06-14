# Frontend-derived parquet pipeline — reproducible, AI-free.
#
#   make test       # fast fixture tests (no network, no big data) — the CI gate
#   make wide       # download + checksum the canonical wide parquet
#   make oc-wide    # download + checksum Eric's OC PQG wide (concept source of truth, #272)
#   make enrich     # overlay OC material/object-type concepts onto $(WIDE) -> $(ENRICHED)
#   make validate-enrich  # independent trust gate for the enrichment (non-zero exit on failure)
#   make derived    # build the derived files from $(DERIVED_WIDE) into $(OUTDIR)
#   make validate   # algebraic trust gate over the built files (non-zero exit on failure)
#   make all        # wide -> derived -> validate           (no enrichment)
#   make all-272    # wide+oc-wide -> enrich -> validate-enrich -> derived -> validate
#
# Override on the command line, e.g.:
#   make all-272 TAG=isamples_202606
#
# Requirements: python with `pip install -r scripts/requirements.txt`, plus
# network access on first run (DuckDB pulls the h3 community extension).

PY      ?= python
WIDE_URL ?= https://data.isamples.org/isamples_202604_wide.parquet
OC_WIDE_URL ?= https://storage.googleapis.com/opencontext-parquet/oc_isamples_pqg_wide.parquet
OUTDIR  ?= build/derived
WIDE    ?= $(OUTDIR)/wide.parquet
OC_WIDE ?= $(OUTDIR)/oc_wide.parquet
TAG     ?= isamples_dev
ENRICHED ?= $(OUTDIR)/$(TAG)_wide.parquet
# derived files build from the plain wide by default; all-272 overrides to the enriched one
DERIVED_WIDE ?= $(WIDE)
BUILD   := scripts/build_frontend_derived.py
VALIDATE := scripts/validate_frontend_derived.py
ENRICH  := scripts/enrich_wide_with_oc_concepts.py
VALIDATE_ENRICH := scripts/validate_oc_concept_enrichment.py

.PHONY: help test wide oc-wide enrich validate-enrich derived validate all all-272 ingest-272 all-202608 clean
help:
	@grep -E '^#   make' Makefile | sed 's/^#   /  /'

# Fast, deterministic fixture tests — the gate a human (or CI) runs without any AI.
test:
	$(PY) -m pytest tests/test_frontend_derived.py tests/test_oc_concept_enrichment.py -q

wide: $(WIDE)
$(WIDE):
	@mkdir -p $(OUTDIR)
	curl -fSL -o $(WIDE) "$(WIDE_URL)"
	@echo "sha256: $$(shasum -a 256 $(WIDE) | cut -d' ' -f1)  $(WIDE)"

oc-wide: $(OC_WIDE)
$(OC_WIDE):
	@mkdir -p $(OUTDIR)
	curl -fSL -o $(OC_WIDE) "$(OC_WIDE_URL)"
	@echo "sha256: $$(shasum -a 256 $(OC_WIDE) | cut -d' ' -f1)  $(OC_WIDE)"

# real file dependency so `make -j` orders enrich before validate-enrich
enrich: $(ENRICHED)
$(ENRICHED): $(WIDE) $(OC_WIDE)
	$(PY) $(ENRICH) --src $(WIDE) --oc-wide $(OC_WIDE) --out $(ENRICHED)

validate-enrich: $(ENRICHED)
	$(PY) $(VALIDATE_ENRICH) --src $(WIDE) --oc-wide $(OC_WIDE) --out $(ENRICHED)

derived: $(DERIVED_WIDE)
	$(PY) $(BUILD) --wide $(DERIVED_WIDE) --outdir $(OUTDIR) --tag $(TAG) --skip wide_h3

# Sentinel expectation tracks data vintage: the plain (non-enriched) chain
# validates a frozen-export wide -> legacy value; the all-272 chain overrides
# to the OC-corrected default baked into the validator.
LEGACY_SENTINEL := https://w3id.org/isample/vocabulary/material/1.0/anthropogenicmetal
SENTINEL_FLAG ?= --sentinel-material $(LEGACY_SENTINEL)

validate:
	$(PY) $(VALIDATE) --dir $(OUTDIR) --tag $(TAG) $(SENTINEL_FLAG)

# ordered sub-makes: safe under `make -j` (derived must finish before validate)
all: wide
	$(MAKE) derived
	$(MAKE) validate

# Full #272 chain: enrich the wide with OC concepts, gate it, then build+gate derived.
all-272: validate-enrich
	$(MAKE) derived DERIVED_WIDE=$(ENRICHED) TAG=$(TAG)
	$(MAKE) validate TAG=$(TAG) SENTINEL_FLAG=

# TRUE SYNC ingestion: add 67,187 new OC pids + remove 21,227 stale OC pids (#272 Phase 2, D3).
# Requires the 202606 wide (--src) and Eric's OC wide (--oc-wide).
# Outputs a 202608-tagged wide parquet + derived files in $(OUTDIR).
#
#   make ingest-272 \
#     SRC_202606=~/Data/iSample/pqg_refining/isamples_202606_wide.parquet \
#     OC_WIDE_2026=~/Data/iSample/pqg_refining/oc_isamples_pqg_wide_2026-06-09.parquet
#
INGEST_TAG ?= isamples_202608
SRC_202606 ?= $(OUTDIR)/isamples_202606_wide.parquet
OC_WIDE_2026 ?= $(OUTDIR)/oc_isamples_pqg_wide_2026-06-09.parquet
INGEST_OUT ?= $(OUTDIR)/$(INGEST_TAG)_wide.parquet
INGEST := scripts/ingest_oc_records.py

$(INGEST_OUT): $(SRC_202606) $(OC_WIDE_2026)
	@mkdir -p $(OUTDIR)
	$(PY) $(INGEST) --src $(SRC_202606) --oc-wide $(OC_WIDE_2026) --out $(INGEST_OUT)

ingest-272: $(INGEST_OUT)

# Full 202608 pipeline: ingest -> derived -> validate
all-202608: ingest-272
	$(MAKE) derived DERIVED_WIDE=$(INGEST_OUT) TAG=$(INGEST_TAG)
	$(MAKE) validate TAG=$(INGEST_TAG) SENTINEL_FLAG=

clean:
	rm -rf $(OUTDIR)
