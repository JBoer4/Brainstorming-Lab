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
GROUND_ATTACK_START = 0x2C
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
                         p_stocks, o_stocks, first_gameplay,
                         o_last_attack_landed=None):
    """Compute conversions/openings for player attacking opponent.

    Follows slippi-js logic:
    - Start percent uses the previous frame (before the first hit lands)
    - Damage is accumulated move-by-move via frame-over-frame percent diffs
    - Reset counter keeps incrementing once started, regardless of state
    - Reset triggers at > PUNISH_RESET_FRAMES (not >=)
    - Tracks move count (changes in lastAttackLanded) for conversion rate
    """
    conversions = []
    current = None
    reset_counter = 0
    move_damage = 0.0
    move_count = 0
    last_attack = None

    for i in range(first_gameplay, len(o_states)):
        o_state = o_states[i]
        o_stock = o_stocks[i]

        in_hitlag = _is_damaged(o_state) or _is_grabbed(o_state) or _is_command_grabbed(o_state)

        # Accumulate per-move damage during active conversions
        if current is not None and i > 0:
            if o_percents[i] is not None and o_percents[i - 1] is not None:
                diff = o_percents[i] - o_percents[i - 1]
                if diff > 0:
                    move_damage += diff

        # Track moves via lastAttackLanded changes
        if current is not None and o_last_attack_landed is not None:
            atk = o_last_attack_landed[i]
            if atk is not None and atk != last_attack:
                move_count += 1
                last_attack = atk

        if current is None:
            if in_hitlag:
                prev_pct = o_percents[i - 1] if i > 0 and o_percents[i - 1] is not None else 0
                current = {
                    "start_frame": i,
                    "start_percent": prev_pct,
                    "end_frame": i,
                    "did_kill": False,
                    "start_stocks": o_stock,
                }
                reset_counter = 0
                move_damage = 0.0
                move_count = 0
                last_attack = None
                # Count damage from this first frame
                if o_percents[i] is not None:
                    diff = (o_percents[i] or 0) - (prev_pct or 0)
                    if diff > 0:
                        move_damage = diff
                # Track first move
                if o_last_attack_landed is not None:
                    atk = o_last_attack_landed[i]
                    if atk is not None:
                        move_count = 1
                        last_attack = atk
        else:
            if in_hitlag:
                current["end_frame"] = i
                reset_counter = 0
            else:
                should_start = reset_counter == 0 and _is_in_control(o_state)
                should_continue = reset_counter > 0
                if should_start or should_continue:
                    reset_counter += 1

            # Check for stock loss
            if o_stock is not None and current["start_stocks"] is not None:
                if o_stock < current["start_stocks"]:
                    current["did_kill"] = True
                    current["end_frame"] = i
                    current["damage"] = move_damage
                    current["move_count"] = move_count
                    conversions.append(current)
                    current = None
                    reset_counter = 0
                    move_damage = 0.0
                    move_count = 0
                    last_attack = None
                    continue

            if reset_counter > PUNISH_RESET_FRAMES:
                current["damage"] = move_damage
                current["move_count"] = move_count
                conversions.append(current)
                current = None
                reset_counter = 0
                move_damage = 0.0
                move_count = 0
                last_attack = None

    if current is not None:
        current["damage"] = move_damage
        current["move_count"] = move_count
        conversions.append(current)

    return conversions


def _classify_conversions(p_conversions, o_conversions):
    """Classify conversions as neutral_win, counter_attack, or trade.

    Follows slippi-js logic: track the opponent's most recent conversion
    end frame. If the opponent was still comboing us when our conversion
    started, it's a counter-attack. If both start on the same frame, trade.
    Otherwise, neutral win.
    """
    neutral_wins = 0
    counter_hits = 0
    trades = 0

    o_by_start = {}
    for c in o_conversions:
        o_by_start.setdefault(c["start_frame"], []).append(c)

    # Track the latest end frame of any opponent conversion seen so far
    # Process opponent conversions in start_frame order
    o_sorted = sorted(o_conversions, key=lambda c: c["start_frame"])
    o_idx = 0
    last_opp_end_frame = -1

    # Process player conversions in start_frame order
    p_sorted = sorted(p_conversions, key=lambda c: c["start_frame"])

    for conv in p_sorted:
        sf = conv["start_frame"]

        # Advance opponent pointer: include all opponent conversions that
        # started before or at this frame
        while o_idx < len(o_sorted) and o_sorted[o_idx]["start_frame"] <= sf:
            last_opp_end_frame = max(last_opp_end_frame, o_sorted[o_idx]["end_frame"])
            o_idx += 1

        # Trade: opponent conversion starts on same frame
        if sf in o_by_start:
            trades += 1
            continue

        # Counter-attack: opponent's last conversion hadn't ended yet
        if last_opp_end_frame > sf:
            counter_hits += 1
            continue

        neutral_wins += 1

    return neutral_wins, counter_hits, trades


