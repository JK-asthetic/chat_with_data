┌─────────────────────────────────────────────────────────────────────────────┐
│  USER INPUT                                                                  │
│  "top accounts by ARR in EMEA FY 2026 Q1 for salesforce"                   │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STAGE 1 — LLM CLASSIFIER + FISCAL NORMALIZER                               │
│                                                                              │
│  A. Fiscal Pre-Normalizer (regex, no model)                                 │
│     "FY 2026 Q1" → "Q1FY26"   "fiscal 2026" → "FY26"                       │
│     Runs BEFORE everything else, zero latency                               │
│                                                                              │
│  B. LLM Intent + Entity Extractor (Ollama llama3.2:3b or phi4:mini)        │
│     Input: normalized query                                                  │
│     Output: Pydantic schema {                                               │
│       intent: RANK/LOOKUP/AGGREGATE/TREND/COMPARE/QBR                      │
│       metric_raw: "ARR"                                                     │
│       account_raw: "salesforce"       ← raw, unresolved                    │
│       fiscal_year: "FY26"                                                   │
│       fiscal_quarter: "Q1FY26"                                              │
│       geo: "EMEA"                                                           │
│       product_raw: null                                                     │
│       operator: "top"                                                       │
│       limit_n: 10                                                           │
│       missing_critical: ["fiscal_year_range?"]  ← LLM flags ambiguity      │
│     }                                                                        │
│     Fallback: keyword regex if LLM confidence < 0.6                        │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STAGE 2 — ENTITY SEARCH (Hardcoded Tools, Parallel)                       │
│                                                                              │
│  Runs CONCURRENTLY for all raw entities extracted in Stage 1               │
│                                                                              │
│  Tool 1: search_company(account_raw)                                        │
│    → pg_trgm ILIKE on dim_account_new.account_name                         │
│    → Returns top-3 fuzzy matches with similarity score                      │
│    "salesforce" → [                                                         │
│       {name: "Salesforce Inc",     score: 0.97},                           │
│       {name: "Salesforce Japan",   score: 0.81},                           │
│       {name: "Salesforce EMEA Ltd",score: 0.78}                            │
│    ]                                                                        │
│    ⚠ TRIGGER CLARIFICATION if top score < 0.95 OR multiple > 0.80          │
│                                                                              │
│  Tool 2: search_product(product_raw)                                        │
│    → Match against dim_product_hierarchy_new (L1→L2→L3→L4)                │
│    "ZIA" → found at L2. No ambiguity.                                      │
│    "platform" → matches L1=ZIA, L1=ZPA, L1=ZDX                            │
│    ⚠ TRIGGER CLARIFICATION if matches span multiple L-levels               │
│                                                                              │
│  Tool 3: validate_fiscal(fiscal_year, fiscal_quarter)                      │
│    → Check against Redis enum cache (all valid FY/quarter combos)          │
│    → "Q1FY26" exists? YES. OK.                                             │
│    → Missing? ⚠ TRIGGER CLARIFICATION                                      │
│                                                                              │
│  Tool 4: validate_geo(geo)                                                  │
│    → Hardcoded set: {AMER, EMEA, APAC, APJ}                                │
│    → "Europe" → closest match "EMEA" with note                             │
│                                                                              │
│  All 4 tools run in parallel (asyncio.gather)                               │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STAGE 3 — SMART CLARIFICATION BOT (One-Shot, Side-by-Side)                │
│                                                                              │
│  Rule Engine collects ALL ambiguities from Stage 2 at once                 │
│  Presents them as a SINGLE multi-question card — never asks twice          │
│                                                                              │
│  Clarification triggers (priority ordered):                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ C1. Multiple company matches (score < 0.95, >1 match above 0.75)   │   │
│  │ C2. Product level ambiguity (query says "ZIA" — which level?)       │   │
│  │ C3. Missing fiscal year (revenue/ARR/ACV query with no year)        │   │
│  │ C4. Fiscal range ambiguity (single Q vs full FY vs range)           │   │
│  │ C5. Metric ambiguity (ARR vs ACV, pipeline vs actual)               │   │
│  │ C6. Geo sub-ambiguity ("Asia" → APAC or APJ?)                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  EXAMPLE — Single clarification card shown to user:                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Before I run this, I need 2 quick things:                          │   │
│  │                                                                     │   │
│  │  [Q1] Which Salesforce entity?        [Q2] Fiscal scope?           │   │
│  │  ○ Salesforce Inc          (global)   ○ Q1FY26 only               │   │
│  │  ○ Salesforce Japan        (APAC)     ○ All of FY26 (Q1-Q4)       │   │
│  │  ○ Salesforce EMEA Ltd     (EMEA)     ○ Last 4 quarters           │   │
│  │  ○ All Salesforce entities            ○ Keep as Q1FY26            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  Max 3 questions per card. Max 1 card per query (never ask twice).         │
│  If user ignores/skips → use highest-confidence default + note in output   │
│                                                                              │
│  FALLBACK: If no ambiguities → skip this stage entirely, proceed to Stage 4│
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                        user responds
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STAGE 4 — SCHEMA LINKER + CONTEXT BUILDER                                 │
│                                                                              │
│  Takes resolved entities → maps to exact tables + columns                  │
│                                                                              │
│  Router Matrix (deterministic):                                             │
│  metric=ARR           → primary: data_arr                                  │
│  metric=ACV           → primary: data_acv                                  │
│  metric=churn         → primary: data_churn_reason                         │
│  metric=pipeline      → primary: data_pippeline_curr                       │
│  metric=renewal risk  → primary: data_renewal_risk                         │
│  account filter       → join: dim_account_new ON account_id                │
│                                                                              │
│  Column resolver:                                                           │
│  geo in data_arr      → cfy_geo  (NOT geo)                                 │
│  geo in data_acv      → geo                                                 │
│  geo in data_churn    → geo                                                 │
│                                                                              │
│  Context Builder output (minimal — never full schema):                     │
│  {                                                                          │
│    primary_table: "data_arr",                                               │
│    join: "LEFT JOIN dim_account_new ON data_arr.account_id = ...",         │
│    allowed_columns: [cfy_geo, fiscal_year, fiscal_quarter, arr,            │
│                      end_user_parent_name, product_l2, account_id],        │
│    where_values: {cfy_geo: "EMEA", fiscal_quarter: "Q1FY26"},             │
│    normalized_question: "top 10 accounts by ARR in EMEA for Q1FY26"       │
│  }                                                                          │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STAGE 5 — SQL GENERATION (SQLCoder + AI Fallback)                         │
│                                                                              │
│  Attempt 1: SQLCoder (Ollama, local, fine-tuned weekly)                    │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │  Model: pop_db_sqlcoder (your fine-tuned GGUF)               │          │
│  │  Input: minimal context from Stage 4                         │          │
│  │  temperature=0, stop=["###"]                                 │          │
│  │  timeout=15s                                                 │          │
│  └──────────────────────────────────────────────────────────────┘          │
│                    │                                                         │
│                    ▼                                                         │
│  STAGE 6 VALIDATION (run immediately after generation)                     │
│  ────────────────────────────────────────────────────                       │
│  V1. sqlglot AST parse — syntax valid?                                      │
│  V2. Table registry check — all tables exist in pop_db?                    │
│  V3. Column existence check — each column exists in its table?             │
│  V4. Dead table check — using dim_account not dim_account_new?             │
│  V5. Geo column check — data_arr uses cfy_geo not geo?                     │
│  V6. Fiscal format check — 'FY26' not '2026' in WHERE?                    │
│  V7. Row explosion guard — large table without LIMIT?                      │
│                    │                                                         │
│          ┌─────────┴──────────┐                                             │
│        PASS                 FAIL                                            │
│          │                    │                                             │
│          │          Retry 1: inject error back into SQLCoder               │
│          │          "Fix this error: column geo does not exist             │
│          │           in data_arr. Use cfy_geo instead."                    │
│          │                    │                                             │
│          │          ┌─────────┴──────────┐                                 │
│          │        PASS                 FAIL                                │
│          │          │                    │                                 │
│          │          │       Fallback: Claude Sonnet / GPT-4o              │
│          │          │       Same minimal context, same rules              │
│          │          │       Last attempt before error to user             │
│          │          │                    │                                 │
│          │          │          ┌─────────┴──────────┐                     │
│          │          │        PASS                 FAIL                    │
│          │          │          │                    │                     │
│          │          │          │         ⛔ Return structured error        │
│          │          │          │         Log to failed_queries table       │
│          └──────────┴──────────┘         → feeds weekly retraining        │
│                               │                                             │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │  Validated SQL
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STAGE 7 — POSTGRES EXECUTION                                               │
│                                                                              │
│  asyncpg read-only replica                                                  │
│  statement_timeout = 30s                                                    │
│  row_cap = 50,000 (hard stop)                                               │
│  pg_stat_statements audit log                                               │
│                                                                              │
│  Result states:                                                             │
│  → SUCCESS + rows     → proceed to Stage 8                                 │
│  → SUCCESS + 0 rows   → "No data found" + suggest filter relaxation        │
│  → TIMEOUT            → partial result + warning                           │
│  → DB ERROR           → log as failed attempt → weekly retrain feed        │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STAGE 8 — VALIDATION WITH INSIGHT (Post-Execution)                        │
│                                                                              │
│  This is where you catch "valid SQL, wrong answer"                         │
│                                                                              │
│  8A. STATISTICAL SANITY CHECKS (deterministic, no model)                   │
│  ─────────────────────────────────────────────────────                      │
│  S1. Zero rows + filters present                                            │
│      → "Query returned 0 rows. Possible cause: geo filter 'EMEA' may      │
│         not match exact values. Try removing geo filter to verify."        │
│                                                                             │
│  S2. Outlier detection                                                      │
│      → Any single row = >50% of SUM(metric)?                               │
│      → Flag: "Salesforce Inc represents 67% of total ARR shown"            │
│                                                                             │
│  S3. Expected range check                                                   │
│      → ARR values sanity: should be in $1k–$500M range per account         │
│      → If avg ARR < $100 → likely returned raw values not summed           │
│      → If single row ARR > $1B → likely missing GROUP BY                   │
│                                                                             │
│  S4. Row count reasonability                                                │
│      → Asked for "top 10" but got 847 rows → LIMIT not applied             │
│      → Asked for single account but got 50 rows → missing WHERE filter     │
│                                                                             │
│  S5. Fiscal period cross-check                                              │
│      → Result has rows across multiple fiscal_years despite single FY      │
│         filter → possible OR condition bug                                 │
│                                                                             │
│  8B. LLM INSIGHT GENERATOR (Ollama phi4:mini or llama3.2:3b)              │
│  ─────────────────────────────────────────────────────────                  │
│  Input: result rows (max 50) + original question                           │
│  Output: 2-3 sentence factual summary — only from actual rows              │
│  temperature=0, strictly grounded — no fabrication                         │
│                                                                             │
│  Example output:                                                            │
│  "Top 10 EMEA accounts by ARR in Q1FY26 total $48.3M combined.            │
│   Salesforce Inc leads at $8.2M (17% of total). 6 of 10 accounts          │
│   are in DACH region. Lowest in top 10 is SAP SE at $2.1M."               │
│                                                                             │
│  FALLBACK: If insight LLM fails → show raw table only, no narrative       │
│                                                                             │
│  8C. AUTO CHART RULE (no model — pure logic)                               │
│  ──────────────────────────────────────────                                 │
│  time col + numeric col  → line chart                                      │
│  category + numeric      → bar chart                                       │
│  single numeric          → stat card                                       │
│  2 numeric cols          → scatter                                         │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STAGE 9 — RESPONSE TO USER                                                 │
│                                                                              │
│  [Chart/Table] + [2-3 line insight] + [sanity warnings if any]             │
│  + [Show SQL toggle — collapsed by default]                                 │
│  + [👍 / 👎 feedback button → feeds retraining log]                        │
│  + [session memory write: resolved entities for follow-up queries]         │
└─────────────────────────────────────────────────────────────────────────────┘
