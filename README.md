# cube-nirs

Rubik's Cube re-learning tracked with fNIRS (prefrontal + occipital).

```
scripts/run_session.py   run one session: sends LSL markers, logs times, generates scrambles
scripts/triggers.py      marker code table (single source of truth)
scripts/scramble.py      random scramble generator
scripts/make_tables.py   regenerate LaTeX tables from triggers.py and data/*.csv
protocol/protocol.tex    experimental protocol + trigger table
report/report.tex        progress report (sessions/solves tables, notes)
logs/                    per-session json + log (committed)
data/solves.csv          one row per solve
data/sessions.csv        one row per session
data/raw/                fNIRS recordings (git-ignored)
examples/                old runner scripts used as reference
```

## Setup (Windows 11 acquisition PC)

```
git clone https://github.com/adamaske/cube-nirs
cd cube-nirs
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Run a session

```
python scripts/run_session.py --subject 1 --trials 5
python scripts/run_session.py --no-lsl --rest-pre 2 --rest-post 2 --break 5   # quick dry run
python scripts/run_session.py --help
```

Start the fNIRS recording first and select the `Triggers` LSL stream. After the session:

```
python scripts/make_tables.py
cd report && latexmk -pdf report.tex
```

Then commit `logs/` and `data/*.csv` and push.
