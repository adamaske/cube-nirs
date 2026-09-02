#!/usr/bin/env python3
"""Generate LaTeX table fragments from the trigger table and the session logs.

Writes:
    protocol/tables/triggers.tex   trigger code table (from triggers.py)
    report/tables/sessions.tex     one row per session (from data/sessions.csv)
    report/tables/solves.tex       one row per solve   (from data/solves.csv)

Run after every session, then rebuild the tex files.
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from triggers import TRIGGERS  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def esc(s: str) -> str:
    return str(s).replace("_", r"\_").replace("%", r"\%").replace("'", r"\textquotesingle{}")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    print("wrote", os.path.relpath(path, ROOT))


def triggers_table():
    rows = "\n".join(f"  {c} & \\texttt{{{esc(n)}}} & {esc(m)} \\\\" for c, (n, m) in TRIGGERS.items())
    return ("\\begin{tabular}{r l p{8.5cm}}\n\\toprule\nCode & Name & Meaning \\\\\n\\midrule\n"
            f"{rows}\n\\bottomrule\n\\end{{tabular}}\n")


def read_csv(name):
    path = os.path.join(ROOT, "data", name)
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return list(csv.DictReader(f))


def sessions_table():
    rows = read_csv("sessions.csv")
    if not rows:
        return "\\emph{No sessions recorded yet.}\n"
    body = "\n".join(
        f"  {r['subject']} & {r['session']} & {esc(r['date'])} & {r['trials_completed']}/{r['trials_planned']} & "
        f"{r['mean_solve_s'] or '--'} & {r['best_solve_s'] or '--'} & {'yes' if r['completed'] == '1' else 'no'} & {esc(r['comment'])} \\\\"
        for r in rows)
    return ("\\begin{tabular}{r r l c r r c p{4cm}}\n\\toprule\nSub & Ses & Date & Trials & Mean solve (s) & Best (s) & Complete & Comment \\\\\n"
            f"\\midrule\n{body}\n\\bottomrule\n\\end{{tabular}}\n")


def solves_table():
    rows = read_csv("solves.csv")
    if not rows:
        return "\\emph{No solves recorded yet.}\n"
    body = "\n".join(
        f"  {r['subject']} & {r['session']} & {r['trial']} & {esc(r['date'])} & {r['plan_s']} & {r['solve_s']} & "
        f"{'DNF' if r['dnf'] == '1' else ''} & \\texttt{{\\scriptsize {esc(r['scramble'])}}} \\\\"
        for r in rows)
    return ("\\begin{tabular}{r r r l r r c l}\n\\toprule\nSub & Ses & Trial & Date & Plan (s) & Solve (s) & DNF & Scramble \\\\\n"
            f"\\midrule\n{body}\n\\bottomrule\n\\end{{tabular}}\n")


if __name__ == "__main__":
    write(os.path.join(ROOT, "protocol", "tables", "triggers.tex"), triggers_table())
    write(os.path.join(ROOT, "report", "tables", "sessions.tex"), sessions_table())
    write(os.path.join(ROOT, "report", "tables", "solves.tex"), solves_table())
