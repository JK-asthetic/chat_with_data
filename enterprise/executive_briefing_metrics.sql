-- =====================================================================================
-- EXECUTIVE BRIEFING  -  every metric SQL (PostgreSQL), grouped by dashboard element
-- Page: ExecutiveBriefingPage.tsx -> v2/ExecutiveBriefingPageV2.tsx
-- Defaults used: quarter 'FY 2027 Q1' (latest complete); pipeline 'FY 2027 Q2'; churn risk 'FY 2027 Q3' (snapshot qtr + 2)
-- Verified: every statement below was executed against local pop_db and returned rows.
-- Not applied: persona/product-scope filters, geo filters, exclude-Standard toggle.
--
-- INDEX
--  A. KPI TILES (MetricGrid)       01 Exit ARR | 02 N/U ACV + Logos | 03 Churn + Swap | 04 NNACV | 05 Plan %
--                                  06 Open Pipeline | 07 Churn Risk | 08 Quantity | 09 ARPU | 10 Attach Rate | 11 Undeployed
--                                  each as  _product / _account / _parent  where the source table supports it
--  B. TREND CARDS (TrendCard)      12 Exit ARR | 13 N/U ACV | 14 NNACV     (trailing 8 quarters)
--  C. TOP LISTS (TopListsSection)  15 New Logos | 16 Churn | 17 Open Deals | 18 Lost Deals
--  D. PLAN                         19 NNACV plan L1/L2/L3  (05 is the per-product Plan %)
--  E. PIPELINE (PipelineCoverageCard)  20 by stage | 21 stage deals
--
-- NOTES
--  * data_arr: ONE row per account per fiscal month -> always pin the quarter's MAX(fiscal_month_end_date).
--  * data_inc_arr: every row repeats per aggregation_level -> always pin 'Level L3'.  account_id is 100% NULL there (parent/product only).
--  * data_acv.parent_account_id is empty -> use end_user_parent_id / end_user_parent_name.
--  * dim_account has a parent for only ~12k of 188k accounts -> parent cuts derive the map from data_arr.
--  * Quantity: use the level-matched column (L1 -> product_l1_qty); never mix levels in one sum.
-- =====================================================================================

-- ################ A. KPI TILES ################
-- ===== 01_exit_arr_account
SELECT r.account_id, d.account_name, r.product_l1, ROUND(SUM(r.arr)) AS exit_arr
FROM data_arr r LEFT JOIN dim_account d ON d.account_id = r.account_id
WHERE r.fiscal_quarter = 'FY 2027 Q1' AND r.fiscal_month_end_date = (SELECT MAX(fiscal_month_end_date) FROM data_arr WHERE fiscal_quarter = 'FY 2027 Q1')
GROUP BY r.account_id, d.account_name, r.product_l1 ORDER BY exit_arr DESC NULLS LAST;
-- ===== 01_exit_arr_parent
SELECT r.end_user_parent_id, r.end_user_parent_name, ROUND(SUM(r.arr)) AS exit_arr
FROM data_arr r 
WHERE r.fiscal_quarter = 'FY 2027 Q1' AND r.fiscal_month_end_date = (SELECT MAX(fiscal_month_end_date) FROM data_arr WHERE fiscal_quarter = 'FY 2027 Q1')
GROUP BY r.end_user_parent_id, r.end_user_parent_name ORDER BY exit_arr DESC NULLS LAST;
-- ===== 01_exit_arr_product
SELECT r.product_l1, ROUND(SUM(r.arr)) AS exit_arr
FROM data_arr r 
WHERE r.fiscal_quarter = 'FY 2027 Q1' AND r.fiscal_month_end_date = (SELECT MAX(fiscal_month_end_date) FROM data_arr WHERE fiscal_quarter = 'FY 2027 Q1')
GROUP BY r.product_l1 ORDER BY exit_arr DESC NULLS LAST;
-- ===== 02_nu_acv_account
SELECT a.account_id, a.account_name, a.product_l1, ROUND(SUM(a.adjusted_acv)) AS nu_acv,
       COUNT(DISTINCT a.account_id) FILTER (WHERE a.adjusted_acv > 0) AS logos
