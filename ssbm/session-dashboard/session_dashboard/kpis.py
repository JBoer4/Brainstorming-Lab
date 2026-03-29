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

# --- Melee action state constants ---
# Damaged states: 0x4B-0x5B, plus special cases
DAMAGE_START = 0x4B
DAMAGE_END = 0x5B
DAMAGE_FALL = 0x26
JAB_RESET_UP = 0xB9
JAB_RESET_DOWN = 0xC1

# Grabbed states
GRAB_START = 0xDF
GRAB_END = 0xE8

# Command grab states
CMD_GRAB_START = 0x10A
CMD_GRAB_END = 0x130
CMD_GRAB2_START = 0x147
CMD_GRAB2_END = 0x152
BARREL_WAIT = 0x125

# Grounded control states
GROUNDED_CONTROL_START = 0x0E
GROUNDED_CONTROL_END = 0x18
SQUAT_START = 0x27
SQUAT_END = 0x29
GROUND_ATTACK_START = 0x2D
GROUND_ATTACK_END = 0x40
GRAB_STATE = 0xD4

# Movement / defensive action states
SPOT_DODGE = 0xEB
AIR_DODGE = 0xEC
ROLL_FORWARD = 0xE9
ROLL_BACKWARD = 0xEA
CLIFF_CATCH = 0xFC
KNEE_BEND = 0x18
LANDING_FALL_SPECIAL = 0x2B
DASH = 0x14
TURN = 0x12

# Jump states range
JUMP_START = 0x19
JUMP_END = 0x22

PUNISH_RESET_FRAMES = 45
WAVEDASH_LOOKBACK = 15


def char_name(char_id: int) -> str:
    return CHARACTER_NAMES.get(char_id, f"Unknown ({char_id})")


def _get_port_idx(metadata: dict, port: int) -> int:
    """Get the frames.ports[] index for a given port number."""
    for player in metadata["players"]:
        if player["port"] == port:
            return player["port_idx"]
    raise ValueError(f"Port {port} not found in game")


def _is_damaged(state: int) -> bool:
    return (DAMAGE_START <= state <= DAMAGE_END
            or state == DAMAGE_FALL
            or state == JAB_RESET_UP
            or state == JAB_RESET_DOWN)


def _is_grabbed(state: int) -> bool:
    return GRAB_START <= state <= GRAB_END


def _is_command_grabbed(state: int) -> bool:
    if CMD_GRAB_START <= state <= CMD_GRAB_END:
        return state != BARREL_WAIT
    return CMD_GRAB2_START <= state <= CMD_GRAB2_END


def _is_in_hitlag(state: int) -> bool:
    return _is_damaged(state) or _is_grabbed(state) or _is_command_grabbed(state)


def _is_in_control(state: int) -> bool:
    return (GROUNDED_CONTROL_START <= state <= GROUNDED_CONTROL_END
            or SQUAT_START <= state <= SQUAT_END
            or GROUND_ATTACK_START < state <= GROUND_ATTACK_END
            or state == GRAB_STATE)


def _compute_conversions(p_states, o_states, p_percents, o_percents,
                         p_stocks, o_stocks, first_gameplay):
    """Compute conversions/openings for player attacking opponent.

    Returns list of dicts with: start_frame, end_frame, damage, did_kill, moves.
    """
    conversions = []
    current = None
    reset_counter = 0

    for i in range(first_gameplay, len(o_states)):
        o_state = o_states[i]
        o_stock = o_stocks[i]

        # Check if opponent is being hit
        in_hitlag = _is_damaged(o_state) or _is_grabbed(o_state) or _is_command_grabbed(o_state)

        if current is None:
            if in_hitlag:
                current = {
                    "start_frame": i,
                    "start_percent": o_percents[i],
                    "end_frame": i,
                    "end_percent": o_percents[i],
                    "did_kill": False,
                    "start_stocks": o_stock,
                }
                reset_counter = 0
        else:
            if in_hitlag:
                current["end_frame"] = i
                current["end_percent"] = o_percents[i]
                reset_counter = 0
            elif _is_in_control(o_state):
                reset_counter += 1
            elif o_state == 0:  # dead
                reset_counter += 1

            # Check for stock loss
            if o_stock is not None and current["start_stocks"] is not None:
                if o_stock < current["start_stocks"]:
                    current["did_kill"] = True
                    current["end_percent"] = o_percents[i]
                    current["end_frame"] = i
                    current["damage"] = (current["end_percent"] or 0) - (current["start_percent"] or 0)
                    if current["did_kill"]:
                        # Add the percent from the last stock
                        current["damage"] = current["end_percent"] or 0
                        if not current["did_kill"]:
                            current["damage"] = (current["end_percent"] or 0) - (current["start_percent"] or 0)
                    conversions.append(current)
                    current = None
                    reset_counter = 0
                    continue

            if reset_counter >= PUNISH_RESET_FRAMES:
                current["damage"] = (current["end_percent"] or 0) - (current["start_percent"] or 0)
                conversions.append(current)
                current = None
                reset_counter = 0

    # Close any remaining conversion
    if current is not None:
        current["damage"] = (current["end_percent"] or 0) - (current["start_percent"] or 0)
        conversions.append(current)

    return conversions


