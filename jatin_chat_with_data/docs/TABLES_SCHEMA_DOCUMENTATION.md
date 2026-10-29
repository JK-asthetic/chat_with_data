# Database Schema & Column Documentation

**Generated:** 2026-10-16  
**Source:** PostgreSQL (pop_db) via Docker  
**Total Tables:** 26  
**Total Rows:** 15M+ (varies by table refresh cycle)

---

## Table Index

| Table | Type | Rows | Columns |
|-------|------|------|---------|
| `data_acv` | Fact | 390379 | 45 |
| `data_arr` | Fact | 1824577 | 84 |
| `data_churn_reason` | Fact | 21881 | 39 |
| `data_inc_arr` | Fact | 2192797 | 36 |
| `data_nacv_target` | Fact | 3924 | 9 |
| `data_p360_dash_mon` | Fact | 147982 | 950 |
| `data_pipeline_master` | Fact | 4684870 | 152 |
| `data_pippeline_curr` | Fact | 271381 | 69 |
| `data_qbr_incident_summary` | Fact | 74 | 13 |
| `data_qbr_incidents` | Fact | 829 | 21 |
| `data_quantity` | Fact | 4050640 | 36 |
| `data_renewal_risk` | Fact | 695276 | 46 |
| `data_whitespace` | Fact | 126792 | 68 |
| `deal_notes` | Fact | 0 | 6 |
| `digest_send_log` | Fact | 0 | 7 |
| `dim_account` | Dimension | 0 | 89 |
| `dim_account_new` | Dimension | 188387 | 89 |
| `dim_churn_signal_llm_payload` | Dimension | 11227 | 5 |
| `dim_churn_signal_metrics` | Dimension | 9870 | 110 |
| `dim_con_capability_fy26_curr` | Dimension | 0 | 20 |
| `dim_con_capability_fy26_curr_new` | Dimension | 3239 | 20 |
| `dim_product_hierarchy` | Dimension | 0 | 8 |
| `dim_product_hierarchy_new` | Dimension | 2177 | 8 |
| `dim_terminated_users` | Dimension | 0 | 4 |
| `dim_usage_metrics` | Dimension | 0 | 13 |
| `dim_usage_metrics_new` | Dimension | 15147 | 13 |

---

## data_acv

**Description:** ACV (Annual Contract Value) fact table - Contains transactional records for ACV by order, contract, and product hierarchy from Snowflake sync.

**Rows:** 390379  
**Columns:** 45

| Column | Data Type | Nullable |
|--------|-----------|----------|
| `id` | `integer` | NO |
| `end_user_parent_id` | `character varying` | YES |
| `end_user_id` | `character varying` | YES |
| `end_user_parent_name` | `character varying` | YES |
| `parent_account_id` | `character varying` | YES |
| `parent_account_name` | `character varying` | YES |
| `account_id` | `character varying` | YES |
| `account_name` | `character varying` | YES |
| `order_date` | `date` | YES |
| `contract_details_number` | `character varying` | YES |
| `raw_sku` | `character varying` | YES |
| `sku` | `character varying` | YES |
| `ns_sales_order_number` | `character varying` | YES |
| `fiscal_quarter` | `character varying` | YES |
| `fiscal_year` | `character varying` | YES |
| `sku_l1` | `character varying` | YES |
| `sku_l2` | `character varying` | YES |
| `sku_l3` | `character varying` | YES |
| `sku_l4` | `character varying` | YES |
| `product_l1` | `character varying` | YES |
| `product_l2` | `character varying` | YES |
| `product_l3` | `character varying` | YES |
| `product_l4` | `character varying` | YES |
| `product_l5` | `character varying` | YES |
| `product_rl1` | `character varying` | YES |
| `sku_variant` | `character varying` | YES |
| `contract_acv` | `numeric` | YES |
| `contract_tcv` | `numeric` | YES |
| `opportunity_id` | `character varying` | YES |
| `fiscal_quarter_end_date` | `date` | YES |
| `contract_split_type` | `character varying` | YES |
| `geo` | `character varying` | YES |
| `fp_a_parent_industry` | `character varying` | YES |
| `carve_split_type` | `character varying` | YES |
| `sku_split_type` | `character varying` | YES |
| `acv_splits` | `numeric` | YES |
| `tcv_splits` | `numeric` | YES |
| `src_refresh_timestamp` | `timestamp without time zone` | YES |
| `acv_carve` | `numeric` | YES |
| `adjustments` | `numeric` | YES |
| `prod_adjustment` | `numeric` | YES |
| `adjusted_acv` | `numeric` | YES |
| `trf_refresh_timestamp` | `timestamp without time zone` | YES |
| `created_at` | `timestamp without time zone` | NO |
| `updated_at` | `timestamp without time zone` | NO |

---

## data_arr

**Description:** ARR (Annual Recurring Revenue) fact table - Contains recurring revenue records aggregated by contract and product hierarchy.

**Rows:** 1824577  
**Columns:** 84

| Column | Data Type | Nullable |
|--------|-----------|----------|
| `id` | `integer` | NO |
| `fiscal_year` | `character varying` | YES |
| `fiscal_quarter` | `character varying` | YES |
| `fiscal_month` | `character varying` | YES |
| `fiscal_month_end_date` | `date` | YES |
| `sales_order_date` | `date` | YES |
| `sales_order_number` | `character varying` | YES |
| `sales_order_rma` | `character varying` | YES |
| `end_user_id` | `character varying` | YES |
| `end_user_name` | `character varying` | YES |
| `end_user` | `character varying` | YES |
| `bill_to_customer_id` | `character varying` | YES |
| `bill_to_customer_name` | `character varying` | YES |
| `bill_to_parent_id` | `character varying` | YES |
| `bill_to_parent_name` | `character varying` | YES |
| `rev_rec_start_date` | `timestamp without time zone` | YES |
| `start_date` | `timestamp without time zone` | YES |
| `rev_rec_end_date` | `timestamp without time zone` | YES |
| `end_date` | `timestamp without time zone` | YES |
| `company_size` | `numeric` | YES |
| `end_user_parent_id` | `character varying` | YES |
| `end_user_parent_name` | `character varying` | YES |
| `contract_details_number` | `character varying` | YES |
| `item_name` | `character varying` | YES |
| `end_user_parent_country` | `character varying` | YES |
| `end_user_parent_geo` | `character varying` | YES |
| `mrr_order_type` | `character varying` | YES |
| `customer_since` | `date` | YES |
| `opportunity_id` | `character varying` | YES |
| `oppor_created_date` | `timestamp without time zone` | YES |
| `oppor_close_date` | `timestamp without time zone` | YES |
| `account_id` | `character varying` | YES |
| `parent_account_id` | `character varying` | YES |
| `employees` | `numeric` | YES |
| `fp_a_parent_industry` | `character varying` | YES |
| `end_user_company_size` | `numeric` | YES |
| `market_segment` | `character varying` | YES |
| `top_level_parent_customer_since` | `timestamp without time zone` | YES |
| `product_id` | `character varying` | YES |
| `arr` | `numeric` | YES |
| `quantity` | `numeric` | YES |
| `qty` | `numeric` | YES |
| `cfy_geo` | `character varying` | YES |
| `cfy_area` | `character varying` | YES |
| `cfy_region` | `character varying` | YES |
| `cfy_sub_region` | `character varying` | YES |
| `sales_territory_name` | `character varying` | YES |
| `cfy_territory_type` | `character varying` | YES |
| `tier` | `character varying` | YES |
| `pricing_meter` | `character varying` | YES |
| `rev_model` | `character varying` | YES |
| `product_category` | `character varying` | YES |
| `sku_category_type` | `character varying` | YES |
| `sku_sub_category` | `character varying` | YES |
| `finance_sku_category` | `character varying` | YES |
| `carve_start_date` | `date` | YES |
| `carve_end_date` | `date` | YES |
| `carve_percentage` | `numeric` | YES |
| `is_recurring` | `character varying` | YES |
| `one_time_sku_flag` | `boolean` | YES |
| `product_l1` | `character varying` | YES |
| `product_l2` | `character varying` | YES |
| `product_l3` | `character varying` | YES |
| `product_l4` | `character varying` | YES |
| `product_l5` | `character varying` | YES |
| `sku_l1` | `character varying` | YES |
| `sku_l2` | `character varying` | YES |
| `sku_l3` | `character varying` | YES |
| `sku_l4` | `character varying` | YES |
| `sku_type` | `character varying` | YES |
| `sku_variant` | `character varying` | YES |
| `paid_pilot` | `character varying` | YES |
| `market_place` | `character varying` | YES |
| `reporting_sub_industry` | `character varying` | YES |
| `product_4_pillar` | `character varying` | YES |
| `product_8_pillar` | `character varying` | YES |
| `parent_product_id` | `numeric` | YES |
| `parent_product_name` | `character varying` | YES |
| `src_refresh_timestamp` | `timestamp without time zone` | YES |
| `source_bu` | `character varying` | YES |
| `data_origin` | `character varying` | YES |
| `trf_refresh_timestamp` | `timestamp without time zone` | YES |
| `created_at` | `timestamp without time zone` | NO |
| `updated_at` | `timestamp without time zone` | NO |