FROM data_acv a
WHERE a.fiscal_quarter = 'FY 2027 Q1' AND lower(replace(replace(trim(a.carve_split_type),'-','_'),' ','_')) IN
      ('new_logo','new_cust','new_customer','newlogo','new_to_product','ntp',
       'new_l1_product','new_l2_product','new_l3_product','new_l4_product','new_l5_product',
       'new_to_l1','new_to_l2','new_to_l3','new_to_l4','new_to_l5','upsell')
GROUP BY a.account_id, a.account_name, a.product_l1 ORDER BY nu_acv DESC NULLS LAST;
-- ===== 02_nu_acv_parent
SELECT a.end_user_parent_id, a.end_user_parent_name, ROUND(SUM(a.adjusted_acv)) AS nu_acv,
       COUNT(DISTINCT a.account_id) FILTER (WHERE a.adjusted_acv > 0) AS logos
FROM data_acv a
WHERE a.fiscal_quarter = 'FY 2027 Q1' AND lower(replace(replace(trim(a.carve_split_type),'-','_'),' ','_')) IN
      ('new_logo','new_cust','new_customer','newlogo','new_to_product','ntp',
       'new_l1_product','new_l2_product','new_l3_product','new_l4_product','new_l5_product',
       'new_to_l1','new_to_l2','new_to_l3','new_to_l4','new_to_l5','upsell')
GROUP BY a.end_user_parent_id, a.end_user_parent_name ORDER BY nu_acv DESC NULLS LAST;
-- ===== 02_nu_acv_product
SELECT a.product_l1, ROUND(SUM(a.adjusted_acv)) AS nu_acv,
       COUNT(DISTINCT a.account_id) FILTER (WHERE a.adjusted_acv > 0) AS logos
FROM data_acv a
WHERE a.fiscal_quarter = 'FY 2027 Q1' AND lower(replace(replace(trim(a.carve_split_type),'-','_'),' ','_')) IN
      ('new_logo','new_cust','new_customer','newlogo','new_to_product','ntp',
       'new_l1_product','new_l2_product','new_l3_product','new_l4_product','new_l5_product',
       'new_to_l1','new_to_l2','new_to_l3','new_to_l4','new_to_l5','upsell')
GROUP BY a.product_l1 ORDER BY nu_acv DESC NULLS LAST;
-- ===== 03_churn_swap_parent
SELECT i.end_user_parent_id, i.end_user_parent_name,
       ROUND(-SUM(i.downsell) FILTER (WHERE i.comment IN ('Customer Churn','ARR Churn'))) AS churn,   -- positive loss
       ROUND(SUM(i.swap_positive + i.swap_negative))                                       AS swap
FROM data_inc_arr i
WHERE i.aggregation_level = 'Level L3' AND i.fiscal_quarter = 'FY 2027 Q1'
GROUP BY i.end_user_parent_id, i.end_user_parent_name ORDER BY churn DESC NULLS LAST;
-- ===== 03_churn_swap_product
SELECT i.product_l1,
       ROUND(-SUM(i.downsell) FILTER (WHERE i.comment IN ('Customer Churn','ARR Churn'))) AS churn,   -- positive loss
       ROUND(SUM(i.swap_positive + i.swap_negative))                                       AS swap
FROM data_inc_arr i
WHERE i.aggregation_level = 'Level L3' AND i.fiscal_quarter = 'FY 2027 Q1'
GROUP BY i.product_l1 ORDER BY churn DESC NULLS LAST;
-- ===== 04_nnacv_parent
WITH nu AS (SELECT a.end_user_parent_id AS k, SUM(a.adjusted_acv) AS nu_acv
            FROM data_acv a WHERE a.fiscal_quarter = 'FY 2027 Q1' AND lower(replace(replace(trim(a.carve_split_type),'-','_'),' ','_')) IN
      ('new_logo','new_cust','new_customer','newlogo','new_to_product','ntp',
       'new_l1_product','new_l2_product','new_l3_product','new_l4_product','new_l5_product',
       'new_to_l1','new_to_l2','new_to_l3','new_to_l4','new_to_l5','upsell') GROUP BY 1),
