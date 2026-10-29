# demo3 questions — spacy S1 — 2026-10-29 10:31

| # | Question | Intent | Account | Products | Geo | Segment | Fiscal | Filters | Result |
|---|---|---|---|---|---|---|---|---|---|
| 1 | What is the total ARR for Q1FY26? | AGGREGATE | — | — | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
| 2 | Show me Private Access ARR. | AGGREGATE | — | Private Access | — | — | — | — | ok |
| 3 | What is HSBC ARR? | LOOKUP | HSBC | — | — | — | — | — | ok |
| 4 | Give me EMEA ARR Q1FY26. | AGGREGATE | — | — | EMEA | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'end_user_parent_geo': 'EMEA'} | ok |
| 5 | What is Internet Access and Platform ARR Q1FY26? | AGGREGATE | — | ZIA, Platform | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'product_l1__in': ['ZIA', 'Platform']} | ok |
| 6 | Show ARR for large enterprise accounts. | AGGREGATE | — | — | — | Large Enterprise | — | {'market_segment': 'Large Enterprise'} | ok |
| 7 | What is Digital Experience ARR? | AGGREGATE | — | Digital Experience | — | — | — | {'product_l1': 'Digital Experience'} | ok |
| 8 | Give me APAC ARR Q2FY26. | AGGREGATE | — | — | APJ | — | FY 2026 Q2 | {'fiscal_quarter': 'FY 2026 Q2', 'end_user_parent_geo': 'APJ'} | ok |
| 9 | What is Siemens ARR Q1FY26? | LOOKUP | Siemens | — | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
| 10 | Show me total ARR for enterprise accounts Q1FY26. | AGGREGATE | — | — | — | Enterprise | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'market_segment': 'Enterprise'} | ok |
| 11 | What is Private Access and Digital Experience ARR for EMEA Q1FY26? | AGGREGATE | — | Digital Experience | EMEA | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'product_l1': 'Digital Experience', 'end_user_parent_geo': 'EMEA'} | ok |
| 12 | Show me top 10 accounts by ARR in Q1FY26. | RANK | — | — | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
| 13 | What is ARR breakdown by product for HSBC Q1FY26? | LOOKUP | HSBC | — | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
| 14 | Give me Data Security ARR for enterprise accounts EMEA Q1FY26. | AGGREGATE | — | Data Security | EMEA | Enterprise | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'product_l1': 'Data Security', 'end_user_parent_geo': 'EMEA', 'market_segment': 'Enterprise'} | ok |
| 15 | Which accounts have Private Access ARR above 1M in EMEA Q1FY26? | AGGREGATE | — | Private Access | EMEA | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'end_user_parent_geo': 'EMEA'} | ok |
| 16 | Show me top 5 accounts by Internet Access ARR in EMEA Q1FY26. | RANK | — | ZIA | EMEA | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'product_l1': 'ZIA', 'end_user_parent_geo': 'EMEA'} | ok |
| 17 | What is AI Security ARR for enterprise accounts across all geos Q1FY26? | AGGREGATE | — | AI Security | — | Enterprise | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'market_segment': 'Enterprise'} | ok |
| 18 | Give me ARR for Siemens and Toyota Q1FY26. | LOOKUP | Siemens | — | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
| — | ↳ Give me ARR for Toyota Q1FY26. | LOOKUP | Toyota | — | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
| 19 | What is the ARR split between Private Access and Internet Access for APAC Q1FY26? | COMPARE | — | ZIA | APJ | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'product_l1': 'ZIA', 'end_user_parent_geo': 'APJ'} | ok |
| 20 | Show bottom 10 accounts by ARR in AMER large enterprise Q1FY26. | RANK | — | — | Americas | Large Enterprise | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'end_user_parent_geo': 'Americas', 'market_segment': 'Large Enterprise'} | ok |
| 21 | Which top 10 EMEA enterprise accounts had the highest ARR growth from Q4FY25 to Q1FY26? | DELTA | — | — | EMEA | Enterprise | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'end_user_parent_geo': 'EMEA', 'market_segment': 'Enterprise'} | ok |
| 22 | Show me accounts where Internet Access ARR increased but Private Access ARR decreased Q1FY26. | RISK | — | ZIA | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'product_l1': 'ZIA'} | ok |
| 23 | What is the QoQ ARR change for enterprise accounts in APAC from Q4FY25 to Q1FY26? | DELTA | — | — | APJ | Enterprise | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'end_user_parent_geo': 'APJ', 'market_segment': 'Enterprise'} | ok |
| 24 | Give me ARR trend for Private Access enterprise accounts in EMEA over last 4 quarters. | TREND | — | Private Access | EMEA | Enterprise | FY 2026 Q2, FY 2026 Q3, FY 2026 Q4, FY 2027 Q1 | {'fiscal_quarter__in': ['FY 2026 Q2', 'FY 2026 Q3', 'FY 2026 Q4', 'FY 2027 Q1'], 'end_user_parent_geo': 'EMEA', 'market_segment': 'Enterprise'} | ok |
| 25 | Compare Internet Access vs Private Access ARR for top 10 accounts in EMEA Q1FY26. | COMPARE | — | ZIA | EMEA | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'product_l1': 'ZIA', 'end_user_parent_geo': 'EMEA'} | ok |
| 26 | Which accounts have Internet Access ARR but no Private Access ARR in EMEA enterprise Q1FY26? | AGGREGATE | — | ZIA | EMEA | Enterprise | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'product_l1': 'ZIA', 'end_user_parent_geo': 'EMEA', 'market_segment': 'Enterprise'} | ok |
| 27 | Show me bottom 10 accounts by ARR growth rate in APAC large enterprise Q1FY26. | DELTA | — | — | APJ | Large Enterprise | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'end_user_parent_geo': 'APJ', 'market_segment': 'Large Enterprise'} | ok |
| 28 | Give me Internet Access, Private Access and Digital Experience ARR breakdown for Siemens and HSBC in Q1FY26. | LOOKUP | Siemens | ZIA, Digital Experience | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'product_l1__in': ['ZIA', 'Digital Experience']} | ok |
| — | ↳ Give me Internet Access, Private Access and Digital Experience ARR breakdown for HSBC in Q1FY26. | LOOKUP | HSBC | ZIA, Digital Experience | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'product_l1__in': ['ZIA', 'Digital Experience']} | ok |
| 29 | What is total ARR for accounts renewing in Q2FY26 across EMEA? | AGGREGATE | — | — | EMEA | — | FY 2026 Q2 | {'fiscal_quarter': 'FY 2026 Q2', 'end_user_parent_geo': 'EMEA', 'mrr_order_type': 'Renewal'} | ok |
| 30 | Show me top 10 EMEA enterprise accounts by Private Access ARR in Q1FY26 that also have Internet Access ARR above 2M but had a QoQ ARR decline on Internet Access from Q4FY25. | RISK | — | ZIA | EMEA | Enterprise | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'product_l1': 'ZIA', 'end_user_parent_geo': 'EMEA', 'market_segment': 'Enterprise'} | ok |
| 31 | Which major accounts in APAC grew Private Access ARR by more than 20% QoQ in Q1FY26 but have Digital Experience ARR below 100K — potential Digital Experience upsell targets. | DELTA | — | Digital Experience | APJ | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'product_l1': 'Digital Experience', 'end_user_parent_geo': 'APJ', 'mrr_order_type': 'Upsell'} | ok |
| 32 | Compare total platform ARR for enterprise in EMEA and APAC for Q1FY27 vs Q1FY26 — show YoY growth rate per segment per geo. | COMPARE | — | Platform | EMEA, APJ | Enterprise | FY 2027 Q1 | {'fiscal_quarter': 'FY 2027 Q1', 'product_l1': 'Platform', 'end_user_parent_geo__in': ['EMEA', 'APJ'], 'market_segment': 'Enterprise'} | ok |
| 33 | Give me accounts with consecutive ARR decline across last 3 quarters on Internet Access in EMEA enterprise — ranked by total ARR lost. | RISK | — | ZIA | EMEA | Enterprise | FY 2026 Q3, FY 2026 Q4, FY 2027 Q1 | {'fiscal_quarter__in': ['FY 2026 Q3', 'FY 2026 Q4', 'FY 2027 Q1'], 'product_l1': 'ZIA', 'end_user_parent_geo': 'EMEA', 'market_segment': 'Enterprise'} | ok |
| 34 | Show ARR contribution of Internet Access vs Private Access vs Digital Experience as a percentage of total account ARR for top 20 accounts in EMEA Q1FY26 — flag accounts where Internet Access is above 80%. | COMPARE | — | ZIA, Digital Experience | EMEA | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'product_l1__in': ['ZIA', 'Digital Experience'], 'end_user_parent_geo': 'EMEA'} | ok |
| 35 | Which EMEA large enterprise accounts had ARR expansion on Private Access but downsell on Internet Access in Q1FY26 and what is the net ARR impact per account? | RISK | — | ZIA | EMEA | Large Enterprise | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'product_l1': 'ZIA', 'end_user_parent_geo': 'EMEA', 'market_segment': 'Large Enterprise'} | ok |
| — | ↳ What is the net ARR impact per account in Q1FY26? | AGGREGATE | — | — | — | Enterprise | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'market_segment': 'Enterprise'} | ok |
| 36 | Give me top 5 accounts per geo by Private Access ARR growth rate in Q1FY26 — exclude accounts with total ARR below 500K — enterprise and large enterprise only. | DELTA | — | Private Access | — | Enterprise, Large Enterprise | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'market_segment__in': ['Enterprise', 'Large Enterprise']} | ok |
| 37 | Compare ARR for HSBC, Siemens, Deutsche Bank and Toyota across Internet Access, Private Access, Digital Experience and Data Security for Q1FY26 and Q2FY26 — show QoQ delta per product per account. | COMPARE | HSBC | ZIA, Digital Experience, Data Security | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'product_l1__in': ['ZIA', 'Digital Experience', 'Data Security']} | ok |
| — | ↳ Compare ARR for Siemens and Toyota across Internet Access, Private Access, Digital Experience and Data Security for Q1FY26 and Q2FY26 — show QoQ delta per product per account. | COMPARE | Siemens | ZIA, Digital Experience, Data Security | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'product_l1__in': ['ZIA', 'Digital Experience', 'Data Security']} | ok |
| — | ↳ Compare ARR for Deutsche Bank and Toyota across Internet Access, Private Access, Digital Experience and Data Security for Q1FY26 and Q2FY26 — show QoQ delta per product per account. | COMPARE | Deutsche Bank | ZIA, Digital Experience, Data Security | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'product_l1__in': ['ZIA', 'Digital Experience', 'Data Security'], 'account_id': '0010g00001k9Ig5AAE'} | ok |
| 38 | Which accounts have high Internet Access ARR above 3M but zero Private Access ARR in EMEA enterprise Q1FY26 — rank by Internet Access ARR and show renewal quarter as upsell priority list. | AGGREGATE | — | ZIA | EMEA | Enterprise | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'product_l1': 'ZIA', 'end_user_parent_geo': 'EMEA', 'market_segment': 'Enterprise'} | ok |
| — | ↳ Show renewal quarter as upsell priority list. on ZIA on Private Access in EMEA for Enterprise in Q1FY26 ARR | AGGREGATE | — | ZIA | EMEA | Enterprise | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'product_l1': 'ZIA', 'end_user_parent_geo': 'EMEA', 'market_segment': 'Enterprise', 'mrr_order_type__in': ['Renewal', 'Upsell']} | ok |
| 39 | Show me AI Security and Data Security ARR for EMEA and APAC large enterprise in Q1FY26 — compare both products QoQ vs Q4FY25 and flag any account where combined ARR dropped more than 10% with their renewal quarter. | RISK | — | Data Security | EMEA, APJ | Large Enterprise | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'product_l1': 'Data Security', 'end_user_parent_geo__in': ['EMEA', 'APJ'], 'market_segment': 'Large Enterprise', 'mrr_order_type': 'Renewal'} | ok |
| 40 | Show me ARR. | AGGREGATE | — | — | — | — | — | — | ok |
| 41 | What is Private Access ARR? | AGGREGATE | — | Private Access | — | — | — | — | ok |
| 42 | Give me EMEA ARR. | AGGREGATE | — | — | EMEA | — | — | {'end_user_parent_geo': 'EMEA'} | ok |
| 43 | What is HSBC revenue? | LOOKUP | HSBC | — | — | — | — | — | ok |
| 44 | Show me top 10 accounts. | RANK | — | — | — | — | — | — | ok |
| 45 | What is enterprise ARR? | AGGREGATE | — | — | — | Enterprise | — | {'market_segment': 'Enterprise'} | ok |
| 46 | Give me Q1FY26 ARR. | AGGREGATE | — | — | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
| 47 | How is Siemens doing? | LOOKUP | Siemens | — | — | — | — | — | ok |
| 48 | Show me large enterprise numbers. | AGGREGATE | — | — | — | Large Enterprise | — | {'market_segment': 'Large Enterprise'} | ok |
| 49 | What is Digital Experience performance? | AGGREGATE | — | Digital Experience | — | — | — | {'product_l1': 'Digital Experience'} | ok |
| 50 | What is ZIA ARR? | AGGREGATE | — | ZIA | — | — | — | {'product_l1': 'ZIA'} | ok |
| 51 | What is ZPA ARR for EMEA this year? | AGGREGATE | — | ZPA | EMEA | — | FY 2027 | {'fiscal_year': 'FY 2027', 'product_l1': 'ZPA', 'end_user_parent_geo': 'EMEA'} | ok |
| 52 | Give me ZTNA revenue Q1FY26. | AGGREGATE | — | ZPA | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'product_l1': 'ZPA'} | ok |
| 53 | Show me APAC numbers for Q1FY26. | AGGREGATE | — | — | APJ | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'end_user_parent_geo': 'APJ'} | ok |
| 54 | What is Zscaler ARR? | AGGREGATE | — | — | — | — | — | — | ok |
| 55 | Give me SWG and CASB ARR Q1FY26. | AGGREGATE | — | ZIA > SWG, Data Security > SaaS Security > CASB | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', '__or__': [{'product_l1': 'ZIA', 'product_l2': 'SWG'}, {'product_l1': 'Data Security', 'product_l2': 'SaaS Security', 'product_l3': 'CASB'}]} | ok |
| 56 | Show me ARR for major accounts EMEA. | AGGREGATE | — | — | EMEA | — | — | {'end_user_parent_geo': 'EMEA'} | ok |
| 57 | What is the ARR for our top product Q1FY26? | RANK | — | — | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
| 58 | Give me DLP numbers last quarter. | AGGREGATE | — | — | — | — | FY 2026 Q4 | {'fiscal_quarter': 'FY 2026 Q4'} | ok |
| 59 | How much are we making from cloud security? | AGGREGATE | — | — | — | — | — | — | ok |
| 60 | What is EMEA ARR for Q1FY26 and Q2FY26? | COMPARE | — | — | EMEA | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'end_user_parent_geo': 'EMEA'} | ok |
| 61 | Show me top 10 and bottom 10 accounts by Private Access ARR in EMEA Q1FY26. | RANK | — | Private Access | EMEA | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'end_user_parent_geo': 'EMEA'} | ok |
| — | ↳ Bottom 10 accounts by Private Access ARR in EMEA Q1FY26. | RANK | — | Private Access | EMEA | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'end_user_parent_geo': 'EMEA'} | ok |
| 62 | What is Private Access ARR for enterprise and all segments Q1FY26? | AGGREGATE | — | Private Access | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
| 63 | Give me ARR for EMEA and all geos Q1FY26. | AGGREGATE | — | — | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
| 64 | Show me ARR growth and ARR total for HSBC Q1FY26. | DELTA | HSBC | — | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
| 65 | What is Private Access ARR in EMEA for Siemens globally? | LOOKUP | Siemens | Private Access | EMEA | — | — | {'end_user_parent_geo': 'EMEA'} | ok |
| 66 | Give me last quarter and this quarter ARR for Digital Experience EMEA. | COMPARE | — | Digital Experience | EMEA | — | FY 2026 Q4 | {'fiscal_quarter': 'FY 2026 Q4', 'product_l1': 'Digital Experience', 'end_user_parent_geo': 'EMEA'} | ok |
| 67 | Show me all ARR for no specific product in Q1FY26 enterprise. | AGGREGATE | — | — | — | Enterprise | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'market_segment': 'Enterprise'} | ok |
| 68 | What is the ARR for Private Access in EMEA, AMER and globally for Q1FY26? | AGGREGATE | — | Private Access | EMEA, Americas | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'end_user_parent_geo__in': ['EMEA', 'Americas']} | ok |
| 69 | Give me Internet Access ARR for Siemens in EMEA but their global number as well Q1FY26. | LOOKUP | Siemens | ZIA | EMEA | Global | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'product_l1': 'ZIA', 'end_user_parent_geo': 'EMEA', 'market_segment': 'Global'} | ok |
| 70 | Show me ARR by product for Q1FY26. | AGGREGATE | — | — | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
| 71 | What is EMEA ARR Q1FY26? | AGGREGATE | — | — | EMEA | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'end_user_parent_geo': 'EMEA'} | ok |
| 72 | Give me ARR breakdown by geo Q1FY26. | AGGREGATE | — | — | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
| 73 | What is large enterprise ARR Q1FY26? | AGGREGATE | — | — | — | Large Enterprise | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'market_segment': 'Large Enterprise'} | ok |
| 74 | Show me Private Access ARR across all geos Q1FY26. | AGGREGATE | — | Private Access | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
| 75 | What is total ARR for EMEA enterprise Q1FY26? | AGGREGATE | — | — | EMEA | Enterprise | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'end_user_parent_geo': 'EMEA', 'market_segment': 'Enterprise'} | ok |
| 76 | Give me QoQ ARR change from Q4FY25 to Q1FY26. | DELTA | — | — | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
| 77 | Which product had highest ARR Q1FY26? | RANK | — | — | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
| 78 | Show me ARR by segment Q1FY26. | AGGREGATE | — | — | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
| 79 | What is Internet Access ARR for EMEA enterprise Q1FY26? | AGGREGATE | — | ZIA | EMEA | Enterprise | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'product_l1': 'ZIA', 'end_user_parent_geo': 'EMEA', 'market_segment': 'Enterprise'} | ok |
| 80 | Give me top 10 accounts by ARR in EMEA Q1FY26. | RANK | — | — | EMEA | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'end_user_parent_geo': 'EMEA'} | ok |
| 81 | Which geo had highest ARR growth QoQ in Q1FY26? | DELTA | — | — | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
| 82 | Show me ARR trend over last 4 quarters for Private Access. | TREND | — | Private Access | — | — | FY 2026 Q2, FY 2026 Q3, FY 2026 Q4, FY 2027 Q1 | {'fiscal_quarter__in': ['FY 2026 Q2', 'FY 2026 Q3', 'FY 2026 Q4', 'FY 2027 Q1']} | ok |
| 83 | What is Data Security ARR for large enterprise Q1FY26? | AGGREGATE | — | Data Security | — | Large Enterprise | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'product_l1': 'Data Security', 'market_segment': 'Large Enterprise'} | ok |
| 84 | What is ARR for APAC large enterprise Private Access Q1FY26? | AGGREGATE | — | Private Access | APJ | Large Enterprise | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'end_user_parent_geo': 'APJ', 'market_segment': 'Large Enterprise'} | ok |
| 85 | Show me bottom 10 accounts by ARR  in AMER Q1FY26. | RANK | — | — | Americas | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'end_user_parent_geo': 'Americas'} | ok |
| 86 | Which segment has highest Internet Access ARR in EMEA Q1FY26? | RANK | — | ZIA | EMEA | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'product_l1': 'ZIA', 'end_user_parent_geo': 'EMEA'} | ok |
| 87 | Give me QoQ ARR change for Digital Experience in APAC Q1FY26. | DELTA | — | Digital Experience | APJ | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'product_l1': 'Digital Experience', 'end_user_parent_geo': 'APJ'} | ok |
| 88 | What is AI Security ARR for enterprise accounts Q1FY26? | AGGREGATE | — | AI Security | — | Enterprise | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'market_segment': 'Enterprise'} | ok |
| 89 | Show me ARR by product for EMEA large enterprise Q1FY26. | AGGREGATE | — | — | EMEA | Large Enterprise | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'end_user_parent_geo': 'EMEA', 'market_segment': 'Large Enterprise'} | ok |
| 90 | Which product had biggest ARR decline QoQ in Q1FY26? | RISK | — | — | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
| 91 | Give me top 5 accounts by Private Access ARR in APAC Q1FY26. | RANK | — | Private Access | APJ | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'end_user_parent_geo': 'APJ'} | ok |
| 92 | What is total ARR for accounts renewing in Q2FY26? | AGGREGATE | — | — | — | — | FY 2026 Q2 | {'fiscal_quarter': 'FY 2026 Q2', 'mrr_order_type': 'Renewal'} | ok |
| 93 | Show me ARR trend for EMEA enterprise over last 4 quarters. | TREND | — | — | EMEA | Enterprise | FY 2026 Q2, FY 2026 Q3, FY 2026 Q4, FY 2027 Q1 | {'fiscal_quarter__in': ['FY 2026 Q2', 'FY 2026 Q3', 'FY 2026 Q4', 'FY 2027 Q1'], 'end_user_parent_geo': 'EMEA', 'market_segment': 'Enterprise'} | ok |
| 94 | What is Siemens total ARR Q1FY26? | LOOKUP | Siemens | — | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
| 95 | Show me HSBC ARR by product Q1FY26. | LOOKUP | HSBC | — | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
| 96 | What is JPMorgan Private Access ARR Q1FY26? | LOOKUP | JPMorgan | Private Access | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
| 97 | Give me Toyota ARR trend over last 4 quarters. | TREND | Toyota | — | — | — | FY 2026 Q2, FY 2026 Q3, FY 2026 Q4, FY 2027 Q1 | {'fiscal_quarter__in': ['FY 2026 Q2', 'FY 2026 Q3', 'FY 2026 Q4', 'FY 2027 Q1']} | ok |
| 98 | What is Deutsche Bank Internet Access ARR Q1FY26? | LOOKUP | Deutsche Bank | ZIA | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'product_l1': 'ZIA', 'account_id': '0010g00001k9Ig5AAE'} | ok |
| 99 | Show me Infosys ARR breakdown by product Q1FY26. | LOOKUP | Infosys | — | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
| 100 | What is Shell total ARR Q1FY26? | LOOKUP | Shell | — | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
| 101 | Give me Pfizer ARR Q1FY26. | LOOKUP | Pfizer | — | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
| 102 | What is Siemens Private Access ARR QoQ change from Q4FY25 to Q1FY26? | DELTA | Siemens | Private Access | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
| 103 | Show me HSBC ARR trend for Internet Access over last 4 quarters. | TREND | HSBC | ZIA | — | — | FY 2026 Q2, FY 2026 Q3, FY 2026 Q4, FY 2027 Q1 | {'fiscal_quarter__in': ['FY 2026 Q2', 'FY 2026 Q3', 'FY 2026 Q4', 'FY 2027 Q1'], 'product_l1': 'ZIA'} | ok |
| 104 | Did Toyota ARR grow or decline QoQ in Q1FY26? | RISK | Toyota | — | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
| 105 | What products does Deutsche Bank have ARR in for Q1FY26? | LOOKUP | Deutsche Bank | — | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'account_id': '0010g00001k9Ig5AAE'} | ok |
| 106 | Show me Siemens ARR breakdown by product and geo Q1FY26. | LOOKUP | Siemens | — | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
| 107 | What is JPMorgan Data Security ARR QoQ change Q1FY26? | DELTA | JPMorgan | Data Security | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1', 'product_l1': 'Data Security'} | ok |
| 108 | Give me full ARR profile for HSBC in Q1FY26 — all products, total ARR and QoQ change. | LOOKUP | HSBC | — | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
| — | ↳ Total ARR and QoQ change. for HSBC in Q1FY26 | DELTA | — | — | — | — | FY 2026 Q1 | {'fiscal_quarter': 'FY 2026 Q1'} | ok |
