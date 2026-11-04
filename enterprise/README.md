# Enterprise Chat with Data — ARR Analytics

A production-grade NL-to-SQL analytics system built with a **Metric-Agent Fan-Out Architecture**, **Deterministic Entity Extraction**, and a cost-optimized LLM model.

---

## 🌟 Key Architecture Innovations

1. **Deterministic-First Extraction ($0 cost)**
   - All entity extraction for products, geographies, fiscal periods, SKUs, and segments is performed using deterministic Python tools (`spaCy` POS/DEP matching, regex normalizers, and RapidFuzz). Zero LLM tokens wasted on parsing entities.

2. **Metrics YAML as Single Source of Truth (`config/metrics.yaml`)**
   - Every metric (`ARR`, `ACV`, `NNACV`, `INCR_ARR`, `CHURN`, `NACV`, `QTY`, `RENEWAL_RISK`, `CHURN_REASON`) defines:
     - Primary table & target aggregation column
     - Allowed filter dimensions
     - Snapshot rules & mandatory filters
     - Dedicated MetricAgent class
     - Domain-specific SQL generation rules

3. **Parallel Metric Agent Fan-Out**
   - Multi-metric questions (e.g. *"Compare ARR and ACV for Siemens in Q1 FY 2026"*) are split and dispatched to their respective `MetricAgent` instances simultaneously via `asyncio.gather`.
   - Each agent manages its own schema context, SQL generation, validation, and execution.

4. **8-Point SQL Static Validator**
   - Syntax validation via `sqlglot`
   - Dead and unknown table guards
   - Table-specific column rules (e.g. `data_arr` must use `cfy_geo` and `end_user_name`, while `data_acv` uses plain `geo` and `account_name`)
   - Mandatory `LIMIT` and mutation prevention (`INSERT`/`UPDATE`/`DELETE` blocked)

5. **Guaranteed Fallback (Never Hard-Crashes)**
   - If the LLM is unreachable or all 3 retry attempts fail, the system automatically builds and executes a syntactically guaranteed deterministic SQL skeleton.

6. **Separate Database and AI Configurations**
   - `config/db.yaml`: Database host, port, credentials, connection pool, and `dry_run` toggle.
   - `config/ai.yaml`: LLM endpoint, model names, retry counts, and cache settings.
   - Built-in `dry_run` mode reads from local sample CSVs without needing an active Postgres database.

---

## 📁 Project Directory Structure

```
enterprise/
├── config/
│   ├── db.yaml               # Database credentials & dry-run settings
│   ├── ai.yaml               # LLM model choices & NL->SQL cache configuration
│   ├── metrics.yaml          # Unified Metric Registry for all 9 metrics
│   └── schema.yaml           # Geographic, product, and segment aliases
├── core/
│   ├── db.py                 # Asyncpg pool, sync psycopg2 fallback, & CSV dry-run loader
│   ├── mdl.py                # Model Definition Language (MDL) catalog & table definitions
│   ├── mdl_registry.py       # Joins metrics.yaml with MDL TableDefs into MetricDefinitions
│   └── settings.py           # Typed Pydantic v2 settings for DB, AI, and pipeline
├── extraction/
│   ├── spacy_ner.py          # Fast spaCy POS/DEP + PhraseMatcher entity extraction
│   ├── orchestrator.py       # Asynchronously runs all 7 extraction tools in parallel
│   └── tools/
│       ├── company_tool.py   # Account resolver (pg_trgm in DB, RapidFuzz in dry-run)
│       ├── fiscal_tool.py    # Fiscal period parser & quarter-of date math
│       ├── geo_tool.py       # Geographic alias expansion & CFY hierarchy matching
│       ├── order_type_tool.py# Deal motion resolver ('new logo' -> 'NEW_CUST')
│       ├── product_tool.py   # Product family & sub-product hierarchy matching
│       ├── segment_tool.py   # Market segment resolver ('ENT' -> 'Enterprise')
│       └── sku_tool.py       # Fixed vocabulary SKU extractor
├── pipeline/
│   ├── models.py             # Strict Pydantic v2 contracts for all pipeline stages
│   ├── classifier.py         # Haiku LLM classifier (metric routing & intent)
│   ├── clarifier.py          # Terminal clarification card for unresolvable ambiguities
│   ├── memory.py             # Session memory storing resolved entities & prior row values
│   └── orchestrator.py       # Top-level pipeline orchestrator & agent fan-out coordinator
├── agents/
│   ├── base_agent.py         # Abstract MetricAgent (context -> SQL -> execute -> sanity -> insight)
│   ├── arr_agent.py          # ARR point-in-time snapshot agent
│   ├── acv_agent.py          # ACV bookings & deal-level agent
│   ├── incr_arr_agent.py     # Incremental / net ARR change agent
│   ├── churn_agent.py        # Downsell & ARR attrition agent
│   ├── nacv_target_agent.py  # Planning target agent
│   ├── quantity_agent.py     # License / seat count agent
│   ├── renewal_risk_agent.py # Account renewal risk score agent
│   └── churn_reason_agent.py # Customer churn category agent
├── sql/
│   ├── builder.py            # Context-driven SQL prompt builder & skeleton constructor
│   ├── validator.py          # 8-point AST static SQL validator
│   ├── generator.py          # Sonnet LLM generator with retry loop & NL->SQL cache
│   └── executor.py           # SQL executor with clean column projection
├── response/
│   ├── formatter.py          # Rich terminal table and panel formatter
│   ├── insight.py            # Streamed executive summary narrative
│   ├── logger.py             # CSV and JSONL session audit logger
│   └── sanity.py             # Statistical sanity checks on returned rows
├── tests/
│   ├── run_tests.py          # Unittest test runner
│   ├── test_extraction.py    # Unit tests for deterministic tools
│   ├── test_metrics_yaml.py  # Schema validation tests
│   └── test_sql_validator.py # SQL validation tests
├── main.py                   # Interactive terminal REPL and CLI runner
├── requirements.txt          # Production dependencies
└── .env.example              # Template for environment variables
```

---

## 🚀 Getting Started

### 1. Environment Setup
```powershell
cd C:\Users\jatin\Documents\chat_with_data\enterprise

# Install dependencies
pip install -r requirements.txt

# Download spaCy English model
python -m spacy download en_core_web_sm
```

### 2. Configuration
Copy `.env.example` to `.env` (or configure `config/db.yaml` and `config/ai.yaml`):
```bash
# To test with real database, set DRY_RUN=false and supply Postgres credentials:
DRY_RUN=true
DB_HOST=localhost
DB_PORT=5432
DB_NAME=pop_db
DB_USER=pop
DB_PASSWORD=pop_secret

# AI settings
ZLLAMA_BASE_URL=https://zllama.corp.zscaler.com
ZLLAMA_API_KEY=your_key_here
```

### 3. Run Automated Tests
```powershell
python tests/run_tests.py
```

### 4. Interactive Terminal REPL
```powershell
python main.py
```

### 5. Single-Query CLI Execution
```powershell
python main.py "top 10 accounts by ARR in EMEA FY 2026 Q1"
python main.py "compare ARR and ACV for Siemens in Q1 FY 2026"
```

