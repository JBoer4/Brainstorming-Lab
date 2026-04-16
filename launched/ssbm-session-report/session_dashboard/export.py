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


def load_history_for_range(
    output_dir: Path,
    date_from: str | None,
    date_to: str | None,
) -> list[dict]:
    """Return all games within a date range from game_history.csv.

    Args:
        output_dir: Directory containing game_history.csv.
        date_from: Start date (YYYY-MM-DD, inclusive). None = no lower bound.
        date_to: End date (YYYY-MM-DD, inclusive). None = no upper bound.

    Returns:
        List of dicts (one per game), or empty list if no data found.
    """
    history_path = output_dir / "game_history.csv"
    if not history_path.exists():
        return []
    df = pd.read_csv(history_path)
    if "session_date" not in df.columns:
        return []
    mask = pd.Series([True] * len(df), index=df.index)
    if date_from:
        mask &= df["session_date"] >= date_from
    if date_to:
        mask &= df["session_date"] <= date_to
    result = df[mask]
    return result.where(result.notna(), other=None).to_dict(orient="records")


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
