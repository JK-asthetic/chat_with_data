Easy (1–10)
text
Download
Copy

1.  What is the total ARR for Q1FY26?

2.  Show me Private Access ARR.

3.  What is HSBC ARR?

4.  Give me EMEA ARR Q1FY26.

5.  What is Internet Access and Platform ARR Q1FY26?

6.  Show ARR for large enterprise accounts.

7.  What is Digital Experience ARR?

8.  Give me APAC ARR Q2FY26.

9.  What is Siemens ARR Q1FY26?

10. Show me total ARR for enterprise accounts Q1FY26.


Medium (11–20)
text
Download
Copy
11. What is Private Access and Digital Experience ARR for EMEA Q1FY26?

12. Show me top 10 accounts by ARR in Q1FY26.

13. What is ARR breakdown by product for HSBC Q1FY26?

14. Give me Data Security ARR for enterprise accounts EMEA Q1FY26.

15. Which accounts have Private Access ARR above 1M in EMEA Q1FY26?

16. Show me top 5 accounts by Internet Access ARR in EMEA Q1FY26.

17. What is AI Security ARR for enterprise accounts across all geos Q1FY26?

18. Give me ARR for Siemens and Toyota Q1FY26.

19. What is the ARR split between Private Access and Internet Access for APAC Q1FY26?

20. Show bottom 10 accounts by ARR in AMER large enterprise Q1FY26.
Hard (21–30)
text
Download
Copy
21. Which top 10 EMEA enterprise accounts had the highest ARR growth from Q4FY25 to Q1FY26?

22. Show me accounts where Internet Access ARR increased but Private Access ARR decreased Q1FY26.

23. What is the QoQ ARR change for enterprise accounts in APAC from Q4FY25 to Q1FY26?


25. Give me ARR trend for Private Access enterprise accounts in EMEA over last 4 quarters.

26. Compare Internet Access vs Private Access ARR for top 10 accounts in EMEA Q1FY26.

27. Which accounts have Internet Access ARR but no Private Access ARR in EMEA enterprise Q1FY26?

28. Show me bottom 10 accounts by ARR growth rate in APAC large enterprise Q1FY26.

29. Give me Internet Access, Private Access and Digital Experience ARR breakdown for Siemens and HSBC in Q1FY26.

30. What is total ARR for accounts renewing in Q2FY26 across EMEA?

Complex (31–40)
text
Download
Copy
31. Show me top 10 EMEA enterprise accounts by Private Access ARR in Q1FY26 that also have Internet Access ARR above 2M but had a QoQ ARR decline on Internet Access from Q4FY25.

32. Which major accounts in APAC grew Private Access ARR by more than 20% QoQ in Q1FY26 but have Digital Experience ARR below 100K — potential Digital Experience upsell targets.

33. Compare total platform ARR for enterprise in EMEA and APAC for Q1FY27 vs Q1FY26 — show YoY growth rate per segment per geo.

34. Give me accounts with consecutive ARR decline across last 3 quarters on Internet Access in EMEA enterprise — ranked by total ARR lost.

35. Show ARR contribution of Internet Access vs Private Access vs Digital Experience as a percentage of total account ARR for top 20 accounts in EMEA Q1FY26 — flag accounts where Internet Access is above 80%.

36. Which EMEA large enterprise accounts had ARR expansion on Private Access but downsell on Internet Access in Q1FY26 and what is the net ARR impact per account?

37. Give me top 5 accounts per geo by Private Access ARR growth rate in Q1FY26 — exclude accounts with total ARR below 500K — enterprise and large enterprise only.

38. Compare ARR for HSBC, Siemens, Deutsche Bank and Toyota across Internet Access, Private Access, Digital Experience and Data Security for Q1FY26 
and Q2FY26 — show QoQ delta per product per account.

39. Which accounts have high Internet Access ARR above 3M but zero Private Access ARR in EMEA enterprise Q1FY26 — rank by Internet Access ARR and show renewal quarter as upsell priority list.

40. Show me AI Security and Data Security ARR for 
    EMEA and APAC large enterprise in Q1FY26 — 
    compare both products QoQ vs Q4FY25 and flag 
    any account where combined ARR dropped more 
    than 10% with their renewal quarter.






