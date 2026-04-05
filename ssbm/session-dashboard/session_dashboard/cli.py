"""CLI entry point for session-dashboard."""

import argparse
from datetime import date
from pathlib import Path

from .parse import load_session, identify_player, get_player_port
from .kpis import compute_game_kpis, aggregate_by_character, filter_completed_games
from .export import append_to_history, get_processed_filenames, load_history_for_range
from .report import generate_report
from .slippi_api import RankCache


def _display_code(code: str) -> str:
    """Replace Slippi's full-width ＃ with standard # for terminal display."""
    return code.replace("\uFF03", "#") if code else code


def _generate_report_from_history(output_dir, date_from, date_to):
    import webbrowser
    games = load_history_for_range(output_dir, date_from, date_to)
    if not games:
        label = date_from or "the requested date"
        print(f"No data in history for {label}.")
        return
    date_label = date_from if date_from == date_to else f"{date_from}_to_{date_to}"
    report_path = generate_report(games, output_dir, date_str=date_label)
    print(f"Session report: {report_path}")
    webbrowser.open(report_path.resolve().as_uri())


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
        "--from",
        dest="date_from",
        type=str,
        default=None,
        help="Start date (YYYY-MM-DD, inclusive). Omit for all files.",
    )
    parser.add_argument(
        "--to",
        dest="date_to",
        type=str,
        default=None,
        help="End date (YYYY-MM-DD, inclusive). Defaults to --from if only that is set.",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Shorthand for --from DATE --to DATE (single day).",
    )
    parser.add_argument(
        "--connect-code",
        type=str,
        default=None,
        help="Your Slippi connect code(s). Comma-separate multiple codes for alts "
             "(e.g. JOJO#821,ALT#420).",
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
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reprocess games already in game_history.csv (default: skip them).",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Generate and open a session HTML report after processing.",
    )
    args = parser.parse_args()

    # --date is shorthand for a single-day range
    date_from = args.date or args.date_from
    date_to = args.date or args.date_to

    range_desc = (
        f"{date_from} to {date_to}" if date_from and date_to and date_from != date_to
        else date_from or "all dates"
    )
    skip_filenames = None if args.force else get_processed_filenames(args.output)
    if skip_filenames:
        print(f"{len(skip_filenames)} games already in history — skipping (use --force to reprocess).")

    print(f"Loading replays from {args.replay_dir} ({range_desc})...")
    games = load_session(args.replay_dir, date_from=date_from, date_to=date_to, skip_filenames=skip_filenames)

    if not games:
        print(f"No replays found for {range_desc}.")
        return

    print(f"Found {len(games)} games.")

    connect_codes = (
        [c.strip() for c in args.connect_code.split(",")]
        if args.connect_code else None
    )
    player_codes = identify_player(games, connect_codes=connect_codes)
    print(f"Identified player: {', '.join(_display_code(c) for c in player_codes)}")

    game_kpis = []
    for game in games:
        try:
            player_port, matched_code = get_player_port(game, player_codes)
            kpis = compute_game_kpis(game, player_port)
            kpis["session_date"] = game["metadata"]["file_date"]
            kpis["game_timestamp"] = game["metadata"]["game_timestamp"]
            kpis["player_code"] = _display_code(matched_code)
            game_kpis.append(kpis)
        except Exception as e:
            print(f"Warning: skipping {game['metadata']['filename']}: {e}")

    if not game_kpis:
        if args.report:
            print("No new games to process — generating report from history.")
            _generate_report_from_history(args.output, date_from, date_to)
        else:
            print("No new games to process.")
        return

    game_kpis, filtered_count = filter_completed_games(game_kpis)
    if filtered_count:
        print(f"Filtered out {filtered_count} incomplete games "
              f"(<600 frames or <3 stocks lost by either player).")

    if not game_kpis:
        if args.report:
            print("No completed games to analyze — generating report from history.")
            _generate_report_from_history(args.output, date_from, date_to)
        else:
            print("No completed games to analyze.")
        return

    print(f"Analyzing {len(game_kpis)} completed games.")

    if not args.no_ranks:
        rank_cache = RankCache()
        upper_player_codes = {c.upper() for c in player_codes}

        # Look up rank for each of the player's codes
        rank_cache.prefetch(set(player_codes))
        player_ranks = {c: rank_cache.get(c) for c in player_codes}
        for c, rank in player_ranks.items():
            if rank and rank.get("rating") is not None:
                print(f"Your rank ({_display_code(c)}): {rank['tier']} ({rank['rating']:.0f})")
            else:
                print(f"Your rank ({_display_code(c)}): {rank['tier'] if rank else 'Unknown'}")

        # Collect unique opponent codes (excluding all player codes)
        opp_codes = set()
        for game in games:
            for player in game["metadata"]["players"]:
                if player["connect_code"] and player["connect_code"].upper() not in upper_player_codes:
                    opp_codes.add(player["connect_code"])

        rank_cache.prefetch(opp_codes)
        print(f"Looked up ranks for {rank_cache.api_calls_made} players.")

        # Attach rank for the specific code used in each game
        player_ranks_by_display = {_display_code(c): r for c, r in player_ranks.items()}
        for kpis in game_kpis:
            rank = player_ranks_by_display.get(kpis.get("player_code"))
            kpis["player_rating"] = rank["rating"] if rank else None
            kpis["player_tier"] = rank["tier"] if rank else None

            opp_code = kpis.get("opp_code")
            if opp_code:
                opp_rank = rank_cache.get(opp_code)
                kpis["opponent_rating"] = opp_rank["rating"] if opp_rank else None
                kpis["opponent_tier"] = opp_rank["tier"] if opp_rank else None
            else:
                kpis["opponent_rating"] = None
                kpis["opponent_tier"] = None

    aggregates = aggregate_by_character(game_kpis)

    for char, data in aggregates.items():
        s = data["summary"]
        lc_str = f"{s['lcancel_rate']:.0%}" if s["lcancel_rate"] else "N/A"
        print(f"\n--- {char} ---")
        print(f"  Games: {s['games_played']}  W/L: {s['wins']}-{s['losses']}  "
              f"Win rate: {s['win_rate']:.0%}")
        print(f"  Avg stocks taken: {s['avg_stocks_taken']:.1f}  "
              f"lost: {s['avg_stocks_lost']:.1f}")

        _p = lambda k: s.get(k) if s.get(k) is not None else "N/A"
        print(f"  Damage/game: {_p('avg_total_damage')}  "
              f"Conversion rate: {_p('avg_conversion_rate')}%  "
              f"Openings/kill: {_p('avg_openings_per_kill')}  "
              f"Dmg/opening: {_p('avg_damage_per_opening')}")
        print(f"  Neutral win ratio: {_p('avg_neutral_win_ratio')}  "
              f"Counter hit ratio: {_p('avg_counter_hit_ratio')}  "
              f"Beneficial trade ratio: {_p('avg_beneficial_trade_ratio')}")
        print(f"  Spot dodges: {_p('avg_spot_dodges')}  "
              f"Air dodges: {_p('avg_air_dodges')}  "
              f"Rolls: {_p('avg_rolls')}")
        print(f"  Wavedashes: {_p('avg_wavedashes')}  "
              f"Wavelands: {_p('avg_wavelands')}  "
              f"Dash dances: {_p('avg_dash_dances')}  "
              f"Ledge grabs: {_p('avg_ledge_grabs')}")
        print(f"  L-cancel: {lc_str}  "
              f"IPM: {_p('avg_inputs_per_minute')}  "
              f"Digital IPM: {_p('avg_digital_inputs_per_minute')}")

    history_path = append_to_history(game_kpis, args.output)
    print(f"\nExported to {history_path}")

    if args.report:
        _generate_report_from_history(args.output, date_from, date_to)


if __name__ == "__main__":
    main()