---

## data_churn_reason

**Description:** Churn reason dimension - Maps churn classifications, reasons, and categories for churn analysis.

**Rows:** 21881  
**Columns:** 39

| Column | Data Type | Nullable |
|--------|-----------|----------|
| `id` | `integer` | NO |
| `fiscal_quarter` | `character varying` | YES |
| `account_id` | `character varying` | YES |
| `account_name` | `character varying` | YES |
| `end_user_parent_id` | `character varying` | YES |
| `end_user_parent_name` | `character varying` | YES |
| `account_arr_pq` | `double precision` | YES |
| `account_arr_cq` | `double precision` | YES |
| `account_arr_change` | `double precision` | YES |
| `arr_change_bucket` | `character varying` | YES |
| `seats_pq` | `double precision` | YES |
| `seats_cq` | `double precision` | YES |
| `seats_change` | `double precision` | YES |
| `arpu_pq` | `double precision` | YES |
| `arpu_cq` | `double precision` | YES |
| `arpu_change` | `double precision` | YES |
| `top_sku_pq` | `character varying` | YES |
| `top_sku_cq` | `character varying` | YES |
| `moved_to_platform` | `character varying` | YES |
| `deployment_status` | `character varying` | YES |
| `geo` | `character varying` | YES |
| `area` | `character varying` | YES |
| `region` | `character varying` | YES |
| `tsm_assigned` | `character varying` | YES |
| `primary_tsm` | `character varying` | YES |
| `churn_category` | `character varying` | YES |
| `churn_reason` | `character varying` | YES |
| `primary_competitor` | `character varying` | YES |
| `churn_details` | `character varying` | YES |
| `created_at` | `timestamp without time zone` | NO |
| `updated_at` | `timestamp without time zone` | NO |
| `product_l3` | `character varying` | YES |
| `product_arr_pq` | `double precision` | YES |
| `product_arr_cq` | `double precision` | YES |
| `product_arr_change` | `double precision` | YES |
| `product_arr_bucket` | `character varying` | YES |
| `churn_severity` | `character varying` | YES |
| `churn_reason_detail` | `character varying` | YES |
| `package_change` | `character varying` | YES |

---

## data_inc_arr

**Description:** Incremental ARR fact table - Tracks incremental ARR changes, adjustments, and quarterly movements.

**Rows:** 2192797  
**Columns:** 36

| Column | Data Type | Nullable |
|--------|-----------|----------|
| `id` | `integer` | NO |
| `fiscal_quarter` | `character varying` | YES |
| `fiscal_quarter_end_date` | `date` | YES |
| `end_user_parent_id` | `character varying` | YES |
| `end_user_parent_name` | `character varying` | YES |
| `end_user_parent_geo` | `character varying` | YES |
| `cfy_geo` | `character varying` | YES |
| `cfy_area` | `character varying` | YES |
| `cfy_region` | `character varying` | YES |
| `cfy_sub_region` | `character varying` | YES |
| `cfy_territory_type` | `character varying` | YES |
| `fp_a_parent_industry` | `character varying` | YES |
| `market_segment` | `character varying` | YES |
| `customer_since` | `date` | YES |
| `product_l1` | `character varying` | YES |
| `product_l2` | `character varying` | YES |
| `product_l3` | `character varying` | YES |
| `product_4_pillar` | `character varying` | YES |
| `product_8_pillar` | `character varying` | YES |
| `aggregation_level` | `character varying` | YES |
| `prev_qtr_arr` | `numeric` | YES |
| `curr_qtr_arr` | `numeric` | YES |
| `arr_change` | `numeric` | YES |
| `downsell` | `numeric` | YES |
| `swap_positive` | `numeric` | YES |
| `swap_negative` | `numeric` | YES |
| `swap_impact` | `numeric` | YES |
| `source_bu` | `character varying` | YES |
| `data_origin` | `character varying` | YES |
| `comment` | `character varying` | YES |
| `is_merger_demerger` | `character varying` | YES |
| `src_refresh_timestamp` | `timestamp without time zone` | YES |
| `trf_refresh_timestamp` | `timestamp without time zone` | YES |
| `created_at` | `timestamp without time zone` | NO |
| `updated_at` | `timestamp without time zone` | NO |
| `account_id` | `character varying` | YES |

---

## data_nacv_target

**Description:** NACV (Net ACV) target table - Stores projected/target NACV values for planning and forecasting.

**Rows:** 3924  
**Columns:** 9

| Column | Data Type | Nullable |
|--------|-----------|----------|
| `id` | `integer` | NO |
| `fy27_product_l3` | `character varying` | YES |
| `fiscal_quarter` | `character varying` | YES |
| `target_type` | `character varying` | YES |
| `target` | `numeric` | YES |
| `created_at` | `timestamp without time zone` | NO |
| `updated_at` | `timestamp without time zone` | NO |
| `fy27_product_l1` | `character varying` | YES |
| `fy27_product_l2` | `character varying` | YES |

---


## data_pipeline_master

**Description:** Master pipeline fact table - Contains detailed pipeline opportunity records with stage, forecast, and probability data.

**Rows:** 4684870  
**Columns:** 152

