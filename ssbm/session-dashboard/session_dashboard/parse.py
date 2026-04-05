"""Parse Slippi replay files into structured game dicts."""

import re
from pathlib import Path

from peppi_py import read_slippi

_MONTH_FOLDER_RE = re.compile(r"^\d{4}-\d{2}$")


def _resolve_search_dirs(
    replay_dir: Path,
    date_from_str: str | None,
    date_to_str: str | None,
) -> tuple[list[Path], bool]:
    """Determine which directories to scan for .slp files.

    If replay_dir contains YYYY-MM subfolders, returns only the month folders
    that overlap the requested date range (or all of them if no range given).
    Also returns whether day-level mtime filtering is still needed.

    Returns:
        (search_dirs, needs_day_filter)
    """
    from datetime import date

    month_dirs = sorted(
        d for d in replay_dir.iterdir()
        if d.is_dir() and _MONTH_FOLDER_RE.match(d.name)
    )
    if not month_dirs:
        # Flat layout — caller handles mtime filtering
        return [replay_dir], bool(date_from_str or date_to_str)

    # Monthly layout detected
    if not date_from_str and not date_to_str:
        return month_dirs, False

    start = date.fromisoformat(date_from_str) if date_from_str else date.min
    end = date.fromisoformat(date_to_str) if date_to_str else date.max

    # Build the set of YYYY-MM strings that fall within [start, end]
    relevant: set[str] = set()
    y, m = start.year, start.month
    while date(y, m, 1) <= end.replace(day=1):
        relevant.add(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1

    dirs = [d for d in month_dirs if d.name in relevant]

    # Day-level mtime filtering is only needed if the range is narrower than whole months
    start_is_month_start = start.day == 1
    import calendar
    end_is_month_end = end.day == calendar.monthrange(end.year, end.month)[1]
    needs_day_filter = not (start_is_month_start and end_is_month_end)

    return dirs, needs_day_filter


def load_replay(path: Path) -> dict:
    """Load a single .slp file and return game object + metadata."""
    from datetime import datetime

    game = read_slippi(str(path))

    # Parse game date from filename (Game_YYYYMMDDTHHMMSS.slp) — accurate regardless
    # of when the file was copied. Falls back to mtime if filename doesn't match.
    match = re.match(r"Game_(\d{8})T(\d{6})", path.name)
    if match:
        file_date = datetime.strptime(match.group(1), "%Y%m%d").date().isoformat()
        game_timestamp = datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S").isoformat()
    else:
        dt = datetime.fromtimestamp(path.stat().st_mtime)
        file_date = dt.date().isoformat()
        game_timestamp = dt.isoformat()

    metadata = {
        "path": path,
        "filename": path.name,
        "file_date": file_date,
        "game_timestamp": game_timestamp,
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


def load_session(
    replay_dir: Path,
    date_from: str | None = None,
    date_to: str | None = None,
    on_progress: callable = None,
    skip_filenames: set[str] | None = None,
) -> list[dict]:
    """Load all .slp files from a directory.

    Args:
        replay_dir: Path to directory containing .slp files.
        date_from: Optional start date (YYYY-MM-DD, inclusive) to filter by file mtime.
        date_to: Optional end date (YYYY-MM-DD, inclusive) to filter by file mtime.
            If only date_from is given, loads only that single day.
        on_progress: Optional callback(current, total) called after each file is parsed.
        skip_filenames: Optional set of filenames (basename only) to skip entirely,
            e.g. files already present in game_history.csv.

    Returns:
        List of parsed game dicts.
    """
    from datetime import date, datetime

    search_dirs, needs_day_filter = _resolve_search_dirs(replay_dir, date_from, date_to)

    slp_files = sorted(f for d in search_dirs for f in d.glob("*.slp"))

    if needs_day_filter:
        start = date.fromisoformat(date_from) if date_from else date.min
        end = date.fromisoformat(date_to) if date_to else (
            date.fromisoformat(date_from) if date_from else date.max
        )
        slp_files = [
            f for f in slp_files
            if start <= datetime.fromtimestamp(f.stat().st_mtime).date() <= end
        ]

    if skip_filenames:
        skipped = sum(1 for f in slp_files if f.name in skip_filenames)
        slp_files = [f for f in slp_files if f.name not in skip_filenames]
        if skipped:
            print(f"Skipping {skipped} already-processed files.")

    games = []
    doubles_count = 0
    total = len(slp_files)
    for i, f in enumerate(slp_files):
        if on_progress:
            on_progress(i + 1, total)
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


def _display_code(code: str) -> str:
    return code.replace("\uFF03", "#") if code else code


def identify_player(
    games: list[dict],
    connect_codes: list[str] | str | None = None,
) -> list[str]:
    """Determine which connect codes belong to 'self' across a session.

    Args:
        games: Parsed game dicts.
        connect_codes: One or more connect codes to identify as the player.
            Accepts a list, a single string, or None for auto-detection.

    Returns:
        List of normalized connect codes identified as the player.

    Raises:
        ValueError: If player cannot be identified.
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

    if connect_codes:
        if isinstance(connect_codes, str):
            connect_codes = [connect_codes]
        normalized = [_normalize_code(c.strip()) for c in connect_codes]
        matched = []
        for norm in normalized:
            for actual_code in code_counts:
                if actual_code.upper() == norm.upper():
                    matched.append(actual_code)
                    break
            else:
                all_codes = ", ".join(_display_code(c) for c in code_counts)
                raise ValueError(
                    f"Connect code '{_display_code(norm)}' not found in any replay. "
                    f"Codes found: {all_codes}"
                )
        return matched

    # Auto-detect: the code that appears in every game
    candidates = [code for code, count in code_counts.items() if count == total_games]

    if len(candidates) == 1:
        return candidates
    elif len(candidates) == 0:
        # Fall back to the most frequent code (handles games with missing netplay data)
        if code_counts:
            best, best_count = code_counts.most_common(1)[0]
            if best_count >= total_games * 0.8:
                return [best]
        codes = ", ".join(
            f"{_display_code(c)}({n})" for c, n in code_counts.most_common()
        )
        raise ValueError(
            f"Could not auto-detect player — no connect code appears in enough games. "
            f"Codes found: {codes}. Use --connect-code to specify who you are."
        )
    else:
        display = ", ".join(_display_code(c) for c in candidates)
        raise ValueError(
            f"Multiple connect codes appear in every game: {display}. "
            f"Use --connect-code to specify which one is you."
        )


def get_player_port(game: dict, player_codes: list[str]) -> tuple[int, str]:
    """Get the port number for the player in a specific game.

    Args:
        game: Parsed game dict.
        player_codes: List of normalized connect codes that belong to the player.

    Returns:
        (port, matched_code) — the port index and which of the player's codes was used.

    Raises:
        ValueError: If none of the codes are found, or if both appear (alt vs alt game).
    """
    upper_codes = {c.upper() for c in player_codes}
    matching = [
        p for p in game["metadata"]["players"]
        if p["connect_code"] and p["connect_code"].upper() in upper_codes
    ]
    if len(matching) > 1:
        raise ValueError(
            f"Both player codes appear in {game['metadata']['filename']} — skipping."
        )
    if len(matching) == 0:
        raise ValueError(
            f"None of the player codes found in {game['metadata']['filename']}"
        )
    p = matching[0]
    return p["port"], p["connect_code"]
