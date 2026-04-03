"""CLI entry point for session-dashboard."""

import argparse
from datetime import date
from pathlib import Path

from .parse import load_session, identify_player, get_player_port
from .kpis import compute_game_kpis, aggregate_by_character, filter_completed_games
from .export import export_session, append_to_history
from .slippi_api import RankCache, rating_to_tier


def _display_code(code: str) -> str:
    """Replace Slippi's full-width ＃ with standard # for terminal display."""
    return code.replace("\uFF03", "#") if code else code


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
    parser.add_argument(
        "--no-ranks",
        action="store_true",
        help="Skip Slippi API rank lookups (offline mode).",
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
    print(f"Identified player: {_display_code(player_code)}")

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

    # Look up ranked ratings for all players
    if not args.no_ranks:
        rank_cache = RankCache()

        # Look up the player's own rank
        player_rank = rank_cache.get(player_code)
        player_rating = player_rank["rating"] if player_rank else None
        player_tier = player_rank["tier"] if player_rank else None

        # Collect unique opponent codes from the games
        opp_codes = set()
        for game in games:
            for player in game["metadata"]["players"]:
                if player["connect_code"] and player["connect_code"] != player_code:
                    opp_codes.add(player["connect_code"])

        # Pre-fetch all opponent ranks concurrently
        rank_cache.prefetch(opp_codes)

        print(f"Looked up ranks for {rank_cache.api_calls_made} players.")
        if player_rating is not None:
            print(f"Your rank: {player_tier} ({player_rating:.0f})")
        else:
            print(f"Your rank: {player_tier}")

        # Attach rank data to each game's KPIs
        for kpis in game_kpis:
            kpis["player_rating"] = player_rating
            kpis["player_tier"] = player_tier

            opp_code = kpis.get("opp_code")
            if opp_code:
                opp_rank = rank_cache.get(opp_code)
                kpis["opponent_rating"] = opp_rank["rating"] if opp_rank else None
                kpis["opponent_tier"] = opp_rank["tier"] if opp_rank else None
            else:
                kpis["opponent_rating"] = None
                kpis["opponent_tier"] = None

    # Aggregate by character
    aggregates = aggregate_by_character(game_kpis)

    # Print quick summary
    for char, data in aggregates.items():
        s = data["summary"]
        lc_str = f"{s['lcancel_rate']:.0%}" if s["lcancel_rate"] else "N/A"
        print(f"\n--- {char} ---")
        print(f"  Games: {s['games_played']}  W/L: {s['wins']}-{s['losses']}  "
              f"Win rate: {s['win_rate']:.0%}")
        print(f"  Avg stocks taken: {s['avg_stocks_taken']:.1f}  "
              f"lost: {s['avg_stocks_lost']:.1f}")

        # Combat
        _p = lambda k: s.get(k) if s.get(k) is not None else "N/A"
        print(f"  Damage/game: {_p('avg_total_damage')}  "
              f"Conversion rate: {_p('avg_conversion_rate')}%  "
              f"Openings/kill: {_p('avg_openings_per_kill')}  "
              f"Dmg/opening: {_p('avg_damage_per_opening')}")

        # Neutral (ratios: player share of each exchange type, 0–1)
        print(f"  Neutral win ratio: {_p('avg_neutral_win_ratio')}  "
              f"Counter hit ratio: {_p('avg_counter_hit_ratio')}  "
              f"Beneficial trade ratio: {_p('avg_beneficial_trade_ratio')}")

        # Defensive
        print(f"  Spot dodges: {_p('avg_spot_dodges')}  "
              f"Air dodges: {_p('avg_air_dodges')}  "
              f"Rolls: {_p('avg_rolls')}")

        # Movement
        print(f"  Wavedashes: {_p('avg_wavedashes')}  "
              f"Wavelands: {_p('avg_wavelands')}  "
              f"Dash dances: {_p('avg_dash_dances')}  "
              f"Ledge grabs: {_p('avg_ledge_grabs')}")

        # Inputs
        print(f"  L-cancel: {lc_str}  "
              f"IPM: {_p('avg_inputs_per_minute')}  "
              f"Digital IPM: {_p('avg_digital_inputs_per_minute')}")

    # Export CSVs
    created = export_session(game_kpis, aggregates, args.output, args.date)
    history_path = append_to_history(game_kpis, args.output)
    created.append(history_path)

    print(f"\nExported {len(created)} files to {args.output}/")
    for p in created:
        print(f"  {p.name}")


if __name__ == "__main__":
    main()
