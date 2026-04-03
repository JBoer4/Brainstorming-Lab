"""Compute per-character KPIs from Slippi replay files."""

import pandas as pd

from .stats import compute_game_stats

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

STAGE_NAMES = {
    2:  "Fountain of Dreams",
    3:  "Pokemon Stadium",
    4:  "Princess Peach's Castle",
    5:  "Kongo Jungle",
    6:  "Brinstar",
    7:  "Corneria",
    8:  "Yoshi's Story",
    9:  "Onett",
    10: "Mute City",
    11: "Rainbow Cruise",
    12: "Jungle Japes",
    13: "Great Bay",
    14: "Hyrule Temple",
    15: "Brinstar Depths",
    16: "Yoshi's Island",
    17: "Green Greens",
    18: "Fourside",
    19: "Mushroom Kingdom I",
    20: "Mushroom Kingdom II",
    22: "Venom",
    23: "Poke Floats",
    24: "Big Blue",
    25: "Icicle Mountain",
    27: "Flat Zone",
    28: "Dream Land N64",
    29: "Yoshi's Island N64",
    30: "Kongo Jungle N64",
    31: "Battlefield",
    32: "Final Destination",
}

MIN_DURATION_FRAMES = 600
MIN_STOCKS_LOST = 3


def char_name(char_id: int) -> str:
    return CHARACTER_NAMES.get(char_id, f"Unknown ({char_id})")


def stage_name(stage_id: int) -> str:
    return STAGE_NAMES.get(stage_id, f"Unknown ({stage_id})")


def _ratio_value(ratio_obj: dict | None) -> float | None:
    """Extract the .ratio field from a slippi-js RatioType, or None if unavailable."""
    if ratio_obj is None:
        return None
    return ratio_obj.get("ratio")


def _lcancel_from_actions(actions: dict) -> dict:
    lc = actions.get("lCancelCount") or {}
    success = lc.get("success", 0)
    fail = lc.get("fail", 0)
    total = success + fail
    return {
        "lcancel_success": success,
        "lcancel_miss": fail,
        "lcancel_rate": success / total if total > 0 else None,
    }


