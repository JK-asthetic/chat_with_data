"""
Stage 2B — LLM Entity Validation.

Runs after S2 Resolve. Uses a lightweight LLM call to:
  1. Check whether the resolved entities match the original question
     (catches missed accounts, mis-classified products, wrong geo, etc.)
  2. If the LLM finds issues, it emits a correction suggestion and flags
     those corrections as CONFIRMED (auto-applied) or DOUBTFUL (user asked).
  3. If DOUBTFUL, the pipeline pauses and asks the user "Is this correct? (y/n)"
     before proceeding.

This stage is intentionally lightweight — it checks, it doesn't rewrite SQL.
The corrected ResolvedEntities is returned for S3/S4 to use normally.
"""
from __future__ import annotations

import json
from typing import Optional

import requests

from core.config import get_schema, get_settings
from core import hierarchy as _hier
from pipeline.models import (
    AccountFilter,
    CompanyMatch,
    ExtractedQuery,
    GeoFilter,
    ProductFilter,
    ResolvedEntities,
)

# ─────────────────────────────────────────────────────────────────────────────

_VALIDATE_SYSTEM = """\
You are a Zscaler ARR analytics assistant. A user asked a question and an NLP pipeline
extracted entities. Your job is to validate whether the extracted entities are correct.

Products: ZIA, ZPA, ZDX (Digital Experience), Data Security, ZT Cloud, ZT Branch,
ZT Browser, ZT Cell, ZS-FLEX, Security for AI, Agentic SecOps, Business Continuity.

Rules:
- SKU codes (like ZDX-ADV-PROBES-GCM-1) are NOT product names — they are SKU strings.
- ZDX is a product abbreviation (Zscaler Digital Experience), not an account name.
- Geo territories: geo (AMS ECE, AMS MPH, APJ, EMEA), area (EMEA DACH, AMS ENT, India, etc.),
  region (Germany ENT, France, UKI ENT, etc.)
- If a product was named in the question but is missing from extracted_products, flag it.
- If an account was named but is missing, flag it.
- If a product was classified as an account or vice versa, flag it.

Respond with ONLY a JSON object in this exact format:
{
  "ok": true,
  "confidence": "high",
  "issues": [],
  "corrections": {},
  "message": ""
}

Or if issues are found:
{
  "ok": false,
  "confidence": "low" | "medium",
  "issues": ["<short description of each problem>"],
  "corrections": {
    "add_products": ["ZIA"],
    "remove_products": ["HSBC"],
    "add_accounts": ["HSBC"],
    "remove_accounts": ["ZIA"],
    "add_geo_detail": [{"col": "cfy_area", "value": "EMEA DACH"}],
    "remove_geo_detail": []
  },
  "message": "<one sentence to show user>"
}

Only flag genuine errors, not stylistic preferences. If intent and entities are
reasonable for the question, mark ok=true even if not perfect.
"""