inc AS (SELECT i.end_user_parent_id AS k,
               COALESCE(SUM(i.downsell) FILTER (WHERE i.comment IN ('Customer Churn','ARR Churn')),0) AS churn_neg,
               COALESCE(SUM(i.swap_positive + i.swap_negative),0) AS swap
        FROM data_inc_arr i WHERE i.aggregation_level = 'Level L3' AND i.fiscal_quarter = 'FY 2027 Q1' GROUP BY 1)
SELECT COALESCE(nu.k, inc.k) AS parent_id,
       ROUND(COALESCE(nu.nu_acv,0) + COALESCE(inc.churn_neg,0) + COALESCE(inc.swap,0)) AS nnacv   -- N/U ACV + Churn(neg) + Swap
FROM nu FULL JOIN inc ON nu.k = inc.k
ORDER BY nnacv DESC NULLS LAST;
-- ===== 04_nnacv_product
WITH nu AS (SELECT a.product_l1 AS k, SUM(a.adjusted_acv) AS nu_acv
            FROM data_acv a WHERE a.fiscal_quarter = 'FY 2027 Q1' AND lower(replace(replace(trim(a.carve_split_type),'-','_'),' ','_')) IN
      ('new_logo','new_cust','new_customer','newlogo','new_to_product','ntp',
       'new_l1_product','new_l2_product','new_l3_product','new_l4_product','new_l5_product',
       'new_to_l1','new_to_l2','new_to_l3','new_to_l4','new_to_l5','upsell') GROUP BY 1),
inc AS (SELECT i.product_l1 AS k,
               COALESCE(SUM(i.downsell) FILTER (WHERE i.comment IN ('Customer Churn','ARR Churn')),0) AS churn_neg,
               COALESCE(SUM(i.swap_positive + i.swap_negative),0) AS swap
        FROM data_inc_arr i WHERE i.aggregation_level = 'Level L3' AND i.fiscal_quarter = 'FY 2027 Q1' GROUP BY 1)
SELECT COALESCE(nu.k, inc.k) AS product_l1,
       ROUND(COALESCE(nu.nu_acv,0) + COALESCE(inc.churn_neg,0) + COALESCE(inc.swap,0)) AS nnacv   -- N/U ACV + Churn(neg) + Swap
FROM nu FULL JOIN inc ON nu.k = inc.k
ORDER BY nnacv DESC NULLS LAST;
-- ===== 05_plan_pct_product
SELECT t.fy27_product_l1 AS product_l1,
       SUM(t.target) FILTER (WHERE t.target_type='ACV')          - SUM(t.target) FILTER (WHERE t.target_type='Churn')        AS plan,
       SUM(t.target) FILTER (WHERE t.target_type='ACV Actual')   - GREATEST(SUM(t.target) FILTER (WHERE t.target_type='Churn Actual'),
                                                                            SUM(t.target) FILTER (WHERE t.target_type='Churn')) AS actual,
       ROUND(100 * (SUM(t.target) FILTER (WHERE t.target_type='ACV Actual') - GREATEST(SUM(t.target) FILTER (WHERE t.target_type='Churn Actual'), SUM(t.target) FILTER (WHERE t.target_type='Churn')))
             / NULLIF(SUM(t.target) FILTER (WHERE t.target_type='ACV') - SUM(t.target) FILTER (WHERE t.target_type='Churn'),0)) AS plan_pct