Download
Copy
1.  Show me ARR.
    missing: [fiscal, product, geo]

2.  What is Private Access ARR?
    missing: [fiscal]

3.  Give me EMEA ARR.
    missing: [fiscal]

4.  What is HSBC revenue?
    missing: [fiscal]

5.  Show me top 10 accounts.
    missing: [fiscal]

6.  What is enterprise ARR?
    missing: [fiscal, product]

7.  Give me Q1FY26 ARR.
    missing: []   ← NOT ambiguous, valid query
    (tests if model over-flags missing)

8.  How is Siemens doing?
    missing: [fiscal, metric unclear]

9.  Show me large enterprise numbers.
    missing: [fiscal, product, metric unclear]

10. What is Digital Experience performance?
    missing: [fiscal, metric unclear]
Tier 2 — Misleading / Noise Words (11–20)
text
Download
Copy
11. What is ZIA ARR?
    trap: ZIA is old name → should map to
    "Internet Access and Platform"
    missing: [fiscal]

12. What is ZPA ARR for EMEA this year?
    trap: ZPA → "Private Access"
    fiscal_raw: "this year" ← not null

13. Give me ZTNA revenue Q1FY26.
    trap: "revenue" ≠ ARR → metric unclear
    also: ZTNA → "Private Access"

14. Show me APAC numbers for Q1FY26.
    trap: "numbers" → metric unclear
    also: APAC → APJ

15. What is Zscaler ARR?
    trap: "Zscaler" = the company
    → products_raw: []  (all products)
    missing: [fiscal]

16. Give me SWG and CASB ARR Q1FY26.
    trap: SWG  → "Internet Access and Platform"
          CASB → "Data Security"
    two different L1s from informal names

17. Show me ARR for major accounts EMEA.
    trap: "major accounts" → "Large Enterprise"
    missing: [fiscal, product]

18. What is the ARR for our top product Q1FY26?
    trap: "top product" is vague
    → products_raw: []
    missing: [] or [product] depending

19. Give me DLP numbers last quarter.
    trap: "numbers" → metric unclear
          DLP → "Data Security"
          "last quarter" → fiscal_raw: "last quarter"

20. How much are we making from cloud security?
    trap: "cloud security" not a valid product_l1
    → products_raw: []
    missing: [fiscal, product]
Tier 3 — Conflicting / Contradictory Info (21–30)
text
Download
Copy
21. What is EMEA ARR for Q1FY26 and Q2FY26?
    trap: two quarters in one query
    → fiscal_raw: "Q1FY26 and Q2FY26"
    intent: should be COMPARE or TREND

22. Show me top 10 and bottom 10 accounts by Private Access ARR in EMEA Q1FY26.
    trap: both top AND bottom in one query
    → operator: ??? model must pick or flag

23. What is Private Access ARR for enterprise and all segments Q1FY26?
    trap: "enterprise AND all segments"
    → contradictory: all segments means 
       segment_raw: []

24. Give me ARR for EMEA and all geos Q1FY26.
    trap: "EMEA and all geos"
    → contradictory: all geos means geo_raw: []

25. Show me ARR growth and ARR total 
    for HSBC Q1FY26.
    trap: two metrics in one — ARR and DELTA
    → model must pick one intent
       or flag as ambiguous

26. What is Private Access ARR in 
    EMEA for Siemens globally?
    trap: "EMEA" vs "globally" contradict
    → geo_raw: ["EMEA"] or []?

27. Give me last quarter and this quarter 
    ARR for Digital Experience EMEA.
    trap: two fiscal periods
    → fiscal_raw: "last quarter and this quarter"
    intent: COMPARE

28. Show me all ARR for no specific product in Q1FY26 enterprise.
    trap: "no specific product" explicitly stated
    → products_raw: []   ← forced empty

29. What is the ARR for Private Access in EMEA,
    AMER and globally for Q1FY26?
    trap: "EMEA, AMER and globally"
    → "globally" contradicts specific geos
    → geo_raw: [] or ["EMEA", "AMER"]?

30. Give me Internet Access ARR for Siemens in EMEA but their global number as well Q1FY26.
    trap: account-level EMEA + account-level global
    → two different scopes in one query
    → model cannot resolve, should flag
    








    .  What is total ARR for Q1FY26?

