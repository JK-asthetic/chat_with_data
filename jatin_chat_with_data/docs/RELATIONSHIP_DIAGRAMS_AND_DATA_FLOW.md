# Relationship Diagrams & Data Flow Visualization

**Companion to:** `TABLE_RELATIONSHIPS_AND_DATA_INTEGRITY.md`  
**Generated:** 2026-10-16  
**Purpose:** Visual architecture reference for query design and agent development

---

## 1. Complete Entity-Relationship Diagram (Conceptual)

```
┌──────────────────────────────────────────────────────────────────────┐
│                      MAESTRO ANALYTICS PLATFORM                      │
│                         (12 Core Tables)                             │
└──────────────────────────────────────────────────────────────────────┘

                            ┌─────────────────────┐
                            │  ACCOUNT DIMENSION  │
                            │ (dim_account_new)   │
                            │  PK: account_id +   │
                            │      end_user_      │
                            │      parent_id      │
                            └──────────┬──────────┘
                                       │
                 ┌─────────────────────┼──────────────────────┐
                 │                     │                      │
                 │ parent_account_id   │ parent_account_id    │
                 │ account_id          │ account_id           │
                 │ account_id          │ account_id           │
                 │                     │                      │
    ┌────────────▼────────┐ ┌─────────▼────────┐ ┌──────────▼────┐
    │    data_acv         │ │    data_arr      │ │ data_churn_   │
    │  (390K rows)        │ │  (1.8M rows)     │ │  reason       │
    │                     │ │                  │ │  (21K rows)   │
    │  PK: id             │ │  PK: id          │ │  PK: id       │
    │  FK: (implied)      │ │  FK: (implied)   │ │  FK: (impl.)  │
    │  ├─ parent_account  │ │  ├─ bill_to_par  │ │  ├─ account   │
    │  ├─ product_l1..l5  │ │  ├─ product_l1..5 │ │  ├─ product_  │
    │  ├─ fiscal_quarter  │ │  ├─ fiscal_month │ │  │   l3        │
    │  └─ order_date      │ │  ├─ rev_rec_date │ │  └─ fiscal_q  │
    │                     │ │  └─ arr          │ │               │
    └───────────┬─────────┘ └────────┬─────────┘ └───────────────┘
                │                    │
                │ product_l1..l5     │ product_l1..l5, opportunity_id
                │ (denormalized)     │ (denormalized)
                │                    │
                └────────┬───────────┘
                         │
                ┌────────▼────────────┐
                │ PRODUCT HIERARCHY   │
                │ (dim_product_       │
                │  hierarchy_new)     │
                │  PK: id             │
                │  ├─ product_l1      │
                │  ├─ product_l2      │
                │  ├─ product_l3      │
                │  ├─ product_l4      │
                │  └─ product_l5      │
                └─────────────────────┘


    ┌──────────────────────────────────┐
    │      PIPELINE (OPPORTUNITY)      │
    │   (data_pipeline_master)         │
    │   (4.7M rows)                    │
    │                                  │
    │   PK: id                         │
    │   FK: (implied)                  │
    │   ├─ account_id                  │
    │   ├─ parent_account_id           │
    │   ├─ opportunity_id              │
    │   ├─ product_l1..l4              │
    │   ├─ close_date                  │
    │   └─ (152 columns total)         │
    └───────────┬──────────────────────┘
                │ opportunity_id
                │ (weak link)
    ┌───────────┼──────────────┬────────────────┐
    │           │              │                │
    │ opportunity_id     opportunity_id   opportunity_id
    │ (80% pop)          (70% pop)        (variable)
    │           │              │                │
    ▼           ▼              ▼                ▼
data_renewal  data_        data_            data_inc_arr
_risk      whitespace     churn_reason     (derived)
(695K)     (126K)         (21K)            
  │          │              │
  │ account  │ account      │ account
  │ _id      │ _id          │ _id
  │          │              │
  └──────┬───┴────────┬─────┘
         │            │
         │ product_   │ product_l2
         │ rl1        │
         │            │
    ┌────▼────────────▼────┐
    │ CHURN SIGNALS (110+) │
    │ (dim_churn_signal_   │
    │  metrics)            │
    │                      │
    │ PK: id, account_id   │
    │ ├─ churn_probability │
    │ ├─ signal_metrics    │
    │ ├─ risk_factors (×100) │
    │ └─ renewal_date      │
    └──────────────────────┘


    OTHER DIMENSIONS:
    ┌─────────────────────────┐
    │ dim_usage_metrics_new   │ ──FK──> data_arr (product, fiscal_month)
    │ (13 cols, sparse)       │
    └─────────────────────────┘

    ┌─────────────────────────┐
    │ dim_con_capability_     │ ──FK──> data_arr (capability, product_l2, account)
    │ fy26_curr_new           │
    │ (20 cols)               │
    └─────────────────────────┘

Legend:
  PK = Primary Key (application-enforced or semantic)
  FK = Foreign Key (implied, not DB constraint)
  ──> = Relationship / Join path
  (%) = Null percentage if sparse
```