| Column | Data Type | Nullable |
|--------|-----------|----------|
| `id` | `integer` | NO |
| `run_date` | `date` | YES |
| `run_day` | `character varying` | YES |
| `run_day_rounded` | `character varying` | YES |
| `is_latest` | `boolean` | YES |
| `fiscal_quarter` | `character varying` | YES |
| `fiscal_qtr_modified` | `character varying` | YES |
| `account_id` | `character varying` | YES |
| `account_name` | `character varying` | YES |
| `parent_account_id` | `character varying` | YES |
| `parent_account_name` | `character varying` | YES |
| `campaign_id` | `character varying` | YES |
| `campaign_name` | `character varying` | YES |
| `opportunity_id` | `character varying` | YES |
| `opportunity_name` | `character varying` | YES |
| `opportunity_name_latest` | `character varying` | YES |
| `duplicate_opportunity_id` | `character varying` | YES |
| `proposal_id` | `character varying` | YES |
| `proposal_name` | `character varying` | YES |
| `quote_number` | `character varying` | YES |
| `primary_quote_id` | `character varying` | YES |
| `is_primary_proposal` | `boolean` | YES |
| `price_list_applied` | `character varying` | YES |
| `quote_stage` | `character varying` | YES |
| `approval_status` | `character varying` | YES |
| `play_type` | `character varying` | YES |
| `play_sub_type` | `character varying` | YES |
| `product_sourced_date` | `date` | YES |
| `product_sourced_pipeline` | `boolean` | YES |
| `opportunity_type_original` | `character varying` | YES |
| `opportunity_type_arr` | `character varying` | YES |
| `opportunity_type_acv` | `character varying` | YES |
| `opportunity_type_product_l1_arr` | `character varying` | YES |
| `opportunity_type_product_l1_acv` | `character varying` | YES |
| `opportunity_type_product_l2_arr` | `character varying` | YES |
| `opportunity_type_product_l2_acv` | `character varying` | YES |
| `opportunity_type_product_l3_arr` | `character varying` | YES |
| `opportunity_type_product_l3_acv` | `character varying` | YES |
| `opportunity_type_product_l4_arr` | `character varying` | YES |
| `opportunity_type_product_l4_acv` | `character varying` | YES |
| `rep_forecast_category` | `character varying` | YES |
| `rep_forecast_category_original` | `character varying` | YES |
| `stage` | `character varying` | YES |
| `sub_stage` | `character varying` | YES |
| `grouped_stage` | `character varying` | YES |
| `close_date` | `date` | YES |
| `opp_close_quarter` | `character varying` | YES |
| `created_date` | `timestamp without time zone` | YES |
| `last_modified_date` | `timestamp without time zone` | YES |
| `item_name` | `character varying` | YES |
| `sku` | `character varying` | YES |
| `sku_variant` | `character varying` | YES |
| `sku_l1` | `character varying` | YES |
| `sku_l2` | `character varying` | YES |
| `sku_l3` | `character varying` | YES |
| `sku_l4` | `character varying` | YES |
| `product_l1` | `character varying` | YES |
| `product_l2` | `character varying` | YES |
| `product_l3` | `character varying` | YES |
| `product_l4` | `character varying` | YES |
| `product_rl1` | `character varying` | YES |
| `has_product_l4` | `boolean` | YES |
| `original_arr` | `numeric` | YES |
| `original_acv` | `numeric` | YES |
| `arr` | `numeric` | YES |
| `acv` | `numeric` | YES |
| `l1_non_weighted_arr` | `numeric` | YES |
| `l1_non_weighted_acv` | `numeric` | YES |
| `l1_arr` | `numeric` | YES |
| `l1_acv` | `numeric` | YES |
| `l2_non_weighted_arr` | `numeric` | YES |
| `l2_non_weighted_acv` | `numeric` | YES |
| `l2_arr` | `numeric` | YES |
| `l2_acv` | `numeric` | YES |
| `l3_non_weighted_arr` | `numeric` | YES |
| `l3_non_weighted_acv` | `numeric` | YES |
| `l3_arr` | `numeric` | YES |
| `l3_acv` | `numeric` | YES |
| `l4_non_weighted_arr` | `numeric` | YES |
| `l4_non_weighted_acv` | `numeric` | YES |
| `l4_arr` | `numeric` | YES |
| `l4_acv` | `numeric` | YES |
| `tcv` | `numeric` | YES |
| `quantity` | `numeric` | YES |
| `start_date` | `date` | YES |
| `end_date` | `date` | YES |
| `net_price` | `numeric` | YES |
| `net_pupy` | `numeric` | YES |
| `recommended_pupy` | `numeric` | YES |
| `net_variance` | `numeric` | YES |
| `avp_in_my_number` | `character varying` | YES |
| `geo_vp_in_my_number` | `character varying` | YES |
| `rd_in_my_number` | `character varying` | YES |
| `rvp_in_my_number` | `character varying` | YES |
| `gvp_in_my_number_pl` | `character varying` | YES |
| `avp_in_my_number_pl` | `character varying` | YES |
| `rd_in_my_number_pl` | `character varying` | YES |
| `rvp_in_my_number_pl` | `character varying` | YES |
| `forecast` | `character varying` | YES |
| `sales_forecast` | `character varying` | YES |
| `technical_validation_stage` | `character varying` | YES |
| `technical_validation_start_date` | `date` | YES |
| `technical_validation_end_date` | `date` | YES |
| `technical_validation_next_steps` | `character varying` | YES |
| `partner_program` | `character varying` | YES |
| `se_name` | `character varying` | YES |
| `business_champion_contact` | `character varying` | YES |
| `economic_buyer_contact` | `character varying` | YES |
| `service_owner_contact` | `character varying` | YES |
| `deal_reg_type` | `character varying` | YES |
| `next_step` | `character varying` | YES |
| `zia_competitors` | `character varying` | YES |
| `zpa_competitor` | `character varying` | YES |
| `other_competitors` | `character varying` | YES |
| `area` | `character varying` | YES |
| `geo` | `character varying` | YES |
| `fp_a_parent_industry` | `character varying` | YES |
| `market_segment` | `character varying` | YES |
| `region` | `character varying` | YES |
| `opportunity_account_manager_id` | `character varying` | YES |
| `rep_person_id` | `character varying` | YES |
| `sales_poc_name` | `character varying` | YES |
| `sales_poc_title` | `character varying` | YES |
| `sales_poc_email` | `character varying` | YES |
| `csm_name` | `character varying` | YES |
| `account_manager_name` | `character varying` | YES |
| `area_director_name` | `character varying` | YES |
| `regional_vp_name` | `character varying` | YES |
| `area_vp_name` | `character varying` | YES |
| `geo_vp_name` | `character varying` | YES |
| `pushed_from` | `character varying` | YES |
| `pushed_to` | `character varying` | YES |
| `end_date_pushed` | `date` | YES |
| `lost_date` | `date` | YES |
| `latest_run_date` | `boolean` | YES |
| `latest_renewal_opp` | `numeric` | YES |
| `latest_upsell_opp` | `numeric` | YES |
| `flexible_identifier` | `character varying` | YES |
| `primary_competitor` | `character varying` | YES |
| `incumbent` | `character varying` | YES |
| `risk_reason` | `character varying` | YES |
| `ci_confidence` | `character varying` | YES |
| `ci_team_member` | `character varying` | YES |
| `ci_summary_status` | `character varying` | YES |
| `ci_action_next_steps` | `character varying` | YES |
| `days_since_last_stage_update` | `numeric` | YES |
| `src_refresh_timestamp` | `timestamp without time zone` | YES |
| `quarter_difference` | `numeric` | YES |
| `trf_refresh_timestamp` | `timestamp without time zone` | YES |
| `created_at` | `timestamp without time zone` | NO |
| `updated_at` | `timestamp without time zone` | NO |
| `opp_close_qtr` | `character varying` | YES |

---

## data_pippeline_curr

**Description:** Current pipeline snapshot - Lightweight current pipeline state for dashboard refreshes (updated more frequently than master).

**Rows:** 271381  
**Columns:** 69

| Column | Data Type | Nullable |
|--------|-----------|----------|
| `id` | `integer` | NO |
| `pipeline_type` | `character varying` | YES |
| `pipeline_type_group` | `character varying` | YES |
| `pipeline_type_def` | `character varying` | YES |
| `opportunity_id` | `character varying` | YES |
| `sfdc_link` | `character varying` | YES |
| `opportunity_type` | `character varying` | YES |
| `days_since_last_stage_update` | `numeric` | YES |
| `rep_forecast_category` | `character varying` | YES |
| `close_date` | `date` | YES |
| `created_date` | `timestamp without time zone` | YES |
| `technical_validation_stage` | `character varying` | YES |
| `technical_validation_start_date` | `date` | YES |
| `technical_validation_end_date` | `date` | YES |
| `technical_validation_next_steps` | `character varying` | YES |
| `proposal_name` | `character varying` | YES |
| `quote_number` | `character varying` | YES |
| `product_l4` | `character varying` | YES |
| `sku` | `character varying` | YES |
| `pipeline_qty` | `double precision` | YES |
| `sales_forecast` | `character varying` | YES |
| `product_l1` | `character varying` | YES |
| `opportunity_type_product_l2_acv` | `character varying` | YES |
| `opportunity_type_product_l3_acv` | `character varying` | YES |
| `opportunity_type_product_l4_acv` | `character varying` | YES |
| `engagement_created_by` | `character varying` | YES |
| `engagement_request_note` | `character varying` | YES |
| `engagement_stage` | `character varying` | YES |
| `engagement_type` | `character varying` | YES |
| `engagement_last_modified_by` | `character varying` | YES |
| `engagement_notes_next_steps` | `character varying` | YES |
| `engagement_owner` | `character varying` | YES |
| `engagement_probability_of_quarter_close` | `character varying` | YES |
| `timeframe_for_the_engagement` | `character varying` | YES |
| `engagement_record_id` | `character varying` | YES |
| `engagement_created_date` | `timestamp without time zone` | YES |
| `engagement_owner_name` | `character varying` | YES |
| `sales_specialist_name` | `character varying` | YES |
| `sales_architect_name` | `character varying` | YES |
| `field_pm_name` | `character varying` | YES |
| `tag_member_name` | `character varying` | YES |
| `technical_outcome` | `character varying` | YES |
| `unquoted_column` | `character varying` | YES |
| `unquoted_value` | `character varying` | YES |
| `deal_acv` | `double precision` | YES |
| `account_id` | `character varying` | YES |
| `product_l2` | `character varying` | YES |
| `product_l3` | `character varying` | YES |
| `product_l2_map` | `character varying` | YES |
| `product_engagement_name` | `character varying` | YES |
| `stage` | `character varying` | YES |
| `opp_close_qtr` | `character varying` | YES |
| `pipeline_acv` | `double precision` | YES |
| `unquoted_acv` | `double precision` | YES |
| `special_terms` | `character varying` | YES |
| `opportunity_name` | `character varying` | YES |
| `opportunity_created_date` | `date` | YES |
| `product_added_date` | `date` | YES |
| `opportunity_age_days` | `numeric` | YES |
| `product_age_days` | `numeric` | YES |
| `product_age_days_bucket` | `character varying` | YES |
| `src_refresh_timestamp` | `timestamp without time zone` | YES |
| `trf_refresh_timestamp` | `timestamp without time zone` | YES |
| `sku_variant` | `character varying` | YES |
| `geo` | `character varying` | YES |
| `area` | `character varying` | YES |
| `region` | `character varying` | YES |
| `industry` | `character varying` | YES |
| `market_segment` | `character varying` | YES |