FROM data_nacv_target t WHERE t.fiscal_quarter = 'FY 2027 Q1' GROUP BY 1 ORDER BY plan DESC NULLS LAST;
-- ===== 06_open_pipeline_account
SELECT p.account_id, d.account_name, p.product_l1, p.opp_close_qtr, ROUND(SUM(p.pipeline_acv)) AS open_pipeline_acv
FROM data_pippeline_curr p LEFT JOIN dim_account d ON d.account_id = p.account_id
WHERE p.pipeline_type_group = 'Open Pipeline' AND p.stage NOT IN ('6 - Closed Won','7 - Closed Lost') AND p.opp_close_qtr = 'FY 2027 Q2'
GROUP BY p.account_id, d.account_name, p.product_l1, p.opp_close_qtr ORDER BY open_pipeline_acv DESC NULLS LAST;
-- ===== 06_open_pipeline_parent
SELECT d.end_user_parent_id, d.end_user_parent_name, p.opp_close_qtr, ROUND(SUM(p.pipeline_acv)) AS open_pipeline_acv
FROM data_pippeline_curr p LEFT JOIN (SELECT DISTINCT ON (account_id) account_id, end_user_parent_id, end_user_parent_name
        FROM data_arr WHERE end_user_parent_id IS NOT NULL
        ORDER BY account_id, fiscal_month_end_date DESC) d ON d.account_id = p.account_id
WHERE p.pipeline_type_group = 'Open Pipeline' AND p.stage NOT IN ('6 - Closed Won','7 - Closed Lost') AND p.opp_close_qtr = 'FY 2027 Q2'
GROUP BY d.end_user_parent_id, d.end_user_parent_name, p.opp_close_qtr ORDER BY open_pipeline_acv DESC NULLS LAST;
-- ===== 06_open_pipeline_product
SELECT p.product_l1, p.opp_close_qtr, ROUND(SUM(p.pipeline_acv)) AS open_pipeline_acv
FROM data_pippeline_curr p 
WHERE p.pipeline_type_group = 'Open Pipeline' AND p.stage NOT IN ('6 - Closed Won','7 - Closed Lost') AND p.opp_close_qtr = 'FY 2027 Q2'
GROUP BY p.product_l1, p.opp_close_qtr ORDER BY open_pipeline_acv DESC NULLS LAST;
-- ===== 07_churn_risk_account
SELECT r.account_id, d.account_name, ROUND(SUM(r.renewal_arr)) AS renewal_arr_at_risk_window
FROM data_renewal_risk r LEFT JOIN dim_account d ON d.account_id = r.account_id
WHERE r.max_fiscal_month_flag = 1 AND r.renewal_qtr = 'FY 2027 Q3'   -- snapshot quarter + 2
GROUP BY r.account_id, d.account_name ORDER BY 2 DESC NULLS LAST;
-- ===== 07_churn_risk_parent
SELECT d.end_user_parent_id, d.end_user_parent_name, ROUND(SUM(r.renewal_arr)) AS renewal_arr_at_risk_window
FROM data_renewal_risk r LEFT JOIN (SELECT DISTINCT ON (account_id) account_id, end_user_parent_id, end_user_parent_name
        FROM data_arr WHERE end_user_parent_id IS NOT NULL
        ORDER BY account_id, fiscal_month_end_date DESC) d ON d.account_id = r.account_id