---

## 2. Data Flow Diagram (Snowflake → Postgres → AI Agent)

```
                          SNOWFLAKE (Cloud DW)
                       ┌───────────────────────┐
                       │   PUBLIC.SCHEMA       │
                       │                       │
                       │  • CONTRACTS table    │
                       │  • ORDERS             │
                       │  • OPPORTUNITIES      │
                       │  • ACCOUNT_MASTER     │
                       │  • PRODUCT_MASTER     │
                       │                       │
                       │  (Live, full history) │
                       └───────────┬───────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │    DAILY SYNC SCHEDULE       │
                    │ (backend/scripts/scheduler   │
                    │  .py, via Celery beat)       │
                    │                              │
                    │  • Runs daily at 02:00 UTC   │
                    │  • Incremental (watermark)   │
                    │  • Staging-swap pattern      │
                    │  • On failure: retry 3x      │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │   TRANSFORM LAYER (Python)   │
                    │                              │
                    │  • SQL templating (tier-based) │
                    │  • Product hierarchy lookup  │
                    │  • Account denormalization   │
                    │  • Churn signal computation  │
                    │                              │
                    │  Cost: ~$10–15 Snowflake    │
                    │  per day (query cost)        │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │  POSTGRES (pop_db, local)           │
                    │                                     │
                    │  FACT TABLES (indexed, cached):     │
                    │  ├─ data_acv (daily refresh)        │
                    │  ├─ data_arr (daily refresh)        │
                    │  ├─ data_inc_arr (derived)          │
                    │  ├─ data_churn_reason (daily)       │
                    │  ├─ data_renewal_risk (daily)       │
                    │  ├─ data_whitespace (weekly)        │
                    │  └─ data_pipeline_master (hourly)   │
                    │                                     │
                    │  DIMENSION TABLES (cached):         │
                    │  ├─ dim_account_new (daily)         │
                    │  ├─ dim_product_hierarchy_new (wk)  │
                    │  ├─ dim_churn_signal_metrics (daily) │
                    │  ├─ dim_usage_metrics_new (wk)      │
                    │  └─ dim_con_capability_fy26_* (daily) │
                    │                                     │
                    │  Total size: ~3–5 GB (varies)      │
                    │  Query SLA: <500ms (99th %ile)      │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │    CACHE LAYER (Redis/Valkey)       │
                    │                                     │
                    │  • Result cache: SELECT * results   │
                    │  • TTL: Until next sync (~23h)      │
                    │  • Size: Up to 10 MB per key        │
                    │  • Hit rate: ~30% (repeating q's)   │
                    │                                     │
                    │  Cost savings: 70% for cached       │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │   MAESTRO SQL PIPELINE ENGINE       │
                    │   (backend/src/agents/runtime/)     │
                    │                                     │
                    │  1. Intent Classifier (Haiku)       │
                    │     → query_type, table_hints       │
                    │                                     │
                    │  2. Adaptive Planner (Sonnet)       │
                    │     → SQL template resolution       │
                    │     → Signal extraction             │
                    │     → Tier selection (t3–t6)        │
                    │                                     │
                    │  3. SQL Generator + Validator       │
                    │     → read-only guard check         │
                    │     → hard LIMIT enforcement        │
                    │                                     │
                    │  4. Execute (cached or fresh)       │
                    │     → if hit: serve from Redis      │
                    │     → if miss: run on Postgres      │
                    │                                     │
                    │  5. Enrichment (parallel Haiku)     │
                    │     → Chart config                  │
                    │     → Insight extraction            │
                    │                                     │
                    │  6. Response Assemble + Stream      │
                    │     → [STATUS], [DATA], [CHART],    │
                    │     → [INSIGHT], [DONE]             │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │   FRONTEND (Next.js)                │
                    │                                     │
                    │  Real-time SSE parsing:             │
                    │  • [STATUS] → "Loading data..."     │
                    │  • [DATA] → Table render            │
                    │  • [CHART] → Recharts/Chart.js      │
                    │  • [INSIGHT] → Bullet list          │
                    │  • [DONE] → Ready for interaction   │
                    │                                     │
                    │  Cost: O(data_size) frontend        │
                    └──────────────────────────────────────┘

COST & LATENCY PROFILE:
├─ Snowflake sync cost: $10–15/day (once, all facts)
├─ Postgres query: $0 (local infrastructure)
├─ Redis cache hit: <50ms, $0 (local)
├─ Redis cache miss → Postgres: 100–500ms, $0
├─ Intent classifier (Haiku): <50ms, $0.00001
├─ Adaptive planner (Sonnet): 1–2s, $0.002
├─ Chart/insight generation (Haiku×2): 200–400ms, $0.0001
├─ SSE streaming: <1s frontend parse
└─ Total end-to-end (cache miss): 2–3s, $0.0021 per query

RELIABILITY:
└─ Sync failure handling: Stale data OK (23h max); no crash
└─ Orphan handling: LEFT JOIN → 100% of facts preserved
└─ Product hierarchy gaps: COALESCE → silent NULLs in GROUP BY
└─ Opportunity link gaps: 5–95% NULL; fallback to account_id
```

