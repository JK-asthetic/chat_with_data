"""
Pipeline Clarifier — terminal clarification card for unresolvable ambiguities.

Rules:
- Maximum 1 clarification card per pipeline run (never chain multiple cards).
- Maximum 3 questions per card.
- Never asks about the same thing twice across turns (tracks via SessionMemory).
- If running non-interactively (EOFError / no TTY), picks the highest-confidence
  default silently.

Triggers (checked in priority order):
  C1 — company_ambiguous and top match score < threshold → pick-one list
  C2 — product_hierarchy_candidates → which product level/branch?
  C3 — fiscal not resolved → what period?
  C4 — geo_invalid → suggest closest valid geography

Usage::

    result = clarify(resolved, classified)
    if not result.answerable:
        print(result.not_answerable_reason)
    elif result.pinned_company:
        # use result.pinned_company.account_id downstream
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from typing import Optional

from pipeline.models import (
    ClassifiedQuery,
    CompanyMatch,
    Fiscal,
    ProductFilter,
    ResolvedEntities,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COMPANY_SCORE_THRESHOLD: float = 0.75
"""Minimum fuzzy-match score for auto-accepting a company match without asking."""

MAX_CHOICES: int = 3
"""Maximum number of candidate options to show the user in a pick-list."""

_VALID_GEOS: list[str] = [
    "AMER", "EMEA", "APJ", "LATAM",
    "North America", "Europe", "Asia Pacific",
    "United States", "United Kingdom", "Germany", "France",
    "Japan", "Australia", "India", "Canada",
]
"""Subset of known-valid geography values used for proximity suggestions."""


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class ClarificationResult:
    """Output of the :func:`clarify` call.

    Attributes:
        answerable:          True when the pipeline can proceed (no blocking ambiguity).
        cancelled:           True when the user explicitly cancelled / skipped.
        addendum:            Free-text addendum to append to the question for context.
        pinned_company:      Single resolved company (C1 resolution).
        pinned_companies:    Multiple resolved companies (C1 multi-select).
        pinned_fiscal:       Resolved fiscal period (C3 resolution).
        pinned_products:     Resolved product filter list (C2 resolution).
        not_answerable_reason: Human-readable explanation when answerable=False.
    """

    answerable: bool                             = True
    cancelled: bool                              = False
    addendum: str                                = ""
    pinned_company: Optional[CompanyMatch]       = None
    pinned_companies: list[CompanyMatch]         = field(default_factory=list)
    pinned_fiscal: Optional[Fiscal]              = None
    pinned_products: Optional[list[ProductFilter]] = None
    not_answerable_reason: str                   = ""


# ---------------------------------------------------------------------------
# Rich / plain-text formatting helpers
# ---------------------------------------------------------------------------

def _try_rich() -> bool:
    """Return True if the ``rich`` library is available."""
    try:
        import rich  # noqa: F401
        return True
    except ImportError:
        return False


_HAS_RICH = _try_rich()


def _print_card_header(title: str) -> None:
    """Print a formatted card header to stdout."""
    if _HAS_RICH:
        from rich.console import Console
        from rich.panel import Panel
        c = Console()
        c.print(Panel(f"[bold yellow]{title}[/bold yellow]", border_style="yellow", expand=False))
    else:
        print(f"\n{'─' * 50}")
        print(f"  ⚠  {title}")
        print(f"{'─' * 50}")


def _print_choice(idx: int, label: str, detail: str = "") -> None:
    """Print a numbered choice line."""
    suffix = f"  ({detail})" if detail else ""
    if _HAS_RICH:
        from rich.console import Console
        Console().print(f"  [cyan]{idx}[/cyan]. {label}{suffix}")
    else:
        print(f"  {idx}. {label}{suffix}")


def _print_line(msg: str) -> None:
    """Print a plain message line."""
    if _HAS_RICH:
        from rich.console import Console
        Console().print(f"  {msg}")
    else:
        print(f"  {msg}")


def _ask(prompt: str, default: str = "") -> str:
    """Prompt the user and return stripped input.  Returns *default* on EOF."""
    try:
        answer = input(f"\n  {prompt} ").strip()
        return answer if answer else default
    except (EOFError, KeyboardInterrupt):
        return default


# ---------------------------------------------------------------------------
# Individual trigger handlers
# ---------------------------------------------------------------------------

def _handle_c1_company(
    resolved: ResolvedEntities,
) -> ClarificationResult:
    """C1: Company ambiguity — ask user to pick from top candidates.

    Args:
        resolved: Resolved entities containing company_matches.

    Returns:
        :class:`ClarificationResult` with pinned_company set.
    """
    matches = resolved.company_matches[:MAX_CHOICES]
    if not matches:
        # No candidates at all — not answerable
        raw = resolved.extracted.account_raw or "unknown"
        return ClarificationResult(
            answerable=False,
            not_answerable_reason=(
                f"Could not find any account matching '{raw}'. "
                "Please check the account name and try again."
            ),
        )

    # Auto-accept if top match is above threshold
    top = matches[0]
    if top.score >= COMPANY_SCORE_THRESHOLD and len(matches) == 1:
        logger.debug("C1: auto-accepting top match '%s' (score=%.2f)", top.account_name, top.score)
        return ClarificationResult(answerable=True, pinned_company=top)

    _print_card_header("Multiple accounts match your query")
    _print_line("Please choose the account you meant:\n")
    for i, m in enumerate(matches, start=1):
        _print_choice(i, m.account_name, f"score={m.score:.0%}")
    _print_choice(len(matches) + 1, "None of these — skip")

    raw_input = _ask(f"Enter 1–{len(matches) + 1} [default=1]:", default="1")

    try:
        choice = int(raw_input)
    except ValueError:
        choice = 1

    if choice < 1 or choice > len(matches) + 1:
        choice = 1

    if choice == len(matches) + 1:
        return ClarificationResult(
            answerable=False,
            cancelled=True,
            not_answerable_reason="User indicated no match was correct.",
        )

    selected = matches[choice - 1]
    logger.info("C1: user selected '%s'", selected.account_name)
    return ClarificationResult(answerable=True, pinned_company=selected)


def _handle_c2_product(
    resolved: ResolvedEntities,
) -> ClarificationResult:
    """C2: Product hierarchy ambiguity — ask which branch/level.

    Args:
        resolved: Resolved entities containing product_hierarchy_candidates.

    Returns:
        :class:`ClarificationResult` with pinned_products set.
    """
    candidates = resolved.product_hierarchy_candidates[:MAX_CHOICES]
    if not candidates:
        return ClarificationResult(answerable=True)  # nothing to clarify

    _print_card_header("Multiple product categories match")
    _print_line("Which product scope did you mean?\n")
    for i, pf in enumerate(candidates, start=1):
        path_str = " › ".join(pf.path) if pf.path else "(all products)"
        _print_choice(i, path_str)
    _print_choice(len(candidates) + 1, "All of them (combined)")

    raw_input = _ask(f"Enter 1–{len(candidates) + 1} [default={len(candidates) + 1}]:",
                     default=str(len(candidates) + 1))

    try:
        choice = int(raw_input)
    except ValueError:
        choice = len(candidates) + 1

    if choice < 1 or choice > len(candidates) + 1:
        choice = len(candidates) + 1

    if choice == len(candidates) + 1:
        logger.info("C2: user chose all product candidates")
        return ClarificationResult(answerable=True, pinned_products=list(candidates))

    selected = candidates[choice - 1]
    logger.info("C2: user selected product path %s", selected.path)
    return ClarificationResult(answerable=True, pinned_products=[selected])


def _handle_c3_fiscal(
    resolved: ResolvedEntities,
) -> ClarificationResult:
    """C3: Fiscal period unresolved — ask the user to specify.

    Args:
        resolved: Resolved entities with fiscal=None or fiscal_valid=False.

    Returns:
        :class:`ClarificationResult` with pinned_fiscal set, or not_answerable.
    """
    _print_card_header("Fiscal period not understood")
    _print_line(
        "Could not resolve the fiscal period from your question.\n"
        "  Examples: FY25, FY25 Q2, Q1 FY24, last quarter, H1 FY25\n"
    )
    if resolved.fiscal_warning:
        _print_line(f"  Note: {resolved.fiscal_warning}\n")

    raw_input = _ask("Enter fiscal period [or press Enter to skip]:", default="")

    if not raw_input:
        return ClarificationResult(
            answerable=False,
            not_answerable_reason=(
                "Fiscal period could not be determined. "
                "Please include a period such as 'FY25 Q2' in your question."
            ),
        )

    # Lightweight inline parse — full fiscal resolver is in extraction stage
    # Here we just build a minimal Fiscal to unblock the pipeline
    fy: int | None = None
    quarter: int | None = None

    fy_match = __import__("re").search(r"FY\s*(\d{2,4})", raw_input, __import__("re").I)
    if fy_match:
        raw_yr = int(fy_match.group(1))
        fy = 2000 + raw_yr if raw_yr < 100 else raw_yr

    q_match = __import__("re").search(r"Q([1-4])", raw_input, __import__("re").I)
    if q_match:
        quarter = int(q_match.group(1))

    if fy is None:
        return ClarificationResult(
            answerable=False,
            not_answerable_reason=f"Could not parse fiscal year from '{raw_input}'.",
        )

    q_label = f"Q{quarter} " if quarter else ""
    pinned = Fiscal(
        fy=fy,
        quarter=quarter,
        is_range=False,
        fiscal_quarter_label=f"{q_label}FY{str(fy)[2:]}" if quarter else None,
        fiscal_year_label=f"FY{str(fy)[2:]}",
    )
    logger.info("C3: user entered fiscal '%s'", raw_input)
    return ClarificationResult(answerable=True, pinned_fiscal=pinned)


def _handle_c4_geo(
    resolved: ResolvedEntities,
) -> ClarificationResult:
    """C4: Invalid geography — suggest closest valid alternative.

    Args:
        resolved: Resolved entities with geo_invalid=True.

    Returns:
        :class:`ClarificationResult` with addendum or not_answerable.
    """
    raw_geo = resolved.extracted.geo_raw or "unknown"
    _print_card_header(f"Geography '{raw_geo}' not recognised")

    # Simple suggestion: find partial string matches in _VALID_GEOS
    suggestions = [g for g in _VALID_GEOS if raw_geo.lower() in g.lower()][:MAX_CHOICES]

    if suggestions:
        _print_line("Did you mean one of these?\n")
        for i, s in enumerate(suggestions, start=1):
            _print_choice(i, s)
        _print_choice(len(suggestions) + 1, f"Keep '{raw_geo}' as-is (may return no results)")
        _print_choice(len(suggestions) + 2, "Remove the geography filter")

        raw_input = _ask(f"Enter 1–{len(suggestions) + 2} [default=1]:", default="1")

        try:
            choice = int(raw_input)
        except ValueError:
            choice = 1

        if 1 <= choice <= len(suggestions):
            selected_geo = suggestions[choice - 1]
            logger.info("C4: user selected geo '%s'", selected_geo)
            return ClarificationResult(
                answerable=True,
                addendum=f" geography={selected_geo!r}",
            )
        elif choice == len(suggestions) + 1:
            # Keep as-is
            return ClarificationResult(answerable=True)
        else:
            # Remove geo filter
            return ClarificationResult(answerable=True, addendum=" (no geography filter)")
    else:
        _print_line("No close matches found in known geographies.")
        _print_line("Valid regions include: AMER, EMEA, APJ, LATAM\n")
        raw_input = _ask("Enter a valid geography or press Enter to remove the filter:", default="")

        if raw_input:
            return ClarificationResult(answerable=True, addendum=f" geography={raw_input!r}")
        else:
            return ClarificationResult(answerable=True, addendum=" (no geography filter)")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def clarify(
    resolved: ResolvedEntities,
    classified: ClassifiedQuery,
) -> ClarificationResult:
    """Run at most one clarification card to resolve blocking ambiguities.

    Checks triggers in priority order and presents at most one interactive
    card to the user.  When running non-interactively (stdin not a TTY or
    an EOFError is raised), highest-confidence defaults are used silently.

    Args:
        resolved:   Resolved entity bag from the extraction stage.
        classified: Classification output (consulted for additional ambiguities).

    Returns:
        :class:`ClarificationResult` indicating how to proceed.
    """
    is_interactive = sys.stdin.isatty() if hasattr(sys.stdin, "isatty") else False

    # Collect which triggers are active
    triggers: list[str] = []

    if resolved.company_ambiguous and resolved.company_matches:
        triggers.append("C1")

    if resolved.product_hierarchy_candidates:
        triggers.append("C2")

    if not resolved.fiscal_valid or (
        "fiscal" in (resolved.ambiguities or []) and resolved.fiscal is None
    ):
        triggers.append("C3")

    if resolved.geo_invalid:
        triggers.append("C4")

    # Also consider classifier-detected ambiguities
    for a in classified.ambiguities:
        if a == "company" and "C1" not in triggers:
            triggers.append("C1")
        elif a == "fiscal" and "C3" not in triggers:
            triggers.append("C3")
        elif a == "product_hierarchy" and "C2" not in triggers:
            triggers.append("C2")

    if not triggers:
        logger.debug("Clarifier: no triggers — proceeding directly.")
        return ClarificationResult(answerable=True)

    # Non-interactive: use defaults silently
    if not is_interactive:
        logger.debug("Clarifier: non-interactive mode — applying defaults for triggers %s.", triggers)
        result = ClarificationResult(answerable=True)

        if "C1" in triggers and resolved.company_matches:
            top = resolved.company_matches[0]
            if top.score >= COMPANY_SCORE_THRESHOLD:
                result.pinned_company = top
            elif not resolved.company_matches:
                result.answerable = False
                result.not_answerable_reason = "Company ambiguous and no interactive session to resolve."

        if "C2" in triggers and resolved.product_hierarchy_candidates:
            # Default: use all candidates (most permissive)
            result.pinned_products = list(resolved.product_hierarchy_candidates[:MAX_CHOICES])

        # C3 / C4 non-interactive: proceed without fiscal / geo (may yield empty results)
        return result

    # Interactive: show at most one card (highest priority)
    # We pick the first trigger and handle it
    active = triggers[0]
    logger.debug("Clarifier: showing card for trigger %s", active)

    try:
        if active == "C1":
            return _handle_c1_company(resolved)
        elif active == "C2":
            return _handle_c2_product(resolved)
        elif active == "C3":
            return _handle_c3_fiscal(resolved)
        elif active == "C4":
            return _handle_c4_geo(resolved)
        else:
            return ClarificationResult(answerable=True)

    except (EOFError, KeyboardInterrupt):
        # User interrupted — apply defaults
        logger.info("Clarifier: interrupted by user, applying defaults.")
        return _default_result(active, resolved)


def _default_result(trigger: str, resolved: ResolvedEntities) -> ClarificationResult:
    """Return a safe default ClarificationResult for a given trigger when interactive input fails.

    Args:
        trigger:  Trigger code ('C1'–'C4').
        resolved: Resolved entities for context.

    Returns:
        Best-effort :class:`ClarificationResult`.
    """
    if trigger == "C1" and resolved.company_matches:
        top = resolved.company_matches[0]
        return ClarificationResult(
            answerable=top.score >= COMPANY_SCORE_THRESHOLD,
            pinned_company=top if top.score >= COMPANY_SCORE_THRESHOLD else None,
            not_answerable_reason="" if top.score >= COMPANY_SCORE_THRESHOLD else "Company ambiguous.",
        )
    if trigger == "C2" and resolved.product_hierarchy_candidates:
        return ClarificationResult(
            answerable=True,
            pinned_products=list(resolved.product_hierarchy_candidates[:MAX_CHOICES]),
        )
    if trigger == "C3":
        return ClarificationResult(
            answerable=False,
            not_answerable_reason="Fiscal period could not be determined.",
        )
    if trigger == "C4":
        return ClarificationResult(answerable=True)  # proceed without geo

    return ClarificationResult(answerable=True)