def compute_game_kpis(game_data: dict, player_port: int) -> dict:
    """Compute KPIs for a single game.

    Args:
        game_data: Dict returned by parse.load_replay (includes metadata and peppi-py game).
        player_port: 0-indexed port number for the player.
    """
    metadata = game_data["metadata"]

    # Player/opponent identity from peppi-py metadata
    players = metadata["players"]
    p_info = next(p for p in players if p["port"] == player_port)
    o_info = next(p for p in players if p["port"] != player_port)

    player_char = int(p_info["character"])
    opp_char = int(o_info["character"])

    # Game identity (present even on filtered games)
    kpis = {
        "filename": metadata["filename"],
        "stage": stage_name(int(metadata["stage"])),
        "character": char_name(player_char),
        "opp_character": char_name(opp_char),
        "opp_code": o_info.get("connect_code"),
    }

    # Compute stats in pure Python from the peppi-py game object
    data = compute_game_stats(
        game_data["game"],
        p_info["port_idx"],
        o_info["port_idx"],
    )
    settings = data["settings"]
    stats = data["stats"]

    player_idx = p_info["port_idx"]
    opp_idx = o_info["port_idx"]

    # Duration
    playable_frames = stats.get("playableFrameCount") or 0
    kpis["duration_frames"] = playable_frames
    kpis["duration_seconds"] = round(playable_frames / 60, 1)

    # Stock counts (needed for filter check)
    all_stocks = stats.get("stocks") or []
    p_stocks_lost = sum(
        1 for s in all_stocks
        if s["playerIndex"] == player_idx and s.get("endFrame") is not None
    )
    o_stocks_lost = sum(
        1 for s in all_stocks
        if s["playerIndex"] == opp_idx and s.get("endFrame") is not None
    )
    max_stocks_lost = max(p_stocks_lost, o_stocks_lost)

    # --- Filter: skip incomplete games ---
    if playable_frames < MIN_DURATION_FRAMES or max_stocks_lost < MIN_STOCKS_LOST:
        kpis["filtered"] = True
        return kpis

    kpis["filtered"] = False

    # Win / loss (tiebreak on final percent)
    p_last_stock = next(
        (s for s in reversed(all_stocks) if s["playerIndex"] == player_idx), None
    )
    o_last_stock = next(
        (s for s in reversed(all_stocks) if s["playerIndex"] == opp_idx), None
    )
    p_final_pct = p_last_stock.get("currentPercent", 0) if p_last_stock else 0
    o_final_pct = o_last_stock.get("currentPercent", 0) if o_last_stock else 0

    if o_stocks_lost > p_stocks_lost:
        result = "win"
    elif p_stocks_lost > o_stocks_lost:
        result = "loss"
    else:
        result = "win" if p_final_pct < o_final_pct else "loss"

    settings_players = {p["playerIndex"]: p for p in (settings.get("players") or [])}
    p_start_stocks = (settings_players.get(player_idx) or {}).get("startStocks") or 4
    o_start_stocks = (settings_players.get(opp_idx) or {}).get("startStocks") or 4

    kpis["result"] = result

    # Pre-fetch overall and action-count dicts
    overall_by_idx = {o["playerIndex"]: o for o in (stats.get("overall") or [])}
    p_ov = overall_by_idx.get(player_idx) or {}
    o_ov = overall_by_idx.get(opp_idx) or {}

    actions_by_idx = {a["playerIndex"]: a for a in (stats.get("actionCounts") or [])}
    p_ac = actions_by_idx.get(player_idx) or {}
    o_ac = actions_by_idx.get(opp_idx) or {}

    p_lc = _lcancel_from_actions(p_ac)
    o_lc = _lcancel_from_actions(o_ac)

    # ----------------------------------------------------------------
    # PLAYER
    # ----------------------------------------------------------------
    kpis["stocks_remaining"] = p_start_stocks - p_stocks_lost
    kpis["stocks_lost"]      = p_stocks_lost
    kpis["stocks_taken"]     = o_stocks_lost
    kpis["final_percent"]    = p_final_pct

    kpis["total_damage"]    = round(p_ov.get("totalDamage") or 0, 1)
    kpis["kills"]           = p_ov.get("killCount") or 0
    kpis["opening_count"]   = p_ov.get("conversionCount") or 0
    sc = _ratio_value(p_ov.get("successfulConversions"))
    kpis["conversion_rate"]     = round(sc * 100, 1) if sc is not None else None
    kpis["openings_per_kill"]   = round(r, 1) if (r := _ratio_value(p_ov.get("openingsPerKill"))) is not None else None
    kpis["damage_per_opening"]  = round(r, 1) if (r := _ratio_value(p_ov.get("damagePerOpening"))) is not None else None
    kpis["neutral_win_ratio"]       = round(r, 3) if (r := _ratio_value(p_ov.get("neutralWinRatio"))) is not None else None
    kpis["counter_hit_ratio"]       = round(r, 3) if (r := _ratio_value(p_ov.get("counterHitRatio"))) is not None else None
    kpis["beneficial_trade_ratio"]  = round(r, 3) if (r := _ratio_value(p_ov.get("beneficialTradeRatio"))) is not None else None
    kpis["inputs_per_minute"]         = round(r, 1) if (r := _ratio_value(p_ov.get("inputsPerMinute"))) is not None else None
    kpis["digital_inputs_per_minute"] = round(r, 1) if (r := _ratio_value(p_ov.get("digitalInputsPerMinute"))) is not None else None

    kpis["wavedashes"]  = p_ac.get("wavedashCount", 0)
    kpis["wavelands"]   = p_ac.get("wavelandCount", 0)
    kpis["dash_dances"] = p_ac.get("dashDanceCount", 0)
    kpis["ledge_grabs"] = p_ac.get("ledgegrabCount", 0)
    kpis["air_dodges"]  = p_ac.get("airDodgeCount", 0)
    kpis["spot_dodges"] = p_ac.get("spotDodgeCount", 0)
    kpis["rolls"]       = p_ac.get("rollCount", 0)
    kpis["lcancel_success"] = p_lc["lcancel_success"]
    kpis["lcancel_miss"]    = p_lc["lcancel_miss"]
    kpis["lcancel_rate"]    = p_lc["lcancel_rate"]

    # ----------------------------------------------------------------
    # OPPONENT
    # ----------------------------------------------------------------
    kpis["opp_final_percent"]    = o_final_pct

    kpis["opp_total_damage"]   = round(o_ov.get("totalDamage") or 0, 1)
    kpis["opp_kills"]          = o_ov.get("killCount") or 0
    kpis["opp_opening_count"]  = o_ov.get("conversionCount") or 0
    sc = _ratio_value(o_ov.get("successfulConversions"))
    kpis["opp_conversion_rate"]     = round(sc * 100, 1) if sc is not None else None
    kpis["opp_openings_per_kill"]   = round(r, 1) if (r := _ratio_value(o_ov.get("openingsPerKill"))) is not None else None
    kpis["opp_damage_per_opening"]  = round(r, 1) if (r := _ratio_value(o_ov.get("damagePerOpening"))) is not None else None
    kpis["opp_neutral_win_ratio"]       = round(r, 3) if (r := _ratio_value(o_ov.get("neutralWinRatio"))) is not None else None
    kpis["opp_counter_hit_ratio"]       = round(r, 3) if (r := _ratio_value(o_ov.get("counterHitRatio"))) is not None else None
    kpis["opp_beneficial_trade_ratio"]  = round(r, 3) if (r := _ratio_value(o_ov.get("beneficialTradeRatio"))) is not None else None
    kpis["opp_inputs_per_minute"]         = round(r, 1) if (r := _ratio_value(o_ov.get("inputsPerMinute"))) is not None else None
    kpis["opp_digital_inputs_per_minute"] = round(r, 1) if (r := _ratio_value(o_ov.get("digitalInputsPerMinute"))) is not None else None

    kpis["opp_wavedashes"]  = o_ac.get("wavedashCount", 0)
    kpis["opp_wavelands"]   = o_ac.get("wavelandCount", 0)
    kpis["opp_dash_dances"] = o_ac.get("dashDanceCount", 0)
    kpis["opp_ledge_grabs"] = o_ac.get("ledgegrabCount", 0)
    kpis["opp_air_dodges"]  = o_ac.get("airDodgeCount", 0)
    kpis["opp_spot_dodges"] = o_ac.get("spotDodgeCount", 0)
    kpis["opp_rolls"]       = o_ac.get("rollCount", 0)
    kpis["opp_lcancel_success"] = o_lc["lcancel_success"]
    kpis["opp_lcancel_miss"]    = o_lc["lcancel_miss"]
    kpis["opp_lcancel_rate"]    = o_lc["lcancel_rate"]

    return kpis


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

    # Player avg cols (no prefix)
    avg_cols = [
        "total_damage", "conversion_rate", "openings_per_kill", "damage_per_opening",
        "neutral_win_ratio", "counter_hit_ratio", "beneficial_trade_ratio",
        "inputs_per_minute", "digital_inputs_per_minute",
        "wavedashes", "wavelands", "dash_dances", "ledge_grabs",
        "air_dodges", "spot_dodges", "rolls",
        # Opponent
        "opp_total_damage", "opp_conversion_rate", "opp_openings_per_kill", "opp_damage_per_opening",
        "opp_neutral_win_ratio", "opp_counter_hit_ratio", "opp_beneficial_trade_ratio",
        "opp_inputs_per_minute", "opp_digital_inputs_per_minute",
        "opp_wavedashes", "opp_wavelands", "opp_dash_dances", "opp_ledge_grabs",
        "opp_air_dodges", "opp_spot_dodges", "opp_rolls",
    ]

    for char, group in df.groupby("character"):
        total_lcancels = group["lcancel_success"].sum() + group["lcancel_miss"].sum()
        opp_total_lcancels = group["opp_lcancel_success"].sum() + group["opp_lcancel_miss"].sum()

        agg = {
            # Game
            "games_played": len(group),
            "wins": int((group["result"] == "win").sum()),
            "losses": int((group["result"] == "loss").sum()),
            "win_rate": float((group["result"] == "win").mean()),
            # Player
            "avg_stocks_remaining": float(group["stocks_remaining"].mean()),
            "avg_stocks_lost": float(group["stocks_lost"].mean()),
            "avg_stocks_taken": float(group["stocks_taken"].mean()),
            "avg_final_percent": float(group["final_percent"].mean()),
            "lcancel_rate": (
                float(group["lcancel_success"].sum() / total_lcancels)
                if total_lcancels > 0 else None
            ),
            # Opponent
            "avg_opp_final_percent": float(group["opp_final_percent"].mean()),
            "opp_lcancel_rate": (
                float(group["opp_lcancel_success"].sum() / opp_total_lcancels)
                if opp_total_lcancels > 0 else None
            ),
        }

        for col in avg_cols:
            if col in group.columns:
                vals = group[col].dropna()
                agg[f"avg_{col}"] = round(float(vals.mean()), 3) if len(vals) > 0 else None

        matchup_stats = (
            group.groupby("opp_character")
            .agg(
                games=("result", "count"),
                wins=("result", lambda x: (x == "win").sum()),
            )
            .assign(win_rate=lambda d: d["wins"] / d["games"])
        )

        result[str(char)] = {"summary": agg, "matchups": matchup_stats}

    return result