WHERE r.max_fiscal_month_flag = 1 AND r.renewal_qtr = 'FY 2027 Q3'   -- snapshot quarter + 2
GROUP BY d.end_user_parent_id, d.end_user_parent_name ORDER BY 2 DESC NULLS LAST;
-- ===== 07_churn_risk_product
SELECT r.product_rl1, ROUND(SUM(r.renewal_arr)) AS renewal_arr_at_risk_window
FROM data_renewal_risk r 
WHERE r.max_fiscal_month_flag = 1 AND r.renewal_qtr = 'FY 2027 Q3'   -- snapshot quarter + 2
GROUP BY r.product_rl1 ORDER BY 2 DESC NULLS LAST;
-- ===== 08_quantity_account
SELECT q.account_id, q.account_name, q.product_l1, SUM(q.product_l1_qty) AS quantity     -- level-matched column: L1 -> product_l1_qty
FROM data_quantity q 
WHERE q.fiscal_quarter = 'FY 2027 Q1' AND q.fiscal_month = (SELECT MAX(fiscal_month) FROM data_quantity WHERE fiscal_quarter = 'FY 2027 Q1')
GROUP BY q.account_id, q.account_name, q.product_l1 ORDER BY quantity DESC NULLS LAST;
-- ===== 08_quantity_parent
SELECT d.end_user_parent_id, d.end_user_parent_name, SUM(q.product_l1_qty) AS quantity     -- level-matched column: L1 -> product_l1_qty
FROM data_quantity q LEFT JOIN (SELECT DISTINCT ON (account_id) account_id, end_user_parent_id, end_user_parent_name
        FROM data_arr WHERE end_user_parent_id IS NOT NULL
        ORDER BY account_id, fiscal_month_end_date DESC) d ON d.account_id = q.account_id
WHERE q.fiscal_quarter = 'FY 2027 Q1' AND q.fiscal_month = (SELECT MAX(fiscal_month) FROM data_quantity WHERE fiscal_quarter = 'FY 2027 Q1')
GROUP BY d.end_user_parent_id, d.end_user_parent_name ORDER BY quantity DESC NULLS LAST;
-- ===== 08_quantity_product
SELECT q.product_l1, SUM(q.product_l1_qty) AS quantity     -- level-matched column: L1 -> product_l1_qty
FROM data_quantity q 
WHERE q.fiscal_quarter = 'FY 2027 Q1' AND q.fiscal_month = (SELECT MAX(fiscal_month) FROM data_quantity WHERE fiscal_quarter = 'FY 2027 Q1')
GROUP BY q.product_l1 ORDER BY quantity DESC NULLS LAST;
-- ===== 09_arpu_account
WITH e AS (SELECT r.account_id AS k, SUM(r.arr) AS exit_arr FROM data_arr r
            WHERE r.fiscal_quarter = 'FY 2027 Q1' AND r.fiscal_month_end_date = (SELECT MAX(fiscal_month_end_date) FROM data_arr WHERE fiscal_quarter = 'FY 2027 Q1') GROUP BY 1),
qt AS (SELECT q.account_id AS k, SUM(q.product_l1_qty) AS qty FROM data_quantity q WHERE q.fiscal_quarter = 'FY 2027 Q1' AND q.fiscal_month = (SELECT MAX(fiscal_month) FROM data_quantity WHERE fiscal_quarter = 'FY 2027 Q1') GROUP BY 1)
SELECT e.k AS account_id, ROUND(e.exit_arr) AS exit_arr, qt.qty AS quantity, ROUND(e.exit_arr / NULLIF(qt.qty,0), 2) AS arpu
FROM e JOIN qt ON qt.k = e.k ORDER BY exit_arr DESC NULLS LAST;
-- ===== 09_arpu_product
WITH e AS (SELECT r.product_l1 AS k, SUM(r.arr) AS exit_arr FROM data_arr r
            WHERE r.fiscal_quarter = 'FY 2027 Q1' AND r.fiscal_month_end_date = (SELECT MAX(fiscal_month_end_date) FROM data_arr WHERE fiscal_quarter = 'FY 2027 Q1') GROUP BY 1),
