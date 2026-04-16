"""Generate an end-of-session HTML report from per-game KPIs."""

from __future__ import annotations

import webbrowser
from pathlib import Path

MIN_GAMES_FOR_SECTION = 5


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _safe(val, default=0.0):
    return val if val is not None else default


def _score_best_game(g: dict, maxes: dict) -> float:
    """Score a game for 'best performance' — high L-cancel, digital IPM, combo density."""
    def _norm(val, key):
        m = maxes.get(key, 0)
        return _safe(val) / m if m else 0.0

    return (
        0.30 * _norm(g.get("lcancel_rate"), "lcancel_rate")
        + 0.30 * _norm(g.get("digital_inputs_per_minute"), "digital_inputs_per_minute")
        + 0.25 * _norm(g.get("combo_density"), "combo_density")
        + 0.075 * _norm(g.get("neutral_win_ratio"), "neutral_win_ratio")
        + 0.075 * _norm(g.get("conversion_rate"), "conversion_rate")
    )


def _score_review_game(g: dict, maxes: dict) -> float:
    """Score a game for VOD review value — close game + neutral interactions + combo quality."""
    stock_diff = abs(_safe(g.get("stocks_lost"), 0) - _safe(g.get("stocks_taken"), 0))
    closeness = 1.0 / (1.0 + stock_diff * 2.5)

    # Use percent differential as a secondary closeness signal when stocks are equal
    if stock_diff == 0:
        pct_diff = abs(_safe(g.get("final_percent")) - _safe(g.get("opp_final_percent")))
        closeness *= 1.0 / (1.0 + pct_diff / 60.0)

    neutral_density = _safe(g.get("neutral_win_ratio")) * _safe(g.get("opening_count"))
    max_neutral = maxes.get("neutral_density", 1) or 1
    neutral_score = neutral_density / max_neutral

    combo_score = _safe(g.get("best_combo_damage")) / (maxes.get("best_combo_damage") or 1)

    return 0.50 * closeness + 0.30 * neutral_score + 0.20 * combo_score


def _compute_maxes(games: list[dict]) -> dict:
    def _max(key):
        vals = [_safe(g.get(key)) for g in games]
        return max(vals) if vals else 1.0

    maxes = {k: _max(k) for k in (
        "lcancel_rate", "digital_inputs_per_minute", "combo_density",
        "neutral_win_ratio", "conversion_rate", "best_combo_damage",
    )}
    # Composite: neutral_density = neutral_win_ratio * opening_count
    maxes["neutral_density"] = max(
        _safe(g.get("neutral_win_ratio")) * _safe(g.get("opening_count"))
        for g in games
    ) or 1.0
    return maxes


def _find_best_combo(games: list[dict]) -> dict | None:
    """Find the single best combo across a list of games."""
    candidates = [g for g in games if g.get("best_combo_damage") is not None]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda g: (
            _safe(g.get("best_combo_damage")),
            _safe(g.get("best_combo_hits")),
            -_safe(g.get("best_combo_duration_frames"), float("inf")),
        ),
    )


