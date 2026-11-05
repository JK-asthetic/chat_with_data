"""Shared terminal logger — rich console helpers used across all pipeline stages."""
from __future__ import annotations

from rich.console import Console

console = Console(highlight=False)


def step(label: str, detail: str = "") -> None:
    """Mid-process stage marker."""
    if detail:
        console.print(f"  [dim cyan]▸[/dim cyan] [bold]{label}[/bold]  [dim]{detail}[/dim]")
    else:
        console.print(f"  [dim cyan]▸[/dim cyan] [bold]{label}[/bold]")


def ok(label: str, detail: str = "") -> None:
    if detail:
        console.print(f"  [green]✓[/green] [bold]{label}[/bold]  [dim]{detail}[/dim]")
    else:
        console.print(f"  [green]✓[/green] [bold]{label}[/bold]")


def warn(label: str, detail: str = "") -> None:
    if detail:
        console.print(f"  [yellow]⚠[/yellow] [bold]{label}[/bold]  [dim]{detail}[/dim]")
    else:
        console.print(f"  [yellow]⚠[/yellow] [bold]{label}[/bold]")


def sql_block(sql: str) -> None:
    """Print an indented SQL snippet (first 6 lines)."""
    lines = sql.strip().splitlines()
    preview = "\n    ".join(lines[:6])
    if len(lines) > 6:
        preview += f"\n    [dim]… +{len(lines)-6} more lines[/dim]"
    console.print(f"    [dim green]{preview}[/dim green]")
