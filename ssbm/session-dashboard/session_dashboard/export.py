"""Export KPI data to CSV for Tableau consumption."""

from pathlib import Path

import pandas as pd


def get_processed_filenames(output_dir: Path) -> set[str]:
    """Return the set of filenames already recorded in game_history.csv."""
    history_path = output_dir / "game_history.csv"
    if not history_path.exists():
        return set()
    df = pd.read_csv(history_path, usecols=["filename"])
    return set(df["filename"].dropna())


def append_to_history(game_kpis: list[dict], output_dir: Path) -> Path:
    """Append game-level KPIs to a running history CSV.

    This enables Tableau trend views across sessions without re-parsing.
    Deduplicates by filename so re-running a date range is safe.
    """
    history_path = output_dir / "game_history.csv"
    new_df = pd.DataFrame(game_kpis)

    if history_path.exists():
        existing = pd.read_csv(history_path)
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["filename"], keep="last")
    else:
        combined = new_df

    output_dir.mkdir(parents=True, exist_ok=True)
    combined.to_csv(history_path, index=False)
    return history_path