---

## 3. Join Graph (Navigating Relationships)

```
START: User asks a question → Intent Classifier picks a path

Path A: "Show me ARR by account"
  START
    └─> extract: parent_account_id, fiscal_month
    └─> route: data_arr (primary)
    └─> JOIN: dim_account_new (LEFT on bill_to_parent_id)
    └─> GROUP BY: parent_account_id, fiscal_month
    └─> ORDER BY: fiscal_month DESC
    └─> RESULT: Account-level ARR trend
    
    Orphan handling: Some accounts have no dim row
                    → LEFT JOIN includes them with NULL attrs

Path B: "Which accounts are at churn risk and have pipeline?"
  START
    └─> extract: account_id, churn_probability, opportunity_id
    └─> route: dim_churn_signal_metrics (primary)
        └─> FK: account_id
        └─> JOIN: data_pipeline_master (LEFT on account_id)
            ├─ ⚠️ WEAK LINK: opportunity_id is 80% NULL
            ├─ Strategy: Join on account_id + close_date > TODAY
            └─ GROUP BY: account, min(churn_prob), count(open_opps)
    └─> RESULT: Accounts + risk + opportunity count
    
    Orphan handling: Some pipeline opps have no churn signal row
                    → FULL OUTER JOIN to include all

Path C: "What is the product mix by account and capability coverage?"
  START
    └─> extract: account, product_l2, capability
    └─> route: data_arr (primary)
        └─> FK: product_l2
        └─> JOIN: dim_con_capability_fy26_curr_new (LEFT)
            ├─ Join key: account_id + product_l2
            └─ Result: 3-way: ARR + product + capability
    └─> GROUP BY: account, product_l2, capability_status
    └─> RESULT: Coverage matrix with ARR
    
    Orphan handling: Some (account, product) pairs have no capability row
                    → LEFT JOIN shows NULL; interpret as "not covered"

Path D: "Show all ACV transactions, flag which accounts are in our master"
  START
    └─> route: data_acv (primary; 100% of rows)
    └─> JOIN: dim_account_new (LEFT on parent_account_id)
    └─> COALESCE: product_l2, product_l3 (fill NULLs)
    └─> ADD: data_quality_flag = CASE WHEN dim.id IS NULL
                                      THEN 'ORPHAN'
                                      ELSE 'LINKED' END
    └─> RESULT: All transactions + quality flags
    
    Orphan handling: 100% preservation; explicit flag for audit

Path E: "Which high-ARR accounts are losing usage (trend)?"
  START
    └─> route: data_arr (primary)
    └─> WHERE: arr > threshold AND fiscal_year >= '2025'
    └─> JOIN: dim_usage_metrics_new (LEFT)
        ├─ Join key: product_l1 + fiscal_month
        ├─ ⚠️ SPARSE: usage_metrics is 70% NULL
        └─ Strategy: COALESCE(usage, 0); GROUP BY to find trends
    └─> JOIN: dim_account_new (LEFT)
    └─> RESULT: Accounts + ARR + usage trend
    
    Orphan handling: Accounts with ARR but no usage row → 0 usage shown
```

