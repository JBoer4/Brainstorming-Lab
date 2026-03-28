"""Parse Slippi replay files into structured game dicts."""

from pathlib import Path

from peppi_py import read_slippi


def load_replay(path: Path) -> dict:
    """Load a single .slp file and return game object + metadata."""
    game = read_slippi(str(path))

    metadata = {
        "path": path,
        "filename": path.name,
        "stage": game.start.stage,
        "players": [],
    }

    for i, player in enumerate(game.start.players):
        if player is not None:
            netplay = getattr(player, "netplay", None)
            metadata["players"].append({
                "port": i,
                "port_idx": len(metadata["players"]),  # index into frames.ports[]
                "character": player.character,
                "display_name": netplay.name if netplay else None,
                "connect_code": netplay.code if netplay else None,
            })

    return {"metadata": metadata, "game": game}


def load_session(replay_dir: Path, date_filter: str | None = None) -> list[dict]:
    """Load all .slp files from a directory.

    Args:
        replay_dir: Path to directory containing .slp files.
        date_filter: Optional date string (YYYY-MM-DD) to filter replays by
            file modification date.

    Returns:
        List of parsed game dicts.
    """
    slp_files = sorted(replay_dir.glob("**/*.slp"))

    if date_filter:
        from datetime import date, datetime

        target = date.fromisoformat(date_filter)
        slp_files = [
            f for f in slp_files
            if datetime.fromtimestamp(f.stat().st_mtime).date() == target
        ]

    games = []
    doubles_count = 0
    for f in slp_files:
        try:
            game = load_replay(f)
            if len(game["metadata"]["players"]) != 2:
                doubles_count += 1
                continue
            games.append(game)
        except Exception as e:
            print(f"Warning: could not parse {f.name}: {e}")

    if doubles_count:
        print(f"Skipped {doubles_count} doubles/multi-player games.")

    return games


def _normalize_code(code: str) -> str:
    """Normalize a connect code to match Slippi's format.

    Slippi stores codes with a full-width ＃ (U+FF03), not standard # (U+0023).
    Accepts JOJO-821, JOJO#821, or JOJO＃821 and converts to JOJO＃821.
    """
    code = code.replace("-", "\uFF03", 1)
    code = code.replace("#", "\uFF03", 1)
    return code


def identify_player(games: list[dict], connect_code: str | None = None) -> str:
    """Determine which connect code is 'self' across a session.

    Strategy:
    1. If connect_code is provided, verify it exists in the replays.
    2. Otherwise, find the connect code that appears in every game
       (you played every game, opponents rotate).

    Returns:
        The connect code identified as the player.

    Raises:
        SystemExit: If player cannot be identified.
    """
    from collections import Counter

    code_counts = Counter()
    total_games = len(games)
    for game in games:
        codes_in_game = set()
        for player in game["metadata"]["players"]:
            if player["connect_code"]:
                codes_in_game.add(player["connect_code"])
        for code in codes_in_game:
            code_counts[code] += 1

    if connect_code:
        connect_code = _normalize_code(connect_code)
        # Case-insensitive match against codes found in replays
        for actual_code in code_counts:
            if actual_code.upper() == connect_code.upper():
                return actual_code
        print(f"Error: connect code '{connect_code}' not found in any replay.")
        print(f"Codes found: {', '.join(code_counts.keys())}")
        raise SystemExit(1)

    # Auto-detect: the code that appears in every game
    candidates = [code for code, count in code_counts.items() if count == total_games]

    if len(candidates) == 1:
        return candidates[0]
    elif len(candidates) == 0:
        print("Error: no connect code appears in every game. Cannot auto-detect player.")
        print(f"Codes found: {code_counts}")
        print("Use --connect-code to specify who you are.")
        raise SystemExit(1)
    else:
        # Multiple codes in every game (e.g. played same person all session)
        print(f"Multiple players appear in every game: {candidates}")
        print("Use --connect-code to specify which one is you.")
        raise SystemExit(1)


def get_player_port(game: dict, connect_code: str) -> int:
    """Get the port number for a connect code in a specific game.

    Port can change between games, so this must be called per-game.
    """
    for player in game["metadata"]["players"]:
        if player["connect_code"] == connect_code:
            return player["port"]
    raise ValueError(f"'{connect_code}' not found in {game['metadata']['filename']}")
