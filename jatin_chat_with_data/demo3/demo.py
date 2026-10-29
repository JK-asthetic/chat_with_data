#!/usr/bin/env python3
"""
Multi-question demo: one message in, a plan of self-contained sub-questions, one combined answer out.

  python3 demo.py            # scripted walkthrough, simple -> complex (about 3 minutes)
  python3 demo.py --pause    # same, waits for Enter between scenes (for presenting)
  python3 demo.py --repl     # live session; every question is a fresh call (main.USE_MEMORY is off)
  python3 demo.py --memory   # also run the follow-up scene (memory is only used inside that scene)
  python3 demo.py 3 5        # only scenes 3 and 5

Scenes use fully specified questions so nothing blocks on a clarification card.
Needs Ollama (S1), ZLLAMA (S0/S5/S7) and the database.
"""
import builtins
import json
import sys

import main
from core.memory import SessionMemory
from pipeline import s0_decompose

B, D, C, Y, RS = "\033[1m", "\033[2m", "\033[96m", "\033[93m", "\033[0m"


def banner(n: int, title: str, why: str) -> None:
    print(f"\n\n{B}{C}{'━' * 76}{RS}\n{B}{C}  Scene {n} — {title}{RS}\n{D}  {why}{RS}\n{B}{C}{'━' * 76}{RS}")


def ask(q: str, memory: SessionMemory) -> None:
    print(f"\n  {B}You ›{RS} {q}\n")
    main.run_multi(q, memory, show_plan_json=True)


def scene_simple(m):    ask("What is the total ARR for ZPA in EMEA in Q1FY26?", m)
def scene_compare(m):   ask("Compare ZIA and ZPA ARR in APJ for Q1FY26 vs Q4FY25", m)
def scene_split(m):     ask("What is the total ZIA ARR in EMEA in Q1FY26 and what is the total ZPA ARR in APJ in Q1FY26?", m)
def scene_dependent(m): ask("Who is the top account by ARR in EMEA in Q1FY26 and what is its ZPA ARR in Q1FY26?", m)
def scene_three(m):     ask("Total ARR in Q1FY26, ZPA ARR in EMEA in Q1FY26, and the top 3 accounts in APJ in Q1FY26", m)


def scene_followups(m):
    ask("Top 6 accounts by ZPA ARR in EMEA in Q1FY26", m)
    ask("What is the sixth one's ZIA ARR in Q1FY26?", m)       # 'sixth one' comes from the stored rows
    ask("and for Digital Experience?", m)                      # keeps the account and period from the last turn
    ask("What is the tenth one's ARR?", m)                     # past the end of the list: asks, never guesses


def scene_guard(m):
    """Simulated misbehaving splitter: it invents an account. The guard rejects it, then the plan is retried."""
    q = "What is total ZIA ARR in EMEA in Q1FY26 and what is total ZPA ARR in APJ in Q1FY26?"
    answers = iter([
        [("What is the total ZIA ARR in EMEA in Q1FY26?", []), ("What is Barclays ZPA ARR in APJ in Q1FY26?", [])],
        [("What is the total ZIA ARR in EMEA in Q1FY26?", []), ("What is the total ZPA ARR in APJ in Q1FY26?", [])],
    ])

    def bad_then_good(_system, _user):
        return json.dumps({"sub_queries": [{"id": f"q{i + 1}", "text": t, "depends_on": d}
                                           for i, (t, d) in enumerate(next(answers))]})

    print(f"\n  {B}You ›{RS} {q}\n  {D}(splitter is simulated: first attempt invents 'Barclays'){RS}\n")
    main._print_plan(s0_decompose.plan(q, memory=SessionMemory(), llm=bad_then_good), show_json=False)


SCENES = [
    ("Simple question", "Every question goes to the S0 LLM first; a single ask comes back as one part, unchanged.", scene_simple),
    ("One question that LOOKS like two", "'Compare' stays whole: splitting it would break the comparison.", scene_compare),
    ("Two independent questions", "Split into two self-contained parts, each answered by its own query, then merged.", scene_split),
    ("Second part depends on the first", "'its ZPA ARR' needs the top account, so it runs in a later stage. The name is read from the real result row, never invented.", scene_dependent),
    ("Three questions in one sentence", "A comma-separated list of asks becomes three parts.", scene_three),
    ("Follow-ups using memory", "'the sixth one' and 'and for ...?' resolve from stored results; an unresolvable reference asks.", scene_followups, True),
    ("Safety: the grounding guard", "A split that adds an entity the user never typed is rejected and retried.", scene_guard),
]


def main_demo(argv: list[str]) -> None:
    if "--repl" in argv:
        main.repl()
        return
    pause = "--pause" in argv
    picked = {int(a) for a in argv if a.isdigit()}
    real_input = builtins.input

    def no_clarification(*_a, **_k):
        raise EOFError  # scenes are fully specified; a clarification card would only block the demo

    builtins.input = no_clarification
    scenes = [sc for sc in SCENES if len(sc) == 3 or "--memory" in argv]   # a 4th field marks a memory scene
    for n, (title, why, fn, *_flag) in enumerate(scenes, 1):
        if picked and n not in picked:
            continue
        banner(n, title, why)
        fn(SessionMemory())
        if pause:
            real_input(f"\n  {D}[Enter for the next scene]{RS} ")


if __name__ == "__main__":
    main_demo(sys.argv[1:])