---

## 4. Data Quality Maturity by Table

```
MATURITY SCORE: Based on FK coverage, NULL rates, deduplication quality

┌─────────────────────────────┬──────────┬──────────┬────────────┐
│ Table                       │ Maturity │ Null %   │ PK Quality │
├─────────────────────────────┼──────────┼──────────┼────────────┤
│ dim_account_new             │ ████████░ 80%       │ <1%        │ ✅ Best
│ data_arr                    │ ████████░ 80%       │ <1%        │ ✅ Good
│ data_acv                    │ ███████░░ 75%       │ <0.1%      │ ✅ Good
│ data_pipeline_master        │ ███████░░ 75%       │ <2%        │ ✅ Good
│ data_renewal_risk           │ ██████░░░ 65%       │ ~5%        │ ⚠️ Fair
│ data_inc_arr                │ ██████░░░ 65%       │ ~3%        │ ⚠️ Fair
│ dim_churn_signal_metrics    │ ██████░░░ 65%       │ <1%        │ ✅ Good
│ data_churn_reason           │ █████░░░░ 55%       │ ~2%        │ ⚠️ Fair
│ data_whitespace             │ █████░░░░ 55%       │ ~10%       │ ⚠️ Fair
│ dim_usage_metrics_new       │ ████░░░░░ 45%       │ ~15%       │ ⚠️ Fair
│ dim_con_capability_fy26_    │ ███░░░░░░ 35%       │ ~20%       │ ⚠️ Poor
│ dim_product_hierarchy_new   │ ██░░░░░░░ 25%       │ ~5%        │ ⚠️ Poor
└─────────────────────────────┴──────────┴──────────┴────────────┘

LEGEND:
  Maturity = FK coverage + PK uniqueness + temporal consistency
  Null % = Percentage of rows with ≥1 NULL in join-key columns
  PK Quality = Surrogate key collision rate / uniqueness

ISSUES BY TABLE:
  dim_product_hierarchy_new   → Product L2/L3 often NULL; affects GROUP BY
  dim_con_capability_fy26_    → Only ~3,239 rows; sparse by design
  data_whitespace             → Multiple opp IDs; ambiguous joins
  data_churn_reason           → No opportunity_id; hard to cross-link to pipeline
  dim_usage_metrics_new       → Grain unclear; product_name vs. product_l1 mismatch
```

---

