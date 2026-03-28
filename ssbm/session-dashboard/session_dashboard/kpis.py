"""Compute per-character KPIs from parsed replay data."""

import pandas as pd

# Melee external character IDs → names
CHARACTER_NAMES = {
    0: "Captain Falcon",
    1: "Donkey Kong",
    2: "Fox",
    3: "Mr. Game & Watch",
    4: "Kirby",
    5: "Bowser",
    6: "Link",
    7: "Luigi",
    8: "Mario",
    9: "Marth",
    10: "Mewtwo",
    11: "Ness",
    12: "Peach",
    13: "Pikachu",
    14: "Ice Climbers",
    15: "Jigglypuff",
    16: "Samus",
    17: "Yoshi",
    18: "Zelda",
    19: "Sheik",
    20: "Falco",
    21: "Young Link",
    22: "Dr. Mario",
    23: "Roy",
    24: "Pichu",
    25: "Ganondorf",
    26: "Wire Frame Male",
    27: "Wire Frame Female",
    28: "Giga Bowser",
    29: "Crazy Hand",
    30: "Master Hand",
    31: "Sandbag",
}

MIN_DURATION_FRAMES = 600
MIN_STOCKS_LOST = 3


def char_name(char_id: int) -> str:
    return CHARACTER_NAMES.get(char_id, f"Unknown ({char_id})")


def _get_port_idx(metadata: dict, port: int) -> int:
    """Get the frames.ports[] index for a given port number."""
    for player in metadata["players"]:
        if player["port"] == port:
            return player["port_idx"]
    raise ValueError(f"Port {port} not found in game")


def compute_game_kpis(game_data: dict, player_port: int) -> dict:
    """Compute KPIs for a single game from the player's perspective."""
    game = game_data["game"]
    metadata = game_data["metadata"]
    frames = game.frames

    players = metadata["players"]
    opponent_port = next(p["port"] for p in players if p["port"] != player_port)

    player_idx = _get_port_idx(metadata, player_port)
    opp_idx = _get_port_idx(metadata, opponent_port)

    player_char = int(next(p["character"] for p in players if p["port"] == player_port))
    opp_char = int(next(p["character"] for p in players if p["port"] == opponent_port))

    # Access post-frame data via struct-of-arrays
    p_post = frames.ports[player_idx].leader.post
    o_post = frames.ports[opp_idx].leader.post

    # --- Game duration (frames of actual gameplay) ---
    frame_ids = frames.id.to_pylist()
    first_gameplay = 0
    for i, fid in enumerate(frame_ids):
        if fid >= 0:
            first_gameplay = i
            break
    duration_frames = len(frame_ids) - first_gameplay

    # --- Stocks ---
    p_stocks_final = p_post.stocks[-1].as_py()
    o_stocks_final = o_post.stocks[-1].as_py()
    p_stocks_start = p_post.stocks[first_gameplay].as_py()
    o_stocks_start = o_post.stocks[first_gameplay].as_py()
    p_stocks_lost = p_stocks_start - p_stocks_final
    o_stocks_lost = o_stocks_start - o_stocks_final
    max_stocks_lost = max(p_stocks_lost, o_stocks_lost)

    kpis = {
        "filename": metadata["filename"],
        "character": char_name(player_char),
        "opponent_character": char_name(opp_char),
        "duration_frames": duration_frames,
        "stocks_lost": p_stocks_lost,
        "stocks_taken": o_stocks_lost,
    }

    # --- Filter: skip incomplete games ---
    if duration_frames < MIN_DURATION_FRAMES or max_stocks_lost < MIN_STOCKS_LOST:
        kpis["filtered"] = True
        return kpis

    kpis["filtered"] = False

    # --- Win/Loss ---
    p_pct_final = p_post.percent[-1].as_py()
    o_pct_final = o_post.percent[-1].as_py()

    if p_stocks_final > o_stocks_final:
        result = "win"
    elif o_stocks_final > p_stocks_final:
        result = "loss"
    else:
        result = "win" if p_pct_final < o_pct_final else "loss"

    kpis["result"] = result
    kpis["stocks_remaining"] = p_stocks_final
    kpis["final_percent"] = p_pct_final
    kpis["opponent_final_percent"] = o_pct_final

    # --- L-cancel rate ---
    kpis.update(_lcancel_stats(p_post))

    return kpis


def _lcancel_stats(post) -> dict:
    """Compute L-cancel stats from post-frame data.

    peppi-py exposes post.l_cancel as an Arrow array where:
    - 0 = not applicable (not landing from aerial)
    - 1 = L-cancel success
    - 2 = L-cancel miss
    """
    l_cancel = getattr(post, "l_cancel", None)
    if l_cancel is None:
        return {"lcancel_success": 0, "lcancel_miss": 0, "lcancel_rate": None}

    values = l_cancel.to_pylist()
    successes = values.count(1)
    misses = values.count(2)
    total = successes + misses

    return {
        "lcancel_success": successes,
        "lcancel_miss": misses,
        "lcancel_rate": successes / total if total > 0 else None,
    }


def filter_completed_games(game_kpis: list[dict]) -> tuple[list[dict], int]:
    """Separate completed games from filtered-out ones.

    Returns (completed_kpis, filtered_count).
    """
    completed = [g for g in game_kpis if not g.get("filtered", False)]
    filtered = len(game_kpis) - len(completed)
    return completed, filtered


def aggregate_by_character(game_kpis: list[dict]) -> dict[str, dict]:
    """Group game-level KPIs by character and compute aggregates."""
    df = pd.DataFrame(game_kpis)
    result = {}

    for char, group in df.groupby("character"):
        total_lcancels = group["lcancel_success"].sum() + group["lcancel_miss"].sum()

        agg = {
            "games_played": len(group),
            "wins": int((group["result"] == "win").sum()),
            "losses": int((group["result"] == "loss").sum()),
            "win_rate": float((group["result"] == "win").mean()),
            "avg_stocks_taken": float(group["stocks_taken"].mean()),
            "avg_stocks_lost": float(group["stocks_lost"].mean()),
            "avg_final_percent": float(group["final_percent"].mean()),
            "avg_opponent_final_percent": float(group["opponent_final_percent"].mean()),
            "lcancel_rate": (
                float(group["lcancel_success"].sum() / total_lcancels)
                if total_lcancels > 0
                else None
            ),
        }

        matchup_stats = (
            group.groupby("opponent_character")
            .agg(
                games=("result", "count"),
                wins=("result", lambda x: (x == "win").sum()),
            )
            .assign(win_rate=lambda d: d["wins"] / d["games"])
        )

        result[str(char)] = {"summary": agg, "matchups": matchup_stats}

    return result
