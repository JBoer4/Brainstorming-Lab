# Session Dashboard

A Slippi replay analysis pipeline and Tableau dashboard for tracking SSBM improvement over time.

Parse a folder of `.slp` replay files, compute per-character KPIs, and export to a running history CSV that feeds an interactive Tableau dashboard.

## What it does

- Parses Slippi replay files using [peppi-py](https://github.com/hohav/peppi-py)
- Computes per-game KPIs: win/loss, L-cancel rate, conversion rate, damage per opening, inputs per minute, and more
- Exports to `game_history.csv` — a cumulative log of every game analyzed
- Tableau workbook connects to that CSV for interactive dashboards

## Dashboards

Two dashboards included in `dashboard/SessionDashboard.twb`:

**Performance Trends** — win rate, L-cancel rate, and IPM over time, filterable by character and opponent pool

**Matchup Analysis** — conversion rate and damage per opening broken down by opponent character, with four interactive matchup panels

## Usage

### GUI
Download `SessionDashboard.exe` from the [latest release](https://github.com/JBoer4/Brainstorming-Lab/releases/tag/v0.1.0-beta) (Windows).

- Point at your replay folder (supports `YYYY-MM` monthly subfolders — point at the root)
- Set a date range, or leave blank to process everything
- Enter your connect code (comma-separate multiple codes for alts: `JOJO#821, ALT#420`)
- Hit Run

Output goes to `game_history.csv` in your chosen output folder. Re-runs skip already-processed games by default — tick **Force recalculate** to reprocess after a code update.

### CLI
```bash
session-dashboard C:\path\to\replays --from 2026-03-01 --to 2026-03-31 --connect-code JOJO#821
```

Options:
- `--from / --to` — date range (YYYY-MM-DD). Omit for all files.
- `--date` — shorthand for single day
- `--connect-code` — your connect code(s), comma-separated for alts
- `--no-ranks` — skip Slippi API rank lookups (faster, offline)
- `--force` — reprocess games already in history

### Tableau
Open `dashboard/SessionDashboard.twb` in Tableau Public (free). Point the data source at your `game_history.csv`. All dashboards update automatically.

## Stack

- Python 3.12 + peppi-py (Slippi parsing)
- pandas (aggregation)
- Tkinter (GUI)
- PyInstaller (exe packaging)
- Tableau Public (dashboarding)

## Notes

This is a beta / brainstorming project. See `notes.md` for known limitations and the planned full project roadmap.