## 5. Cost & Performance Optimization Matrix

```
QUERY TYPE              │ BEST APPROACH              │ Est. Cost  │ Latency
────────────────────────┼────────────────────────────┼────────────┼─────────
Simple account query    │ Cache hit (reuse yesterday)│ $0         │ <50ms
(e.g. "Show ARR")       │ or Postgres direct         │ or $0.0001 │ or <200ms
                        │                            │            │
Account + dimension     │ LEFT JOIN (account × dims) │ $0.0001    │ 100–300ms
multi-fact              │ + cache result             │            │
(e.g. ARR + capability) │                            │            │
                        │                            │            │
Churn + pipeline        │ Account_id + date filters  │ $0.0005    │ 500ms–2s
cross-domain           │ (not opportunity_id, weak) │            │
(high risk + open opps) │                            │            │
                        │                            │            │
Time-series trend       │ Aggregate by fiscal_month  │ $0.0001    │ 200–500ms
(e.g. ARR growth)       │ + denormalize product      │            │
                        │                            │            │
Orphan audit            │ LEFT JOIN with NULL flags  │ $0.0002    │ 300–800ms
(find unlinked rows)    │ + COUNT(*) GROUP BY status │            │
                        │                            │            │
Full hierarchy rebuild  │ Star schema (dim × fact)   │ $0.001     │ 1–3s
(account × product ×    │ + aggregate first          │            │
 capability)            │                            │            │
                        │                            │            │
Prediction model input  │ Denormalize to wide table  │ $0.002     │ 2–5s
(features for LLM)      │ + cache 1 week             │            │

OPTIMIZATION RULES:
1. Aggregate first, join dims second (never INNER JOIN facts)
2. Cache identical queries; TTL until next sync (~23h)
3. Filter by fiscal_quarter/month early (pushdown to Postgres)
4. Use COALESCE for product hierarchy (avoid NULLs in GROUP BY)
5. For orphans, use LEFT JOIN + explicit NULL flag
6. Never use opportunity_id as primary join (80% NULL); use account_id + date
7. Pre-compute derived metrics (e.g. churn + pipeline union) if queried >1/hour
```

---

## 6. Unlinked Data Handling Decision Tree

```
Question: "I have a fact row. How do I know if it's linked to a dimension?"

                            START
                              │
                              ▼
                    Is parent_account_id NULL?
                    │
                ┌───┴────┐
                │        │
               NO        YES
                │        │
                ▼        ▼
         JOIN dim_account  ORPHAN_FLAG = 'MISSING_ACCOUNT'
         on parent_account_id  │
                │             └──> Include in results with NULL dims
                ▼                   ├─ Flag for audit
                │                   ├─ Include in aggregates (correct)
         Is dim match found?        └─ Report to data team
                │
            ┌───┴────┐
            │        │
          YES        NO
            │        │
            ▼        ▼
         LINKED   ORPHAN
         ✅         ⚠️
         Include    Include with NULL dims
         dims       + ORPHAN_FLAG


Question: "How do I join two fact tables when some rows don't match?"

                    START (fact1 + fact2)
                         │
        ┌────────────────┼────────────────┐
        │                │                │
        ▼                ▼                ▼
    INNER JOIN        LEFT JOIN      FULL OUTER JOIN
    (Not usually)      (Best)          (Also fine)
    │                  │               │
    └─> Loses fact     ├─> fact1 rows  ├─> ALL rows
       rows with no    │   with no      │   preserved
       match in fact2   │   match in     │   ├─ Separate
    ├─ Risk: Silent    │   fact2 = NULL │   │   handling for
    │  undercount      │               │   │   "fact1 only"
    └─ Only use if:    │   ├─ Best for │   │   and "fact2 only"
       You KNOW all    │   │  revenue   │   │
       fact1 rows have │   │  reporting │   ├─ Slightly slower
       a match         │   └─ RECOMMEND │   │   (extra scan)
                       │   THIS         │   └─ Use for audits
                       │               │
                       └─> Include     └─> Include fact2
                          fact1 + NULLs    rows with NULL
                          from fact2       from fact1


Question: "Should I GROUP BY a nullable column (e.g., product_l2)?"

                        START
                         │
        Is product_l2 populated ≥80% of rows?
        │
    ┌───┴────┐
    │        │
   NO       YES
    │       │
    ▼       ▼
COALESCE   GROUP BY product_l2 directly
before     │
GROUP BY   ├─ OK, NULLs go to "NULL" bucket
│          └─ Risk: ~2–5% of rows in NULL
├─ Syntax: COALESCE(product_l2, 'Unclassified')
│  GROUP BY COALESCE(product_l2, 'Unclassified')
│
├─ Result: All rows bucketed
└─ Report as product_l2 with "(Unclassified)" label
```