def _find_pointers(games: list[dict]) -> dict:
    """Return best_game, review_game, and best_combo dicts for a group of games."""
    maxes = _compute_maxes(games)
    scored_best = sorted(games, key=lambda g: _score_best_game(g, maxes), reverse=True)
    scored_review = sorted(games, key=lambda g: _score_review_game(g, maxes), reverse=True)

    best_game = scored_best[0] if scored_best else None
    review_game = scored_review[0] if scored_review else None

    # Avoid picking the same game for both if we have options
    if review_game and best_game and review_game["filename"] == best_game["filename"] and len(games) > 1:
        review_game = scored_review[1]

    combo_game = _find_best_combo(games)

    return {
        "best_game": best_game,
        "review_game": review_game,
        "combo_game": combo_game,
    }


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _aggregate(games: list[dict]) -> dict:
    """Compute session-level aggregates for a group of games."""
    total = len(games)
    wins = sum(1 for g in games if g.get("result") == "win")

    def _avg(key):
        vals = [g[key] for g in games if g.get(key) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    def _lcancel_pooled():
        s = sum(g.get("lcancel_success") or 0 for g in games)
        f = sum(g.get("lcancel_miss") or 0 for g in games)
        return round(s / (s + f), 3) if (s + f) > 0 else None

    return {
        "games": total,
        "wins": wins,
        "losses": total - wins,
        "win_rate": wins / total if total else None,
        "lcancel_rate": _lcancel_pooled(),
        "avg_digital_ipm": _avg("digital_inputs_per_minute"),
        "avg_conversion_rate": _avg("conversion_rate"),
        "avg_damage_per_opening": _avg("damage_per_opening"),
        "avg_neutral_win_ratio": _avg("neutral_win_ratio"),
        "avg_combo_density": _avg("combo_density"),
    }


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _pct(val) -> str:
    if val is None:
        return "—"
    return f"{val:.0%}"


def _fmt(val, decimals=1) -> str:
    if val is None:
        return "—"
    return f"{val:.{decimals}f}"


def _frames_to_timestamp(frames: int | None) -> str:
    if frames is None:
        return "—"
    total_sec = int(frames / 60)
    m, s = divmod(total_sec, 60)
    return f"{m}:{s:02d}"


def _game_label(g: dict) -> str:
    opp = g.get("opp_character") or "Unknown"
    stage = g.get("stage") or "Unknown"
    result = g.get("result", "?").upper()
    return f"{result} vs {opp} on {stage}"


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    background: #0f1117;
    color: #e2e8f0;
    font-family: 'Segoe UI', system-ui, sans-serif;
    font-size: 15px;
    line-height: 1.5;
    padding: 32px 24px 64px;
    max-width: 960px;
    margin: 0 auto;
}
header {
    border-bottom: 1px solid #2d3748;
    padding-bottom: 20px;
    margin-bottom: 32px;
}
header h1 {
    font-size: 1.8rem;
    font-weight: 700;
    color: #f7fafc;
    letter-spacing: -0.5px;
}
header .meta {
    color: #718096;
    margin-top: 4px;
    font-size: 0.9rem;
}
.char-section {
    margin-bottom: 48px;
}
.char-header {
    display: flex;
    align-items: baseline;
    gap: 12px;
    margin-bottom: 20px;
}
.char-header h2 {
    font-size: 1.3rem;
    font-weight: 700;
    color: #f7fafc;
}
.char-header .badge {
    background: #2d3748;
    color: #a0aec0;
    font-size: 0.75rem;
    padding: 2px 8px;
    border-radius: 12px;
}
.char-header .record {
    color: #718096;
    font-size: 0.9rem;
}
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: 12px;
    margin-bottom: 24px;
}
.kpi-card {
    background: #1a202c;
    border: 1px solid #2d3748;
    border-radius: 8px;
    padding: 14px 16px;
}
.kpi-card .label {
    color: #718096;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 4px;
}
.kpi-card .value {
    font-size: 1.4rem;
    font-weight: 700;
    color: #f7fafc;
}
.kpi-card .value.good { color: #68d391; }
.kpi-card .value.mid  { color: #f6e05e; }
.kpi-card .value.bad  { color: #fc8181; }
.pointers {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 14px;
}
.pointer-card {
    background: #1a202c;
    border: 1px solid #2d3748;
    border-radius: 8px;
    padding: 16px 18px;
}
.pointer-card .tag {
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: 600;
    margin-bottom: 8px;
}
.pointer-card.best-game .tag  { color: #68d391; }
.pointer-card.review-game .tag { color: #63b3ed; }
.pointer-card.best-combo .tag  { color: #f6ad55; }
.pointer-card .game-line {
    font-weight: 600;
    color: #e2e8f0;
    margin-bottom: 6px;
    font-size: 0.95rem;
}
.pointer-card .detail-line {
    color: #718096;
    font-size: 0.82rem;
    margin-top: 2px;
}
.pointer-card .filename {
    color: #4a5568;
    font-size: 0.75rem;
    margin-top: 8px;
    font-family: monospace;
    word-break: break-all;
}
.divider {
    border: none;
    border-top: 1px solid #2d3748;
    margin: 12px 0 24px;
}
.overall-label {
    color: #718096;
    text-transform: uppercase;
    font-size: 0.72rem;
    letter-spacing: 0.1em;
    font-weight: 600;
    margin-bottom: 8px;
}
"""


def _kpi_card(label: str, value: str, quality: str = "") -> str:
    cls = f"value {quality}".strip()
    return f"""
        <div class="kpi-card">
            <div class="label">{label}</div>
            <div class="{cls}">{value}</div>
        </div>"""


def _quality(val, lo, hi) -> str:
    """Return 'good', 'mid', or 'bad' color class based on thresholds."""
    if val is None:
        return ""
    if val >= hi:
        return "good"
    if val >= lo:
        return "mid"
    return "bad"


def _kpi_section(agg: dict) -> str:
    lc = agg.get("lcancel_rate")
    ipm = agg.get("avg_digital_ipm")
    cr = agg.get("avg_conversion_rate")
    dpo = agg.get("avg_damage_per_opening")
    nwr = agg.get("avg_neutral_win_ratio")

    cards = [
        _kpi_card("Win Rate", _pct(agg.get("win_rate")), _quality(agg.get("win_rate"), 0.45, 0.60)),
        _kpi_card("L-Cancel %", _pct(lc), _quality(lc, 0.70, 0.90)),
        _kpi_card("Digital IPM", _fmt(ipm), _quality(ipm, 100, 140)),
        _kpi_card("Conversion %", _fmt(cr) + ("%" if cr is not None else ""), _quality((cr or 0) / 100, 0.35, 0.50)),
        _kpi_card("Dmg / Opening", _fmt(dpo), _quality(dpo, 30, 45)),
        _kpi_card("Neutral Win %", _pct(nwr), _quality(nwr, 0.40, 0.55)),
    ]
    return f'<div class="kpi-grid">{"".join(cards)}</div>'


def _pointer_card(css_class: str, tag: str, game: dict | None, extra_lines: list[str]) -> str:
    if game is None:
        return f"""
        <div class="pointer-card {css_class}">
            <div class="tag">{tag}</div>
            <div class="game-line" style="color:#4a5568">No data</div>
        </div>"""

    lines = "".join(f'<div class="detail-line">{l}</div>' for l in extra_lines)
    filename = game.get("filename", "")
    return f"""
        <div class="pointer-card {css_class}">
            <div class="tag">{tag}</div>
            <div class="game-line">{_game_label(game)}</div>
            {lines}
            <div class="filename">{filename}</div>
        </div>"""


def _best_game_card(game: dict | None) -> str:
    if game is None:
        return _pointer_card("best-game", "Best Game", None, [])
    details = [
        f"L-cancel {_pct(game.get('lcancel_rate'))}  ·  Digital IPM {_fmt(game.get('digital_inputs_per_minute'))}",
        f"Conversion {_fmt(game.get('conversion_rate'))}%  ·  Neutral win {_pct(game.get('neutral_win_ratio'))}",
    ]
    return _pointer_card("best-game", "Best Game", game, details)


def _review_game_card(game: dict | None) -> str:
    if game is None:
        return _pointer_card("review-game", "Best Game to Review", None, [])
    stock_diff = abs(_safe(game.get("stocks_lost"), 0) - _safe(game.get("stocks_taken"), 0))
    closeness = "Close" if stock_diff <= 1 else f"{stock_diff}-stock diff"
    details = [
        f"{closeness}  ·  {game.get('opening_count') or 0} openings",
        f"Best combo: {_fmt(game.get('best_combo_damage'))}%  ·  Neutral win {_pct(game.get('neutral_win_ratio'))}",
    ]
    return _pointer_card("review-game", "Best Game to Review", game, details)


def _combo_card(game: dict | None) -> str:
    if game is None:
        return _pointer_card("best-combo", "Best Combo", None, [])
    dmg = _fmt(game.get("best_combo_damage"))
    hits = game.get("best_combo_hits") or "?"
    ts = _frames_to_timestamp(game.get("best_combo_start_frame"))
    details = [
        f"{dmg}% damage  ·  {hits} hits",
        f"Starts at {ts} in the game",
        f"vs {game.get('opp_character') or 'Unknown'} on {game.get('stage') or 'Unknown'}",
    ]
    return _pointer_card("best-combo", "Best Combo", game, details)


def _character_section(char: str, games: list[dict]) -> str:
    agg = _aggregate(games)
    pointers = _find_pointers(games)

    wins, losses = agg["wins"], agg["losses"]
    record = f"{wins}W – {losses}L"
    badge = f"{len(games)} games"

    pointer_html = "".join([
        _best_game_card(pointers["best_game"]),
        _review_game_card(pointers["review_game"]),
        _combo_card(pointers["combo_game"]),
    ])

    return f"""
    <div class="char-section">
        <div class="char-header">
            <h2>{char}</h2>
            <span class="badge">{badge}</span>
            <span class="record">{record}</span>
        </div>
        {_kpi_section(agg)}
        <div class="pointers">{pointer_html}</div>
    </div>"""


def generate_report(game_kpis: list[dict], output_dir: Path, date_str: str | None = None) -> Path:
    """Generate an HTML session report and write it to output_dir.

    Args:
        game_kpis: List of completed per-game KPI dicts.
        output_dir: Directory to write the report into.
        date_str: Session date string for the header (YYYY-MM-DD). Defaults to today.

    Returns:
        Path to the written HTML file.
    """
    from datetime import date as _date

    if not date_str:
        date_str = _date.today().isoformat()

    total_games = len(game_kpis)

    # Group by character, sort by most games played
    from collections import defaultdict
    by_char: dict[str, list[dict]] = defaultdict(list)
    for g in game_kpis:
        char = g.get("character") or "Unknown"
        by_char[char].append(g)

    chars_ordered = sorted(by_char.keys(), key=lambda c: len(by_char[c]), reverse=True)

    # Character sections (min 5 games)
    char_sections = []
    small_char_games = []
    for char in chars_ordered:
        games = by_char[char]
        if len(games) >= MIN_GAMES_FOR_SECTION:
            char_sections.append(_character_section(char, games))
        else:
            small_char_games.extend(games)

    # Overall section (always shown)
    overall_section = _character_section("Overall", game_kpis)

    # Build body
    sections_html = overall_section
    if char_sections:
        sections_html += '<hr class="divider">' + "".join(char_sections)

    # Note characters with too few games
    small_note = ""
    if small_char_games:
        small_chars = sorted(
            {g.get("character") or "Unknown" for g in small_char_games},
            key=lambda c: -len([g for g in small_char_games if g.get("character") == c]),
        )
        small_note = (
            f'<p style="color:#4a5568;font-size:0.8rem;margin-top:8px">'
            f'Not enough games for a section: {", ".join(small_chars)} '
            f'(need {MIN_GAMES_FOR_SECTION}+)</p>'
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Session Report — {date_str}</title>
<style>{_CSS}</style>
</head>
<body>
<header>
    <h1>Session Report</h1>
    <div class="meta">{date_str} &nbsp;·&nbsp; {total_games} completed game{"s" if total_games != 1 else ""}</div>
    {small_note}
</header>
{sections_html}
</body>
</html>"""

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"session_{date_str}.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path