def _classify_conversions(p_conversions, o_conversions):
    """Classify conversions as neutral_win, counter_attack, or trade.

    Returns (neutral_wins, counter_hits, trades) counts for player.
    """
    neutral_wins = 0
    counter_hits = 0
    trades = 0

    o_by_start = {}
    for c in o_conversions:
        o_by_start.setdefault(c["start_frame"], []).append(c)

    # Build a sorted list of opponent conversion end frames for counter-hit detection
    o_sorted = sorted(o_conversions, key=lambda c: c["start_frame"])

    for conv in p_conversions:
        sf = conv["start_frame"]

        # Trade: opponent conversion starts on same frame
        if sf in o_by_start:
            trades += 1
            continue

        # Counter-attack: player was being comboed when this conversion started
        is_counter = False
        for oc in o_sorted:
            if oc["end_frame"] >= sf and oc["start_frame"] < sf:
                is_counter = True
                break
        if is_counter:
            counter_hits += 1
            continue

        neutral_wins += 1

    return neutral_wins, counter_hits, trades


def _compute_action_counts(states, positions_y, first_gameplay):
    """Count defensive and movement actions from action state sequence.

    Returns dict with spot_dodges, air_dodges, rolls, wavedashes, wavelands,
    dash_dances, ledge_grabs.
    """
    counts = {
        "spot_dodges": 0,
        "air_dodges": 0,
        "rolls": 0,
        "wavedashes": 0,
        "wavelands": 0,
        "dash_dances": 0,
        "ledge_grabs": 0,
    }

    n = len(states)

    for i in range(first_gameplay, n):
        s = states[i]
        prev = states[i - 1] if i > 0 else None

        # Only count on state transitions
        if s == prev:
            continue

        if s == SPOT_DODGE:
            counts["spot_dodges"] += 1
        elif s == AIR_DODGE:
            counts["air_dodges"] += 1
        elif s in (ROLL_FORWARD, ROLL_BACKWARD):
            counts["rolls"] += 1
        elif s == CLIFF_CATCH:
            counts["ledge_grabs"] += 1
        elif s == LANDING_FALL_SPECIAL:
            # Possible wavedash/waveland — check lookback window
            lookback_start = max(first_gameplay, i - WAVEDASH_LOOKBACK)
            window = states[lookback_start:i]

            had_airdodge = AIR_DODGE in window
            had_kneebend = KNEE_BEND in window

            if not had_airdodge:
                continue

            # Check if it's just a late air dodge (only airdodge + current in window)
            unique_in_window = set(window)
            unique_in_window.discard(s)
            if unique_in_window == {AIR_DODGE}:
                continue  # Late air dodge, not wavedash

            # Deduct the air dodge since it's part of wavedash
            counts["air_dodges"] = max(0, counts["air_dodges"] - 1)

            if had_kneebend:
                # Check Y movement to distinguish wavedash vs waveland
                kb_idx = None
                for j in range(i - 1, lookback_start - 1, -1):
                    if states[j] == KNEE_BEND:
                        kb_idx = j
                        break

                if kb_idx is not None and positions_y is not None:
                    y_start = positions_y[kb_idx]
                    y_end = positions_y[i]
                    # Count airborne frames
                    airborne_frames = sum(
                        1 for j in range(kb_idx, i)
                        if JUMP_START <= states[j] <= JUMP_END
                    )
                    if airborne_frames >= 5 and abs(y_end - y_start) > 0.1:
                        counts["wavelands"] += 1
                    else:
                        counts["wavedashes"] += 1
                else:
                    counts["wavedashes"] += 1
            else:
                counts["wavelands"] += 1

        # Dash dance detection: DASH → TURN → DASH
        if i >= 2 and s == DASH and states[i - 1] == TURN and states[i - 2] == DASH:
            counts["dash_dances"] += 1

    return counts


