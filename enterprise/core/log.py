"""Shared terminal logger — rich console helpers used across all pipeline stages."""
from __future__ import annotations

from rich.console import Console
from rich.markup import escape

console = Console(highlight=False)


def step(label: str, detail: str = "") -> None:
    """Mid-process stage marker."""
    if detail:
        console.print(f"  [dim cyan]▸[/dim cyan] [bold]{label}[/bold]  [dim]{escape(detail)}[/dim]")
    else:
        console.print(f"  [dim cyan]▸[/dim cyan] [bold]{label}[/bold]")


def ok(label: str, detail: str = "") -> None:
    if detail:
        console.print(f"  [green]✓[/green] [bold]{label}[/bold]  [dim]{escape(detail)}[/dim]")
    else:
        console.print(f"  [green]✓[/green] [bold]{label}[/bold]")


def warn(label: str, detail: str = "") -> None:
    if detail:
        console.print(f"  [yellow]⚠[/yellow] [bold]{label}[/bold]  [dim]{escape(detail)}[/dim]")
    else:
        console.print(f"  [yellow]⚠[/yellow] [bold]{label}[/bold]")


def sql_block(sql: str) -> None:
    """Print the full SQL, indented."""
    body = escape("\n    ".join(sql.strip().splitlines()))
    console.print(f"    [dim green]{body}[/dim green]")


def entity(kind: str, text: str) -> None:
    """One resolved/classified entity line, aligned under a stage."""
    console.print(f"    [magenta]◆[/magenta] [bold]{kind:<10}[/bold] {escape(text)}")
