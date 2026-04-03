"""Tkinter GUI for session-dashboard."""

import threading
import tkinter as tk
from tkinter import filedialog, ttk
from datetime import date
from pathlib import Path

from session_dashboard.parse import load_session, identify_player, get_player_port
from session_dashboard.kpis import compute_game_kpis, aggregate_by_character, filter_completed_games
from session_dashboard.export import export_session, append_to_history
from session_dashboard.slippi_api import RankCache


def _display_code(code: str) -> str:
    return code.replace("\uFF03", "#") if code else code


class SessionDashboardApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Session Dashboard")
        root.resizable(False, False)

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

        # Date
        ttk.Label(form, text="Date:").grid(row=1, column=0, sticky="w", pady=4)
        self.session_date = tk.StringVar(value=date.today().isoformat())
        ttk.Entry(form, textvariable=self.session_date, width=14).grid(
            row=1, column=1, sticky="w", pady=4
        )

        # Connect code
        ttk.Label(form, text="Connect Code:").grid(
            row=2, column=0, sticky="w", pady=4
        )
        self.connect_code = tk.StringVar()
        ttk.Entry(form, textvariable=self.connect_code, width=14).grid(
            row=2, column=1, sticky="w", pady=4
        )

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

        # Skip ranks checkbox
        self.no_ranks = tk.BooleanVar()
        ttk.Checkbutton(form, text="Skip rank lookups (faster)", variable=self.no_ranks).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=4
        )

        form.columnconfigure(1, weight=1)

        # --- Run button ---
        self.run_btn = ttk.Button(root, text="Run", command=self._run)
        self.run_btn.pack(pady=8)

        # --- Log output ---
        log_frame = ttk.LabelFrame(root, text="Output", padding=8)
        log_frame.pack(padx=16, pady=(0, 16), fill="both", expand=True)

        self.log = tk.Text(log_frame, height=20, width=80, state="disabled", wrap="word")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

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
        self.root.after(0, _update)

    def _run(self):
        # Validate inputs
        replay_dir = self.replay_dir.get().strip()
        if not replay_dir:
            self._log("Error: Please select a replay folder.")
            return
        replay_path = Path(replay_dir)
        if not replay_path.is_dir():
            self._log(f"Error: Folder not found: {replay_dir}")
            return

        session_date = self.session_date.get().strip()
        connect_code = self.connect_code.get().strip() or None
        output_path = Path(self.output_dir.get().strip())
        no_ranks = self.no_ranks.get()

        # Clear log
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

        self._set_running(True)
        threading.Thread(
            target=self._run_pipeline,
            args=(replay_path, session_date, connect_code, output_path, no_ranks),
            daemon=True,
        ).start()

    def _run_pipeline(self, replay_dir, session_date, connect_code, output_dir, no_ranks):
        try:
            self._log(f"Loading replays from {replay_dir} for {session_date}...")
            games = load_session(replay_dir, date_filter=session_date)

            if not games:
                self._log(f"No replays found for {session_date}.")
                return

            self._log(f"Found {len(games)} games.")

            player_code = identify_player(games, connect_code=connect_code)
            self._log(f"Identified player: {_display_code(player_code)}")

            game_kpis = []
            for game in games:
                try:
                    player_port = get_player_port(game, player_code)
                    kpis = compute_game_kpis(game, player_port)
                    kpis["session_date"] = session_date
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

            if not no_ranks:
                rank_cache = RankCache()
                player_rank = rank_cache.get(player_code)
                player_rating = player_rank["rating"] if player_rank else None
                player_tier = player_rank["tier"] if player_rank else None

                opp_codes = set()
                for game in games:
                    for player in game["metadata"]["players"]:
                        if player["connect_code"] and player["connect_code"] != player_code:
                            opp_codes.add(player["connect_code"])

                rank_cache.prefetch(opp_codes)
                self._log(f"Looked up ranks for {rank_cache.api_calls_made} players.")

                if player_rating is not None:
                    self._log(f"Your rank: {player_tier} ({player_rating:.0f})")
                else:
                    self._log(f"Your rank: {player_tier}")

                for kpis in game_kpis:
                    kpis["player_rating"] = player_rating
                    kpis["player_tier"] = player_tier
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

            created = export_session(game_kpis, aggregates, output_dir, session_date)
            history_path = append_to_history(game_kpis, output_dir)
            created.append(history_path)

            self._log(f"\nExported {len(created)} files to {output_dir}/")
            for p in created:
                self._log(f"  {p.name}")

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