---

## data_qbr_incident_summary

**Description:** QBR incident summary - High-level summaries of critical incidents tracked in QBR reviews.

**Rows:** 74  
**Columns:** 13

| Column | Data Type | Nullable |
|--------|-----------|----------|
| `id` | `integer` | NO |
| `fiscal_quarter` | `character varying` | YES |
| `incident_product` | `character varying` | YES |
| `fy27_product_l3` | `character varying` | YES |
| `num_incidents` | `integer` | YES |
| `num_customers_impacted` | `integer` | YES |
| `arr_impacted` | `double precision` | YES |
| `num_customers_impacted_200k` | `integer` | YES |
| `arr_impacted_200k` | `double precision` | YES |
| `num_customer_impact_gt2` | `integer` | YES |
| `num_incidents_mttr_gt6h` | `integer` | YES |
| `created_at` | `timestamp without time zone` | NO |
| `updated_at` | `timestamp without time zone` | NO |

---

## data_qbr_incidents

**Description:** QBR incident details - Detailed incident tracking for quarterly business reviews.

**Rows:** 829  
**Columns:** 21

| Column | Data Type | Nullable |
|--------|-----------|----------|
| `id` | `integer` | NO |
| `incident_number` | `character varying` | YES |
| `incident_priority` | `character varying` | YES |
| `subject` | `character varying` | YES |
| `incident_status` | `character varying` | YES |
| `incident_product` | `character varying` | YES |
| `fy27_product_l3` | `character varying` | YES |
| `fy27_product_l1` | `character varying` | YES |
| `fy27_product_l2` | `character varying` | YES |
| `incident_owner` | `character varying` | YES |
| `created_date` | `timestamp without time zone` | YES |
| `resolution_date_time` | `timestamp without time zone` | YES |
| `cloud` | `character varying` | YES |
| `data_centre` | `character varying` | YES |
| `fiscal_quarter` | `character varying` | YES |
| `customers_impacted` | `text` | YES |
| `support_tickets` | `text` | YES |
| `is_repeat` | `boolean` | YES |
| `open_arr` | `double precision` | YES |
| `created_at` | `timestamp without time zone` | NO |
| `updated_at` | `timestamp without time zone` | NO |

---

## data_quantity

**Description:** Usage quantity fact table - Tracks product usage quantities, metrics, and consumption patterns.

**Rows:** 4050640  
**Columns:** 36

| Column | Data Type | Nullable |
|--------|-----------|----------|
| `id` | `integer` | NO |
| `fiscal_month` | `date` | YES |
| `account_id` | `character varying` | YES |
| `account_name` | `character varying` | YES |
| `fiscal_quarter` | `character varying` | YES |
| `fiscal_month_m_of_quarter` | `character varying` | YES |
| `product_4_pillar` | `character varying` | YES |
| `sku_variant` | `character varying` | YES |
| `sku_l1` | `character varying` | YES |
| `sku_l2` | `character varying` | YES |
| `sku_l3` | `character varying` | YES |
| `raw_sku` | `character varying` | YES |
| `product_l1` | `character varying` | YES |
| `product_l2` | `character varying` | YES |
| `product_l3` | `character varying` | YES |
| `product_l4` | `character varying` | YES |
| `product_l5` | `character varying` | YES |
| `product_rl1` | `character varying` | YES |
| `sku` | `character varying` | YES |
| `product_8_pillar` | `character varying` | YES |
| `arr` | `numeric` | YES |
| `product_l1_qty` | `numeric` | YES |
| `product_l2_qty` | `numeric` | YES |
| `product_l3_qty` | `numeric` | YES |
| `product_l4_qty` | `numeric` | YES |
| `product_l5_qty` | `numeric` | YES |
| `product_rl1_qty` | `numeric` | YES |
| `raw_qty` | `numeric` | YES |
| `product_8_pillar_qty` | `numeric` | YES |
| `zs_users_qty` | `numeric` | YES |
| `src_refresh_timestamp` | `timestamp without time zone` | YES |
| `qty_mon_flag` | `character varying` | YES |
| `key` | `character varying` | YES |
| `trf_refresh_timestamp` | `timestamp without time zone` | YES |
| `created_at` | `timestamp without time zone` | NO |
| `updated_at` | `timestamp without time zone` | NO |

---

## data_renewal_risk

**Description:** Renewal risk fact table - Scores and flags accounts at risk of non-renewal with reason codes.

**Rows:** 695276  
**Columns:** 46

| Column | Data Type | Nullable |
|--------|-----------|----------|
| `id` | `integer` | NO |
| `fiscal_month` | `date` | YES |
| `max_fiscal_month_flag` | `numeric` | YES |
| `account_id` | `character varying` | YES |
| `product_rl1` | `character varying` | YES |
| `capability` | `character varying` | YES |
| `opportunity_id` | `character varying` | YES |
| `opportunity_name` | `character varying` | YES |
| `zia_seats` | `double precision` | YES |
| `zpa_seats` | `double precision` | YES |
| `zdx_seats` | `double precision` | YES |
| `arr` | `double precision` | YES |
| `qty` | `double precision` | YES |
| `renewal_qtr` | `character varying` | YES |
| `high_risk_start_date` | `date` | YES |
| `good_signal` | `character varying` | YES |
| `bad_signal` | `character varying` | YES |
| `renewal_qtr_bucket` | `character varying` | YES |
| `acc_arr` | `double precision` | YES |
| `acc_arr_bucket` | `character varying` | YES |
| `renewal_arr` | `double precision` | YES |
| `renewal_arr_bucket` | `character varying` | YES |
| `acc_risk_reason` | `character varying` | YES |
| `prod_risk_reason` | `character varying` | YES |
| `tsm_defined_risk_reason` | `character varying` | YES |
| `competitive_risk` | `character varying` | YES |
| `renewal_team_defined_risk_reason` | `character varying` | YES |
| `tsm_sentiment_score` | `character varying` | YES |
| `zia_active_users_perc` | `double precision` | YES |
| `zpa_active_users_perc` | `double precision` | YES |
| `zdx_active_users_perc` | `double precision` | YES |
| `dlp_rules_active` | `double precision` | YES |
| `casb_apps_connected` | `double precision` | YES |
| `deployment_score` | `double precision` | YES |
| `deployment_score_colour` | `character varying` | YES |
| `movement_summary` | `character varying` | YES |
| `product_risk_level` | `character varying` | YES |
| `product_risk_level_l30d` | `character varying` | YES |
| `prod_score` | `numeric` | YES |
| `initial_score` | `numeric` | YES |
| `account_risk_level` | `character varying` | YES |
| `risk_summary` | `character varying` | YES |
| `src_refresh_timestamp` | `timestamp without time zone` | YES |
| `trf_refresh_timestamp` | `timestamp without time zone` | YES |
| `created_at` | `timestamp without time zone` | YES |
| `updated_at` | `timestamp without time zone` | YES |

---

## data_whitespace

**Description:** Whitespace opportunity table - Identifies expansion/upsell opportunities within existing customer accounts.

**Rows:** 126792  
**Columns:** 68

