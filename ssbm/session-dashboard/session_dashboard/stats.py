"""
Pure Python re-implementation of @slippi/slippi-js stat computation.

Ports the slippi-js algorithms directly to work with peppi-py game objects,
eliminating the Node.js subprocess dependency.

Reference: @slippi/slippi-js dist/node/index.esm.js
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Frame/timing constants
# ---------------------------------------------------------------------------
FIRST_PLAYABLE = -39  # Frames.FIRST_PLAYABLE — countdown ends, game starts
PUNISH_RESET_FRAMES = 45  # Timers.PUNISH_RESET_FRAMES

# ---------------------------------------------------------------------------
# Action state IDs (from slippi-js State object)
# ---------------------------------------------------------------------------

# Ranges
DAMAGE_START = 0x4B
DAMAGE_END = 0x5B
CAPTURE_START = 0xDF
CAPTURE_END = 0xE8
GROUNDED_CONTROL_START = 0x0E
GROUNDED_CONTROL_END = 0x18
SQUAT_START = 0x27
SQUAT_END = 0x29
GROUND_ATTACK_START = 0x2C  # isInControl uses strictly > this
GROUND_ATTACK_END = 0x40
DYING_START = 0x00
DYING_END = 0x0A
CONTROLLED_JUMP_START = 0x18  # also ACTION_KNEE_BEND
CONTROLLED_JUMP_END = 0x22
AERIAL_LANDING_START = 0x46
AERIAL_LANDING_END = 0x4A
COMMAND_GRAB_RANGE1_START = 0x10A
COMMAND_GRAB_RANGE1_END = 0x130
COMMAND_GRAB_RANGE2_START = 0x147
COMMAND_GRAB_RANGE2_END = 0x152

# Specific states
DAMAGE_FALL = 0x26
JAB_RESET_UP = 0xB9
JAB_RESET_DOWN = 0xC1
BARREL_WAIT = 0x125
ROLL_FORWARD = 0xE9
ROLL_BACKWARD = 0xEA
SPOT_DODGE = 0xEB
AIR_DODGE = 0xEC
LANDING_FALL_SPECIAL = 0x2B
CLIFF_CATCH = 0xFC
DASH = 0x14
TURN = 0x12
FALL = 0x1D
FALL_AERIAL = 0x1E          # airborne version of fall
FALL_SPECIAL = 0x1F         # special-fall (e.g. after B-moves)
FALL_AERIAL_SPECIAL = 0x20
FALL_BACK = 0x21
FALL_BACK_AERIAL = 0x22
TEETER = 0xF5
GRAB = 0xD4

# Joystick dead-zone threshold (from slippi-js getJoystickRegion)
JOY_THRESHOLD = 0.2875

# ---------------------------------------------------------------------------
# State predicate functions (ported from slippi-js)
# ---------------------------------------------------------------------------

def _is_damaged(s: int) -> bool:
    return (DAMAGE_START <= s <= DAMAGE_END) or s == DAMAGE_FALL or s == JAB_RESET_UP or s == JAB_RESET_DOWN


def _is_grabbed(s: int) -> bool:
    return CAPTURE_START <= s <= CAPTURE_END


def _is_command_grabbed(s: int) -> bool:
    in_range = (
        (COMMAND_GRAB_RANGE1_START <= s <= COMMAND_GRAB_RANGE1_END) or
        (COMMAND_GRAB_RANGE2_START <= s <= COMMAND_GRAB_RANGE2_END)
    )
    return in_range and s != BARREL_WAIT


def _is_dead(s: int) -> bool:
    return DYING_START <= s <= DYING_END


def _is_in_control(s: int) -> bool:
    """True when the player is in a grounded-control, squat, ground-attack, or grab state."""
    ground = GROUNDED_CONTROL_START <= s <= GROUNDED_CONTROL_END
    squat = SQUAT_START <= s <= SQUAT_END
    ground_attack = GROUND_ATTACK_START < s <= GROUND_ATTACK_END  # strictly >
    is_grab = s == GRAB
    return ground or squat or ground_attack or is_grab


def _is_aerial_landing(s: int) -> bool:
    return AERIAL_LANDING_START <= s <= AERIAL_LANDING_END


def _is_actionable(s: int) -> bool:
    """True when the player has agency (can input actions).

    Used for the L-cancel miss check: if the player becomes actionable within
    8 frames of a failed L-cancel flag, the landing was cut short by something
    (edge cancel, etc.) and we don't count it as a miss.
    """
    return not (
        _is_aerial_landing(s) or
        _is_damaged(s) or
        _is_dead(s) or
        _is_grabbed(s) or
        _is_command_grabbed(s)
    )


def _is_wavedash_initiation(s: int) -> bool:
    return s == AIR_DODGE or (CONTROLLED_JUMP_START <= s <= CONTROLLED_JUMP_END)


def _is_rolling(s: int) -> bool:
    return s == ROLL_FORWARD or s == ROLL_BACKWARD


def _joystick_region(x: float, y: float) -> int:
    """Map analog stick coordinates to a region (0=DZ, 1–8=directional)."""
    t = JOY_THRESHOLD
    if x >= t and y >= t:
        return 1   # NE
    if x >= t and y <= -t:
        return 2   # SE
    if x <= -t and y <= -t:
        return 3   # SW
    if x <= -t and y >= t:
        return 4   # NW
    if y >= t:
        return 5   # N
    if x >= t:
        return 6   # E
    if y <= -t:
        return 7   # S
    if x <= -t:
        return 8   # W
    return 0       # DZ


def _count_bits(x: int) -> int:
    """Count set bits (Hamming weight)."""
    count = 0
    while x:
        x &= x - 1
        count += 1
    return count


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _dedup_indices(frame_ids: list) -> list:
    """
    Return sorted indices of the *last* occurrence of each frame number.

    Online replays use rollback netcode, so the same frame number can appear
    multiple times in peppi-py's flat arrays.  Slippi-js only processes the
    final (corrected) version of each frame; we reproduce that by keeping only
    the last occurrence of each frame ID.
    """
    last_by_frame: dict[int, int] = {}
    for i, fid in enumerate(frame_ids):
        last_by_frame[fid] = i
    return sorted(last_by_frame.values())


def compute_game_stats(game, p_port_idx: int, o_port_idx: int) -> dict:
    """
    Compute Slippi stats from a peppi-py Game object.

    Returns a dict that mirrors the slippi-js JSON schema so that kpis.py
    needs minimal changes.  ``playerIndex`` values in the output are
    *port_idx* values (0 or 1), not the game's port numbers.

    Args:
        game: peppi_py.game.Game object.
        p_port_idx: Index into game.frames.ports[] for the player.
        o_port_idx: Index into game.frames.ports[] for the opponent.
    """
    raw_frame_ids = game.frames.id.to_pylist()
    keep = _dedup_indices(raw_frame_ids)
    frame_ids = [raw_frame_ids[i] for i in keep]
    n = len(frame_ids)

    def _pick(arr) -> list:
        """Extract deduplicated values from a pyarrow array."""
        lst = arr.to_pylist()
        return [lst[i] for i in keep]

    # --- Extract columnar frame data, deduplicated to finalized frames ---

    p_post_raw = game.frames.ports[p_port_idx].leader.post
    o_post_raw = game.frames.ports[o_port_idx].leader.post
    p_pre_raw = game.frames.ports[p_port_idx].leader.pre
    o_pre_raw = game.frames.ports[o_port_idx].leader.pre

    p_s   = _pick(p_post_raw.state)        # action state ID
    p_sa  = _pick(p_post_raw.state_age)    # float or None
    p_pct = _pick(p_post_raw.percent)
    p_stk = _pick(p_post_raw.stocks)
    p_dir = _pick(p_post_raw.direction)
    p_px  = _pick(p_post_raw.position.x)
    p_lc  = _pick(p_post_raw.l_cancel)     # 0=N/A, 1=success, 2=fail
    p_la  = _pick(p_post_raw.last_attack_landed)

    o_s   = _pick(o_post_raw.state)
    o_sa  = _pick(o_post_raw.state_age)
    o_pct = _pick(o_post_raw.percent)
    o_stk = _pick(o_post_raw.stocks)
    o_dir = _pick(o_post_raw.direction)
    o_px  = _pick(o_post_raw.position.x)
    o_lc  = _pick(o_post_raw.l_cancel)
    o_la  = _pick(o_post_raw.last_attack_landed)

    p_btn = _pick(p_pre_raw.buttons_physical)
    p_jx  = _pick(p_pre_raw.joystick.x)
    p_jy  = _pick(p_pre_raw.joystick.y)
    p_cx  = _pick(p_pre_raw.cstick.x)
    p_cy  = _pick(p_pre_raw.cstick.y)
    p_tl  = _pick(p_pre_raw.triggers_physical.l)
    p_tr  = _pick(p_pre_raw.triggers_physical.r)

    o_btn = _pick(o_pre_raw.buttons_physical)
    o_jx  = _pick(o_pre_raw.joystick.x)
    o_jy  = _pick(o_pre_raw.joystick.y)
    o_cx  = _pick(o_pre_raw.cstick.x)
    o_cy  = _pick(o_pre_raw.cstick.y)
    o_tl  = _pick(o_pre_raw.triggers_physical.l)
    o_tr  = _pick(o_pre_raw.triggers_physical.r)

    # Start stocks from game settings
    p_start_stk = game.start.players[p_port_idx].stocks
    o_start_stk = game.start.players[o_port_idx].stocks

    # --- Playable frame count ---
    last_frame = frame_ids[-1] if frame_ids else FIRST_PLAYABLE
    playable_frame_count = max(0, last_frame - FIRST_PLAYABLE)

    # --- Stocks ---
    stocks = _compute_stocks(
        frame_ids, n,
        p_port_idx, p_s, p_pct, p_stk,
        o_port_idx, o_s, o_pct, o_stk,
    )

    # --- Action counts ---
    p_actions = _compute_action_counts(
        p_port_idx, frame_ids, n,
        p_s, p_sa, p_pct, p_px, p_dir, p_lc,
        o_px,
    )
    o_actions = _compute_action_counts(
        o_port_idx, frame_ids, n,
        o_s, o_sa, o_pct, o_px, o_dir, o_lc,
        p_px,
    )

    # --- Inputs ---
    p_inputs = _compute_inputs(
        p_port_idx, frame_ids, n,
        p_btn, p_jx, p_jy, p_cx, p_cy, p_tl, p_tr,
    )
    o_inputs = _compute_inputs(
        o_port_idx, frame_ids, n,
        o_btn, o_jx, o_jy, o_cx, o_cy, o_tl, o_tr,
    )

    # --- Conversions ---
    conversions = _compute_conversions(
        frame_ids, n,
        p_port_idx, p_s, p_sa, p_pct, p_stk, p_la,
        o_port_idx, o_s, o_sa, o_pct, o_stk, o_la,
    )
    _populate_conversion_types(conversions)

    # --- Overall stats ---
    game_minutes = playable_frame_count / 3600.0
    p_overall = _compute_overall(
        p_port_idx, o_port_idx, conversions,
        p_inputs, game_minutes,
    )
    o_overall = _compute_overall(
        o_port_idx, p_port_idx, conversions,
        o_inputs, game_minutes,
    )

    # --- Build output dict (mirrors slippi-js schema) ---
    settings = {
        "players": [
            {"playerIndex": p_port_idx, "startStocks": p_start_stk},
            {"playerIndex": o_port_idx, "startStocks": o_start_stk},
        ],
    }
    stats = {
        "playableFrameCount": playable_frame_count,
        "stocks": stocks,
        "overall": [p_overall, o_overall],
        "actionCounts": [p_actions, o_actions],
        "conversions": conversions,
    }
    return {"settings": settings, "stats": stats}


# ---------------------------------------------------------------------------
# Stocks
# ---------------------------------------------------------------------------

def _compute_stocks(
    frame_ids, n,
    p_idx, p_s, p_pct, p_stk,
    o_idx, o_s, o_pct, o_stk,
) -> list:
    """
    Track stock periods for both players.

    A stock starts when the player first leaves the dying state.
    A stock ends when stocks_remaining decreases.
    """
    stocks = []
    p_stock = None
    o_stock = None

    for i in range(n):
        # --- Player ---
        if p_stock is None:
            if not _is_dead(p_s[i]):
                p_stock = {
                    "playerIndex": p_idx,
                    "startFrame": frame_ids[i],
                    "endFrame": None,
                    "startPercent": 0.0,
                    "endPercent": None,
                    "currentPercent": 0.0,
                    "count": p_stk[i],
                }
                stocks.append(p_stock)
        else:
            prev_stk = p_stk[i - 1] if i > 0 else p_stk[i]
            if p_stk[i] < prev_stk:
                p_stock["endFrame"] = frame_ids[i]
                p_stock["endPercent"] = p_pct[i - 1] if i > 0 else 0.0
                p_stock = None
            else:
                p_stock["currentPercent"] = p_pct[i] or 0.0

        # --- Opponent ---
        if o_stock is None:
            if not _is_dead(o_s[i]):
                o_stock = {
                    "playerIndex": o_idx,
                    "startFrame": frame_ids[i],
                    "endFrame": None,
                    "startPercent": 0.0,
                    "endPercent": None,
                    "currentPercent": 0.0,
                    "count": o_stk[i],
                }
                stocks.append(o_stock)
        else:
            prev_stk = o_stk[i - 1] if i > 0 else o_stk[i]
            if o_stk[i] < prev_stk:
                o_stock["endFrame"] = frame_ids[i]
                o_stock["endPercent"] = o_pct[i - 1] if i > 0 else 0.0
                o_stock = None
            else:
                o_stock["currentPercent"] = o_pct[i] or 0.0

    return stocks


# ---------------------------------------------------------------------------
# Action counts
# ---------------------------------------------------------------------------

def _compute_action_counts(
    player_idx, frame_ids, n,
    s, sa, pct, px, dirn, lc,
    opp_px,
) -> dict:
    """
    Count tech-skill actions for one player.

    Mirrors slippi-js ActionsComputer / handleActionCompute.
    """
    counts = {
        "playerIndex": player_idx,
        "wavedashCount": 0,
        "wavelandCount": 0,
        "airDodgeCount": 0,
        "dashDanceCount": 0,
        "spotDodgeCount": 0,
        "ledgegrabCount": 0,
        "rollCount": 0,
        "lCancelCount": {"success": 0, "fail": 0},
    }

    # Keep a rolling animation history (last 8 frames) for wavedash detection
    anim_history = []

    for i in range(n):
        cur_anim = s[i]
        cur_counter = sa[i]

        # Append current frame to history
        anim_history.append(cur_anim)
        if len(anim_history) > 8:
            anim_history.pop(0)

        prev_anim = anim_history[-2] if len(anim_history) >= 2 else None
        prev_counter = sa[i - 1] if i > 0 else None

        # Detect new action: state changed OR counter reset
        counter_reset = (
            cur_counter is not None and
            prev_counter is not None and
            cur_counter < prev_counter
        )
        is_new_action = (prev_anim is None) or (cur_anim != prev_anim) or counter_reset

        if not is_new_action:
            continue

        # --- Count new actions ---
        last3 = anim_history[-3:] if len(anim_history) >= 3 else []
        if last3 == [DASH, TURN, DASH]:
            counts["dashDanceCount"] += 1

        if _is_rolling(cur_anim):
            counts["rollCount"] += 1

        if cur_anim == SPOT_DODGE:
            counts["spotDodgeCount"] += 1

        if cur_anim == AIR_DODGE:
            counts["airDodgeCount"] += 1

        if cur_anim == CLIFF_CATCH:
            counts["ledgegrabCount"] += 1

        # L-cancel: fires on entering an aerial landing state.
        # For a failed flag (lc==2), look ahead up to 8 frames: if the character
        # reaches an actionable state (not in landing lag / hitstun / grabbed),
        # the landing was cut short by an edge cancel or similar and we skip it.
        if _is_aerial_landing(cur_anim):
            if lc[i] == 1:
                counts["lCancelCount"]["success"] += 1
            elif lc[i] == 2:
                became_actionable = any(
                    _is_actionable(s[j])
                    for j in range(i + 1, min(i + 9, n))
                )
                if not became_actionable:
                    counts["lCancelCount"]["fail"] += 1

        # Wavedash / waveland detection
        _handle_wavedash(counts, anim_history)

    return counts


def _handle_wavedash(counts: dict, anim_history: list) -> None:
    """
    Detect wavedash or waveland from animation history.

    Mirrors slippi-js handleActionWavedash.
    """
    if len(anim_history) < 2:
        return

    cur_anim = anim_history[-1]
    prev_anim = anim_history[-2]

    if cur_anim != LANDING_FALL_SPECIAL:
        return
    if not _is_wavedash_initiation(prev_anim):
        return

    # Check last 8 frames for air dodge
    recent = set(anim_history)

    # Edge case: if the only other animation is air dodge, it might just be a late air dodge
    if len(recent) == 2 and AIR_DODGE in recent:
        return

    if AIR_DODGE in recent:
        # Remove one air dodge from the counter (wavedash consumed it)
        counts["airDodgeCount"] = max(0, counts["airDodgeCount"] - 1)

    # ACTION_KNEE_BEND == CONTROLLED_JUMP_START == 0x18; slippi-js checks this exact value
    if CONTROLLED_JUMP_START in recent:
        counts["wavedashCount"] += 1
    else:
        counts["wavelandCount"] += 1


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

def _compute_inputs(
    player_idx, frame_ids, n,
    btn, jx, jy, cx, cy, tl, tr,
) -> dict:
    """
    Count inputs for one player.

    Mirrors slippi-js InputComputer / handleInputCompute.
    Only counts frames at or after FIRST_PLAYABLE.
    """
    input_count = 0
    button_count = 0
    joystick_count = 0
    cstick_count = 0
    trigger_count = 0

    for i in range(1, n):
        if frame_ids[i] < FIRST_PLAYABLE:
            continue

        # Button presses: bits that go 0 → 1
        prev_btn = btn[i - 1] if btn[i - 1] is not None else 0
        cur_btn = btn[i] if btn[i] is not None else 0
        new_presses = _count_bits((~prev_btn) & cur_btn & 0xFFF)
        input_count += new_presses
        button_count += new_presses

        # Joystick region transitions (exclude return to DZ)
        prev_jr = _joystick_region(jx[i - 1] or 0.0, jy[i - 1] or 0.0)
        cur_jr = _joystick_region(jx[i] or 0.0, jy[i] or 0.0)
        if prev_jr != cur_jr and cur_jr != 0:
            input_count += 1
            joystick_count += 1

        # C-stick region transitions
        prev_cr = _joystick_region(cx[i - 1] or 0.0, cy[i - 1] or 0.0)
        cur_cr = _joystick_region(cx[i] or 0.0, cy[i] or 0.0)
        if prev_cr != cur_cr and cur_cr != 0:
            input_count += 1
            cstick_count += 1

        # Trigger press (threshold 0.3)
        prev_tl = tl[i - 1] or 0.0
        cur_tl = tl[i] or 0.0
        if prev_tl < 0.3 and cur_tl >= 0.3:
            input_count += 1
            trigger_count += 1

        prev_tr = tr[i - 1] or 0.0
        cur_tr = tr[i] or 0.0
        if prev_tr < 0.3 and cur_tr >= 0.3:
            input_count += 1
            trigger_count += 1

    return {
        "playerIndex": player_idx,
        "inputCount": input_count,
        "buttonInputCount": button_count,
        "joystickInputCount": joystick_count,
        "cstickInputCount": cstick_count,
        "triggerInputCount": trigger_count,
    }


# ---------------------------------------------------------------------------
# Conversions
# ---------------------------------------------------------------------------

def _compute_conversions(
    frame_ids, n,
    p_idx, p_s, p_sa, p_pct, p_stk, p_la,
    o_idx, o_s, o_sa, o_pct, o_stk, o_la,
) -> list:
    """
    Compute conversion (punish) records for both player→opponent directions.

    Mirrors slippi-js ConversionComputer / handleConversionCompute.
    A conversion is a period where one player is in a damaged/grabbed state.
    """
    conversions: list[dict] = []

    # State for p attacking o (conversions on the opponent)
    po_state = {"conversion": None, "move": None, "reset_counter": 0, "last_hit_anim": None}
    # State for o attacking p (conversions on the player)
    op_state = {"conversion": None, "move": None, "reset_counter": 0, "last_hit_anim": None}

    for i in range(n):
        fid = frame_ids[i]

        # p→o direction: p is attacker, o is victim
        _handle_conversion_frame(
            conv_state=po_state,
            conversions=conversions,
            frame_id=fid,
            # Attacker (player)
            att_s=p_s, att_sa=p_sa, att_la=p_la,
            att_idx=p_idx,
            # Victim (opponent)
            vic_s=o_s, vic_pct=o_pct, vic_stk=o_stk,
            vic_idx=o_idx,
            i=i,
        )

        # o→p direction: o is attacker, p is victim
        _handle_conversion_frame(
            conv_state=op_state,
            conversions=conversions,
            frame_id=fid,
            att_s=o_s, att_sa=o_sa, att_la=o_la,
            att_idx=o_idx,
            vic_s=p_s, vic_pct=p_pct, vic_stk=p_stk,
            vic_idx=p_idx,
            i=i,
        )

    return conversions


def _handle_conversion_frame(
    conv_state: dict,
    conversions: list,
    frame_id: int,
    att_s, att_sa, att_la, att_idx,
    vic_s, vic_pct, vic_stk, vic_idx,
    i: int,
) -> None:
    """Process one frame for the conversion tracker (one attacker→victim direction)."""
    vic_state_id = vic_s[i]
    opnt_is_damaged = _is_damaged(vic_state_id)
    opnt_is_grabbed = _is_grabbed(vic_state_id)
    opnt_is_cmd_grabbed = _is_command_grabbed(vic_state_id)

    # Damage taken this frame = percent delta
    if i > 0:
        prev_pct = vic_pct[i - 1] or 0.0
        cur_pct = vic_pct[i] or 0.0
        opnt_dmg_taken = cur_pct - prev_pct
    else:
        opnt_dmg_taken = 0.0

    # Detect attacker's action change (for move-counting dedup)
    cur_att_anim = att_s[i]
    cur_att_counter = att_sa[i]
    prev_att_counter = att_sa[i - 1] if i > 0 else None
    counter_reset = (
        cur_att_counter is not None and
        prev_att_counter is not None and
        cur_att_counter < prev_att_counter
    )
    action_changed = (cur_att_anim != conv_state["last_hit_anim"]) or counter_reset
    if action_changed:
        conv_state["last_hit_anim"] = None

    if opnt_is_damaged or opnt_is_grabbed or opnt_is_cmd_grabbed:
        # Start a new conversion if not already tracking one
        if conv_state["conversion"] is None:
            start_pct = (vic_pct[i - 1] or 0.0) if i > 0 else 0.0
            conv = {
                "playerIndex": vic_idx,      # the player being converted
                "lastHitBy": att_idx,
                "startFrame": frame_id,
                "endFrame": None,
                "startPercent": start_pct,
                "currentPercent": vic_pct[i] or 0.0,
                "endPercent": None,
                "moves": [],
                "didKill": False,
                "openingType": "unknown",
            }
            conv_state["conversion"] = conv
            conversions.append(conv)

        if opnt_dmg_taken > 0:
            # New hit if last_hit_anim is cleared
            if conv_state["last_hit_anim"] is None:
                move = {
                    "playerIndex": att_idx,
                    "frame": frame_id,
                    "moveId": att_la[i],
                    "hitCount": 0,
                    "damage": 0.0,
                }
                conv_state["move"] = move
                conv_state["conversion"]["moves"].append(move)

            if conv_state["move"] is not None:
                conv_state["move"]["hitCount"] += 1
                conv_state["move"]["damage"] += opnt_dmg_taken

            # Record animation of the frame where the hit connected
            prev_att_anim = att_s[i - 1] if i > 0 else None
            conv_state["last_hit_anim"] = prev_att_anim

    if conv_state["conversion"] is None:
        return

    opnt_in_control = _is_in_control(vic_state_id)

    # Check stock loss
    opnt_lost_stock = False
    if i > 0:
        opnt_lost_stock = (vic_stk[i - 1] or 0) > (vic_stk[i] or 0)

    # Update current percent unless the stock was lost
    if not opnt_lost_stock:
        conv_state["conversion"]["currentPercent"] = vic_pct[i] or 0.0

    # Reset counter logic (mirrors slippi-js exactly):
    # - Resets to 0 when opponent is in hitstun/grabbed
    # - Starts counting once opponent first re-enters a control state
    # - Continues counting even if opponent is no longer in control (down, tech, air, etc.)
    if opnt_is_damaged or opnt_is_grabbed or opnt_is_cmd_grabbed:
        conv_state["reset_counter"] = 0
    elif conv_state["reset_counter"] == 0 and opnt_in_control:
        conv_state["reset_counter"] += 1
    elif conv_state["reset_counter"] > 0:
        conv_state["reset_counter"] += 1

    # Termination conditions
    terminate = False
    if opnt_lost_stock:
        conv_state["conversion"]["didKill"] = True
        terminate = True
    elif conv_state["reset_counter"] > PUNISH_RESET_FRAMES:
        terminate = True

    if terminate:
        conv_state["conversion"]["endFrame"] = frame_id
        prev_vic_pct = (vic_pct[i - 1] or 0.0) if i > 0 else 0.0
        conv_state["conversion"]["endPercent"] = prev_vic_pct
        conv_state["conversion"] = None
        conv_state["move"] = None


def _populate_conversion_types(conversions: list) -> None:
    """
    Classify each conversion as 'neutral-win', 'counter-attack', or 'trade'.

    Mirrors slippi-js ConversionComputer._populateConversionTypes.
    """
    # Only process unknown conversions
    unknown = [c for c in conversions if c["openingType"] == "unknown"]

    # Group by startFrame
    by_start: dict[int, list] = {}
    for c in unknown:
        by_start.setdefault(c["startFrame"], []).append(c)

    last_end_by_player: dict[int, int | None] = {}

    for start_frame in sorted(by_start.keys()):
        group = by_start[start_frame]
        is_trade = len(group) >= 2

        for conv in group:
            # Record this conversion's end frame for future counter-attack detection
            last_end_by_player[conv["playerIndex"]] = conv["endFrame"]

            if is_trade:
                conv["openingType"] = "trade"
                continue

            # Check if the opponent had a recent conversion ending after our start
            last_move = conv["moves"][-1] if conv["moves"] else None
            opp_player_idx = last_move["playerIndex"] if last_move else conv["playerIndex"]
            opp_end = last_end_by_player.get(opp_player_idx)
            if opp_end is not None and opp_end > start_frame:
                conv["openingType"] = "counter-attack"
            else:
                conv["openingType"] = "neutral-win"


# ---------------------------------------------------------------------------
# Overall stats (from conversions + inputs)
# ---------------------------------------------------------------------------

def _get_ratio(count: int | float, total: int | float) -> dict:
    """Return a RatioType dict matching slippi-js getRatio."""
    return {
        "count": count,
        "total": total,
        "ratio": (count / total) if total else None,
    }


def _compute_overall(
    player_idx: int,
    opponent_idx: int,
    conversions: list,
    inputs: dict,
    game_minutes: float,
) -> dict:
    """
    Compute overall stats for one player.

    Mirrors slippi-js generateOverallStats.
    """
    # Conversions where the OPPONENT is victim (player was attacking)
    opp_conversions = [c for c in conversions if c["playerIndex"] == opponent_idx]
    # Conversions where the PLAYER is victim (opponent was attacking)
    player_conversions = [c for c in conversions if c["playerIndex"] == player_idx]

    # Group by opening type — keyed from the ATTACKER's perspective (mirrors slippi-js
    # conversionsByPlayerByOpening, which groups by moves[0].playerIndex = attacker index)
    # In 1v1: attacker of opp_conversions = player, attacker of player_conversions = opponent
    player_attacks_by_opening: dict[str, list] = {}  # player attacking → opp_conversions
    for c in opp_conversions:
        player_attacks_by_opening.setdefault(c["openingType"], []).append(c)

    opp_attacks_by_opening: dict[str, list] = {}  # opponent attacking → player_conversions
    for c in player_conversions:
        opp_attacks_by_opening.setdefault(c["openingType"], []).append(c)

    # Tally conversion metrics
    conversion_count = 0
    successful_conversion_count = 0
    total_damage = 0.0
    kill_count = 0

    for conv in opp_conversions:
        conversion_count += 1
        if conv["didKill"] and conv["lastHitBy"] == player_idx:
            kill_count += 1
        if len(conv["moves"]) > 1 and conv["moves"] and conv["moves"][0]["playerIndex"] == player_idx:
            successful_conversion_count += 1
        for move in conv["moves"]:
            if move["playerIndex"] == player_idx:
                total_damage += move["damage"]

    # Neutral / counter-hit / trade ratios:
    # player's share = player's openings of type X / (player's + opponent's openings of type X)
    def _opening_ratio(opening_type: str) -> dict:
        p_opens = player_attacks_by_opening.get(opening_type, [])
        o_opens = opp_attacks_by_opening.get(opening_type, [])
        return _get_ratio(len(p_opens), len(p_opens) + len(o_opens))

    def _beneficial_trade_ratio() -> dict:
        p_trades = player_attacks_by_opening.get("trade", [])
        o_trades = opp_attacks_by_opening.get("trade", [])
        # Pair trades by occurrence order (simultaneous per _populate_conversion_types)
        benefits = 0
        for p_conv, o_conv in zip(p_trades, o_trades):
            p_dmg = (p_conv["currentPercent"] or 0) - (p_conv["startPercent"] or 0)
            o_dmg = (o_conv["currentPercent"] or 0) - (o_conv["startPercent"] or 0)
            if p_conv["didKill"] and not o_conv["didKill"]:
                benefits += 1
            elif p_dmg > o_dmg:
                benefits += 1
        return _get_ratio(benefits, len(p_trades))

    return {
        "playerIndex": player_idx,
        "inputCounts": {
            "total": inputs["inputCount"],
            "buttons": inputs["buttonInputCount"],
            "joystick": inputs["joystickInputCount"],
            "cstick": inputs["cstickInputCount"],
            "triggers": inputs["triggerInputCount"],
        },
        "conversionCount": conversion_count,
        "totalDamage": total_damage,
        "killCount": kill_count,
        "successfulConversions": _get_ratio(successful_conversion_count, conversion_count),
        "inputsPerMinute": _get_ratio(inputs["inputCount"], game_minutes),
        "digitalInputsPerMinute": _get_ratio(inputs["buttonInputCount"], game_minutes),
        "openingsPerKill": _get_ratio(conversion_count, kill_count),
        "damagePerOpening": _get_ratio(total_damage, conversion_count),
        "neutralWinRatio": _opening_ratio("neutral-win"),
        "counterHitRatio": _opening_ratio("counter-attack"),
        "beneficialTradeRatio": _beneficial_trade_ratio(),
    }