def _compute_action_counts(states, positions_y, first_gameplay, state_counters=None):
    """Count defensive and movement actions from action state sequence.

    Follows slippi-js logic:
    - New action = animation changed OR actionStateCounter reset
    - Wavedash: frame immediately before LANDING_FALL_SPECIAL must be
      AIR_DODGE or a jump state (not just anywhere in a lookback window)
    - Late air dodge filter: if the only unique states in the 15-frame
      window (including current) are AIR_DODGE and LANDING_FALL_SPECIAL

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

        # Detect new action: animation changed OR actionStateCounter reset
        is_new_action = s != prev
        if not is_new_action and state_counters is not None and i > 0:
            is_new_action = state_counters[i] < state_counters[i - 1]

        if not is_new_action:
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
            # slippi-js: the immediately previous frame must be an
            # acceptable wavedash initiation animation
            is_acceptable_prev = (
                prev == AIR_DODGE
                or (prev is not None and JUMP_START <= prev <= JUMP_END)
            )
            if not is_acceptable_prev:
                continue

            # Check lookback window for late air dodge filter
            lookback_start = max(first_gameplay, i - WAVEDASH_LOOKBACK + 1)
            # Window includes current frame, matching slippi-js .slice(-15)
            window = states[lookback_start:i + 1]
            unique_in_window = set(window)

            # Late air dodge: only AIR_DODGE and LANDING_FALL_SPECIAL in window
            if unique_in_window == {AIR_DODGE, LANDING_FALL_SPECIAL}:
                continue

            # slippi-js does NOT deduct air dodges — wavedashes and air dodges
            # are counted independently

            # Check for knee bend in window to distinguish wavedash vs waveland
            had_kneebend = KNEE_BEND in window

            if had_kneebend:
                kb_idx = None
                for j in range(i - 1, lookback_start - 1, -1):
                    if states[j] == KNEE_BEND:
                        kb_idx = j
                        break

                if kb_idx is not None and positions_y is not None:
                    y_start = positions_y[kb_idx]
                    y_end = positions_y[i]
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

    duration_seconds = round(duration_frames / 60, 1)

    kpis = {
        "filename": metadata["filename"],
        "character": char_name(player_char),
        "opponent_character": char_name(opp_char),
        "opponent_code": opp_info.get("connect_code"),
        "duration_frames": duration_frames,
        "duration_seconds": duration_seconds,
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

    # --- Conversions / Openings ---
    # lastAttackLanded tracks which move hit the opponent (used for move counting)
    o_last_atk = o_post.last_attack_landed.to_pylist() if hasattr(o_post, 'last_attack_landed') else None
    p_last_atk = p_post.last_attack_landed.to_pylist() if hasattr(p_post, 'last_attack_landed') else None

    p_conversions = _compute_conversions(
        p_states, o_states, p_pct_list, o_pct_list,
        p_stocks_list, o_stocks_list, first_gameplay, o_last_atk
    )
    o_conversions = _compute_conversions(
        o_states, p_states, o_pct_list, p_pct_list,
        o_stocks_list, p_stocks_list, first_gameplay, p_last_atk
    )

    # Player conversion stats — matches slippi-js overall.ts
    kill_count = sum(1 for c in p_conversions if c["did_kill"])
    opening_count = len(p_conversions)
    # "Successful conversion" in slippi-js = more than 1 move landed
    successful_count = sum(1 for c in p_conversions if c.get("move_count", 0) > 1)
    total_damage = sum(c["damage"] for c in p_conversions)

    kpis["total_damage"] = round(total_damage, 1)
    kpis["kills"] = o_stocks_lost
    kpis["opening_count"] = opening_count
    kpis["conversion_rate"] = (
        round(successful_count / opening_count * 100, 1) if opening_count > 0 else None
    )
    kpis["openings_per_kill"] = (
        round(opening_count / kill_count, 1) if kill_count > 0 else None
    )
    kpis["damage_per_opening"] = (
        round(total_damage / opening_count, 1) if opening_count > 0 else None
    )

    # Opponent conversion stats
    opp_kill_count = sum(1 for c in o_conversions if c["did_kill"])
    opp_opening_count = len(o_conversions)
    opp_successful_count = sum(1 for c in o_conversions if c.get("move_count", 0) > 1)
    opp_total_damage = sum(c["damage"] for c in o_conversions)

    kpis["opp_total_damage"] = round(opp_total_damage, 1)
    kpis["opp_kills"] = p_stocks_lost
    kpis["opp_opening_count"] = opp_opening_count
    kpis["opp_conversion_rate"] = (
        round(opp_successful_count / opp_opening_count * 100, 1) if opp_opening_count > 0 else None
    )
    kpis["opp_openings_per_kill"] = (
        round(opp_opening_count / opp_kill_count, 1) if opp_kill_count > 0 else None
    )
    kpis["opp_damage_per_opening"] = (
        round(opp_total_damage / opp_opening_count, 1) if opp_opening_count > 0 else None
    )

    # --- Neutral classification ---
    neutral_wins, counter_hits, trades = _classify_conversions(p_conversions, o_conversions)
    o_neutral_wins, o_counter_hits, o_trades = _classify_conversions(o_conversions, p_conversions)

    kpis["neutral_wins"] = neutral_wins
    kpis["counter_hits"] = counter_hits
    kpis["trades"] = trades
    kpis["opp_neutral_wins"] = o_neutral_wins
    kpis["opp_counter_hits"] = o_counter_hits
    kpis["opp_trades"] = o_trades

    # --- L-cancel rate (player) ---
    kpis.update(_lcancel_stats(p_post))

    # --- L-cancel rate (opponent) ---
    opp_lc = _lcancel_stats(o_post)
    kpis["opp_lcancel_success"] = opp_lc["lcancel_success"]
    kpis["opp_lcancel_miss"] = opp_lc["lcancel_miss"]
    kpis["opp_lcancel_rate"] = opp_lc["lcancel_rate"]

    # --- Action counts (player) ---
    p_positions_y = p_post.position.y.to_pylist() if hasattr(p_post.position, 'y') else None
    p_state_counters = p_post.state_age.to_pylist() if hasattr(p_post, 'state_age') else None
    action_counts = _compute_action_counts(p_states, p_positions_y, first_gameplay, p_state_counters)
    kpis.update(action_counts)

    # --- Action counts (opponent) ---
    o_positions_y = o_post.position.y.to_pylist() if hasattr(o_post.position, 'y') else None
    o_state_counters = o_post.state_age.to_pylist() if hasattr(o_post, 'state_age') else None
    opp_actions = _compute_action_counts(o_states, o_positions_y, first_gameplay, o_state_counters)
    for k, v in opp_actions.items():
        kpis[f"opp_{k}"] = v

    # --- Input stats (player) ---
    kpis.update(_compute_inputs(p_pre, first_gameplay, duration_frames))

    # --- Input stats (opponent) ---
    opp_inputs = _compute_inputs(o_pre, first_gameplay, duration_frames)
    kpis["opp_inputs_per_minute"] = opp_inputs["inputs_per_minute"]
    kpis["opp_digital_inputs_per_minute"] = opp_inputs["digital_inputs_per_minute"]

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
        # Opponent stats
        "opp_total_damage", "opp_conversion_rate", "opp_openings_per_kill",
        "opp_damage_per_opening", "opp_neutral_wins", "opp_counter_hits",
        "opp_trades", "opp_spot_dodges", "opp_air_dodges", "opp_rolls",
        "opp_wavedashes", "opp_wavelands", "opp_dash_dances",
        "opp_ledge_grabs", "opp_inputs_per_minute",
        "opp_digital_inputs_per_minute",
    ]

    for char, group in df.groupby("character"):
        total_lcancels = group["lcancel_success"].sum() + group["lcancel_miss"].sum()
        opp_total_lcancels = group["opp_lcancel_success"].sum() + group["opp_lcancel_miss"].sum()

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
            "opp_lcancel_rate": (
                float(group["opp_lcancel_success"].sum() / opp_total_lcancels)
                if opp_total_lcancels > 0
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