| Column | Data Type | Nullable |
|--------|-----------|----------|
| `id` | `integer` | NO |
| `account_id` | `character varying` | YES |
| `account_name` | `character varying` | YES |
| `product_l2` | `character varying` | YES |
| `fiscal_month` | `date` | YES |
| `target_sku` | `character varying` | YES |
| `zia_plt_sku` | `character varying` | YES |
| `zpa_plt_sku` | `character varying` | YES |
| `top_sku` | `character varying` | YES |
| `zs_users` | `double precision` | YES |
| `product_qty` | `double precision` | YES |
| `product_l2_qty` | `double precision` | YES |
| `arr` | `double precision` | YES |
| `prod_ws` | `double precision` | YES |
| `user_match` | `double precision` | YES |
| `employee_match` | `double precision` | YES |
| `next_renewal_quarter` | `character varying` | YES |
| `stage_act` | `character varying` | YES |
| `opp_close_qtr_act` | `character varying` | YES |
| `stage_l12` | `character varying` | YES |
| `opp_close_qtr_l12` | `character varying` | YES |
| `opportunity_id_act` | `character varying` | YES |
| `opp_acv_act` | `double precision` | YES |
| `opp_qty_act` | `double precision` | YES |
| `gap_opportunity_id` | `character varying` | YES |
| `gap_opp_close_qtr` | `character varying` | YES |
| `gap_opp_close_stage` | `character varying` | YES |
| `gap_zpa_acv` | `double precision` | YES |
| `gap_seats` | `double precision` | YES |
| `gap_seat_perc` | `double precision` | YES |
| `zpa_compare_seats` | `double precision` | YES |
| `weighted_score` | `numeric` | YES |
| `signals` | `character varying` | YES |
| `csm_name` | `character varying` | YES |
| `csm_email` | `character varying` | YES |
| `tam_name` | `character varying` | YES |
| `tam_email` | `character varying` | YES |
| `se_name` | `character varying` | YES |
| `se_email` | `character varying` | YES |
| `account_owner_name` | `character varying` | YES |
| `rd_name` | `character varying` | YES |
| `rd_email` | `character varying` | YES |
| `rsm_email` | `character varying` | YES |
| `gvp` | `character varying` | YES |
| `gvp_email` | `character varying` | YES |
| `avp` | `character varying` | YES |
| `avp_email` | `character varying` | YES |
| `rvp` | `character varying` | YES |
| `rvp_email` | `character varying` | YES |
| `lost_opportunity_id` | `character varying` | YES |
| `lost_close_date` | `date` | YES |
| `opp_close_qtr` | `character varying` | YES |
| `opportunity_type` | `character varying` | YES |
| `competitor` | `character varying` | YES |
| `churn_closed_lost_reason` | `character varying` | YES |
| `churn_closed_lost_details` | `character varying` | YES |
| `reason_categorisations` | `character varying` | YES |
| `engagement_stage` | `character varying` | YES |
| `product_engagement_name` | `character varying` | YES |
| `engagement_owner_name` | `character varying` | YES |
| `deployment_metric_name` | `character varying` | YES |
| `deployment_metric_value` | `double precision` | YES |
| `zia_active_user_perc` | `double precision` | YES |
| `zpa_active_user_perc` | `double precision` | YES |
| `zia_seats` | `double precision` | YES |
| `zpa_seats` | `double precision` | YES |
| `created_at` | `timestamp without time zone` | NO |
| `updated_at` | `timestamp without time zone` | NO |

---

## deal_notes

**Description:** Deal-level notes - Unstructured notes and comments attached to individual deals/opportunities.

**Rows:** 0  
**Columns:** 6

| Column | Data Type | Nullable |
|--------|-----------|----------|
| `id` | `integer` | NO |
| `opportunity_id` | `character varying` | NO |
| `content` | `text` | NO |
| `author_user_id` | `integer` | YES |
| `created_at` | `timestamp with time zone` | NO |
| `updated_at` | `timestamp with time zone` | NO |

---

## digest_send_log

**Description:** Digest delivery log - Audit trail of digest notifications sent to users.

**Rows:** 0  
**Columns:** 7

| Column | Data Type | Nullable |
|--------|-----------|----------|
| `id` | `integer` | NO |
| `user_id` | `integer` | NO |
| `agent_slug` | `character varying` | NO |
| `channel` | `character varying` | NO |
| `success` | `boolean` | NO |
| `error_message` | `text` | YES |
| `sent_at` | `timestamp with time zone` | NO |

---

## dim_account

**Description:** Account dimension (legacy) - Denormalized account attributes (hierarchies, industry, geo, size).

**Rows:** 0  
**Columns:** 89

| Column | Data Type | Nullable |
|--------|-----------|----------|
| `account_id` | `character varying` | NO |
| `account_name` | `character varying` | YES |
| `end_user_parent_id` | `character varying` | YES |
| `end_user_parent_name` | `character varying` | YES |
| `geo` | `character varying` | YES |
| `area` | `character varying` | YES |
| `region` | `character varying` | YES |
| `sub_region` | `character varying` | YES |
| `industry` | `character varying` | YES |
| `market_segment` | `character varying` | YES |
| `arr` | `numeric` | YES |
| `zs_users` | `integer` | YES |
| `renewal_date` | `date` | YES |
| `nps` | `numeric` | YES |
| `tsm` | `character varying` | YES |
| `tsm_email` | `character varying` | YES |
| `ae` | `character varying` | YES |
| `rd` | `character varying` | YES |
| `rd_email` | `character varying` | YES |
| `se` | `character varying` | YES |
| `se_email` | `character varying` | YES |
| `avp` | `character varying` | YES |
| `gvp` | `character varying` | YES |
| `customer_type` | `character varying` | YES |
| `synced_at` | `timestamp with time zone` | NO |
| `global_2000_rank` | `integer` | YES |
| `billing_country` | `character varying` | YES |
| `employees` | `integer` | YES |
| `zs_rank_by_arr` | `integer` | YES |
| `csm_name` | `character varying` | YES |
| `renewal_manager_name` | `character varying` | YES |
| `next_renewal_due_date` | `date` | YES |
| `first_purchase_date` | `date` | YES |
| `nps_12` | `numeric` | YES |
| `cap_status` | `character varying` | YES |
| `cap_level` | `character varying` | YES |
| `cap_created_date` | `date` | YES |
| `credit` | `numeric` | YES |
| `p1_l12m` | `integer` | YES |
| `cases_l12m` | `integer` | YES |
| `head_of_networking_des` | `character varying` | YES |
| `head_of_architecture_des` | `character varying` | YES |
| `head_of_security_des` | `character varying` | YES |
| `head_of_it_des` | `character varying` | YES |
| `net_meet` | `integer` | YES |
| `arch_meet` | `integer` | YES |
| `sec_meet` | `integer` | YES |
| `it_meet` | `integer` | YES |
| `zpa_qty` | `integer` | YES |
| `partner_group_account_name` | `character varying` | YES |
| `operational_hq_state` | `character varying` | YES |
| `operational_hq_country` | `character varying` | YES |
| `billing_street` | `character varying` | YES |
| `billing_city` | `character varying` | YES |
| `billing_postal_code` | `character varying` | YES |
| `billing_address` | `character varying` | YES |
| `ae_email` | `character varying` | YES |
| `avp_email` | `character varying` | YES |
| `gvp_email` | `character varying` | YES |
| `renewal_manager_email` | `character varying` | YES |
| `tsm_manager_email` | `character varying` | YES |
| `tsm_business_alignment_email` | `character varying` | YES |
| `se_director_email` | `character varying` | YES |
| `se_sr_director_email` | `character varying` | YES |
| `solution_architect_email` | `character varying` | YES |
| `channel_manager_email` | `character varying` | YES |
| `rvp_email` | `character varying` | YES |
| `sa_email` | `character varying` | YES |
| `sdo_email` | `character varying` | YES |
| `secops_tsm_email` | `character varying` | YES |
| `secondary_tsm_email` | `character varying` | YES |
| `zscaler_cxo_assigned_email` | `character varying` | YES |
| `zscaler_pm_assigned_email` | `character varying` | YES |
| `data_security_solutions_specialist` | `character varying` | YES |
| `data_security_solutions_specialist_email` | `character varying` | YES |
| `data_security_specialist_ae` | `character varying` | YES |
| `data_security_specialist_ae_email` | `character varying` | YES |
| `zt_branch_solutions_specialist` | `character varying` | YES |
| `zt_branch_solutions_specialist_email` | `character varying` | YES |
| `zt_branch_specialist_ae` | `character varying` | YES |
| `zt_branch_specialist_ae_email` | `character varying` | YES |
| `secops_solutions_specialist` | `character varying` | YES |
| `secops_solutions_specialist_email` | `character varying` | YES |
| `secops_specialist_ae` | `character varying` | YES |
| `secops_specialist_ae_email` | `character varying` | YES |
| `zt_cloud_solutions_specialist` | `character varying` | YES |
| `zt_cloud_solutions_specialist_email` | `character varying` | YES |
| `zt_cloud_specialist_ae` | `character varying` | YES |
| `zt_cloud_specialist_ae_email` | `character varying` | YES |

---

## dim_account_new

**Description:** Account dimension (current) - Current version of account master data with fresh hierarchies and attributes.

**Rows:** 188387  
**Columns:** 89

