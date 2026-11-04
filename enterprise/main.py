#!/usr/bin/env python3
"""
Enterprise Chat with Data — Terminal REPL
══════════════════════════════════════════
NL-to-SQL analytics pipeline powered by parallel Metric Agents.

Usage:
    python main.py                               # interactive REPL
    python main.py "top 10 ARR in EMEA FY 2026 Q1"  # single query

Supported metrics:
    ARR · ACV · NNACV · INCR_ARR · CHURN · NACV · QTY · RENEWAL_RISK · CHURN_REASON
"""
from __future__ import annotations

import sys
from rich.console import Console
from rich.panel import Panel

from pipeline.orchestrator import run, init_agent_registry
from pipeline.memory import SessionMemory
from response.formatter import display, display_error, console
from response.logger import SessionLogger

_BANNER = """
[bold cyan]╔══════════════════════════════════════════════════════════════════════╗
║              Enterprise Chat with Data — ARR Analytics               ║
║    Parallel Metric Agents · Deterministic Extractor · NL→SQL Cache   ║
║                       type /help for commands                        ║
╚══════════════════════════════════════════════════════════════════════╝[/bold cyan]
"""

_HELP = """
[bold yellow]Available Commands:[/bold yellow]
  /sql       Toggle SQL query visibility in output
  /clear     Clear session conversation memory
  /memory    Show active session context
  /help      Show this help message
  /quit      Exit the application

[bold yellow]Sample Queries:[/bold yellow]
  • top 10 accounts by ARR in EMEA for FY 2026 Q1
  • total ACV and ARR for Siemens in Q1 FY2026
  • ARR trend for Siemens by quarter in FY 2026
  • top customers by renewal risk score in Americas
  • churn breakdown and lost ARR by segment in Q1 FY26
  • how should we optimize marketing budget across EMEA?
"""


def repl() -> None:
    console.print(_BANNER)
    console.print("  [dim]Initializing metric agents...[/dim]", end="\r")
    agents = init_agent_registry()
    console.print(f"  [green]✓[/green] [dim]{len(agents)} metric agents ready: {', '.join(agents.keys())}[/dim]")

    memory = SessionMemory()
    show_sql = False
    logger = SessionLogger()
    console.print(f"  [dim]Audit log recording to: {logger.path}[/dim]\n")

    try:
        while True:
            try:
                query = console.input("[bold cyan]> [/bold cyan]").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Goodbye.[/dim]\n")
                break

            if not query:
                continue

            # Command handling
            q_lower = query.lower()
            if q_lower in ("/quit", "/exit", "quit", "exit", "q"):
                console.print("\n[dim]Goodbye.[/dim]\n")
                break
            if q_lower == "/help":
                console.print(_HELP)
                continue
            if q_lower == "/sql":
                show_sql = not show_sql
                console.print(f"  [dim]SQL display: {'ON' if show_sql else 'OFF'}[/dim]\n")
                continue
            if q_lower == "/clear":
                memory.clear()
                console.print("  [dim]Session memory cleared.[/dim]\n")
                continue
            if q_lower == "/memory":
                ctx = memory.prompt_context(4)
                console.print(Panel(str(ctx) if ctx else "(Empty memory)", title="Session Memory Context", style="dim"))
                continue

            if query.startswith("/"):
                console.print(f"  [yellow]Unknown command '{query}'. Type /help for options.[/yellow]\n")
                continue

            try:
                response = run(query, memory=memory, interactive=True)
                display(response, show_sql=show_sql)
                logger.log(response)
            except Exception as e:
                display_error(str(e))
    finally:
        logger.close()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        query_str = " ".join(sys.argv[1:])
        init_agent_registry()
        with SessionLogger() as sess_logger:
            resp = run(query_str, memory=SessionMemory(), interactive=False)
            display(resp, show_sql=True)
            sess_logger.log(resp)
    else:
        repl()