2.  Show me ARR by product for Q1FY26.

3.  What is EMEA ARR Q1FY26?

4.  Give me ARR breakdown by geo Q1FY26.

5.  What is large enterprise ARR Q1FY26?

6.  Show me Private Access ARR across 
    all geos Q1FY26.

7.  What is total ARR for EMEA enterprise 
    Q1FY26?

8.  Give me QoQ ARR change from 
    Q4FY25 to Q1FY26.

9.  Which product had highest ARR Q1FY26?

10. Show me ARR by segment Q1FY26.

11. What is Internet Access ARR for 
    EMEA enterprise Q1FY26?

12. Give me top 10 accounts by ARR 
    in EMEA Q1FY26.

13. Which geo had highest ARR growth 
    QoQ in Q1FY26?

14. Show me ARR trend over last 
    4 quarters for Private Access.

15. What is Data Security ARR for 
    large enterprise Q1FY26?
No Company — With Filters (16–25)
text
Download
Copy
16. What is ARR for APAC large enterprise 
    Private Access Q1FY26?

17. Show me bottom 10 accounts by ARR  in AMER Q1FY26.

18. Which segment has highest Internet 
    Access ARR in EMEA Q1FY26?

19. Give me QoQ ARR change for Digital 
    Experience in APAC Q1FY26.

20. What is AI Security ARR for 
    enterprise accounts Q1FY26?

21. Show me ARR by product for 
    EMEA large enterprise Q1FY26.

22. Which product had biggest ARR decline QoQ in Q1FY26?

23. Give me top 5 accounts by Private Access ARR in APAC Q1FY26.

24. What is total ARR for accounts 
    renewing in Q2FY26?

25. Show me ARR trend for EMEA 
    enterprise over last 4 quarters.
Single Company — Simple (26–33)

26. What is Siemens total ARR Q1FY26?

27. Show me HSBC ARR by product Q1FY26.

28. What is JPMorgan Private Access 
    ARR Q1FY26?

29. Give me Toyota ARR trend over 
    last 4 quarters.

30. What is Deutsche Bank Internet Access ARR Q1FY26?

31. Show me Infosys ARR breakdown by product Q1FY26.

32. What is Shell total ARR Q1FY26?

33. Give me Pfizer ARR Q1FY26.
Single Company — With Filters (34–40)
text
Download
Copy
34. What is Siemens Private Access ARR QoQ change from Q4FY25 to Q1FY26?

35. Show me HSBC ARR trend for Internet Access over last 4 quarters.

36. Did Toyota ARR grow or decline QoQ in Q1FY26?

37. What products does Deutsche Bank have ARR in for Q1FY26?

38. Show me Siemens ARR breakdown by product and geo Q1FY26.

39. What is JPMorgan Data Security 
    ARR QoQ change Q1FY26?

40. Give me full ARR profile for HSBC in Q1FY26 — all products, 
total ARR and QoQ change.

















Usage / Quantity Totals

What is the total quantity for ZIA in Q1FY26?
Give me total users for ZPA in EMEA Q1FY26.
What is the total raw quantity for Q2FY26?
Show me ZDX quantity for APJ Q1FY26.
Product-level Quantity

What is the total quantity for Data Security Q1FY26?
Give me product quantity breakdown by product L1 for Q1FY26.
What is the ZIA quantity for commercial accounts Q1FY26?
Show me ZPA quantity for enterprise accounts Q2FY26.
ARR vs Quantity

What is the ARR per user for ZIA in Q1FY26?
Give me ARR and quantity for ZPA in EMEA Q1FY26.
What is the average ARR per unit for Digital Experience Q1FY26?
Account Lookup

What is the total quantity for HSBC Q1FY26?
Give me Siemens user count Q1FY26.
What is the quantity breakdown by product for Barclays Q1FY26?
Ranking

Show top 10 accounts by quantity in Q1FY26.
Give me top 5 accounts by ZIA quantity in EMEA Q1FY26.
What are the top 5 SKUs by quantity in Q1FY26?
Trend / Delta

What is the quantity growth for ZIA from Q1FY26 to Q2FY26?
Show me delta percent for ZPA quantity between Q1FY26 and Q2FY26.
What is the total quantity trend by quarter for FY26?