| Column | Data Type | Nullable |
|--------|-----------|----------|
| `account_id` | `character varying` | NO |
| `account_name` | `character varying` | YES |
| `end_user_parent_id` | `character varying` | YES |
| `end_user_parent_name` | `character varying` | YES |
| `geo` | `character varying` | YES |
| `area` | `character varying` | YES |
| `region` | `character varying` | YES |
| `sub_region` | `character varying` | YES |
| `industry` | `character varying` | YES |
| `market_segment` | `character varying` | YES |
| `arr` | `numeric` | YES |
| `zs_users` | `integer` | YES |
| `renewal_date` | `date` | YES |
| `nps` | `numeric` | YES |
| `tsm` | `character varying` | YES |
| `tsm_email` | `character varying` | YES |
| `ae` | `character varying` | YES |
| `rd` | `character varying` | YES |
| `rd_email` | `character varying` | YES |
| `se` | `character varying` | YES |
| `se_email` | `character varying` | YES |
| `avp` | `character varying` | YES |
| `gvp` | `character varying` | YES |
| `customer_type` | `character varying` | YES |
| `synced_at` | `timestamp with time zone` | NO |
| `global_2000_rank` | `integer` | YES |
| `billing_country` | `character varying` | YES |
| `employees` | `integer` | YES |
| `zs_rank_by_arr` | `integer` | YES |
| `csm_name` | `character varying` | YES |
| `renewal_manager_name` | `character varying` | YES |
| `next_renewal_due_date` | `date` | YES |
| `first_purchase_date` | `date` | YES |
| `nps_12` | `numeric` | YES |
| `cap_status` | `character varying` | YES |
| `cap_level` | `character varying` | YES |
| `cap_created_date` | `date` | YES |
| `credit` | `numeric` | YES |
| `p1_l12m` | `integer` | YES |
| `cases_l12m` | `integer` | YES |
| `head_of_networking_des` | `character varying` | YES |
| `head_of_architecture_des` | `character varying` | YES |
| `head_of_security_des` | `character varying` | YES |
| `head_of_it_des` | `character varying` | YES |
| `net_meet` | `integer` | YES |
| `arch_meet` | `integer` | YES |
| `sec_meet` | `integer` | YES |
| `it_meet` | `integer` | YES |
| `zpa_qty` | `integer` | YES |
| `partner_group_account_name` | `character varying` | YES |
| `operational_hq_state` | `character varying` | YES |
| `operational_hq_country` | `character varying` | YES |
| `billing_street` | `character varying` | YES |
| `billing_city` | `character varying` | YES |
| `billing_postal_code` | `character varying` | YES |
| `billing_address` | `character varying` | YES |
| `ae_email` | `character varying` | YES |
| `avp_email` | `character varying` | YES |
| `gvp_email` | `character varying` | YES |
| `renewal_manager_email` | `character varying` | YES |
| `tsm_manager_email` | `character varying` | YES |
| `tsm_business_alignment_email` | `character varying` | YES |
| `se_director_email` | `character varying` | YES |
| `se_sr_director_email` | `character varying` | YES |
| `solution_architect_email` | `character varying` | YES |
| `channel_manager_email` | `character varying` | YES |
| `rvp_email` | `character varying` | YES |
| `sa_email` | `character varying` | YES |
| `sdo_email` | `character varying` | YES |
| `secops_tsm_email` | `character varying` | YES |
| `secondary_tsm_email` | `character varying` | YES |
| `zscaler_cxo_assigned_email` | `character varying` | YES |
| `zscaler_pm_assigned_email` | `character varying` | YES |
| `data_security_solutions_specialist` | `character varying` | YES |
| `data_security_solutions_specialist_email` | `character varying` | YES |
| `data_security_specialist_ae` | `character varying` | YES |
| `data_security_specialist_ae_email` | `character varying` | YES |
| `zt_branch_solutions_specialist` | `character varying` | YES |
| `zt_branch_solutions_specialist_email` | `character varying` | YES |
| `zt_branch_specialist_ae` | `character varying` | YES |
| `zt_branch_specialist_ae_email` | `character varying` | YES |
| `secops_solutions_specialist` | `character varying` | YES |
| `secops_solutions_specialist_email` | `character varying` | YES |
| `secops_specialist_ae` | `character varying` | YES |
| `secops_specialist_ae_email` | `character varying` | YES |
| `zt_cloud_solutions_specialist` | `character varying` | YES |
| `zt_cloud_solutions_specialist_email` | `character varying` | YES |
| `zt_cloud_specialist_ae` | `character varying` | YES |
| `zt_cloud_specialist_ae_email` | `character varying` | YES |

---

## dim_churn_signal_llm_payload

**Description:** Churn signal LLM input - Curated data payloads fed to LLM models for churn prediction/analysis.

**Rows:** 11227  
**Columns:** 5

| Column | Data Type | Nullable |
|--------|-----------|----------|
| `id` | `integer` | NO |
| `account_id` | `character varying` | NO |
| `account_name` | `character varying` | YES |
| `llm_payload_text` | `text` | YES |
| `synced_at` | `timestamp with time zone` | NO |

---

## dim_churn_signal_metrics

**Description:** Churn signal metrics - Computed churn indicators, risk scores, and leading/lagging metric combinations.

**Rows:** 9870  
**Columns:** 110

| Column | Data Type | Nullable |
|--------|-----------|----------|
| `id` | `integer` | NO |
| `account_id` | `character varying` | NO |
| `account_name` | `character varying` | YES |
| `arr` | `numeric` | YES |
| `qty` | `numeric` | YES |
| `qty_prev_9_month` | `numeric` | YES |
| `first_purchase_date` | `date` | YES |
| `first_purchase_qtr` | `character varying` | YES |
| `next_renewal_date` | `date` | YES |
| `next_renewal_qtr` | `character varying` | YES |
| `zia_active_users` | `numeric` | YES |
| `zia_active_users_perc` | `numeric` | YES |
| `qualified_ssl_traffic_perc` | `numeric` | YES |
| `zia_traffic_per_user` | `numeric` | YES |
| `zia_traffic_gb` | `numeric` | YES |
| `zia_ssl_qualified_traffic_gb` | `numeric` | YES |
| `zia_qualified_total_traffic` | `numeric` | YES |
| `zpa_active_users` | `numeric` | YES |
| `zpa_active_users_perc` | `numeric` | YES |
| `zpa_app_segments_configured` | `numeric` | YES |
| `zpa_connectors_configured` | `numeric` | YES |
| `zpa_apps` | `numeric` | YES |
| `zpa_transactions_per_10k_users` | `numeric` | YES |
| `zpa_traffic_gb` | `numeric` | YES |
| `zdx_active_users` | `numeric` | YES |
| `zdx_active_users_perc` | `numeric` | YES |
| `zdx_probes_configured` | `numeric` | YES |
| `zdx_probes_active` | `numeric` | YES |
| `zdx_total_alerts_configured` | `numeric` | YES |
| `zdx_alerts_triggered_count` | `numeric` | YES |
| `probes_triggered_per_10k_users` | `numeric` | YES |
| `firewall_active_rule_count` | `numeric` | YES |
| `firewall_active_loc_count` | `numeric` | YES |
| `firewall_active_loc_perc` | `numeric` | YES |
| `firewall_auth_traffic_gb_perc` | `numeric` | YES |
| `firewall_non_web_traffic_gb_perc` | `numeric` | YES |
| `sandbox_active_rule_count` | `numeric` | YES |
| `sandbox_aiq_rules` | `numeric` | YES |
| `sandbox_unique_files_examined` | `numeric` | YES |
| `sandbox_unique_files_examined_per_10k_users` | `numeric` | YES |
| `sandbox_malicious_files_examined` | `numeric` | YES |
| `sandbox_malicious_files_examined_per_10k_users` | `numeric` | YES |
| `deception_decoys_configured` | `numeric` | YES |
| `deception_decoys_entitled` | `numeric` | YES |
| `deception_landmine_agents_configured` | `numeric` | YES |
| `deception_landmine_agents_entitled` | `numeric` | YES |
| `deception_all_attackers` | `numeric` | YES |
| `deception_internal_attackers` | `numeric` | YES |
| `deception_active_decoys_perc` | `numeric` | YES |
| `active_landmine_agents_perc` | `numeric` | YES |
| `total_attacks_per_10k_users` | `numeric` | YES |
| `deception_internal_attacks_per_10k_users` | `numeric` | YES |
| `casb_apps_connected` | `numeric` | YES |
| `casb_apps_connected_non_email` | `numeric` | YES |
| `casb_files_scanned` | `numeric` | YES |
| `casb_files_scanned_per_10k_users` | `numeric` | YES |
| `dlp_rules_active` | `numeric` | YES |
| `dlp_dict_configured` | `numeric` | YES |
| `dlp_edm_cell_indexed` | `numeric` | YES |
| `dlp_idm_docs_indexed` | `numeric` | YES |
| `delta_zia_active_users` | `numeric` | YES |
| `delta_zia_traffic_per_user` | `numeric` | YES |
| `delta_qualified_ssl_traffic_perc` | `numeric` | YES |
| `delta_zpa_apps` | `numeric` | YES |
| `delta_zpa_active_users` | `numeric` | YES |
| `delta_zdx_active_users` | `numeric` | YES |
| `delta_zdx_active_probes` | `numeric` | YES |
| `delta_firewall_active_rule_count` | `numeric` | YES |
| `delta_firewall_active_loc_count` | `numeric` | YES |
| `delta_sandbox_active_rule_count` | `numeric` | YES |
| `delta_sandbox_unique_files_examined_per_10k_users` | `numeric` | YES |
| `delta_deception_decoys_configured` | `numeric` | YES |
| `delta_deception_all_attackers` | `numeric` | YES |
| `delta_casb_app_connected` | `numeric` | YES |
| `delta_casb_files_scanned_per_10k_users` | `numeric` | YES |
| `delta_dlp_rules_active` | `numeric` | YES |
| `delta_dlp_edm_cell_indexed` | `numeric` | YES |
| `p1_tickets` | `numeric` | YES |
| `p2_tickets` | `numeric` | YES |
| `all_tickets` | `numeric` | YES |
| `avg_time_to_close_in_hrs` | `numeric` | YES |
| `nps_responses` | `numeric` | YES |
| `nps_score` | `numeric` | YES |
| `nps` | `numeric` | YES |
| `sentiment_score` | `numeric` | YES |
| `company_risk_score` | `numeric` | YES |
| `zia_active_users_l30_vs_l90` | `numeric` | YES |
| `zec_client_uninstall_rate` | `numeric` | YES |
| `customer_sentiment` | `character varying` | YES |
| `account_risk_type` | `character varying` | YES |
| `customer_lifecycle` | `character varying` | YES |
| `key_stake_interactions` | `numeric` | YES |
| `pm_interactions` | `numeric` | YES |
| `helpdesk_interactions` | `numeric` | YES |
| `total_interactions` | `numeric` | YES |
| `z_exec_interactions` | `numeric` | YES |
| `csm_interactions` | `numeric` | YES |
| `rsm_interactions` | `numeric` | YES |
| `se_interactions` | `numeric` | YES |
| `tam_interactions` | `numeric` | YES |
| `eb_interactions` | `numeric` | YES |
| `tech_workshop_timeline` | `character varying` | YES |
| `recent_arr_change_ratio_6m` | `numeric` | YES |
| `renewal_quarter_arr` | `numeric` | YES |
| `previous_quarter_arr` | `numeric` | YES |
| `last_renewal_arr_delta_pct` | `numeric` | YES |
| `account_open_er_gt_30d` | `numeric` | YES |
| `csm_tenure_days` | `numeric` | YES |
| `renewal_risk` | `character varying` | YES |
| `synced_at` | `timestamp with time zone` | NO |