qt AS (SELECT q.product_l1 AS k, SUM(q.product_l1_qty) AS qty FROM data_quantity q WHERE q.fiscal_quarter = 'FY 2027 Q1' AND q.fiscal_month = (SELECT MAX(fiscal_month) FROM data_quantity WHERE fiscal_quarter = 'FY 2027 Q1') GROUP BY 1)
SELECT e.k AS product_l1, ROUND(e.exit_arr) AS exit_arr, qt.qty AS quantity, ROUND(e.exit_arr / NULLIF(qt.qty,0), 2) AS arpu
FROM e JOIN qt ON qt.k = e.k ORDER BY exit_arr DESC NULLS LAST;
-- ===== 10_attach_rate_product
SELECT q.product_l1,
       COUNT(DISTINCT q.account_id) FILTER (WHERE q.product_l1_qty > 0) AS owners,
       (SELECT COUNT(DISTINCT account_id) FROM data_quantity q2 WHERE q2.fiscal_quarter='FY 2027 Q1'
          AND q2.fiscal_month=(SELECT MAX(fiscal_month) FROM data_quantity WHERE fiscal_quarter='FY 2027 Q1') AND q2.zs_users_qty > 0) AS all_customers,
       ROUND(100.0 * COUNT(DISTINCT q.account_id) FILTER (WHERE q.product_l1_qty > 0)
             / NULLIF((SELECT COUNT(DISTINCT account_id) FROM data_quantity q2 WHERE q2.fiscal_quarter='FY 2027 Q1'
          AND q2.fiscal_month=(SELECT MAX(fiscal_month) FROM data_quantity WHERE fiscal_quarter='FY 2027 Q1') AND q2.zs_users_qty > 0),0), 1) AS customer_attach_pct
FROM data_quantity q WHERE q.fiscal_quarter = 'FY 2027 Q1' AND q.fiscal_month = (SELECT MAX(fiscal_month) FROM data_quantity WHERE fiscal_quarter = 'FY 2027 Q1') GROUP BY q.product_l1 ORDER BY owners DESC;
-- ===== 11_undeployed_arr_product
SELECT t.product, ROUND(SUM(t.arr)) AS undeployed_arr
FROM t3_arr_detail t
WHERE t.fiscal_quarter = 'FY 2027 Q1' AND t.level = 'L3'
  AND t.configuration_status IS NOT NULL AND t.deployed_status IS NOT NULL
  AND lower(trim(t.deployed_status)) IN ('undeployed','not deployed','limited entitled')
GROUP BY t.product ORDER BY undeployed_arr DESC NULLS LAST;

-- ################ B-E. TRENDS / TOP LISTS / PLAN / PIPELINE ################
-- ===== 12_trend_exit_arr
-- Trend card "Exit ARR": trailing 8 quarters, latest month end of EACH quarter
WITH m AS (SELECT fiscal_quarter, MAX(fiscal_month_end_date) AS me FROM data_arr
           WHERE fiscal_quarter BETWEEN 'FY 2025 Q2' AND 'FY 2027 Q1' GROUP BY 1)
SELECT r.fiscal_quarter, ROUND(SUM(r.arr)) AS exit_arr
FROM data_arr r JOIN m ON m.fiscal_quarter = r.fiscal_quarter AND m.me = r.fiscal_month_end_date
GROUP BY r.fiscal_quarter ORDER BY r.fiscal_quarter;

-- ===== 13_trend_nu_acv
-- Trend card "N/U ACV": total = New Logo + New-to-Product + Upsell; new_biz = NL + NTP; existing = Upsell
SELECT a.fiscal_quarter,
       ROUND(SUM(a.adjusted_acv))                                         AS total_nu_acv,
       ROUND(SUM(a.adjusted_acv) FILTER (WHERE NOT (lower(trim(a.carve_split_type)) = 'upsell')))               AS new_biz,
       ROUND(SUM(a.adjusted_acv) FILTER (WHERE lower(trim(a.carve_split_type)) = 'upsell'))                     AS existing_upsell
FROM data_acv a
WHERE a.fiscal_quarter BETWEEN 'FY 2025 Q2' AND 'FY 2027 Q1' AND lower(replace(replace(trim(a.carve_split_type),'-','_'),' ','_')) IN
      ('new_logo','new_cust','new_customer','newlogo','new_to_product','ntp',
       'new_l1_product','new_l2_product','new_l3_product','new_l4_product','new_l5_product',
       'new_to_l1','new_to_l2','new_to_l3','new_to_l4','new_to_l5','upsell')
