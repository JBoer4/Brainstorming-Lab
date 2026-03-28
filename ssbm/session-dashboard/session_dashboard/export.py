"""Export KPI data to CSV for Tableau consumption."""

from pathlib import Path

import pandas as pd


def export_session(
    game_kpis: list[dict],
    aggregates: dict,
    output_dir: Path,
    session_date: str,
) -> list[Path]:
    """Export session data as CSVs for Tableau.

    Creates:
    - game_log_{date}.csv — one row per game with all KPIs
    - summary_{character}_{date}.csv — aggregated stats per character
    - matchups_{character}_{date}.csv — per-matchup breakdown per character

    Returns list of created file paths.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    created = []

    # Game-level log
    game_log_path = output_dir / f"game_log_{session_date}.csv"
    game_df = pd.DataFrame(game_kpis)
    game_df["session_date"] = session_date
    game_df.to_csv(game_log_path, index=False)
    created.append(game_log_path)

    # Per-character summaries
    for char, data in aggregates.items():
        char_clean = char.lower().replace(" ", "_")

        summary_path = output_dir / f"summary_{char_clean}_{session_date}.csv"
        summary_df = pd.DataFrame([data["summary"]])
        summary_df["character"] = char
        summary_df["session_date"] = session_date
        summary_df.to_csv(summary_path, index=False)
        created.append(summary_path)

    return created


def append_to_history(game_kpis: list[dict], output_dir: Path) -> Path:
    """Append game-level KPIs to a running history CSV.

    This enables Tableau trend views across sessions without re-parsing.
    """
    history_path = output_dir / "game_history.csv"
    new_df = pd.DataFrame(game_kpis)

    if history_path.exists():
        existing = pd.read_csv(history_path)
        combined = pd.concat([existing, new_df], ignore_index=True)
        # Deduplicate by filename in case of re-runs
        combined = combined.drop_duplicates(subset=["filename"], keep="last")
    else:
        combined = new_df

    combined.to_csv(history_path, index=False)
    return history_path