---

## dim_con_capability_fy26_curr

**Description:** Capability coverage FY26 (legacy) - Capability-by-account matrix for FY26 coverage tracking.

**Rows:** 0  
**Columns:** 20

| Column | Data Type | Nullable |
|--------|-----------|----------|
| `id` | `integer` | NO |
| `sku` | `character varying` | YES |
| `sku_variant` | `character varying` | YES |
| `sku_concat` | `character varying` | YES |
| `section` | `character varying` | YES |
| `subsection` | `character varying` | YES |
| `component` | `character varying` | YES |
| `entitled` | `character varying` | YES |
| `added_later` | `character varying` | YES |
| `prefix_prod_type` | `character varying` | YES |
| `suffix_unit_of_measure` | `character varying` | YES |
| `user_threshold` | `character varying` | YES |
| `flag` | `character varying` | YES |
| `component_value_static` | `character varying` | YES |
| `ratio_qty_min` | `character varying` | YES |
| `ratio_qty_max` | `character varying` | YES |
| `basis_of_ratio_multiplier` | `character varying` | YES |
| `ratio_multiplier` | `character varying` | YES |
| `src_refresh_timestamp` | `timestamp without time zone` | YES |
| `synced_at` | `timestamp with time zone` | NO |

---

## dim_con_capability_fy26_curr_new

**Description:** Capability coverage FY26 (current) - Updated capability-by-account for current year planning.

**Rows:** 3239  
**Columns:** 20

| Column | Data Type | Nullable |
|--------|-----------|----------|
| `id` | `integer` | NO |
| `sku` | `character varying` | YES |
| `sku_variant` | `character varying` | YES |
| `sku_concat` | `character varying` | YES |
| `section` | `character varying` | YES |
| `subsection` | `character varying` | YES |
| `component` | `character varying` | YES |
| `entitled` | `character varying` | YES |
| `added_later` | `character varying` | YES |
| `prefix_prod_type` | `character varying` | YES |
| `suffix_unit_of_measure` | `character varying` | YES |
| `user_threshold` | `character varying` | YES |
| `flag` | `character varying` | YES |
| `component_value_static` | `character varying` | YES |
| `ratio_qty_min` | `character varying` | YES |
| `ratio_qty_max` | `character varying` | YES |
| `basis_of_ratio_multiplier` | `character varying` | YES |
| `ratio_multiplier` | `character varying` | YES |
| `src_refresh_timestamp` | `timestamp without time zone` | YES |
| `synced_at` | `timestamp with time zone` | NO |

---

## dim_product_hierarchy

**Description:** Product hierarchy (legacy) - Product master with L1-L5 classification (deprecated in favor of _new).

**Rows:** 0  
**Columns:** 8

| Column | Data Type | Nullable |
|--------|-----------|----------|
| `id` | `integer` | NO |
| `product_l1` | `character varying` | YES |
| `product_l2` | `character varying` | YES |
| `product_l3` | `character varying` | YES |
| `product_l4` | `character varying` | YES |
| `product_l5` | `character varying` | YES |
| `sku` | `character varying` | YES |
| `synced_at` | `timestamp with time zone` | NO |

---

## dim_product_hierarchy_new

**Description:** Product hierarchy (current) - Current product taxonomy with standard classifications.

**Rows:** 2177  
**Columns:** 8

| Column | Data Type | Nullable |
|--------|-----------|----------|
| `id` | `integer` | NO |
| `product_l1` | `character varying` | YES |
| `product_l2` | `character varying` | YES |
| `product_l3` | `character varying` | YES |
| `product_l4` | `character varying` | YES |
| `product_l5` | `character varying` | YES |
| `sku` | `character varying` | YES |
| `synced_at` | `timestamp with time zone` | NO |

---

## dim_terminated_users

**Description:** Terminated user list - Users marked as inactive/terminated for access/visibility filtering.

**Rows:** 0  
**Columns:** 4

| Column | Data Type | Nullable |
|--------|-----------|----------|
| `first_name` | `text` | YES |
| `last_name` | `text` | YES |
| `email` | `text` | YES |
| `department_name` | `text` | YES |

---

## dim_usage_metrics

**Description:** Usage metrics dimension (legacy) - Pre-computed usage KPIs and consumption buckets.

**Rows:** 0  
**Columns:** 13

| Column | Data Type | Nullable |
|--------|-----------|----------|
| `id` | `integer` | NO |
| `fiscal_year` | `character varying` | YES |
| `fiscal_quarter` | `character varying` | YES |
| `fiscal_month` | `character varying` | YES |
| `product` | `character varying` | YES |
| `level` | `character varying` | YES |
| `capability` | `character varying` | YES |
| `metric` | `character varying` | YES |
| `metric_value` | `numeric` | YES |
| `metric_definition` | `character varying` | YES |
| `is_latest` | `boolean` | YES |
| `has_issues` | `boolean` | YES |
| `synced_at` | `timestamp with time zone` | NO |

---

## dim_usage_metrics_new

**Description:** Usage metrics dimension (current) - Current usage metrics with refreshed calculations.

**Rows:** 15147  
**Columns:** 13