GROUP BY a.fiscal_quarter ORDER BY a.fiscal_quarter;

-- ===== 14_trend_nnacv
-- Trend card "NNACV": total = N/U ACV + churn(neg) + swap
WITH nu AS (SELECT a.fiscal_quarter AS q, SUM(a.adjusted_acv) AS nu_acv FROM data_acv a
            WHERE a.fiscal_quarter BETWEEN 'FY 2025 Q2' AND 'FY 2027 Q1' AND lower(replace(replace(trim(a.carve_split_type),'-','_'),' ','_')) IN
      ('new_logo','new_cust','new_customer','newlogo','new_to_product','ntp',
       'new_l1_product','new_l2_product','new_l3_product','new_l4_product','new_l5_product',
       'new_to_l1','new_to_l2','new_to_l3','new_to_l4','new_to_l5','upsell') GROUP BY 1),
inc AS (SELECT i.fiscal_quarter AS q,
               SUM(i.downsell) FILTER (WHERE i.comment IN ('Customer Churn','ARR Churn')) AS churn_neg,
               SUM(i.swap_positive + i.swap_negative)                                     AS swap
        FROM data_inc_arr i WHERE i.aggregation_level = 'Level L3' AND i.fiscal_quarter BETWEEN 'FY 2025 Q2' AND 'FY 2027 Q1' GROUP BY 1)
SELECT nu.q AS fiscal_quarter, ROUND(nu.nu_acv) AS new_biz, ROUND(inc.churn_neg) AS existing_churn, ROUND(inc.swap) AS swap,
       ROUND(nu.nu_acv + COALESCE(inc.churn_neg,0) + COALESCE(inc.swap,0)) AS nnacv
FROM nu LEFT JOIN inc ON inc.q = nu.q ORDER BY nu.q;

-- ===== 15_toplist_new_logos
-- Top lists 1/4: top accounts by New Logo ACV (renewals excluded)
SELECT a.account_id, a.account_name, ROUND(SUM(a.adjusted_acv)) AS new_logo_acv
FROM data_acv a
WHERE a.fiscal_quarter = 'FY 2027 Q1' AND lower(replace(replace(trim(a.carve_split_type),'-','_'),' ','_')) IN ('new_logo','new_cust','new_customer','newlogo')
GROUP BY a.account_id, a.account_name
HAVING SUM(a.adjusted_acv) > 0 ORDER BY new_logo_acv DESC LIMIT 10;

-- ===== 16_toplist_churn
-- Top lists 2/4: top churned parents (ARR Churn / Customer Churn; swaps excluded; M&A rows excluded)
SELECT i.end_user_parent_id, i.end_user_parent_name, ROUND(-SUM(i.downsell)) AS churn
FROM data_inc_arr i
WHERE i.fiscal_quarter = 'FY 2027 Q1' AND i.aggregation_level = 'Level L3'
  AND i.is_merger_demerger IS NULL AND i.end_user_parent_name IS NOT NULL
  AND i.downsell < 0
GROUP BY i.end_user_parent_id, i.end_user_parent_name ORDER BY churn DESC LIMIT 10;

-- ===== 17_toplist_open_deals
-- Top lists 3/4: open deals (still-open, closing in or before the quarter), merged per parent
SELECT COALESCE(d.end_user_parent_id, p.account_id)       AS parent_id,
       COALESCE(d.end_user_parent_name, d.account_name)   AS parent_name,
       ROUND(SUM(p.pipeline_acv))                          AS open_pipeline_acv
FROM data_pippeline_curr p LEFT JOIN dim_account d ON d.account_id = p.account_id
WHERE p.pipeline_acv IS NOT NULL AND p.account_id IS NOT NULL
  AND p.stage NOT IN ('6 - Closed Won','7 - Closed Lost') AND p.opp_close_qtr <= 'FY 2027 Q1'