---

## 7. AI Agent Query Generation Rules

```
WHEN GENERATING SQL FOR THE AGENT:

Rule 1: ALWAYS use LEFT JOIN for account/product dimensions
  ❌ WRONG:
    SELECT a.id, d.parent_account_name, a.arr
    FROM data_arr a
    INNER JOIN dim_account_new d ON a.bill_to_parent_id = d.end_user_parent_id

  ✅ RIGHT:
    SELECT a.id, d.parent_account_name, a.arr
    FROM data_arr a
    LEFT JOIN dim_account_new d ON a.bill_to_parent_id = d.end_user_parent_id

Rule 2: COALESCE product hierarchy BEFORE GROUP BY
  ❌ WRONG:
    GROUP BY a.product_l2

  ✅ RIGHT:
    GROUP BY COALESCE(a.product_l2, 'Unclassified')

Rule 3: Add data quality flag for transparency
  ✅ RECOMMENDED:
    SELECT ...,
      CASE WHEN d.account_id IS NULL THEN 'ORPHAN'
           ELSE 'LINKED'
      END AS _quality_flag

Rule 4: For cross-fact joins, aggregate first
  ❌ WRONG:
    SELECT ... FROM data_acv
    INNER JOIN data_arr ON data_acv.parent_account_id = data_arr.bill_to_parent_id
    -- Joins at detail level; duplicates possible

  ✅ RIGHT:
    WITH acv_agg AS (
      SELECT parent_account_id, fiscal_quarter, SUM(adjusted_acv) as acv
      FROM data_acv GROUP BY parent_account_id, fiscal_quarter
    ),
    arr_agg AS (
      SELECT bill_to_parent_id, fiscal_quarter, SUM(arr) as arr
      FROM data_arr GROUP BY bill_to_parent_id, fiscal_quarter
    )
    SELECT * FROM acv_agg
    FULL OUTER JOIN arr_agg ON ...

Rule 5: Use opportunity_id with caution (80% NULL in some tables)
  ⚠️ RISKY:
    FROM data_arr a
    INNER JOIN data_pipeline_master p ON a.opportunity_id = p.opportunity_id
    -- Loses 20% of ARR rows silently

  ✅ SAFER:
    FROM data_arr a
    LEFT JOIN data_pipeline_master p
      ON a.account_id = p.account_id
      AND a.fiscal_month >= DATE_TRUNC('month', p.close_date - interval '3 months')
    -- Uses account_id + date proximity instead

Rule 6: Always add LIMIT and LIMIT OFFSET for pagination
  ✅ RECOMMENDED:
    SELECT ... LIMIT 1000 OFFSET 0
    -- Prevents accidental full-table scans

Rule 7: Document NULLs in result labels
  ✅ RECOMMENDED:
    SELECT ...,
      COALESCE(product_l2, '[Unclassified]') as product_category
    FROM data_acv
    -- Tells user that [Unclassified] rows have missing product hierarchy
```

---

**Version:** 1.0 | **Last Updated:** 2026-10-16 | **Next Update:** After next major Snowflake schema change