| Column | Data Type | Nullable |
|--------|-----------|----------|
| `id` | `integer` | NO |
| `fiscal_year` | `character varying` | YES |
| `fiscal_quarter` | `character varying` | YES |
| `fiscal_month` | `character varying` | YES |
| `product` | `character varying` | YES |
| `level` | `character varying` | YES |
| `capability` | `character varying` | YES |
| `metric` | `character varying` | YES |
| `metric_value` | `numeric` | YES |
| `metric_definition` | `character varying` | YES |
| `is_latest` | `boolean` | YES |
| `has_issues` | `boolean` | YES |
| `synced_at` | `timestamp with time zone` | NO |

---


---

## Table Categories & Relationships

### Financial Metrics Tables (Revenue Tracking)

These tables track revenue in various forms:
- **data_acv**: Order-level ACV records, one row per product/split on a contract
- **data_arr**: Monthly recurring revenue fact table with full customer hierarchy
- **data_inc_arr**: Quarterly incremental ARR changes and adjustments
- **data_nacv_target**: Projected NACV targets for forecasting

**Relationship:** ARR is aggregated from ACV orders over time. INC_ARR tracks quarter-over-quarter changes. NACV_TARGET is the forecast/goal.

### Pipeline & Opportunity Tables

- **data_pipeline_master**: Master opportunity records with full stage, forecast, probability hierarchy
- **data_pippeline_curr**: Current snapshot (faster refresh than master)
- **deal_notes**: Unstructured notes attached to deals

**Relationship:** Both reference the same opportunity records; `_curr` is updated more frequently for dashboards.

### Customer Dimension Tables

- **dim_account**: Legacy account master (full hierarchies, industry, geography)
- **dim_account_new**: Current account master (replaces dim_account in active queries)
- **dim_product_hierarchy**: Product taxonomy (L1-L5)
- **dim_product_hierarchy_new**: Current product taxonomy
- **dim_terminated_users**: Inactive user list for access filtering

**Relationship:** Account and product hierarchies denormalize relationships from Snowflake; `_new` versions are the current authoritative versions.

### Churn & Risk Tables

- **data_churn_reason**: Detailed reason codes and categories for churn events
- **dim_churn_signal_metrics**: Computed churn risk scores and leading indicators (110 columns of signals)
- **dim_churn_signal_llm_payload**: Curated data passed to LLM churn models

**Relationship:** Churn signals feed into the LLM payload; reason codes classify the outcome.

### Product 360 Aggregation

- **data_p360_dash_mon**: Monthly denormalized snapshot with 950 columns aggregating account, product, and pipeline metrics for the Product 360 dashboard

**Usage:** Dashboard refresh; one row per (account, product, month). Replaces multiple fact table joins.

### Usage & Capability Tables

- **data_quantity**: Product usage volumes, consumption patterns
- **data_whitespace**: Expansion/upsell opportunity scores within existing accounts
- **data_renewal_risk**: Renewal probability and risk classifications
- **dim_con_capability_fy26_curr**: Capability coverage matrix (capability × account)
- **dim_usage_metrics**: Pre-computed usage KPIs and consumption buckets

**Usage:** Drives adoption metrics, whitespace analysis, and renewal forecasts.

### QBR (Quarterly Business Review) Tables

- **data_qbr_incidents**: Detailed incident records tracked in QBR reviews
- **data_qbr_incident_summary**: High-level incident summaries for executive visibility

**Usage:** QBR dashboards and incident tracking.

### Digest & Notification

- **digest_send_log**: Audit trail of digest notifications sent (churn alerts, executive briefings, etc.)

**Usage:** Deduplication and delivery tracking for digest workflows.

---

## Data Synchronization Pattern

All `data_*` and `dim_*` tables are **Snowflake-synced**:

1. **Source:** Snowflake (`PUBLIC` schema)
2. **Sync Method:** Daily batch sync via `backend/scripts/scheduler.py`
3. **Pattern:** 
   - Full refresh for smaller fact tables (< 5M rows typically)
   - Incremental sync for very large tables (pipeline_master, quantity)
   - Staging-swap pattern to ensure atomicity
4. **Refresh Timestamps:** 
   - `src_refresh_timestamp`: When row was extracted from Snowflake
   - `trf_refresh_timestamp`: When row was transformed/loaded to Postgres
   - `created_at` / `updated_at`: Postgres local timestamps
5. **Current State:** 
   - Tables with `_new` suffix are the active versions (replaced the old versions)
   - Tables with 0 rows are deprecated/legacy (kept for compatibility)

---

## Common Query Patterns

### 1. Revenue by Account & Product
```sql
SELECT 
  end_user_parent_id, product_l2, fiscal_quarter,
  SUM(adjusted_acv) as acv,
  SUM(arr) as arr
FROM data_acv
JOIN data_arr USING (fiscal_quarter, product_l2)
WHERE fiscal_year = '2026'
GROUP BY end_user_parent_id, product_l2, fiscal_quarter
ORDER BY acv DESC;
```

### 2. Churn Risk + Renewal Probability
```sql
SELECT 
  da.parent_account_id, da.parent_account_name,
  drr.renewal_risk_score,
  dcs.churn_probability,
  dcs.leading_signal_count
FROM dim_account_new da
LEFT JOIN data_renewal_risk drr ON da.account_id = drr.account_id
LEFT JOIN dim_churn_signal_metrics dcs ON da.account_id = dcs.account_id
WHERE da.parent_account_id IS NOT NULL
ORDER BY dcs.churn_probability DESC;
```

### 3. Product 360 Dashboard Snapshot
```sql
SELECT * FROM data_p360_dash_mon
WHERE month = DATE_TRUNC('month', CURRENT_DATE)::date
ORDER BY parent_account_id;
```

### 4. Pipeline by Stage & Forecast
```sql
SELECT 
  fiscal_quarter,
  opportunity_stage,
  SUM(opportunity_amount) as pipeline_total,
  SUM(opportunity_amount * forecast_percentage) as weighted_pipeline
FROM data_pipeline_master
WHERE fiscal_year = '2026'
GROUP BY fiscal_quarter, opportunity_stage
ORDER BY fiscal_quarter, pipeline_total DESC;
```

---

## Performance Considerations

| Table | Size | Index Strategy | Query SLA |
|-------|------|-----------------|-----------|
| data_acv | 390K rows, 45 cols | `(parent_account_id, fiscal_quarter)`, `(product_l2)` | <100ms |
| data_arr | 1.8M rows, 84 cols | `(end_user_parent_id, fiscal_month)`, `(product_l1, product_l2)` | <500ms |
| data_pipeline_master | 4.7M rows, 152 cols | `(opportunity_stage, fiscal_quarter)`, `(account_id)` | <1s |
| data_quantity | 4.0M rows, 36 cols | `(account_id, product_l1)`, `(fiscal_month)` | <1s |
| data_p360_dash_mon | 147K rows, 950 cols | `(month, parent_account_id)` | <100ms (denormalized) |
| dim_account_new | 188K rows, 89 cols | `(parent_account_id)`, `(industry, geo)` | <50ms (lookup) |
| dim_churn_signal_metrics | 9.8K rows, 110 cols | `(account_id)`, `(churn_probability)` | <50ms |

All tables have `created_at` / `updated_at` composite indexes for incremental sync checkpointing.

---

## Access & Authorization

All tables are:
- **Readable by:** Product analysts, dashboard builders, AI agents (via Maestro platform)
- **Writable by:** Snowflake sync service only (read-only application role)
- **Visible to:** Any authenticated Maestro user (row-level scoping via `product_l1` / `product_l2` in Maestro platform)

No direct SQL access from UI; all queries routed through:
1. Backend services (`backend/src/apps/*/services/*.py`)
2. Maestro AI agents (with SQL Guard enforcement)
3. Admin dashboards (audit-logged)

---

## Troubleshooting

### Missing Data
- **Check:** `src_refresh_timestamp` vs. current time
- **Root cause:** Sync job failed or skipped
- **Recovery:** Re-run sync via `PYTHONPATH=. python -m scripts.scheduler --sync <table>`

### Stale Dimensions
- **Check:** `_new` version row count > 0, old version = 0?
- **Action:** Migrate queries from old table to new version
- **Example:** Use `dim_account_new` instead of `dim_account`

### High Query Latency
- **Check:** Table row count, column count, index presence
- **Solution:** 
  - Aggregate server-side, not in Python
  - Denormalize to data_p360_dash_mon if dashboard-scoped
  - Use incremental queries with fiscal_month/quarter filters

---

**Last Updated:** 2026-10-16  
**Synced from:** pop_db (PostgreSQL)  
**Next Sync:** Automatic (daily via scheduler)