GROUP BY 1, 2 ORDER BY open_pipeline_acv DESC LIMIT 10;

-- ===== 18_toplist_lost_deals
-- Top lists 4/4: lost deals closed in the quarter, merged per parent
SELECT COALESCE(d.end_user_parent_id, p.account_id)       AS parent_id,
       COALESCE(d.end_user_parent_name, d.account_name)   AS parent_name,
       ROUND(SUM(p.pipeline_acv))                          AS lost_acv
FROM data_pippeline_curr p LEFT JOIN dim_account d ON d.account_id = p.account_id
WHERE p.pipeline_acv IS NOT NULL AND p.account_id IS NOT NULL
  AND p.stage = '7 - Closed Lost' AND p.opp_close_qtr = 'FY 2027 Q1'
GROUP BY 1, 2 ORDER BY lost_acv DESC LIMIT 10;

-- ===== 19_plan_nnacv_l1_l2_l3
-- NNACV plan attainment at L1/L2/L3 (data_nacv_target only); actual uses max(Churn Actual, Churn) per node
SELECT fy27_product_l1 AS l1, fy27_product_l2 AS l2, fy27_product_l3 AS l3,
       plan, actual, ROUND(100 * actual / NULLIF(plan, 0)) AS plan_pct
FROM (
  SELECT t.fy27_product_l1, t.fy27_product_l2, t.fy27_product_l3,
         COALESCE(SUM(t.target) FILTER (WHERE t.target_type='ACV'),0) - COALESCE(SUM(t.target) FILTER (WHERE t.target_type='Churn'),0) AS plan,
         COALESCE(SUM(t.target) FILTER (WHERE t.target_type='ACV Actual'),0)
           - GREATEST(COALESCE(SUM(t.target) FILTER (WHERE t.target_type='Churn Actual'),0), COALESCE(SUM(t.target) FILTER (WHERE t.target_type='Churn'),0)) AS actual
  FROM data_nacv_target t WHERE t.fiscal_quarter = 'FY 2027 Q1'
  GROUP BY t.fy27_product_l1, t.fy27_product_l2, t.fy27_product_l3) x
WHERE plan > 0 ORDER BY plan DESC LIMIT 15;

-- ===== 20_pipeline_by_stage
-- Pipeline coverage card / stage panel: open pipeline closing in the quarter, 5A-5D collapsed into '5 - Procurement'
SELECT CASE WHEN p.stage ~ '^5[A-D]' THEN '5 - Procurement' ELSE p.stage END AS stage,
       ROUND(SUM(p.pipeline_acv)) AS pipeline_acv
FROM data_pippeline_curr p
WHERE p.pipeline_type_group = 'Open Pipeline' AND p.stage NOT IN ('6 - Closed Won','7 - Closed Lost')
  AND p.opp_close_qtr = 'FY 2027 Q2'
GROUP BY 1 ORDER BY 1;

-- ===== 21_pipeline_stage_deals
-- Click a stage: underlying deals (one per opportunity x product), top 200; example stage = 5 - Procurement
SELECT p.account_id, MAX(d.account_name) AS account_name, p.opportunity_id, MAX(p.opportunity_name) AS opp_name,
       p.product_l3, p.stage, p.opp_close_qtr, MAX(p.close_date) AS close_date, SUM(p.pipeline_acv) AS pipeline_acv
FROM data_pippeline_curr p LEFT JOIN dim_account d ON d.account_id = p.account_id
WHERE p.pipeline_type_group = 'Open Pipeline' AND p.stage NOT IN ('6 - Closed Won','7 - Closed Lost')
  AND p.opp_close_qtr = 'FY 2027 Q2' AND p.stage ~ '^5[A-D]'
GROUP BY p.account_id, p.opportunity_id, p.product_l3, p.stage, p.opp_close_qtr
ORDER BY pipeline_acv DESC NULLS LAST LIMIT 200;
