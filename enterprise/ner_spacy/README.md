# ner_spacy — no-training entity extractor for Chat with Data

A professional, zero-training alternative to `pipeline/s1_extract.py` that
uses the broader NLP toolbox: spaCy (POS / dep / lemma / PhraseMatcher),
rapidfuzz (open-set company matching), unicode normalization, deterministic
fiscal date parsing, and a comparison-group splitter.

Drops directly into demo3's pipeline — the rest of the stack
(`s2_resolve` → `s7_respond`) is untouched.

## Design

```
┌──────────────────────── extractor.pipeline.Extractor ────────────────────────┐
│                                                                              │
│   query ─► normalize ─► spaCy parse (tokenizer+tagger+parser+lemmatizer)     │
│                                        │                                     │
│                                        ├──► ClosedSetMatchers  (schema.yaml) │
│                                        │     • GEO    PhraseMatcher          │
│                                        │     • PRODUCT PhraseMatcher         │
│                                        │     • SEGMENT PhraseMatcher         │
│                                        │                                     │
│                                        ├──► fiscal.parse  (regex: Q1FY26…)   │
│                                        │                                     │
│                                        ├──► comparison.split  ("vs" / "and") │
│                                        │                                     │
│                                        └──► AccountFinder (per side)         │
│                                              • PROPN chunks via dep parse    │
│                                              • rapidfuzz vs dim_account      │
│                                              • position scoring              │
│                                                                              │
│   → ExtractionResult { intent, metric, operator, limit, [EntityGroup, …] }   │
└──────────────────────────────────────────────────────────────────────────────┘
```

**No training step. No model weights. No labelled corpus.** Everything is a
pre-trained spaCy model + rules + a schema-driven PhraseMatcher.

## Modules

| File                      | Responsibility                                                       |
|---------------------------|----------------------------------------------------------------------|
| `extractor/types.py`      | `ExtractionResult` + `EntityGroup` + `.to_s1_dict()` back-compat     |
| `extractor/normalize.py`  | NFKC normalization, smart-quote fix, "Quaters"→"quarters"            |
| `extractor/matchers.py`   | PhraseMatcher per label; loads aliases from `config/schema.yaml`     |
| `extractor/fiscal.py`     | Deterministic fiscal parser (Q1FY26, FY26, "last 4 quarters", YTD)  |
| `extractor/accounts.py`   | PROPN chunker + exact lookup + rapidfuzz against known companies     |
| `extractor/comparison.py` | Splits "A vs B" / "A and B" into entity groups                       |
| `extractor/intent.py`     | Cue-word intent / operator / limit / metric detection                |
| `extractor/pipeline.py`   | Orchestrator — single public class `Extractor`                       |
| `cli.py`                  | Interactive & batch tester                                           |
| `tests/test_extractor.py` | Deterministic regression tests                                       |

## Setup

```bash
cd demo3/ner_spacy
python3.11 -m venv .venv && source .venv/bin/activate
pip install -U pip
pip install 'spacy>=3.7,<4' 'pydantic<3' rapidfuzz pyyaml
python -m spacy download en_core_web_sm
```

## Try it

```bash
python cli.py                                                   # self-check
python cli.py "ARR for Toyota in EMEA Q1FY26"
python cli.py "Compare ARR for companies in EMEA in 2026 vs companies in AMER in 2027"
python cli.py --json "Siemnes ARR Q1FY26"                       # fuzzy
python cli.py --live "..."                                      # confirm against dim_account
python tests/test_extractor.py                                  # regression suite
```

Example output for a comparison query:

```
query:    Compare ARR for companies in EMEA in 2026 vs companies in AMER in 2027
intent:   COMPARE    metric: ARR    operator: —    limit: —    comparison: True
  [group 1]
    accounts  —
    products  —
    geo       EMEA
    segments  —
    fiscal    2026   (year: FY 2026, qtr: —)
  [group 2]
    accounts  —
    products  —
    geo       Americas
    segments  —
    fiscal    2027   (year: FY 2027, qtr: —)
```

## Use inside the demo3 pipeline

The adapter `pipeline/s1_extract_spacy.py` exposes the same `extract()` /
`find_slots()` signatures as the legacy regex extractor. Pick the engine
at startup with an env var:

```bash
# default — regex S1
python main.py "ARR for Toyota in EMEA Q1FY26"

# spaCy S1 (this extractor)
MAESTRO_S1=spacy python main.py "ARR for Toyota in EMEA Q1FY26"
```

Everything downstream (S2 resolve, S3 clarify, S4 context, S5 SQL
generate, S6 execute, S7 respond) is unchanged.

Comparison queries flatten into the legacy `fiscal_raw="A vs B"` convention
on the primary group; the full multi-group structure is reachable via
`s1_extract_spacy.extract_rich(query)` for consumers that want it.

## What each NLP technique buys you

| Technique            | Where used                           | Alternative we rejected                           |
|----------------------|--------------------------------------|---------------------------------------------------|
| Unicode normalize    | `normalize.py`                       | Nothing → fails on smart-quoted strings           |
| Lemmatization        | account-chunk termination at metrics | Hard-coded "arr"/"ARR" lists                      |
| POS tagging (PROPN)  | account candidate selection          | Capitalisation regex — misses lowercase companies |
| Dependency parse     | position scoring ("ARR for X")       | Trigram window — noisier                          |
| PhraseMatcher        | GEO/PRODUCT/SEGMENT                  | Per-label regex table — slower, harder to extend  |
| rapidfuzz WRatio     | typo-tolerant company matching       | Edit distance — slower, less accurate for names   |
| Deterministic fiscal | fiscal.parse                         | A date lib (dateparser) — overshoots the domain   |

## When to prefer this over the regex S1

- You want new entity aliases to land as a YAML change, not code.
- You care about typo tolerance in company names.
- You need comparison-group semantics ("EMEA 2026 vs AMER 2027") as first-class output.

## When to stick with the regex S1

- You have specialised position rules that the dep parser doesn't capture.
- You can't ship spaCy / en_core_web_sm into your runtime (~50 MB).
- Latency budget is sub-millisecond (this is ~10-30ms per query vs. ~1ms).

## Status

All 13 regression tests pass. Integration with demo3's pipeline is verified
at the `ExtractedQuery` shape boundary. Not benchmarked on the full dataset
yet — the first thing you should do is point `MAESTRO_S1=spacy` at your
production query set and diff against the regex S1's output.
