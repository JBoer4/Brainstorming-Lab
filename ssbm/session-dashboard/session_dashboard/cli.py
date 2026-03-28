"""CLI entry point for session-dashboard."""

import argparse
from datetime import date
from pathlib import Path

from .parse import load_session, identify_player, get_player_port
from .kpis import compute_game_kpis, aggregate_by_character, filter_completed_games
from .export import export_session, append_to_history


def main():
    parser = argparse.ArgumentParser(
        description="Analyze Slippi replays and export KPIs for Tableau."
    )
    parser.add_argument(
        "replay_dir",
        type=Path,
        nargs="?",
        default=Path.home() / "Documents" / "Slippi",
        help="Directory containing .slp replay files (default: ~/Documents/Slippi)",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=date.today().isoformat(),
        help="Date to analyze (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--connect-code",
        type=str,
        default=None,
        help="Your Slippi connect code (e.g. ABCD#123) for player identification.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("./output"),
        help="Directory for CSV exports (default: ./output)",
    )
    args = parser.parse_args()

    print(f"Loading replays from {args.replay_dir} for {args.date}...")
    games = load_session(args.replay_dir, date_filter=args.date)

    if not games:
        print(f"No replays found for {args.date}.")
        return

    print(f"Found {len(games)} games.")

    # Identify player by connect code
    player_code = identify_player(games, connect_code=args.connect_code)
    print(f"Identified player: {player_code}")

    # Compute KPIs per game (port can change between games)
    game_kpis = []
    for game in games:
        try:
            player_port = get_player_port(game, player_code)
            kpis = compute_game_kpis(game, player_port)
            kpis["session_date"] = args.date
            game_kpis.append(kpis)
        except Exception as e:
            print(f"Warning: skipping {game['metadata']['filename']}: {e}")

    if not game_kpis:
        print("No games could be analyzed.")
        return

    # Filter out incomplete games
    game_kpis, filtered_count = filter_completed_games(game_kpis)
    if filtered_count:
        print(f"Filtered out {filtered_count} incomplete games "
              f"(<600 frames or <3 stocks lost by either player).")

    if not game_kpis:
        print("No completed games to analyze.")
        return

    print(f"Analyzing {len(game_kpis)} completed games.")

    # Aggregate by character
    aggregates = aggregate_by_character(game_kpis)

    # Print quick summary
    for char, data in aggregates.items():
        s = data["summary"]
        lc = f"  L-cancel: {s['lcancel_rate']:.0%}" if s["lcancel_rate"] else ""
        print(f"\n--- {char} ---")
        print(f"  Games: {s['games_played']}  W/L: {s['wins']}-{s['losses']}  "
              f"Win rate: {s['win_rate']:.0%}{lc}")
        print(f"  Avg stocks taken: {s['avg_stocks_taken']:.1f}  "
              f"lost: {s['avg_stocks_lost']:.1f}")

    # Export CSVs
    created = export_session(game_kpis, aggregates, args.output, args.date)
    history_path = append_to_history(game_kpis, args.output)
    created.append(history_path)

    print(f"\nExported {len(created)} files to {args.output}/")
    for p in created:
        print(f"  {p.name}")


if __name__ == "__main__":
    main()