def _joystick_region(x, y, threshold=0.2875):
    """Map joystick position to one of 9 regions (0=deadzone, 1-8=directions)."""
    dx = 0 if abs(x) < threshold else (1 if x > 0 else -1)
    dy = 0 if abs(y) < threshold else (1 if y > 0 else -1)
    if dx == 0 and dy == 0:
        return 0  # deadzone
    return (dx + 1) * 3 + (dy + 1) + 1  # unique region ID 1-8


def _compute_inputs(pre, first_gameplay, duration_frames):
    """Count inputs per minute and digital inputs per minute.

    Follows slippi-js logic:
    - Button presses: XOR physical buttons, count new bits
    - Joystick/C-stick: region changes (deadzone returns don't count)
    - Triggers: crossing 0.3 threshold upward
    """
    buttons = pre.buttons_physical.to_pylist()
    joy_x = pre.joystick.x.to_pylist()
    joy_y = pre.joystick.y.to_pylist()
    cstick_x = pre.cstick.x.to_pylist()
    cstick_y = pre.cstick.y.to_pylist()
    trigger_l = pre.triggers_physical.l.to_pylist()
    trigger_r = pre.triggers_physical.r.to_pylist()

    button_count = 0
    total_count = 0
    prev_joy_region = _joystick_region(joy_x[first_gameplay], joy_y[first_gameplay])
    prev_cstick_region = _joystick_region(cstick_x[first_gameplay], cstick_y[first_gameplay])
    prev_trigger_l = trigger_l[first_gameplay] >= 0.3
    prev_trigger_r = trigger_r[first_gameplay] >= 0.3

    for i in range(first_gameplay + 1, len(buttons)):
        # Button presses (new bits)
        btn_diff = (buttons[i] ^ buttons[i - 1]) & buttons[i] & 0xFFF
        bits = bin(btn_diff).count("1")
        button_count += bits
        total_count += bits

        # Joystick region change
        joy_region = _joystick_region(joy_x[i], joy_y[i])
        if joy_region != prev_joy_region and joy_region != 0:
            total_count += 1
        prev_joy_region = joy_region

        # C-stick region change
        cstick_region = _joystick_region(cstick_x[i], cstick_y[i])
        if cstick_region != prev_cstick_region and cstick_region != 0:
            total_count += 1
        prev_cstick_region = cstick_region

        # Trigger presses
        tl = trigger_l[i] >= 0.3
        tr = trigger_r[i] >= 0.3
        if tl and not prev_trigger_l:
            total_count += 1
        if tr and not prev_trigger_r:
            total_count += 1
        prev_trigger_l = tl
        prev_trigger_r = tr

    game_minutes = duration_frames / 3600  # 60fps
    ipm = total_count / game_minutes if game_minutes > 0 else 0
    dipm = button_count / game_minutes if game_minutes > 0 else 0

    return {
        "inputs_per_minute": round(ipm, 1),
        "digital_inputs_per_minute": round(dipm, 1),
    }


