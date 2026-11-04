"""
Stage 3 — Clarification Gate + Answerability Classifier.

Collects user answers for all S2 ambiguities, then:
  - Builds a clarification addendum text to re-run through S1+S2 (one hop max)
  - Pins definitively resolved entities (company) so S2 skips re-resolution
  - Classifies the query as ANSWERABLE or NOT_ANSWERABLE

Returns ClarificationResult — main.py drives the one-hop re-run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import difflib

from core.config import get_schema
from core.db import query_all
from core.fiscal import quarter_of
from pipeline.models import AccountFilter, CompanyMatch, Fiscal, ProductFilter, ResolvedEntities

_BOLD  = "\033[1m"
_CYAN  = "\033[96m"
_DIM   = "\033[2m"
_GREEN = "\033[92m"
_RED   = "\033[91m"
_RESET = "\033[0m"
_BOX_W = 72


@dataclass
class ClarificationResult:
    """What S3 hands back to main.py."""
    addendum:        str                      = ""    # text appended to original query for LLM re-run
    pinned_company:  Optional[CompanyMatch]   = None  # single resolved company
    pinned_companies: list[CompanyMatch]      = field(default_factory=list)  # confirmed multi-account list
    pinned_fiscal:   Optional[Fiscal]         = None  # already resolved — skip S1 fiscal parsing
    # hierarchy choices; None = not asked, [] = asked and the user chose no product filter
    pinned_products: Optional[list[ProductFilter]] = None
    cancelled:       bool                     = False
    answerable:      bool                     = True
    not_answerable_reason: str               = ""


def _box(lines: list[str]) -> None:
    print(f"  ┌{'─' * (_BOX_W - 2)}┐")
    for line in lines:
        pad = _BOX_W - 4 - len(line)
        print(f"  │ {line}{' ' * max(0, pad)} │")
    print(f"  └{'─' * (_BOX_W - 2)}┘")


# ── Individual question prompts ───────────────────────────────────────────────

_ALL_ACCOUNTS = CompanyMatch(account_id="__all__", account_name="All accounts (no filter)", score=1.0)


def _ask_company(matches: list[CompanyMatch]) -> CompanyMatch:
    """Return chosen match, or _ALL_ACCOUNTS sentinel to proceed without a company filter.

    'None of these' no longer cancels — it continues without a company filter so the
    query still runs globally rather than being blocked.
    """
    lines = [f"{_BOLD}Which company did you mean?{_RESET}", ""]
    for i, m in enumerate(matches, 1):
        bar = "●" if m.score >= 0.95 else ("○" if m.score >= 0.75 else "·")
        lines.append(f"  {i}. {bar} {m.account_name:<40} score: {m.score:.2f}")
    lines.append(f"  {len(matches)+1}. None of these — search is different company / continue without filter")
    lines.append(f"  {len(matches)+2}. All accounts (no company filter)")
    lines.append("")
    lines.append(f"  {_DIM}Press Enter for default [{matches[0].account_name}]{_RESET}")
    _box(lines)
    while True:
        raw = input(f"  {_CYAN}Your choice [1–{len(matches)+2}]: {_RESET}").strip()
        if raw == "":
            return matches[0]
        try:
            idx = int(raw)
            if idx in (len(matches) + 1, len(matches) + 2):
                # Both "none of these" and "all accounts" → continue without filter
                print(f"  {_DIM}Continuing without a company filter — querying all accounts.{_RESET}")
                return _ALL_ACCOUNTS
            if 1 <= idx <= len(matches):
                return matches[idx - 1]
        except ValueError:
            pass
        print(f"  Enter a number between 1 and {len(matches)+2}.")


def _confirm_multi_account(
    matches: list[CompanyMatch],
    typed_names: list[str],
) -> list[CompanyMatch]:
    """Show each typed name → resolved name pair and let the user confirm, swap, or drop each.

    Returns the confirmed list of CompanyMatch objects to proceed with.
    """
    from rapidfuzz import fuzz as _rfuzz

    confirmed: list[CompanyMatch] = []
    for m in matches:
        raw = m.matched_raw or m.account_name
        similarity = _rfuzz.WRatio(raw.lower(), m.account_name.lower()) / 100.0
        match_flag = "●" if similarity >= 0.90 else ("○" if similarity >= 0.70 else "·")

        lines = [
            f"{_BOLD}Confirm company match{_RESET}",
            "",
            f"  You typed:    {_BOLD}{raw}{_RESET}",
            f"  We found:     {match_flag} {m.account_name}  (score: {similarity:.2f})",
            "",
            f"  1. ✓  Yes — use '{m.account_name}'",
            f"  2. ✗  No  — skip this company (don't filter by it)",
            f"  3. ?  Search for a different name",
            "",
            f"  {_DIM}Press Enter to accept [{m.account_name}]{_RESET}",
        ]
        _box(lines)

        while True:
            ans = input(f"  {_CYAN}Your choice [1–3]: {_RESET}").strip()
            if ans in ("", "1"):
                confirmed.append(m)
                break
            elif ans == "2":
                print(f"  {_DIM}Skipping '{raw}' — not filtering by this company.{_RESET}")
                break
            elif ans == "3":
                search = input(f"  {_CYAN}Enter company name to search: {_RESET}").strip()
                if search:
                    from pipeline.s2_resolve import _search_company_trgm, _search_company_ilike, _trgm_available
                    fn = _search_company_trgm if _trgm_available() else _search_company_ilike
                    hits = fn(search)[:5]
                    if hits:
                        choice = _ask_company(hits)
                        if choice.account_id != "__all__":
                            confirmed.append(choice)
                    else:
                        print(f"  {_DIM}No matches found for '{search}'.{_RESET}")
                break
            else:
                print("  Enter 1, 2, or 3.")

    return confirmed


def _ask_product(raw_name: str, candidates: list[str]) -> Optional[str]:
    lines = [f"{_BOLD}Which product did you mean by '{raw_name}'?{_RESET}", ""]
    for i, c in enumerate(candidates, 1):
        lines.append(f"  {i}. {c}")
    lines.append(f"  {len(candidates)+1}. None of these — skip product filter")
    lines.append("")
    lines.append(f"  {_DIM}Press Enter to use '{candidates[0]}'{_RESET}")
    _box(lines)
    while True:
        raw = input(f"  {_CYAN}Your choice [1–{len(candidates)+1}]: {_RESET}").strip()
        if raw == "":
            return candidates[0]
        try:
            idx = int(raw)
            if idx == len(candidates) + 1:
                return None
            if 1 <= idx <= len(candidates):
                return candidates[idx - 1]
        except ValueError:
            pass
        print(f"  Enter a number between 1 and {len(candidates)+1}.")


def _ask_product_hierarchy(phrase: str, paths: list[list[str]]) -> Optional[ProductFilter]:
    """Ask which place in the product hierarchy a phrase means; None = no product filter."""
    lines = [f"{_BOLD}'{phrase}' exists in more than one place in the product hierarchy. Which one?{_RESET}", ""]
    for i, p in enumerate(paths, 1):
        lines.append(f"  {i}. {' › '.join(p)}  {_DIM}(level {len(p)}){_RESET}")
    lines.append(f"  {len(paths)+1}. No product filter (all products)")
    lines.append("")
    lines.append(f"  {_DIM}Press Enter for option 1{_RESET}")
    _box(lines)
    while True:
        raw = input(f"  {_CYAN}Your choice [1–{len(paths)+1}]: {_RESET}").strip()
        if raw == "":
            return ProductFilter.from_path(tuple(paths[0]))
        try:
            idx = int(raw)
            if idx == len(paths) + 1:
                return None
            if 1 <= idx <= len(paths):
                return ProductFilter.from_path(tuple(paths[idx - 1]))
        except ValueError:
            pass
        print(f"  Enter a number between 1 and {len(paths)+1}.")


def _ask_metric(metric_raw: str) -> str:
    options = ["ARR", "ACV", "INCR_ARR", "CHURN"]
    lines = [
        f"{_BOLD}Metric '{metric_raw}' is ambiguous. Which metric?{_RESET}", "",
    ]
    for i, m in enumerate(options, 1):
        lines.append(f"  {i}. {m}")
    lines.append("")
    lines.append(f"  {_DIM}Press Enter for ARR{_RESET}")
    _box(lines)
    while True:
        raw = input(f"  {_CYAN}Your choice [1–{len(options)}]: {_RESET}").strip()
        if raw == "":
            return "ARR"
        try:
            idx = int(raw)
            if 1 <= idx <= len(options):
                return options[idx - 1]
        except ValueError:
            pass
        print(f"  Enter a number between 1 and {len(options)}.")


def _ask_geo(invalid: list[str]) -> list[str]:
    options = ["Americas", "APJ", "EMEA", "All regions (no geo filter)"]
    lines = [f"{_BOLD}Geo '{invalid}' not recognised. Which region?{_RESET}", ""]
    for i, g in enumerate(options, 1):
        lines.append(f"  {i}. {g}")
    _box(lines)
    while True:
        raw = input(f"  {_CYAN}Your choice [1–{len(options)}]: {_RESET}").strip()
        try:
            idx = int(raw)
            if idx == len(options):
                return []
            if 1 <= idx <= len(options) - 1:
                return [options[idx - 1]]
        except ValueError:
            pass
        print(f"  Enter a number between 1 and {len(options)}.")


# ── Zscaler fiscal calendar helpers ──────────────────────────────────────────
# FY label = calendar year when the FY ends (July 31).
# Q1 Aug–Oct | Q2 Nov–Jan | Q3 Feb–Apr | Q4 May–Jul

import re as _re
from datetime import date as _date


_zs_fy_quarter = quarter_of


def _prev_fq(fy_label: str, q: int) -> tuple[str, str]:
    fy = int(fy_label.split()[1])
    if q == 1:
        return f"FY {fy - 1}", f"FY {fy - 1} Q4"
    return fy_label, f"{fy_label} Q{q - 1}"


def _all_quarters_for_fy(fy_label: str, db_quarters: list[str]) -> list[str]:
    """DB quarters for this FY, or synthetic Q1-Q4 if none in DB."""
    found = sorted(q for q in db_quarters if q.startswith(fy_label + " Q"))
    return found or [f"{fy_label} Q{i}" for i in range(1, 5)]


def _parse_manual(text: str) -> Optional[Fiscal]:
    """
    Parse a free-form fiscal string typed by the user.
    Supports:
      'FY 2026 Q1'  →  single quarter
      'FY 2026'     →  full year (no quarter expansion here — S4 uses fiscal_year_label)
      'FY 2025 Q2 to FY 2026 Q3'  →  range (quarter_labels filled by caller)
    """
    text = text.strip()
    # Range: "FY YYYY Q# to FY YYYY Q#"
    m = _re.match(
        r"(FY\s*\d{4}\s*Q[1-4])\s*(?:to|–|-)\s*(FY\s*\d{4}\s*Q[1-4])",
        text, _re.IGNORECASE,
    )
    if m:
        start = _re.sub(r"\s+", " ", m.group(1).upper().replace("FY", "FY ").strip())
        end   = _re.sub(r"\s+", " ", m.group(2).upper().replace("FY", "FY ").strip())
        return Fiscal(is_range=True, quarter_labels=[start, end])  # _expand_range fills rest

    # Single quarter "FY 2026 Q1"
    m = _re.match(r"FY\s*(\d{4})\s*Q([1-4])", text, _re.IGNORECASE)
    if m:
        fy, q = int(m.group(1)), int(m.group(2))
        fyl = f"FY {fy}"
        fql = f"{fyl} Q{q}"
        return Fiscal(fy=fy, quarter=q, fiscal_year_label=fyl, fiscal_quarter_label=fql)

    # Full year "FY 2026"
    m = _re.match(r"FY\s*(\d{4})$", text.strip(), _re.IGNORECASE)
    if m:
        fy  = int(m.group(1))
        fyl = f"FY {fy}"
        return Fiscal(fy=fy, fiscal_year_label=fyl)

    return None


def _available_quarters() -> list[str]:
    """Fetch all distinct fiscal quarters from DB, most-recent first."""
    try:
        rows = query_all(
            "SELECT DISTINCT fiscal_quarter FROM data_arr "
            "WHERE fiscal_quarter IS NOT NULL "
            "ORDER BY fiscal_quarter DESC",
            {},
        )
        return [r["fiscal_quarter"] for r in rows]
    except Exception:
        return []


def _quarters_between(start: str, end: str, all_quarters: list[str]) -> list[str]:
    """All quarters in all_quarters between start and end (inclusive), oldest→newest."""
    if start not in all_quarters or end not in all_quarters:
        return []
    i1, i2 = all_quarters.index(start), all_quarters.index(end)
    lo, hi = min(i1, i2), max(i1, i2)
    return list(reversed(all_quarters[lo:hi + 1]))


def _ask_fiscal(warning: str | None = None) -> Optional[Fiscal]:
    """
    Interactive fiscal period chooser anchored on today's Zscaler fiscal date.
    Returns a pinned Fiscal or None to cancel.
    """
    db_quarters = _available_quarters()
    today = _date.today()
    cur_fyl, cur_fql = _zs_fy_quarter(today)
    prev_fyl, prev_fql = _prev_fq(cur_fyl, int(cur_fql[-1]))
    prev_prev_fyl = f"FY {int(cur_fyl.split()[1]) - 1}"

    header = (f"{_BOLD}⚠  Fiscal period not found — please choose:{_RESET}"
              if warning else f"{_BOLD}Which fiscal period?{_RESET}")

    # ── Build the option list ─────────────────────────────────────────────────
    # Sentinel values: None = range picker, "MANUAL" = free-text entry
    _RANGE  = "__range__"
    _MANUAL = "__manual__"
    options: list[tuple[str, object]] = []

    # Current quarter (computed from today)
    options.append((
        f"{cur_fql}  {_DIM}← current quarter (today: {today}){_RESET}",
        Fiscal(fiscal_quarter_label=cur_fql, fiscal_year_label=cur_fyl),
    ))

    # Previous quarter
    options.append((
        f"{prev_fql}  {_DIM}← previous quarter{_RESET}",
        Fiscal(fiscal_quarter_label=prev_fql, fiscal_year_label=prev_fyl),
    ))

    # Full current FY
    cur_fy_qs = _all_quarters_for_fy(cur_fyl, db_quarters)
    options.append((
        f"All of {cur_fyl}  {_DIM}({', '.join(cur_fy_qs)}){_RESET}",
        Fiscal(fiscal_year_label=cur_fyl, quarter_labels=cur_fy_qs,
               is_range=len(cur_fy_qs) > 1),
    ))

    # Full previous FY
    prev_fy_qs = _all_quarters_for_fy(prev_fyl, db_quarters)
    options.append((
        f"All of {prev_fyl}  {_DIM}({', '.join(prev_fy_qs)}){_RESET}",
        Fiscal(fiscal_year_label=prev_fyl, quarter_labels=prev_fy_qs,
               is_range=len(prev_fy_qs) > 1),
    ))

    # Full FY two years ago
    prev2_fy_qs = _all_quarters_for_fy(prev_prev_fyl, db_quarters)
    options.append((
        f"All of {prev_prev_fyl}",
        Fiscal(fiscal_year_label=prev_prev_fyl, quarter_labels=prev2_fy_qs,
               is_range=len(prev2_fy_qs) > 1),
    ))

    options.append(("Range: pick start → end quarter", _RANGE))
    options.append((f"Enter manually  {_DIM}(e.g. FY 2026 Q1 or FY 2025 Q3 to FY 2026 Q2){_RESET}", _MANUAL))
    options.append(("No time filter (all periods)", Fiscal()))

    lines = [header, ""]
    if warning:
        lines += [f"  {_DIM}{warning}{_RESET}", ""]
    for i, (label, _) in enumerate(options, 1):
        lines.append(f"  {i}. {label}")
    lines.append("")
    lines.append(f"  {_DIM}Press Enter for {cur_fql} (current){_RESET}")
    _box(lines)

    while True:
        raw = input(f"  {_CYAN}Your choice [1–{len(options)}]: {_RESET}").strip()
        if raw == "":
            return options[0][1]  # type: ignore[return-value]
        try:
            idx = int(raw)
            if 1 <= idx <= len(options):
                _, val = options[idx - 1]
                if val == _RANGE:
                    return _ask_fiscal_range(db_quarters or [cur_fql, prev_fql])
                if val == _MANUAL:
                    return _ask_fiscal_manual(db_quarters)
                return val  # type: ignore[return-value]
        except ValueError:
            pass
        print(f"  Enter a number between 1 and {len(options)}.")


def _ask_fiscal_range(quarters: list[str]) -> Optional[Fiscal]:
    """Pick start + end from the numbered list; expand to all quarters in between."""
    for label, prompt_for in (("start", "Start"), ("end", "End")):
        lines = [f"{_BOLD}Range — pick {label} quarter:{_RESET}", ""]
        for i, q in enumerate(quarters, 1):
            lines.append(f"  {i}. {q}")
        _box(lines)
        chosen = None
        while chosen is None:
            raw = input(f"  {_CYAN}{prompt_for} quarter [1–{len(quarters)}]: {_RESET}").strip()
            try:
                idx = int(raw)
                if 1 <= idx <= len(quarters):
                    chosen = quarters[idx - 1]
            except ValueError:
                pass
        if label == "start":
            start_q = chosen
        else:
            end_q = chosen

    labels = _quarters_between(start_q, end_q, quarters)
    if not labels:
        labels = sorted([start_q, end_q])
    print(f"  {_GREEN}✓{_RESET}  Range: {labels[0]} → {labels[-1]}  ({len(labels)} quarters)")
    return Fiscal(
        fiscal_quarter_label=labels[0] if len(labels) == 1 else None,
        fiscal_year_label=labels[0].rsplit(" Q", 1)[0] if len(labels) == 1 else None,
        quarter_labels=labels,
        is_range=len(labels) > 1,
    )


def _ask_fiscal_manual(db_quarters: list[str]) -> Optional[Fiscal]:
    """Free-text entry: 'FY 2026 Q1', 'FY 2026', or 'FY 2025 Q3 to FY 2026 Q2'."""
    print(f"\n  {_DIM}Examples: FY 2026 Q1  |  FY 2026  |  FY 2025 Q3 to FY 2026 Q2{_RESET}")
    while True:
        raw = input(f"  {_CYAN}Fiscal period: {_RESET}").strip()
        if not raw:
            continue
        fiscal = _parse_manual(raw)
        if fiscal is None:
            print("  Couldn't parse that. Try: FY 2026 Q1 or FY 2025 Q3 to FY 2026 Q2")
            continue
        # Expand range if two endpoints given
        if fiscal.is_range and len(fiscal.quarter_labels) == 2:
            start, end = fiscal.quarter_labels
            expanded = _quarters_between(start, end, db_quarters)
            if not expanded:
                expanded = sorted([start, end])
            fiscal = Fiscal(
                quarter_labels=expanded,
                is_range=len(expanded) > 1,
                fiscal_quarter_label=expanded[0] if len(expanded) == 1 else None,
                fiscal_year_label=expanded[0].rsplit(" Q", 1)[0] if len(expanded) == 1 else None,
            )
        desc = (f"{fiscal.quarter_labels[0]} → {fiscal.quarter_labels[-1]}"
                if fiscal.quarter_labels else
                fiscal.fiscal_quarter_label or fiscal.fiscal_year_label or "no filter")
        print(f"  {_GREEN}✓{_RESET}  Accepted: {desc}")
        return fiscal


# ── Answerability classifier ──────────────────────────────────────────────────

_QUICK_COMPANY_FLOOR = 0.85   # Case-B disambiguation needs a very confident company hit


def _quick_company_lookup(term: str) -> list[CompanyMatch]:
    """Trigram similarity company lookup. Only returns matches above a high floor
    so Case-B (product term also being a company) only fires on strong hits."""
    try:
        rows = query_all(
            """
            SELECT account_id::text AS account_id, account_name,
                   similarity(account_name, %(t)s) AS score
            FROM dim_account
            WHERE account_name %% %(t)s
            ORDER BY score DESC, arr DESC NULLS LAST
            LIMIT 3
            """,
            {"t": term},
        )
    except Exception:
        return []
    return [
        CompanyMatch(account_id=r["account_id"], account_name=r["account_name"],
                     score=float(r["score"]))
        for r in rows
        if float(r["score"]) >= _QUICK_COMPANY_FLOOR
    ]


def _fuzzy_product_match(term: str) -> str | None:
    """Return the canonical product alias if `term` fuzzy-matches one (cutoff 0.80), else None."""
    aliases = get_schema().get("product_aliases", {})
    keys = list(aliases.keys())
    hits = difflib.get_close_matches(term.upper(), keys, n=1, cutoff=0.80)
    return aliases[hits[0]] if hits else None


def _ask_product_or_company(term: str, product: str, company: str) -> str:
    """Ask whether a term means a Zscaler product or a company name. Returns 'product' or 'company'."""
    lines = [
        f"{_BOLD}'{term}' could be a product or a company — which did you mean?{_RESET}", "",
        f"  1. Product  →  filter by Zscaler product '{product}'",
        f"  2. Company  →  filter by account '{company}'",
        "",
        f"  {_DIM}Press Enter for default [1. Product]{_RESET}",
    ]
    _box(lines)
    while True:
        raw = input(f"  {_CYAN}Your choice [1–2]: {_RESET}").strip()
        if raw in ("", "1"):
            return "product"
        if raw == "2":
            return "company"
        print("  Enter 1 or 2.")


def _classify(resolved: ResolvedEntities) -> tuple[bool, str]:
    """
    Returns (answerable, reason).
    A query is NOT answerable if it's fundamentally impossible to generate
    meaningful SQL from what we know.
    """
    ext = resolved.extracted

    # Company lookup with zero DB matches → can't filter by this company
    # Guard: if account_raw contains commas it was likely hallucinated from prompt examples — ignore it
    account_raw = ext.account_raw
    if account_raw and "," in account_raw:
        account_raw = None  # treat as no company filter

    if account_raw and not resolved.company_matches:
        # Company named in the query but zero DB matches — continue without a company
        # filter rather than blocking. The user can re-phrase or the query runs globally.
        # (Previously this blocked LOOKUP/RISK intents — now we always proceed.)
        pass  # handled in clarify() with a user-visible notice

    # Off-topic or non-analytics query
    if "not_arr_query" in ext.missing_critical:
        return False, (
            "I can only answer ARR and product analytics questions. "
            "Try something like: 'top 10 accounts by ARR in EMEA Q1FY26'."
        )
    # Critical fields missing that the user said are needed
    if ext.missing_critical:
        return False, f"Missing required information: {', '.join(ext.missing_critical)}"

    # LOOKUP intent needs a company — it can't return "all accounts"
    if ext.intent.value == "LOOKUP" and not ext.account_raw:
        return False, "LOOKUP intent requires a specific company name."

    return True, ""


# ── Public entry point ────────────────────────────────────────────────────────

def clarify(resolved: ResolvedEntities) -> ClarificationResult:
    """
    Present clarification card for all S2 ambiguities.
    Returns ClarificationResult that main.py uses for the one-hop LLM re-run.
    """
    result = ClarificationResult()

    # ── Answerability check first ─────────────────────────────────────────────
    answerable, reason = _classify(resolved)
    if not answerable:
        print(f"\n  {_RED}✗ NOT ANSWERABLE{_RESET}  {reason}")
        result.answerable = False
        result.not_answerable_reason = reason
        return result

    # ── Product-vs-Company disambiguation ────────────────────────────────────────
    # Two cases where the same term could mean a product or a company:
    #
    # Case A: Term was routed as a COMPANY (account_raw set, no product found)
    #         but also fuzzy-matches a product alias  → ask
    # Case B: Term was routed as a PRODUCT (product_filter set, no account)
    #         but also exists as a company in dim_account with high score → ask
    account_raw = resolved.extracted.account_raw

    # Case A: detected as company, but could be product
    if account_raw and resolved.company_matches and not resolved.product_filter:
        best_company = resolved.company_matches[0]
        product_hit = _fuzzy_product_match(account_raw)
        if product_hit and best_company.score >= 0.70:
            print(f"\n  {_BOLD}┄ Ambiguous term — need clarification ┄{_RESET}\n")
            choice = _ask_product_or_company(account_raw, product_hit, best_company.account_name)
            if choice == "product":
                result.addendum = f" for the {product_hit} product, no specific company filter"
                return result
            # else: keep company — fall through

    # Case B: detected as product, but could be a company
    if resolved.product_filter and not account_raw:
        for pf in resolved.product_filter:
            term = pf.path[-1] if pf.path else None   # deepest product node (e.g. "B2B")
            if not term:
                continue
            company_hits = _quick_company_lookup(term)
            if company_hits and company_hits[0].score >= 0.85:
                print(f"\n  {_BOLD}┄ Ambiguous term — need clarification ┄{_RESET}\n")
                product_display = " > ".join(pf.path) if pf.path else term
                choice = _ask_product_or_company(term, product_display, company_hits[0].account_name)
                if choice == "company":
                    # Pin the company AND clear products so main.py takes the
                    # inject path (no S1/S2 hop that would re-detect B2B as a product).
                    result.pinned_company  = company_hits[0]
                    result.pinned_products = []
                    result.addendum        = f" for {company_hits[0].account_name}"
                    return result
                break  # user chose product — keep resolved.product_filter, fall through

    if not resolved.ambiguities:
        return result  # clean pass-through

    print(f"\n  {_BOLD}┄ Clarification needed ({len(resolved.ambiguities)} item(s)) ┄{_RESET}\n")

    addendum_parts: list[str] = []
    questions_asked = 0

    # Q: Company ambiguity ────────────────────────────────────────────────────
    if "company" in resolved.ambiguities and questions_asked < 3:
        typed_names = getattr(resolved.extracted, "accounts_raw", None) or (
            [resolved.extracted.account_raw] if resolved.extracted.account_raw else []
        )
        is_multi = len(typed_names) > 1

        if not resolved.company_matches:
            # No matches at all — notify and continue without a company filter
            print(f"  {_DIM}Company '{resolved.extracted.account_raw}' not found — "
                  f"continuing without a company filter.{_RESET}")
            choice = _ALL_ACCOUNTS
            if choice.account_id == "__all__":
                addendum_parts.append("no specific company filter")

        elif is_multi:
            # Multi-account with low-confidence matches → confirm each one
            print(f"\n  {_BOLD}┄ Please confirm the companies we matched ┄{_RESET}\n")
            confirmed = _confirm_multi_account(resolved.company_matches, typed_names)
            if confirmed:
                if len(confirmed) == 1:
                    result.pinned_company = confirmed[0]
                    addendum_parts.append(f"the company is exactly '{confirmed[0].account_name}'")
                else:
                    result.pinned_companies = confirmed   # full list for main.py
                    result.pinned_company   = confirmed[0]  # primary (for compat)
                    names_str = " and ".join(f"'{c.account_name}'" for c in confirmed)
                    addendum_parts.append(f"the companies are exactly {names_str}")
            else:
                addendum_parts.append("no specific company filter")

        else:
            choice = _ask_company(resolved.company_matches)
            if choice.account_id == "__all__":
                addendum_parts.append("no specific company filter")
            else:
                result.pinned_company = choice
                addendum_parts.append(f"the company is exactly '{choice.account_name}'")

        questions_asked += 1

    # Q: Product ambiguity ────────────────────────────────────────────────────
    if "product" in resolved.ambiguities and questions_asked < 3:
        chosen_products: list[str] = []
        for raw_name, cands in resolved.product_candidates.items():
            if questions_asked >= 3:
                break
            chosen = _ask_product(raw_name, cands)
            if chosen:
                chosen_products.append(chosen)
            questions_asked += 1
        if chosen_products:
            addendum_parts.append(f"the product is {' and '.join(chosen_products)}")

    # Q: Product hierarchy — the phrase names more than one node in the product hierarchy ──
    if "product_hierarchy" in resolved.ambiguities and questions_asked < 3:
        pinned: list[ProductFilter] = []
        for phrase, paths in resolved.product_hierarchy_candidates.items():
            if questions_asked >= 3:
                break
            chosen = _ask_product_hierarchy(phrase, paths)
            questions_asked += 1
            if chosen:
                pinned.append(chosen)
                addendum_parts.append(f"the product is {' > '.join(chosen.path)}")
        result.pinned_products = pinned

    # Q: Metric ambiguity ─────────────────────────────────────────────────────
    if "metric" in resolved.ambiguities and questions_asked < 3:
        chosen_metric = _ask_metric(resolved.extracted.metric_raw)
        addendum_parts.append(f"the metric is {chosen_metric}")
        questions_asked += 1

    # Q: Geo ambiguity ────────────────────────────────────────────────────────
    if "geo" in resolved.ambiguities and questions_asked < 3:
        chosen_geo = _ask_geo(resolved.geo_invalid)
        if chosen_geo:
            addendum_parts.append(f"the geography is {chosen_geo[0]}")
        questions_asked += 1

    # Q: Fiscal (missing or invalid) ─────────────────────────────────────────
    if "fiscal" in resolved.ambiguities and questions_asked < 3:
        warning = resolved.fiscal_warning if not resolved.fiscal.fiscal_quarter_label \
                  and not resolved.fiscal.fiscal_year_label else None
        chosen_fiscal = _ask_fiscal(warning)
        if chosen_fiscal is None:
            result.cancelled = True
            return result
        result.pinned_fiscal = chosen_fiscal
        # Build addendum label for display only (fiscal is pinned — not re-parsed by S1)
        if chosen_fiscal.quarter_labels:
            fq_label = f"{chosen_fiscal.quarter_labels[0]} → {chosen_fiscal.quarter_labels[-1]}"
        elif chosen_fiscal.fiscal_quarter_label:
            fq_label = chosen_fiscal.fiscal_quarter_label
        elif chosen_fiscal.fiscal_year_label:
            fq_label = chosen_fiscal.fiscal_year_label
        else:
            fq_label = "no filter"
        addendum_parts.append(f"fiscal period is {fq_label}")
        questions_asked += 1

    # Build addendum for LLM re-run
    if addendum_parts:
        result.addendum = " [Clarification: " + "; ".join(addendum_parts) + "]"
        print(f"\n  {_GREEN}✓{_RESET}  Re-running with: {result.addendum}")

    return result