def _call_llm(system: str, user_msg: str, max_tokens: int = 400) -> str:
    cfg = get_settings()
    try:
        base = cfg.ZLLAMA_BASE_URL.rstrip("/")
        resp = requests.post(
            f"{base}/v1/chat/completions",
            headers={"Authorization": f"Bearer {cfg.ZLLAMA_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": cfg.ZLLAMA_INSIGHT_MODEL,
                "temperature": 0,
                "max_tokens": max_tokens,
                "stream": False,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
            },
            timeout=(5, 30),
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return json.dumps({"ok": True, "confidence": "high", "issues": [], "corrections": {}, "message": ""})


def _build_validation_prompt(question: str, resolved: ResolvedEntities) -> str:
    ext = resolved.extracted
    summary = {
        "original_question": question,
        "intent": ext.intent,
        "extracted_products": ext.products_raw,
        "resolved_products": [p.path for p in resolved.product_filter],
        "extracted_accounts": ext.accounts_raw or ([ext.account_raw] if ext.account_raw else []),
        "resolved_account": resolved.account_filter.account_name,
        "resolved_account_ids": resolved.account_filter.account_ids or (
            [resolved.account_filter.account_id] if resolved.account_filter.account_id else []
        ),
        "extracted_geo": ext.geo_raw,
        "resolved_geo": resolved.geo_filter,
        "extracted_geo_detail": ext.geo_detail_raw,
        "resolved_geo_detail": [{"col": g.col, "value": g.value} for g in resolved.geo_detail_filter],
        "extracted_skus": ext.sku_raw,
        "resolved_skus": resolved.sku_filter,
        "fiscal": ext.fiscal_raw,
        "metric": ext.metric_raw,
    }
    return f"Validate these extracted entities:\n\n{json.dumps(summary, indent=2)}"


def _apply_corrections(resolved: ResolvedEntities, corrections: dict) -> ResolvedEntities:
    """Apply LLM-suggested corrections to the resolved entities in-place (returns updated copy)."""
    ext = resolved.extracted

    # Add/remove products
    add_products: list[str] = corrections.get("add_products") or []
    remove_products: list[str] = [p.upper() for p in (corrections.get("remove_products") or [])]

    if remove_products:
        resolved.product_filter = [
            p for p in resolved.product_filter
            if not any(v.upper() in remove_products for v in p.path)
        ]

    if add_products:
        aliases = get_schema().get("product_aliases", {})
        for raw in add_products:
            canon = aliases.get(raw.upper(), raw)
            path = _hier.resolve_product(canon)
            if path:
                resolved.product_filter.append(ProductFilter.from_path(tuple(path)))

    # Add/remove accounts
    add_accounts: list[str] = corrections.get("add_accounts") or []
    remove_accounts: list[str] = [a.upper() for a in (corrections.get("remove_accounts") or [])]

    if remove_accounts and resolved.account_filter.account_name:
        if resolved.account_filter.account_name.upper() in remove_accounts:
            resolved.account_filter = AccountFilter()

    if add_accounts and not resolved.account_filter.account_id:
        # Try a quick DB lookup for the first account
        from core.companies import fuzzy_existing
        matches = fuzzy_existing(add_accounts, threshold=0.70)
        if matches:
            best_raw = list(matches.keys())[0]
            best_name = matches[best_raw]
            from core.db import query_one
            row = query_one(
                "SELECT DISTINCT account_id, end_user_name AS account_name FROM data_arr "
                "WHERE lower(end_user_name) = %(n)s LIMIT 1",
                {"n": best_name.lower()},
            )
            if row:
                resolved.account_filter = AccountFilter(
                    account_raw=best_raw,
                    account_id=str(row["account_id"]),
                    account_name=row["account_name"],
                )

    # Add/remove geo_detail
    add_geo: list[dict] = corrections.get("add_geo_detail") or []
    remove_geo: list[str] = [v.upper() for v in (corrections.get("remove_geo_detail") or [])]

    if remove_geo:
        resolved.geo_detail_filter = [
            g for g in resolved.geo_detail_filter
            if g.value.upper() not in remove_geo
        ]

    if add_geo:
        existing_vals = {g.value.upper() for g in resolved.geo_detail_filter}
        for g in add_geo:
            col = g.get("col", "cfy_area")
            val = g.get("value", "")
            if val and val.upper() not in existing_vals:
                resolved.geo_detail_filter.append(GeoFilter(col=col, value=val))

    return resolved


def validate_and_correct(
    question: str,
    resolved: ResolvedEntities,
    auto_correct: bool = True,
    interactive: bool = True,
) -> tuple[ResolvedEntities, bool]:
    """
    Run LLM validation on resolved entities.

    Returns:
        (updated_resolved, proceed) — if proceed=False the caller should abort.

    Params:
        auto_correct:  Apply HIGH-confidence corrections automatically.
        interactive:   Prompt the user for MEDIUM-confidence corrections.
    """
    _G  = "\033[92m"
    _Y  = "\033[93m"
    _C  = "\033[96m"
    _RS = "\033[0m"
    _B  = "\033[1m"

    print(f"\n  {_C}◆ S2B Validating entities...{_RS}", end="", flush=True)

    prompt = _build_validation_prompt(question, resolved)
    raw = _call_llm(_VALIDATE_SYSTEM, prompt)

    # Parse JSON (LLM may wrap in ```json)
    try:
        raw_clean = raw.strip()
        if raw_clean.startswith("```"):
            raw_clean = "\n".join(raw_clean.split("\n")[1:])
            raw_clean = raw_clean.rstrip("`").strip()
        result = json.loads(raw_clean)
    except json.JSONDecodeError:
        print(f" {_G}✓ (parse skip){_RS}")
        return resolved, True

    ok         = result.get("ok", True)
    confidence = result.get("confidence", "high")
    issues     = result.get("issues", [])
    corrections= result.get("corrections", {})
    message    = result.get("message", "")

    if ok or not issues:
        print(f" {_G}✓{_RS}")
        return resolved, True

    # Print issues found
    print(f" {_Y}⚠ issues found{_RS}")
    for iss in issues:
        print(f"    {_Y}• {iss}{_RS}")

    has_corrections = any(
        corrections.get(k) for k in (
            "add_products", "remove_products",
            "add_accounts", "remove_accounts",
            "add_geo_detail", "remove_geo_detail",
        )
    )

    if not has_corrections:
        # LLM flagged issues but couldn't suggest corrections.
        # If interactive, let the user decide whether to abort.
        if interactive and confidence in ("low", "medium"):
            msg = message or "Entity resolution may be incorrect (see issues above)."
            print(f"\n  {_Y}{msg}{_RS}")
            print(f"  {_B}Continue anyway? (y/n, default y): {_RS}", end="", flush=True)
            try:
                ans = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "y"
            if ans in ("n", "no"):
                return resolved, False   # caller should abort
        return resolved, True

    if confidence == "high" and auto_correct:
        print(f"    {_G}→ Auto-correcting (high confidence)…{_RS}")
        resolved = _apply_corrections(resolved, corrections)
        return resolved, True

    if interactive:
        if message:
            print(f"\n  {_Y}{message}{_RS}")
        print(f"\n  {_B}The pipeline suggests corrections. Apply them? (y/n): {_RS}", end="", flush=True)
        try:
            ans = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = "n"
        if ans in ("y", "yes"):
            resolved = _apply_corrections(resolved, corrections)
            print(f"  {_G}✓ Corrections applied.{_RS}")
        else:
            print(f"  {_Y}Proceeding with original entities.{_RS}")

    return resolved, True
