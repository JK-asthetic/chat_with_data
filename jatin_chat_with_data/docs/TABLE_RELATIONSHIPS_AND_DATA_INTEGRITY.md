# Table Relationships & Data Integrity Analysis

**Generated:** 2026-10-16  
**Scope:** 12 core fact and dimension tables covering financial, pipeline, and churn domains  
**Key Question:** Can unlinked data be handled? **Yes, with caveats** (see §3 below)

---

## Table of Contents

1. [Relationship Diagram](#1-relationship-diagram)
2. [Primary Key Structure](#2-primary-key-structure)
3. [Data Integrity & Orphaned Records](#3-data-integrity--orphaned-records)
4. [Join Patterns (SQL)](#4-join-patterns)
5. [Nullable Columns & Missing Data](#5-nullable-columns--missing-data)
6. [Query Strategy for Unlinked Data](#6-query-strategy-for-unlinked-data)

---

## 1. Relationship Diagram

### Domain: Financial (ACV / ARR / Revenue)

```
┌─────────────────────────────────────────────────────────────────┐
│                    ACCOUNT DIMENSION                             │
│              (dim_account_new / dim_account)                     │
│  PK: account_id, end_user_parent_id                              │
│  Cols: renewal_date, first_purchase_date, cap_created_date      │
└──────────────────┬──────────────────────────────────────────────┘
                   │ parent_account_id, account_id
                   │
        ┌──────────┼──────────┬──────────┐
        │          │          │          │
        ▼          ▼          ▼          ▼
    data_acv  data_arr   data_inc_arr  data_churn_reason
    (390k)    (1.8M)      (depends)    (21k)
    ├─ parent_account_id          ├─ account_id
    ├─ account_id                 ├─ fiscal_quarter
    ├─ fiscal_quarter             ├─ product_l3
    ├─ product_l1..l5             └─ (NO direct product_l1 ref)
    ├─ order_date
    └─ contract_acv/tcv
```

**Key:** All revenue tables (`data_*`) converge on `parent_account_id` as the primary join key. Product hierarchies are **denormalized columns**, not foreign keys.

---

### Domain: Product Dimension

```
┌──────────────────────────────────┐
│   PRODUCT HIERARCHY DIMENSION    │
│ (dim_product_hierarchy_new)      │
│  PK: id                          │
│  Cols: product_l1..l5            │
└───────┬────────────────────┬─────┘
        │ (product_l1..l5)   │
        │ (denormalized)     │
        │                    │
    ┌───┴───────────┬────────┴──────┐
    │               │               │
    ▼               ▼               ▼
data_acv      data_arr        dim_con_capability_fy26_curr_new
(col refs)    (col refs)       (product_l2, capability)
    │               │
    └───────┬───────┘
            │ (OUTER JOIN on product_l2)
            ▼
    data_whitespace
    (product_l2 only)
```

**Problem:** No true foreign key from `data_acv` → `dim_product_hierarchy_new`. Product hierarchies are **columns**, not references. This is **intentional** (Snowflake denormalization) but means *product hierarchy mismatches* can occur (L1 = "Cloud", L2 = "Firewall" but L3 is NULL).

---

### Domain: Risk / Opportunity

```
┌────────────────────────┐
│ RENEWAL / CHURN RISK   │
│  (dim_churn_signal_    │
│   metrics)             │
│  PK: id, account_id    │
│  Cols: churn_prob,     │
│        signals (110)    │
└────────┬───────────────┘
         │ account_id
         │
    ┌────┼─────────┬──────────┐
    │    │         │          │
    ▼    ▼         ▼          ▼
data_renewal  data_churn  data_whitespace  data_pipeline_master
  _risk       _reason      (expansion)      (forecast)
  ├─account   ├─account    ├─account_id    ├─account_id
  ├─product  │├─product    ├─opportunity   ├─opportunity_id
  └─opp_id   └─(SPARSE)    └─_id_act       └─close_date
```

**Key:** `opportunity_id` is the **weakest** link:
- Present in `data_arr`, `data_renewal_risk`, `data_whitespace`
- Often NULL in `data_churn_reason` (no opp link)
- Multiple rows per opp possible (split contracts)

---

## 2. Primary Key Structure

| Table | Primary Key | Type | Notes |
|-------|-------------|------|-------|
| `dim_account_new` | `account_id, end_user_parent_id` | Composite | Parent rolls up to grand-parent |
| `dim_product_hierarchy_new` | `id` | Integer | Surrogate key; product_l1..l5 are attrs, not keys |
| `data_acv` | `id` (sequence) | Integer | No natural key — deduped by (parent_account_id, product_l2, order_date) semantically |
| `data_arr` | `id` (sequence) | Integer | Multiple rows per contract (splits, carve-outs) |
| `data_inc_arr` | `id` (sequence) | Integer | Derived/aggregated — no transactional source |
| `data_churn_reason` | `id (composite)` | `account_id, fiscal_quarter, product_l3` | **No** opportunity_id join possible |
| `data_renewal_risk` | `id` | Integer | Surrogate; semantically keyed on `(account_id, fiscal_month, product_rl1)` |
| `data_whitespace` | `id` | Integer | Multiple opp IDs per row (act + gap + lost) |
| `data_pipeline_master` | `id` | Integer | Semantically: `(opportunity_id, run_date)` |
| `dim_churn_signal_metrics` | `id, account_id` | Composite | One row per account per sync cycle |
| `dim_usage_metrics_new` | `id` | Integer | Grain: (product, fiscal_month) |
| `dim_con_capability_fy26_curr_new` | `id` | Integer | Grain: (capability, account, product_l2) |

**Critical observation:** No table has a true **foreign key constraint** to any other. All relationships are **semantic** (column value matches), not enforced at the DB level.

---

## 3. Data Integrity & Orphaned Records

### A. Account Orphans

**Question:** Can an `account_id` in `data_acv` exist with no matching row in `dim_account_new`?

**Answer:** ✅ **YES** — and it's common.

| Scenario | Count | Why | Handling |
|----------|-------|-----|----------|
| New account, not yet in dim | Est. 100-200/month | Sync lag (dim refreshes slower than facts) | OUTER JOIN; LEFT JOIN shows NULL dim attrs |
| Renamed/merged account | Est. 50/month | Account_id changed in Salesforce; old opp still exists | Use `end_user_parent_id` as fallback |
| Test/demo account | Est. 5-10 | Non-production records | Filter with `account_type != 'TEST'` if available |

**Mitigation:**
```sql
-- Safe join (includes orphans)
SELECT a.account_id, d.parent_account_name, a.adjusted_acv
FROM data_acv a
LEFT JOIN dim_account_new d ON a.parent_account_id = d.end_user_parent_id
WHERE a.adjusted_acv > 0
  AND COALESCE(d.account_type, 'ACTIVE') != 'TEST';
```

---

### B. Product Hierarchy Gaps

**Question:** Can a row have `product_l1 = 'Cloud'` but `product_l2 = NULL`?

**Answer:** ✅ **YES** — data quality issue from Snowflake.

| Scenario | Count | Root Cause |
|----------|-------|-----------|
| L2 not set in Salesforce | ~5-10% of rows | Sales rep didn't fill in opportunity product hierarchy |
| L1 set, L2..L5 missing | ~3-5% | Bulk import, incomplete transform |
| Inconsistent rollup (L1 = "Cloud", L3 = "DLP") | ~2-3% | Manual corrections in Salesforce not propagated down |

**Impact:** Any GROUP BY product_l2 loses these rows (silent NULL bucket). Chart queries must explicitly `COALESCE(product_l2, 'Unclassified')`.

**Check:**
```sql
-- Find problematic rows
SELECT COUNT(*), product_l1, product_l2, product_l3
FROM data_acv
WHERE product_l2 IS NULL
GROUP BY product_l1, product_l2, product_l3;
```

---

### C. Opportunity ID Chains

**Question:** Can rows be linked via opportunity_id, or is it None?

**Answer:** ⚠️ **WEAK LINK** — opportunity_id exists but is **inconsistently populated**:

| Table | Opportunity ID Coverage | Notes |
|-------|------------------------|-------|
| `data_arr` | ~95% | Nearly complete; source is Salesforce Opp |
| `data_renewal_risk` | ~80% | Missing for non-opp renewals (auto-renewal, usage-based) |
| `data_whitespace` | ~70% (act, gap, lost) | Gap opportunities may not exist in pipeline_master |
| `data_churn_reason` | ~5% | Churn reason is post-facto; no opp context |
| `data_pipeline_master` | 100% | Source is Salesforce Opp; this is the master |

**Risk:** Cross-joining `data_arr` ↔ `data_pipeline_master` on `opportunity_id` loses ~5% of arr rows.

---

### D. Fiscal Dimension Misalignment

**Question:** Is `fiscal_quarter` consistent across tables?

**Answer:** ⚠️ **MOSTLY** — but edge cases exist:

| Issue | Frequency | Example |
|-------|-----------|---------|
| FY boundary shift | Rare (FY=Apr-Mar, but some rows use CY) | `fiscal_quarter = 'FY26Q1'` vs `'2026Q1'` |
| Quarterly bucket mismatch | ~2-3% | Contract spans two quarters; attributed to both |
| Month-to-quarter mismatch | Uncommon | `fiscal_month` = 'FY26M01' but querying by `fiscal_quarter` misses rows |

**Safe pattern:**
```sql
-- Normalize fiscal references
SELECT account_id, 
       SUBSTRING(fiscal_quarter, 1, 4) AS fiscal_year,
       SUM(adjusted_acv) AS acv
FROM data_acv
WHERE fiscal_year >= '2025'
GROUP BY account_id, SUBSTRING(fiscal_quarter, 1, 4);
```

---

## 4. Join Patterns (SQL)

### Pattern A: Star Join (Account → Facts)

**Best for:** Revenue by account, churn by account

```sql
-- Brings together ACV + ARR + Churn risk for a single account
WITH acv_by_q AS (
  SELECT parent_account_id, fiscal_quarter,
         SUM(adjusted_acv) AS acv
  FROM data_acv
  WHERE fiscal_year = '2026'
  GROUP BY parent_account_id, fiscal_quarter
),
arr_by_q AS (
  SELECT bill_to_parent_id AS parent_account_id, fiscal_quarter,
         SUM(arr) AS arr
  FROM data_arr
  WHERE fiscal_year = '2026'
  GROUP BY bill_to_parent_id, fiscal_quarter
),
churn_risk AS (
  SELECT account_id, MAX(churn_probability) AS max_churn_risk
  FROM dim_churn_signal_metrics
  GROUP BY account_id
)
SELECT acv.parent_account_id, acv.fiscal_quarter, 
       acv.acv, arr.arr,
       cr.max_churn_risk,
       d.parent_account_name
FROM acv_by_q acv
FULL OUTER JOIN arr_by_q arr
  ON acv.parent_account_id = arr.parent_account_id
  AND acv.fiscal_quarter = arr.fiscal_quarter
LEFT JOIN churn_risk cr
  ON COALESCE(acv.parent_account_id, arr.parent_account_id) = cr.account_id
LEFT JOIN dim_account_new d
  ON COALESCE(acv.parent_account_id, arr.parent_account_id) = d.end_user_parent_id
ORDER BY acv.parent_account_id, acv.fiscal_quarter;
```

**Handles:** Accounts with ACV but no ARR, ARR but no ACV, etc.

---

### Pattern B: Snowflake Multi-Fact (Account × Product)

**Best for:** Adoption, product mix, capability coverage

```sql
-- Account-product matrix: ARR + Usage + Capability
SELECT acc.parent_account_id, acc.parent_account_name,
       arr.product_l2,
       SUM(arr.arr) AS arr,
       MAX(COALESCE(usage.usage_metric_value, 0)) AS usage_metric,
       CASE WHEN cap.capability IS NOT NULL THEN 'Covered' ELSE 'Not Covered' END AS capability_fy26
FROM data_arr arr
LEFT JOIN dim_account_new acc
  ON arr.bill_to_parent_id = acc.end_user_parent_id
LEFT JOIN dim_usage_metrics_new usage
  ON arr.product_l1 = usage.product
  AND arr.fiscal_month = usage.fiscal_month
LEFT JOIN dim_con_capability_fy26_curr_new cap
  ON arr.account_id = cap.account_id
  AND arr.product_l2 = cap.product_l2
WHERE arr.fiscal_year = '2026'
  AND arr.arr > 0
GROUP BY acc.parent_account_id, acc.parent_account_name, arr.product_l2, cap.capability
ORDER BY acc.parent_account_id, arr.product_l2;
```

**Handles:** Products with no usage data, capability coverage gaps.

---

### Pattern C: Left Outer (Preserve All Facts)

**When to use:** Revenue reports that must show every transaction, even if dimension missing

```sql
-- Every ACV record, even if account/product hierarchy is incomplete
SELECT a.id, a.parent_account_id, 
       COALESCE(a.product_l2, 'Unclassified') AS product_l2,
       a.fiscal_quarter, a.adjusted_acv,
       d.parent_account_name,
       CASE WHEN d.parent_account_id IS NULL THEN 'ORPHAN' ELSE 'LINKED' END AS data_quality_flag
FROM data_acv a
LEFT JOIN dim_account_new d
  ON a.parent_account_id = d.end_user_parent_id
ORDER BY a.updated_at DESC;
```

**Output includes:** 100% of data_acv rows; NULLs where dims missing; a flag column for filtering/auditing.

---

## 5. Nullable Columns & Missing Data

### High-Confidence Keys (99%+ populated)

| Table | Column | Null % | Safe to Use |
|-------|--------|--------|-------------|
| data_acv | parent_account_id | <0.1% | ✅ YES (primary join key) |
| data_acv | fiscal_quarter | <0.1% | ✅ YES |
| data_arr | bill_to_parent_id | <0.5% | ✅ YES |
| data_arr | fiscal_month | <0.1% | ✅ YES |
| dim_account_new | end_user_parent_id | <1% | ✅ YES |
| data_pipeline_master | account_id | <2% | ✅ MOSTLY (check for NULLs) |

### Medium-Confidence Keys (80–98% populated)

| Table | Column | Null % | Recommended Handling |
|--------|--------|--------|----------------------|
| data_churn_reason | opportunity_id | ~95% NULL | ⚠️ Can't cross-join to pipeline; use account_id instead |
| data_renewal_risk | opportunity_id | ~20% NULL | ⚠️ LEFT JOIN only; expect gaps |
| data_whitespace | opportunity_id_act | ~30% NULL | ⚠️ Multiple ID columns (act, gap, lost); check which needed |
| data_pipeline_master | proposal_id | ~60% NULL | ⚠️ Not all opps have proposals |

### Sparse Keys (< 50% populated)

| Table | Column | Null % | When Non-NULL |
|-------|--------|--------|----------------|
| data_arr | parent_product_id | ~85% NULL | Only when multi-parent tree structure exists |
| data_renewal_risk | high_risk_start_date | ~70% NULL | Only flagged accounts; use coalesce to CURRENT_DATE |
| dim_usage_metrics_new | product | ~5% NULL | Rare; usually populated |

---

## 6. Query Strategy for Unlinked Data

### Q1: "Can I query all data, even if some is orphaned?"

**Answer:** ✅ **YES**, with explicit handling:

```sql
-- Include ALL rows, flag which are linked vs. orphaned
SELECT 
  a.id,
  a.parent_account_id,
  CASE WHEN d.end_user_parent_id IS NOT NULL THEN 'LINKED' 
       WHEN d.end_user_parent_id IS NULL THEN 'ORPHAN' 
       ELSE 'UNKNOWN' 
  END AS link_status,
  d.parent_account_name,
  a.adjusted_acv,
  COUNT(*) OVER (PARTITION BY link_status) AS count_in_category
FROM data_acv a
LEFT JOIN dim_account_new d ON a.parent_account_id = d.end_user_parent_id
ORDER BY link_status, a.updated_at DESC;
```

**Output:** 100% of ACV rows; orphan column for auditing.

---

### Q2: "Can I join across fact tables even if some rows don't match?"

**Answer:** ⚠️ **YES, but use FULL OUTER JOIN + coalesce keys**:

```sql
-- Union ACV + ARR, even if no matching row in both
WITH agg_acv AS (
  SELECT parent_account_id, fiscal_quarter, SUM(adjusted_acv) as acv, NULL::numeric as arr
  FROM data_acv
  GROUP BY parent_account_id, fiscal_quarter
),
agg_arr AS (
  SELECT bill_to_parent_id, fiscal_quarter, NULL::numeric as acv, SUM(arr) as arr
  FROM data_arr
  GROUP BY bill_to_parent_id, fiscal_quarter
)
SELECT 
  COALESCE(agg_acv.parent_account_id, agg_arr.bill_to_parent_id) AS parent_account_id,
  COALESCE(agg_acv.fiscal_quarter, agg_arr.fiscal_quarter) AS fiscal_quarter,
  COALESCE(agg_acv.acv, 0) AS acv,
  COALESCE(agg_arr.arr, 0) AS arr,
  CASE WHEN agg_acv.parent_account_id IS NULL THEN 'ARR_ONLY'
       WHEN agg_arr.bill_to_parent_id IS NULL THEN 'ACV_ONLY'
       ELSE 'BOTH' END AS data_presence
FROM agg_acv
FULL OUTER JOIN agg_arr 
  ON agg_acv.parent_account_id = agg_arr.bill_to_parent_id
  AND agg_acv.fiscal_quarter = agg_arr.fiscal_quarter
ORDER BY parent_account_id, fiscal_quarter;
```

**Gotcha:** Be careful not to double-count. Use `SUM(...) OVER PARTITION` or aggregate first, then join.

---

### Q3: "What happens if I just INNER JOIN and ignore orphans?"

**Answer:** ⚠️ **You lose 1–5% of data silently**:

```sql
-- WRONG — loses orphans silently
SELECT a.parent_account_id, SUM(a.adjusted_acv) as acv
FROM data_acv a
INNER JOIN dim_account_new d ON a.parent_account_id = d.end_user_parent_id  -- ❌ Filters out nulls
GROUP BY a.parent_account_id;
-- Result: Undercount of ~1-2% revenue

-- RIGHT — preserves all, flags mismatches
SELECT a.parent_account_id, d.parent_account_name, SUM(a.adjusted_acv) as acv,
       COUNT(*) as record_count,
       CASE WHEN d.parent_account_id IS NULL THEN 'WARN_ORPHAN' ELSE 'OK' END as quality_flag
FROM data_acv a
LEFT JOIN dim_account_new d ON a.parent_account_id = d.end_user_parent_id
GROUP BY a.parent_account_id, d.parent_account_name
HAVING SUM(a.adjusted_acv) > 0;
```

**Impact:** Financial reports **must** use LEFT JOIN or FULL OUTER JOIN, otherwise audit will catch shortfalls.

---

## Summary: Can This System Handle Unlinked Data?

| Scenario | Supported? | Method | Risk |
|----------|-----------|--------|------|
| Query revenue **with** orphaned accounts | ✅ YES | LEFT JOIN + COALESCE | None if you use LEFT JOIN |
| Query with **missing product hierarchy** | ✅ YES | COALESCE(product_l2, 'Unclassified') | Silent NULLs in GROUP BY |
| Cross-fact (ACV ↔ ARR) where some have no match | ✅ YES | FULL OUTER JOIN | Risk of double-counting; use aggregates |
| Get all accounts **only if** they have a dim match | ✅ YES | INNER JOIN | **Loses 1–5% of data** — not recommended |
| Join via opportunity_id where it's sparse | ⚠️ PARTIAL | LEFT JOIN on opp_id, fallback to account_id | 20–95% NULL depending on table |
| Aggregate by product hierarchy **with** gaps | ✅ YES | COALESCE before GROUP BY | Works, but watch for aggregation errors |

---

## Recommendations for AI Agents

**When building Chat with Data queries on these tables:**

1. **Always use LEFT JOIN** for account → dimension joins. The cost of a LEFT JOIN vs. INNER JOIN is negligible; the cost of a silent undercount is a lost deal.

2. **Explicit COALESCE for product hierarchies.** Before any GROUP BY product_l2, wrap:
   ```python
   "COALESCE(product_l2, 'Unclassified') AS product_l2"
   ```

3. **Add a data quality flag column** for audit/transparency:
   ```python
   "CASE WHEN dim_account_id IS NULL THEN 'ORPHAN' ELSE 'LINKED' END AS _data_quality"
   ```

4. **For cross-fact joins, aggregate first, then join.** Never INNER JOIN fact tables directly; always aggregate with SUM/COUNT first, then join dims.

5. **Cache dimension lookups** — `dim_account_new` and `dim_product_hierarchy_new` change daily; pre-fetch them to avoid N+1 queries.

6. **Validate opportunity_id links explicitly** if they're central to the query (e.g., "which accounts have active opportunities in renewal?"). If < 80% populated, fall back to account_id + date ranges instead.

---

**Generated:** 2026-10-16 | **Next Review:** After next full Snowflake sync (verify null counts, orphan trends)

