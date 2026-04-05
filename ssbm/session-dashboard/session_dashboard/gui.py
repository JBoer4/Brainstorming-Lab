"""Tkinter GUI for session-dashboard."""

import threading
import tkinter as tk
from tkinter import filedialog, ttk
from datetime import date
from pathlib import Path

from session_dashboard.parse import load_session, identify_player, get_player_port
from session_dashboard.kpis import compute_game_kpis, aggregate_by_character, filter_completed_games
from session_dashboard.export import append_to_history, get_processed_filenames
from session_dashboard.slippi_api import RankCache


def _display_code(code: str) -> str:
    return code.replace("\uFF03", "#") if code else code


class SessionDashboardApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Session Dashboard")
        root.resizable(False, False)

        self._cancel_event = threading.Event()

        # --- Input frame ---
        form = ttk.LabelFrame(root, text="Session Settings", padding=12)
        form.pack(padx=16, pady=(16, 8), fill="x")

        # Replay directory
        ttk.Label(form, text="Replay Folder:").grid(
            row=0, column=0, sticky="w", pady=4
        )
        dir_frame = ttk.Frame(form)
        dir_frame.grid(row=0, column=1, sticky="ew", pady=4)
        self.replay_dir = tk.StringVar()
        ttk.Entry(dir_frame, textvariable=self.replay_dir, width=44).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(dir_frame, text="Browse...", command=self._browse_dir).pack(
            side="left", padx=(6, 0)
        )
        ttk.Label(form, text="Point at root folder — YYYY-MM subfolders auto-detected", foreground="gray").grid(
            row=0, column=2, sticky="w", padx=(8, 0)
        )

        # Date range
        ttk.Label(form, text="From:").grid(row=1, column=0, sticky="w", pady=4)
        date_frame = ttk.Frame(form)
        date_frame.grid(row=1, column=1, sticky="w", pady=4)
        self.date_from = tk.StringVar(value=date.today().isoformat())
        ttk.Entry(date_frame, textvariable=self.date_from, width=14).pack(side="left")
        ttk.Label(date_frame, text="  To:").pack(side="left")
        self.date_to = tk.StringVar(value=date.today().isoformat())
        ttk.Entry(date_frame, textvariable=self.date_to, width=14).pack(side="left", padx=(4, 0))
        ttk.Label(date_frame, text="  (leave blank for all dates)", foreground="gray").pack(side="left")

        # Connect code(s)
        ttk.Label(form, text="Connect Code(s):").grid(
            row=2, column=0, sticky="w", pady=4
        )
        code_frame = ttk.Frame(form)
        code_frame.grid(row=2, column=1, sticky="w", pady=4)
        self.connect_code = tk.StringVar()
        ttk.Entry(code_frame, textvariable=self.connect_code, width=28).pack(side="left")
        ttk.Label(code_frame, text="  (comma-separate alts: JOJO#821, ALT#420)", foreground="gray").pack(side="left")

        # Output directory
        ttk.Label(form, text="Output Folder:").grid(
            row=3, column=0, sticky="w", pady=4
        )
        out_frame = ttk.Frame(form)
        out_frame.grid(row=3, column=1, sticky="ew", pady=4)
        self.output_dir = tk.StringVar(value=str(Path("./output").resolve()))
        ttk.Entry(out_frame, textvariable=self.output_dir, width=44).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(out_frame, text="Browse...", command=self._browse_output).pack(
            side="left", padx=(6, 0)
        )

        # Options
        self.no_ranks = tk.BooleanVar()
        ttk.Checkbutton(form, text="Skip rank lookups (faster)", variable=self.no_ranks).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )
        self.force_recalc = tk.BooleanVar()
        ttk.Checkbutton(
            form,
            text="Force recalculate (reprocess games already in history)",
            variable=self.force_recalc,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(0, 4))

        form.columnconfigure(1, weight=1)

        # --- Run / Stop buttons ---
        btn_frame = ttk.Frame(root)
        btn_frame.pack(pady=8)
        self.run_btn = ttk.Button(btn_frame, text="Run", command=self._run)
        self.run_btn.pack(side="left", padx=4)
        self.stop_btn = ttk.Button(btn_frame, text="Stop", command=self._cancel, state="disabled")
        self.stop_btn.pack(side="left", padx=4)

        # --- Log output ---
        log_frame = ttk.LabelFrame(root, text="Output", padding=8)
        log_frame.pack(padx=16, pady=(0, 16), fill="both", expand=True)

        self.log = tk.Text(log_frame, height=20, width=80, state="disabled", wrap="word")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Ctrl+C cancels a running pipeline
        root.bind("<Control-c>", lambda e: self._cancel())

    def _browse_dir(self):
        path = filedialog.askdirectory(title="Select Replay Folder")
        if path:
            self.replay_dir.set(path)

    def _browse_output(self):
        path = filedialog.askdirectory(title="Select Output Folder")
        if path:
            self.output_dir.set(path)

    def _log(self, msg: str):
        """Thread-safe log append."""
        def _append():
            self.log.configure(state="normal")
            self.log.insert("end", msg + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.root.after(0, _append)

    def _set_running(self, running: bool):
        def _update():
            self.run_btn.configure(state="disabled" if running else "normal")
            self.stop_btn.configure(state="normal" if running else "disabled")
        self.root.after(0, _update)

    def _cancel(self):
        self._cancel_event.set()

    def _run(self):
        replay_dir = self.replay_dir.get().strip()
        if not replay_dir:
            self._log("Error: Please select a replay folder.")
            return
        replay_path = Path(replay_dir)
        if not replay_path.is_dir():
            self._log(f"Error: Folder not found: {replay_dir}")
            return

        date_from = self.date_from.get().strip() or None
        date_to = self.date_to.get().strip() or None
        connect_code = self.connect_code.get().strip() or None
        output_path = Path(self.output_dir.get().strip())
        no_ranks = self.no_ranks.get()
        force_recalc = self.force_recalc.get()

        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

        self._cancel_event.clear()
        self._set_running(True)
        threading.Thread(
            target=self._run_pipeline,
            args=(replay_path, date_from, date_to, connect_code, output_path, no_ranks, force_recalc),
            daemon=True,
        ).start()

    def _run_pipeline(self, replay_dir, date_from, date_to, connect_code, output_dir, no_ranks, force_recalc):
        try:
            range_desc = (
                f"{date_from} to {date_to}" if date_from and date_to and date_from != date_to
                else date_from or "all dates"
            )
            self._log(f"Loading replays from {replay_dir} ({range_desc})...")

            skip_filenames = None
            if not force_recalc:
                skip_filenames = get_processed_filenames(output_dir)
                if skip_filenames:
                    self._log(f"  {len(skip_filenames)} games already in history — will skip.")

            _last_progress = [0]
            def _parse_progress(current, total):
                pct = int(current / total * 100)
                milestone = pct // 25
                if milestone > _last_progress[0]:
                    _last_progress[0] = milestone
                    self._log(f"  Parsing files... {current}/{total}")

            games = load_session(
                replay_dir, date_from=date_from, date_to=date_to,
                on_progress=_parse_progress,
                skip_filenames=skip_filenames,
            )

            if not games:
                self._log(f"No replays found for {range_desc}.")
                return

            self._log(f"Found {len(games)} games.")

            if self._cancel_event.is_set():
                self._log("Cancelled.")
                return

            connect_codes = (
                [c.strip() for c in connect_code.split(",")]
                if connect_code else None
            )
            player_codes = identify_player(games, connect_codes=connect_codes)
            self._log(f"Identified player: {', '.join(_display_code(c) for c in player_codes)}")

            game_kpis = []
            total = len(games)
            for i, game in enumerate(games):
                if self._cancel_event.is_set():
                    self._log(f"Cancelled after {len(game_kpis)} games.")
                    break
                if total > 20 and i > 0 and i % 10 == 0:
                    self._log(f"  Computing KPIs... ({i}/{total})")
                try:
                    player_port, matched_code = get_player_port(game, player_codes)
                    kpis = compute_game_kpis(game, player_port)
                    kpis["session_date"] = game["metadata"]["file_date"]
                    kpis["game_timestamp"] = game["metadata"]["game_timestamp"]
                    kpis["player_code"] = _display_code(matched_code)
                    game_kpis.append(kpis)
                except Exception as e:
                    self._log(f"Warning: skipping {game['metadata']['filename']}: {e}")

            if not game_kpis:
                self._log("No games could be analyzed.")
                return

            game_kpis, filtered_count = filter_completed_games(game_kpis)
            if filtered_count:
                self._log(
                    f"Filtered out {filtered_count} incomplete games "
                    f"(<600 frames or <3 stocks lost by either player)."
                )

            if not game_kpis:
                self._log("No completed games to analyze.")
                return

            self._log(f"Analyzing {len(game_kpis)} completed games.")

            if not no_ranks and not self._cancel_event.is_set():
                self._log("Looking up ranks...")
                rank_cache = RankCache()
                upper_player_codes = {c.upper() for c in player_codes}

                rank_cache.prefetch(set(player_codes))
                player_ranks = {c: rank_cache.get(c) for c in player_codes}
                for c, rank in player_ranks.items():
                    if rank and rank.get("rating") is not None:
                        self._log(f"Your rank ({_display_code(c)}): {rank['tier']} ({rank['rating']:.0f})")
                    else:
                        self._log(f"Your rank ({_display_code(c)}): {rank['tier'] if rank else 'Unknown'}")

                opp_codes = set()
                for game in games:
                    for player in game["metadata"]["players"]:
                        if player["connect_code"] and player["connect_code"].upper() not in upper_player_codes:
                            opp_codes.add(player["connect_code"])

                rank_cache.prefetch(opp_codes)
                self._log(f"Looked up ranks for {rank_cache.api_calls_made} players.")

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
                _p = lambda k, s=s: s.get(k) if s.get(k) is not None else "N/A"
                self._log(f"\n--- {char} ---")
                self._log(
                    f"  Games: {s['games_played']}  W/L: {s['wins']}-{s['losses']}  "
                    f"Win rate: {s['win_rate']:.0%}"
                )
                self._log(
                    f"  Avg stocks taken: {s['avg_stocks_taken']:.1f}  "
                    f"lost: {s['avg_stocks_lost']:.1f}"
                )
                self._log(
                    f"  Damage/game: {_p('avg_total_damage')}  "
                    f"Conversion rate: {_p('avg_conversion_rate')}%  "
                    f"Openings/kill: {_p('avg_openings_per_kill')}  "
                    f"Dmg/opening: {_p('avg_damage_per_opening')}"
                )
                self._log(
                    f"  Neutral wins: {_p('avg_neutral_wins')}  "
                    f"Counter hits: {_p('avg_counter_hits')}  "
                    f"Trades: {_p('avg_trades')}"
                )
                self._log(
                    f"  Spot dodges: {_p('avg_spot_dodges')}  "
                    f"Air dodges: {_p('avg_air_dodges')}  "
                    f"Rolls: {_p('avg_rolls')}"
                )
                self._log(
                    f"  Wavedashes: {_p('avg_wavedashes')}  "
                    f"Wavelands: {_p('avg_wavelands')}  "
                    f"Dash dances: {_p('avg_dash_dances')}  "
                    f"Ledge grabs: {_p('avg_ledge_grabs')}"
                )
                self._log(
                    f"  L-cancel: {lc_str}  "
                    f"IPM: {_p('avg_inputs_per_minute')}  "
                    f"Digital IPM: {_p('avg_digital_inputs_per_minute')}"
                )

            history_path = append_to_history(game_kpis, output_dir)
            self._log(f"\nExported to {history_path}")
            self._log("\nDone!")

        except Exception as e:
            self._log(f"\nError: {e}")
        finally:
            self._set_running(False)


def main():
    root = tk.Tk()
    SessionDashboardApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