def compute_game_kpis(game_data: dict, player_port: int) -> dict:
    """Compute KPIs for a single game from the player's perspective."""
    game = game_data["game"]
    metadata = game_data["metadata"]
    frames = game.frames

    players = metadata["players"]
    opponent_port = next(p["port"] for p in players if p["port"] != player_port)

    player_idx = _get_port_idx(metadata, player_port)
    opp_idx = _get_port_idx(metadata, opponent_port)

    player_info = next(p for p in players if p["port"] == player_port)
    opp_info = next(p for p in players if p["port"] == opponent_port)
    player_char = int(player_info["character"])
    opp_char = int(opp_info["character"])

    # Access post-frame data via struct-of-arrays
    p_post = frames.ports[player_idx].leader.post
    o_post = frames.ports[opp_idx].leader.post
    p_pre = frames.ports[player_idx].leader.pre
    o_pre = frames.ports[opp_idx].leader.pre

    # --- Game duration (frames of actual gameplay) ---
    frame_ids = frames.id.to_pylist()
    first_gameplay = 0
    for i, fid in enumerate(frame_ids):
        if fid >= 0:
            first_gameplay = i
            break
    duration_frames = len(frame_ids) - first_gameplay

    # --- Stocks ---
    p_stocks_list = p_post.stocks.to_pylist()
    o_stocks_list = o_post.stocks.to_pylist()
    p_stocks_final = p_stocks_list[-1]
    o_stocks_final = o_stocks_list[-1]
    p_stocks_start = p_stocks_list[first_gameplay]
    o_stocks_start = o_stocks_list[first_gameplay]
    p_stocks_lost = p_stocks_start - p_stocks_final
    o_stocks_lost = o_stocks_start - o_stocks_final
    max_stocks_lost = max(p_stocks_lost, o_stocks_lost)

    kpis = {
        "filename": metadata["filename"],
        "character": char_name(player_char),
        "opponent_character": char_name(opp_char),
        "opponent_code": opp_info.get("connect_code"),
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
    p_pct_list = p_post.percent.to_pylist()
    o_pct_list = o_post.percent.to_pylist()
    p_pct_final = p_pct_list[-1]
    o_pct_final = o_pct_list[-1]

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

    # --- Action states as lists ---
    p_states = p_post.state.to_pylist()
    o_states = o_post.state.to_pylist()

    # --- Total damage dealt ---
    # Sum opponent percent increases (resets on stock loss indicate a kill)
    total_damage = 0.0
    for i in range(first_gameplay + 1, len(o_pct_list)):
        if o_pct_list[i] is not None and o_pct_list[i - 1] is not None:
            diff = o_pct_list[i] - o_pct_list[i - 1]
            if diff > 0:
                total_damage += diff
    kpis["total_damage"] = round(total_damage, 1)

    # --- Conversions / Openings ---
    p_conversions = _compute_conversions(
        p_states, o_states, p_pct_list, o_pct_list,
        p_stocks_list, o_stocks_list, first_gameplay
    )
    o_conversions = _compute_conversions(
        o_states, p_states, o_pct_list, p_pct_list,
        o_stocks_list, p_stocks_list, first_gameplay
    )

    kill_count = sum(1 for c in p_conversions if c["did_kill"])
    opening_count = len(p_conversions)
    total_conv_damage = sum(c["damage"] for c in p_conversions)

    kpis["kills"] = o_stocks_lost
    kpis["opening_count"] = opening_count
    kpis["conversion_rate"] = (
        round(kill_count / opening_count * 100, 1) if opening_count > 0 else None
    )
    kpis["openings_per_kill"] = (
        round(opening_count / kill_count, 1) if kill_count > 0 else None
    )
    kpis["damage_per_opening"] = (
        round(total_conv_damage / opening_count, 1) if opening_count > 0 else None
    )

    # --- Neutral classification ---
    neutral_wins, counter_hits, trades = _classify_conversions(p_conversions, o_conversions)
    o_neutral_wins, o_counter_hits, o_trades = _classify_conversions(o_conversions, p_conversions)

    kpis["neutral_wins"] = neutral_wins
    kpis["counter_hits"] = counter_hits
    kpis["trades"] = trades

    # --- L-cancel rate ---
    kpis.update(_lcancel_stats(p_post))

    # --- Action counts (defensive + movement) ---
    p_positions_y = p_post.position.y.to_pylist() if hasattr(p_post.position, 'y') else None
    action_counts = _compute_action_counts(p_states, p_positions_y, first_gameplay)
    kpis.update(action_counts)

    # --- Input stats ---
    kpis.update(_compute_inputs(p_pre, first_gameplay, duration_frames))

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

    # Numeric columns to average
    avg_cols = [
        "total_damage", "conversion_rate", "openings_per_kill",
        "damage_per_opening", "neutral_wins", "counter_hits", "trades",
        "spot_dodges", "air_dodges", "rolls", "wavedashes", "wavelands",
        "dash_dances", "ledge_grabs", "inputs_per_minute",
        "digital_inputs_per_minute",
    ]

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

        for col in avg_cols:
            if col in group.columns:
                vals = group[col].dropna()
                agg[f"avg_{col}"] = round(float(vals.mean()), 1) if len(vals) > 0 else None

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
