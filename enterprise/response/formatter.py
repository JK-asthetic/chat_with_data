"""Terminal Formatter — renders beautiful output using the Rich library."""
from __future__ import annotations

from typing import Any
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

from pipeline.models import MetricAgentResponse, PipelineResponse, QueryResult

console = Console()


def _format_cell_value(val: Any, col_name: str) -> str:
    """Format numeric currency and numbers cleanly."""
    if val is None or val == "":
        return "-"
    if isinstance(val, (int, float)):
        c_lower = col_name.lower()
        if any(x in c_lower for x in ("arr", "acv", "target", "amount", "downsell")):
            if abs(val) >= 1_000_000:
                return f"${val / 1_000_000:.2f}M"
            elif abs(val) >= 1_000:
                return f"${val / 1_000:.1f}k"
            else:
                return f"${val:,.2f}"
        return f"{val:,}"
    return str(val)


def display_metric(agent_resp: MetricAgentResponse, index: int = 1, total: int = 1, show_sql: bool = False) -> None:
    header = f"[{index}/{total}] {agent_resp.display_name} ({agent_resp.metric_name})"
    console.print(Panel(Text(header, style="bold cyan"), box=box.ROUNDED))

    # Display Warnings
    for w in agent_resp.sanity_warnings:
        console.print(f"  [yellow]⚠ {w.code}:[/yellow] {w.message}")

    # Display Table
    res = agent_resp.result
    if res.success and res.rows:
        table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold magenta")
        for col in res.columns:
            table.add_column(col)

        for row in res.rows:
            formatted_cells = [_format_cell_value(row.get(c), c) for c in res.columns]
            table.add_row(*formatted_cells)

        console.print(table)
        console.print(f"  [dim]Returned {res.row_count} rows in {res.elapsed_ms:.1f}ms | Chart hint: {agent_resp.chart_type}[/dim]\n")
    elif res.success and not res.rows:
        console.print("  [dim]Query executed successfully but returned 0 rows.[/dim]\n")
    else:
        console.print(f"  [red]✗ Error:[/red] {res.db_error}\n")

    # Display SQL if requested
    if show_sql and agent_resp.sql:
        console.print(Panel(agent_resp.sql.sql, title=f"Generated SQL ({agent_resp.sql.source})", style="dim"))


def display(response: PipelineResponse, show_sql: bool = False) -> None:
    total = len(response.agent_responses)
    if total == 0:
        if response.merged_insight:
            console.print(Panel(response.merged_insight, title="💡 Strategy", border_style="green"))
        return

    for i, resp in enumerate(response.agent_responses, 1):
        display_metric(resp, index=i, total=total, show_sql=show_sql)

    if response.merged_insight:
        console.print(Panel(response.merged_insight, title="💡 Executive Summary", border_style="green"))


def display_error(msg: str) -> None:
    console.print(f"\n[bold red]Error:[/bold red] {msg}\n")


def display_strategic(answer: str) -> None:
    console.print(Panel(answer, title="💡 Strategic Advisory", border_style="green"))

