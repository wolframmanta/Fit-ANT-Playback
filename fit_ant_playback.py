#!/usr/bin/env python3
"""
FIT File ANT+ Playback Tool
Broadcasts power and cadence data from a FIT file via ANT+ USB dongle.
Can be read by Zwift or other ANT+ compatible applications.
"""

import logging
import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import time
from pathlib import Path

from fit_ant_playback_core.ant_usb import AntUsbBroadcaster
from fit_ant_playback_core.fit_parser import FitFileParser, fitdecode_available
from fit_ant_playback_core.models import PowerCadenceRecord
from fit_ant_playback_core.playback_engine import FitPlaybackEngine, ManualBroadcastEngine


class TkLogHandler(logging.Handler):
    """Routes package logging into the Tk log widget on the main thread."""

    def __init__(self, root: tk.Tk, write_log):
        super().__init__()
        self.root = root
        self.write_log = write_log

    def emit(self, record: logging.LogRecord) -> None:
        message = self.format(record)
        try:
            self.root.after(0, self.write_log, message)
        except tk.TclError:
            pass


class FitAntPlaybackApp:
    """Main application GUI with dark theme"""

    # Color palette
    BG_DARK = "#1e1e2e"
    BG_MEDIUM = "#2a2a3d"
    BG_LIGHT = "#363650"
    BG_INPUT = "#44446a"
    FG_PRIMARY = "#e0e0f0"
    FG_SECONDARY = "#a0a0c0"
    FG_DIM = "#707090"
    ACCENT = "#6c8cff"
    ACCENT_HOVER = "#8aa4ff"
    SUCCESS = "#50c878"
    WARNING = "#ffb347"
    ERROR = "#ff6b6b"

    # Power zone colors
    ZONE_COLORS = [
        (0, "#a0a0c0"),       # 0 W — gray
        (100, "#50c878"),     # green
        (200, "#8cd96c"),     # light green
        (300, "#ffdd57"),     # yellow
        (400, "#ffb347"),     # orange
        (600, "#ff6b6b"),     # red
        (1000, "#ff3860"),    # deep red
    ]

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("FIT ANT+ Playback")
        self.root.geometry("1050x750")
        self.root.resizable(True, True)
        self.root.configure(bg=self.BG_DARK)
        self.root.minsize(900, 650)

        self.fit_records: list[PowerCadenceRecord] = []
        self.broadcaster: AntUsbBroadcaster | None = None
        self.playback_engine: FitPlaybackEngine | None = None
        self.is_playing = False
        self.is_paused = False
        self.current_index = 0
        self.playback_speed = 1.0

        # Manual mode state
        self.manual_engine: ManualBroadcastEngine | None = None
        self.manual_broadcasting = False
        self._manual_lock = threading.Lock()
        self._manual_power = 300
        self._manual_cadence = 85

        # FIT file info vars (set in _build_fit_tab)
        self.records_var: tk.StringVar = tk.StringVar(value="0")
        self.duration_var: tk.StringVar = tk.StringVar(value="00:00:00")
        self.avg_power_var: tk.StringVar = tk.StringVar(value="0 W")
        self.avg_cadence_var: tk.StringVar = tk.StringVar(value="0 RPM")

        self._setup_styles()
        self._setup_ui()
        self._configure_logging()
        self._log("FIT ANT+ Playback ready")
        self._log("Select a FIT file or switch to Manual Power mode")
        if not fitdecode_available():
            self._log("WARNING: fitdecode is not installed; FIT file loading is disabled")

    # ------------------------------------------------------------------
    # Styling
    # ------------------------------------------------------------------
    def _setup_styles(self):
        """Configure dark-theme ttk styles"""
        self.style = ttk.Style()
        self.style.theme_use("clam")

        # Frames
        self.style.configure("Dark.TFrame", background=self.BG_DARK)
        self.style.configure("Card.TFrame", background=self.BG_MEDIUM)

        # Labels
        self.style.configure("Dark.TLabel", background=self.BG_DARK,
                             foreground=self.FG_PRIMARY, font=("Helvetica", 11))
        self.style.configure("Card.TLabel", background=self.BG_MEDIUM,
                             foreground=self.FG_PRIMARY, font=("Helvetica", 11))
        self.style.configure("Dim.TLabel", background=self.BG_MEDIUM,
                             foreground=self.FG_SECONDARY, font=("Helvetica", 10))
        self.style.configure("Heading.TLabel", background=self.BG_DARK,
                             foreground=self.FG_PRIMARY, font=("Helvetica", 13, "bold"))
        self.style.configure("BigValue.TLabel", background=self.BG_MEDIUM,
                             foreground=self.ACCENT, font=("Helvetica Neue", 32, "bold"))
        self.style.configure("ValueUnit.TLabel", background=self.BG_MEDIUM,
                             foreground=self.FG_DIM, font=("Helvetica", 11))
        self.style.configure("Status.TLabel", background=self.BG_MEDIUM,
                             foreground=self.WARNING, font=("Helvetica", 11, "bold"))

        # LabelFrames
        self.style.configure("Dark.TLabelframe", background=self.BG_MEDIUM,
                             foreground=self.FG_SECONDARY, borderwidth=1,
                             relief="flat")
        self.style.configure("Dark.TLabelframe.Label", background=self.BG_MEDIUM,
                             foreground=self.ACCENT, font=("Helvetica", 11, "bold"))

        # Buttons
        self.style.configure("Accent.TButton", font=("Helvetica", 11, "bold"),
                             padding=(14, 8))
        self.style.map("Accent.TButton",
                       background=[("active", self.ACCENT_HOVER),
                                   ("!active", self.ACCENT)],
                       foreground=[("active", "#ffffff"), ("!active", "#ffffff")])

        self.style.configure("Secondary.TButton", font=("Helvetica", 10),
                             padding=(10, 6))
        self.style.map("Secondary.TButton",
                       background=[("active", self.BG_LIGHT),
                                   ("!active", self.BG_INPUT)],
                       foreground=[("active", self.FG_PRIMARY),
                                   ("!active", self.FG_PRIMARY)])

        self.style.configure("Success.TButton", font=("Helvetica", 11, "bold"),
                             padding=(14, 8))
        self.style.map("Success.TButton",
                       background=[("active", "#3da863"), ("!active", self.SUCCESS)],
                       foreground=[("active", "#ffffff"), ("!active", "#ffffff")])

        self.style.configure("Danger.TButton", font=("Helvetica", 11, "bold"),
                             padding=(14, 8))
        self.style.map("Danger.TButton",
                       background=[("active", "#e05555"), ("!active", self.ERROR)],
                       foreground=[("active", "#ffffff"), ("!active", "#ffffff")])

        # Entry
        self.style.configure("Dark.TEntry", fieldbackground=self.BG_INPUT,
                             foreground=self.FG_PRIMARY, insertcolor=self.FG_PRIMARY,
                             borderwidth=1)

        # Combobox
        self.style.configure("Dark.TCombobox", fieldbackground=self.BG_INPUT,
                             foreground=self.FG_PRIMARY, selectbackground=self.ACCENT,
                             selectforeground="#ffffff")
        self.style.map("Dark.TCombobox",
                       fieldbackground=[("readonly", self.BG_INPUT)],
                       foreground=[("readonly", self.FG_PRIMARY)])

        # Progressbar
        self.style.configure("Accent.Horizontal.TProgressbar",
                             troughcolor=self.BG_INPUT,
                             background=self.ACCENT, thickness=12)

        # Notebook (tabs)
        self.style.configure("Dark.TNotebook", background=self.BG_DARK,
                             borderwidth=0)
        self.style.configure("Dark.TNotebook.Tab",
                             background=self.BG_LIGHT,
                             foreground=self.FG_SECONDARY,
                             font=("Helvetica", 11, "bold"),
                             padding=(18, 8))
        self.style.map("Dark.TNotebook.Tab",
                       background=[("selected", self.ACCENT)],
                       foreground=[("selected", "#ffffff")])

        # Scale (slider)
        self.style.configure("Accent.Horizontal.TScale",
                             troughcolor=self.BG_INPUT,
                             background=self.ACCENT,
                             sliderthickness=20)

        # Scrollbar
        self.style.configure("Dark.Vertical.TScrollbar",
                             troughcolor=self.BG_DARK,
                             background=self.BG_LIGHT)

    # ------------------------------------------------------------------
    # UI Layout
    # ------------------------------------------------------------------
    def _setup_ui(self):
        """Setup the user interface"""
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        outer = ttk.Frame(self.root, style="Dark.TFrame", padding=12)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        # rows: 0=title, 1=ant, 2=tabs, 3=current vals, 4=log
        outer.rowconfigure(2, weight=0)
        outer.rowconfigure(4, weight=1)

        # ---- Title bar ----
        title_lbl = ttk.Label(outer, text="FIT ANT+ Playback",
                              style="Heading.TLabel",
                              font=("Helvetica Neue", 18, "bold"))
        title_lbl.grid(row=0, column=0, sticky="w", pady=(0, 8))

        # ---- ANT+ connection row ----
        ant_frame = ttk.Frame(outer, style="Card.TFrame", padding=10)
        ant_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ant_frame.columnconfigure(1, weight=1)

        ttk.Label(ant_frame, text="ANT+ Status:", style="Card.TLabel"
                  ).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.ant_status_var = tk.StringVar(value="Not Connected")
        self.ant_status_label = ttk.Label(ant_frame, textvariable=self.ant_status_var,
                                          style="Status.TLabel")
        self.ant_status_label.grid(row=0, column=1, sticky="w")

        self.connect_btn = ttk.Button(ant_frame, text="Connect ANT+",
                                      command=self._connect_ant, style="Accent.TButton")
        self.connect_btn.grid(row=0, column=2, padx=(8, 0))

        # ---- Notebook (tabs) ----
        self.notebook = ttk.Notebook(outer, style="Dark.TNotebook")
        self.notebook.grid(row=2, column=0, sticky="ew", pady=(0, 8))

        self._build_fit_tab()
        self._build_manual_tab()

        # ---- Current values ----
        self._build_current_values(outer, row=3)

        # ---- Log ----
        self._build_log(outer, row=4)

    # ---------- FIT Playback tab ----------
    def _build_fit_tab(self):
        tab = ttk.Frame(self.notebook, style="Dark.TFrame", padding=10)
        self.notebook.add(tab, text="  FIT File Playback  ")
        tab.columnconfigure(0, weight=1)

        # File selection
        file_frame = ttk.LabelFrame(tab, text="FIT File", style="Dark.TLabelframe",
                                    padding=8)
        file_frame.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        file_frame.columnconfigure(1, weight=1)

        ttk.Label(file_frame, text="File:", style="Card.TLabel"
                  ).grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.file_path_var = tk.StringVar()
        self.file_entry = ttk.Entry(file_frame, textvariable=self.file_path_var,
                                    state="readonly", style="Dark.TEntry")
        self.file_entry.grid(row=0, column=1, sticky="ew", padx=(0, 6))
        self.browse_btn = ttk.Button(file_frame, text="Browse...",
                                     command=self._browse_file, style="Secondary.TButton")
        self.browse_btn.grid(row=0, column=2)

        # File info
        info_frame = ttk.LabelFrame(tab, text="File Info", style="Dark.TLabelframe",
                                    padding=8)
        info_frame.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        for c in (1, 3):
            info_frame.columnconfigure(c, weight=1)

        for r, (lbl, sv) in enumerate([
            ("Records:", self.records_var),
            ("Duration:", self.duration_var),
        ]):
            ttk.Label(info_frame, text=lbl, style="Dim.TLabel"
                      ).grid(row=r, column=0, sticky="w", padx=(0, 4))
            ttk.Label(info_frame, textvariable=sv, style="Card.TLabel"
                      ).grid(row=r, column=1, sticky="w")

        for r, (lbl, sv) in enumerate([
            ("Avg Power:", self.avg_power_var),
            ("Avg Cadence:", self.avg_cadence_var),
        ]):
            ttk.Label(info_frame, text=lbl, style="Dim.TLabel"
                      ).grid(row=r, column=2, sticky="w", padx=(16, 4))
            ttk.Label(info_frame, textvariable=sv, style="Card.TLabel"
                      ).grid(row=r, column=3, sticky="w")

        # Playback controls
        play_frame = ttk.LabelFrame(tab, text="Playback", style="Dark.TLabelframe",
                                    padding=8)
        play_frame.grid(row=2, column=0, sticky="ew", pady=(0, 2))
        play_frame.columnconfigure(1, weight=1)

        # Progress
        ttk.Label(play_frame, text="Progress:", style="Dim.TLabel"
                  ).grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(play_frame, variable=self.progress_var,
                                            maximum=100,
                                            style="Accent.Horizontal.TProgressbar")
        self.progress_bar.grid(row=0, column=1, columnspan=3, sticky="ew", pady=4)

        self.time_var = tk.StringVar(value="00:00:00 / 00:00:00")
        ttk.Label(play_frame, textvariable=self.time_var, style="Dim.TLabel"
                  ).grid(row=1, column=1, sticky="w")

        # Speed
        ttk.Label(play_frame, text="Speed:", style="Dim.TLabel"
                  ).grid(row=2, column=0, sticky="w", padx=(0, 6))
        self.speed_var = tk.StringVar(value="1.0x")
        speed_combo = ttk.Combobox(play_frame, textvariable=self.speed_var,
                                   values=["0.5x", "1.0x", "1.5x", "2.0x", "4.0x"],
                                   width=8, style="Dark.TCombobox", state="readonly")
        speed_combo.grid(row=2, column=1, sticky="w")
        speed_combo.bind("<<ComboboxSelected>>", self._on_speed_change)

        # Buttons
        btn_frame = ttk.Frame(play_frame, style="Dark.TLabelframe")
        btn_frame.grid(row=3, column=0, columnspan=4, pady=(8, 0))

        self.play_btn = ttk.Button(btn_frame, text="Play",
                                   command=self._play, style="Success.TButton", width=10)
        self.play_btn.grid(row=0, column=0, padx=4)

        self.pause_btn = ttk.Button(btn_frame, text="Pause",
                                    command=self._pause, style="Secondary.TButton",
                                    width=10, state="disabled")
        self.pause_btn.grid(row=0, column=1, padx=4)

        self.stop_btn = ttk.Button(btn_frame, text="Stop",
                                   command=self._stop, style="Danger.TButton",
                                   width=10, state="disabled")
        self.stop_btn.grid(row=0, column=2, padx=4)

    # ---------- Manual Power tab ----------
    def _build_manual_tab(self):
        tab = ttk.Frame(self.notebook, style="Dark.TFrame", padding=10)
        self.notebook.add(tab, text="  Manual Power  ")
        tab.columnconfigure(0, weight=1)

        # Power control
        pwr_frame = ttk.LabelFrame(tab, text="Power (Watts)",
                                   style="Dark.TLabelframe", padding=10)
        pwr_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        pwr_frame.columnconfigure(1, weight=1)

        self.manual_power_var = tk.IntVar(value=300)

        ttk.Label(pwr_frame, text="Watts:", style="Card.TLabel"
                  ).grid(row=0, column=0, sticky="w", padx=(0, 8))

        self.power_slider = ttk.Scale(pwr_frame, from_=0, to=2000,
                                      orient="horizontal",
                                      variable=self.manual_power_var,
                                      command=self._on_power_slider_change,
                                      style="Accent.Horizontal.TScale")
        self.power_slider.grid(row=0, column=1, sticky="ew", padx=(0, 8))

        # Validation: register a callback that allows only integers 0-2000
        vcmd_power = (self.root.register(self._validate_power_entry), "%P")
        self.power_entry = ttk.Entry(pwr_frame, width=6, justify="center",
                                     style="Dark.TEntry", font=("Helvetica", 14, "bold"),
                                     validate="key", validatecommand=vcmd_power)
        self.power_entry.grid(row=0, column=2, padx=(0, 4))
        self.power_entry.insert(0, "300")
        self.power_entry.bind("<Return>", self._on_power_entry_change)
        self.power_entry.bind("<FocusOut>", self._on_power_entry_change)

        ttk.Label(pwr_frame, text="W", style="Dim.TLabel"
                  ).grid(row=0, column=3, sticky="w")

        # Quick-set buttons
        qf = ttk.Frame(pwr_frame, style="Dark.TLabelframe")
        qf.grid(row=1, column=0, columnspan=4, pady=(8, 0))
        for watts in (0, 150, 200, 250, 283, 300, 350, 400, 500, 600, 800, 1000, 1200):
            b = ttk.Button(qf, text=f"{watts}",
                           command=lambda w=watts: self._set_manual_power(w),
                           style="Secondary.TButton", width=5)
            b.pack(side="left", padx=2)

        # W/kg control
        wkg_frame = ttk.LabelFrame(tab, text="W/kg",
                                   style="Dark.TLabelframe", padding=10)
        wkg_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        ttk.Label(wkg_frame, text="Weight (kg):", style="Card.TLabel"
                  ).grid(row=0, column=0, sticky="w", padx=(0, 8))

        vcmd_weight = (self.root.register(self._validate_weight_entry), "%P")
        self.weight_entry = ttk.Entry(wkg_frame, width=6, justify="center",
                                      style="Dark.TEntry", font=("Helvetica", 14, "bold"),
                                      validate="key", validatecommand=vcmd_weight)
        self.weight_entry.grid(row=0, column=1, padx=(0, 4))
        self.weight_entry.insert(0, "75")
        ttk.Label(wkg_frame, text="kg", style="Dim.TLabel"
                  ).grid(row=0, column=2, sticky="w", padx=(0, 20))

        ttk.Label(wkg_frame, text="W/kg:", style="Card.TLabel"
                  ).grid(row=0, column=3, sticky="w", padx=(0, 8))

        vcmd_wkg = (self.root.register(self._validate_wkg_entry), "%P")
        self.wkg_entry = ttk.Entry(wkg_frame, width=6, justify="center",
                                   style="Dark.TEntry", font=("Helvetica", 14, "bold"),
                                   validate="key", validatecommand=vcmd_wkg)
        self.wkg_entry.grid(row=0, column=4, padx=(0, 4))
        self.wkg_entry.bind("<Return>", self._on_wkg_entry_change)
        self.wkg_entry.bind("<FocusOut>", self._on_wkg_entry_change)

        ttk.Label(wkg_frame, text="W/kg", style="Dim.TLabel"
                  ).grid(row=0, column=5, sticky="w", padx=(0, 8))

        self.wkg_apply_btn = ttk.Button(wkg_frame, text="Apply",
                                        command=self._on_wkg_entry_change,
                                        style="Secondary.TButton", width=6)
        self.wkg_apply_btn.grid(row=0, column=6, padx=(8, 0))

        # Cadence control
        cad_frame = ttk.LabelFrame(tab, text="Cadence (RPM)",
                                   style="Dark.TLabelframe", padding=10)
        cad_frame.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        cad_frame.columnconfigure(1, weight=1)

        self.manual_cadence_var = tk.IntVar(value=85)

        ttk.Label(cad_frame, text="RPM:", style="Card.TLabel"
                  ).grid(row=0, column=0, sticky="w", padx=(0, 8))

        self.cadence_slider = ttk.Scale(cad_frame, from_=0, to=200,
                                        orient="horizontal",
                                        variable=self.manual_cadence_var,
                                        command=self._on_cadence_slider_change,
                                        style="Accent.Horizontal.TScale")
        self.cadence_slider.grid(row=0, column=1, sticky="ew", padx=(0, 8))

        vcmd_cadence = (self.root.register(self._validate_cadence_entry), "%P")
        self.cadence_entry = ttk.Entry(cad_frame, width=6, justify="center",
                                       style="Dark.TEntry", font=("Helvetica", 14, "bold"),
                                       validate="key", validatecommand=vcmd_cadence)
        self.cadence_entry.grid(row=0, column=2, padx=(0, 4))
        self.cadence_entry.insert(0, "85")
        self.cadence_entry.bind("<Return>", self._on_cadence_entry_change)
        self.cadence_entry.bind("<FocusOut>", self._on_cadence_entry_change)

        ttk.Label(cad_frame, text="RPM", style="Dim.TLabel"
                  ).grid(row=0, column=3, sticky="w")

        # Start / stop manual broadcast
        ctrl_frame = ttk.Frame(tab, style="Dark.TFrame")
        ctrl_frame.grid(row=3, column=0, pady=(4, 0))

        self.manual_start_btn = ttk.Button(ctrl_frame, text="Start Broadcasting",
                                           command=self._start_manual,
                                           style="Success.TButton", width=20)
        self.manual_start_btn.grid(row=0, column=0, padx=6)

        self.manual_stop_btn = ttk.Button(ctrl_frame, text="Stop Broadcasting",
                                          command=self._stop_manual,
                                          style="Danger.TButton", width=20,
                                          state="disabled")
        self.manual_stop_btn.grid(row=0, column=1, padx=6)

    # ---------- Current values display ----------
    def _build_current_values(self, parent, row):
        cf = ttk.Frame(parent, style="Card.TFrame", padding=14)
        cf.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        cf.columnconfigure(1, weight=1)
        cf.columnconfigure(4, weight=1)

        ttk.Label(cf, text="POWER", style="Dim.TLabel"
                  ).grid(row=0, column=0, sticky="w", padx=(4, 8))
        self.current_power_var = tk.StringVar(value="---")
        self.power_value_label = tk.Label(cf, textvariable=self.current_power_var,
                                          font=("Helvetica Neue", 36, "bold"),
                                          fg=self.ACCENT, bg=self.BG_MEDIUM)
        self.power_value_label.grid(row=0, column=1, sticky="w")
        ttk.Label(cf, text="W", style="ValueUnit.TLabel"
                  ).grid(row=0, column=2, sticky="sw", padx=(2, 30), pady=(0, 6))

        ttk.Label(cf, text="CADENCE", style="Dim.TLabel"
                  ).grid(row=0, column=3, sticky="w", padx=(4, 8))
        self.current_cadence_var = tk.StringVar(value="---")
        self.cadence_value_label = tk.Label(cf, textvariable=self.current_cadence_var,
                                            font=("Helvetica Neue", 36, "bold"),
                                            fg=self.ACCENT, bg=self.BG_MEDIUM)
        self.cadence_value_label.grid(row=0, column=4, sticky="w")
        ttk.Label(cf, text="RPM", style="ValueUnit.TLabel"
                  ).grid(row=0, column=5, sticky="sw", padx=(2, 4), pady=(0, 6))

    # ---------- Log ----------
    def _build_log(self, parent, row):
        lf = ttk.LabelFrame(parent, text="Log", style="Dark.TLabelframe", padding=6)
        lf.grid(row=row, column=0, sticky="nsew", pady=(0, 0))
        lf.columnconfigure(0, weight=1)
        lf.rowconfigure(0, weight=1)

        self.log_text = tk.Text(lf, height=6, state="disabled",
                                bg=self.BG_DARK, fg=self.FG_SECONDARY,
                                insertbackground=self.FG_PRIMARY,
                                selectbackground=self.ACCENT,
                                font=("Menlo", 10), borderwidth=0,
                                highlightthickness=0)
        self.log_text.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(lf, orient=tk.VERTICAL,
                                  command=self.log_text.yview,
                                  style="Dark.Vertical.TScrollbar")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text["yscrollcommand"] = scrollbar.set

    # ------------------------------------------------------------------
    # Power color helper
    # ------------------------------------------------------------------
    def _color_for_power(self, watts: int) -> str:
        color = self.ZONE_COLORS[0][1]
        for threshold, c in self.ZONE_COLORS:
            if watts >= threshold:
                color = c
        return color

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    def _configure_logging(self):
        self.logger = logging.getLogger("fit_ant_playback")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False

        for handler in list(self.logger.handlers):
            if isinstance(handler, TkLogHandler):
                self.logger.removeHandler(handler)

        handler = TkLogHandler(self.root, self._log)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        self.logger.addHandler(handler)

    def _log(self, message: str):
        """Add message to log"""
        self.log_text.configure(state="normal")
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    # ------------------------------------------------------------------
    # FIT File Playback methods
    # ------------------------------------------------------------------
    def _browse_file(self):
        """Open file browser to select FIT file"""
        filepath = filedialog.askopenfilename(
            title="Select FIT File",
            filetypes=[("FIT files", "*.fit"), ("All files", "*.*")]
        )
        if filepath:
            self.file_path_var.set(filepath)
            self._load_fit_file(filepath)

    def _load_fit_file(self, filepath: str):
        """Load and parse FIT file"""
        try:
            parser = FitFileParser()
            self.fit_records = parser.parse(filepath)

            if not self.fit_records:
                self._log("No power/cadence data found in file")
                messagebox.showwarning("Warning",
                                       "No power or cadence data found in the FIT file")
                return

            self.records_var.set(str(len(self.fit_records)))

            if self.fit_records:
                duration_secs = self.fit_records[-1].timestamp
                hours = int(duration_secs // 3600)
                minutes = int((duration_secs % 3600) // 60)
                seconds = int(duration_secs % 60)
                self.duration_var.set(f"{hours:02d}:{minutes:02d}:{seconds:02d}")

                powers = [r.power for r in self.fit_records if r.power > 0]
                cadences = [r.cadence for r in self.fit_records if r.cadence > 0]
                avg_power = sum(powers) / len(powers) if powers else 0
                avg_cadence = sum(cadences) / len(cadences) if cadences else 0
                self.avg_power_var.set(f"{avg_power:.0f} W")
                self.avg_cadence_var.set(f"{avg_cadence:.0f} RPM")

            self._log(f"Loaded {len(self.fit_records)} records from {Path(filepath).name}")

        except ImportError as e:
            self._log(f"Error: {e}")
            messagebox.showerror("Error", str(e))
        except Exception as e:
            self._log(f"Error loading file: {e}")
            messagebox.showerror("Error", f"Failed to load FIT file: {e}")

    def _connect_ant(self):
        """Connect to ANT+ USB stick"""
        if self.broadcaster and self.broadcaster.running:
            if self.is_playing or self.is_paused:
                self._stop()
            if self.manual_broadcasting:
                self._stop_manual()
            self.broadcaster.stop()
            self.broadcaster = None
            self.ant_status_var.set("Not Connected")
            self.ant_status_label.configure(foreground=self.WARNING)
            self.connect_btn.configure(text="Connect ANT+")
            self._log("ANT+ disconnected")
            return

        is_root = os.name == "nt" or not hasattr(os, "geteuid") or os.geteuid() == 0
        if not is_root:
            self._log("WARNING: Not running with admin privileges!")
            self._log("ANT+ USB access requires sudo on macOS")
            self._log("Restart with: sudo python fit_ant_playback.py")

        self._log("Connecting to ANT+ USB stick...")

        try:
            self.broadcaster = AntUsbBroadcaster(logger=self.logger)
            if self.broadcaster.start():
                self.ant_status_var.set("Connected")
                self.ant_status_label.configure(foreground=self.SUCCESS)
                self.connect_btn.configure(text="Disconnect")
                self._log("ANT+ connected successfully")
                self._log(f"Device ID: {self.broadcaster.DEVICE_NUMBER}, Type: Bike Power")
            else:
                self.ant_status_var.set("Connection Failed")
                self.ant_status_label.configure(foreground=self.ERROR)
                detail = self.broadcaster.last_error if self.broadcaster else None
                self._log(f"Failed to connect to ANT+ stick: {detail or 'unknown error'}")

                if not is_root:
                    messagebox.showerror("Permission Denied",
                        "ANT+ USB access requires admin privileges on macOS.\n\n"
                        "Please restart the app with sudo:\n\n"
                        "sudo python fit_ant_playback.py")
                else:
                    messagebox.showerror("Error",
                        f"Failed to connect to ANT+ USB stick.\n\n{detail or ''}\n\n"
                        "Make sure:\n"
                        "- ANT+ USB stick is plugged in\n"
                        "- No other application is using it (Zwift, TrainerRoad, etc.)")
                self.broadcaster = None
        except Exception as e:
            self._log(f"ANT+ error: {e}")
            messagebox.showerror("Error", f"ANT+ connection error: {e}")
            self.broadcaster = None

    def _on_speed_change(self, event=None):
        """Handle playback speed change"""
        speed_str = self.speed_var.get()
        self.playback_speed = float(speed_str.replace("x", ""))
        if self.playback_engine:
            self.playback_engine.set_speed(self.playback_speed)
        self._log(f"Playback speed set to {speed_str}")

    def _play(self):
        """Start or resume playback"""
        if self.manual_broadcasting:
            messagebox.showwarning("Warning",
                                   "Stop manual broadcasting before playing a FIT file")
            return
        if not self.fit_records:
            messagebox.showwarning("Warning", "Please load a FIT file first")
            return
        if not self.broadcaster or not self.broadcaster.running:
            messagebox.showwarning("Warning", "Please connect ANT+ first")
            return

        if self.playback_engine and self.is_paused:
            self.playback_engine.resume()
            self.is_paused = False
            self._log("Playback resumed")
        else:
            self.playback_engine = FitPlaybackEngine(
                records=self.fit_records,
                broadcast=self._broadcast_playback_record,
                on_update=lambda record, total, index: self.root.after(
                    0, self._update_playback_ui, record, total, index
                ),
                on_finished=lambda: self.root.after(0, self._playback_finished),
                on_error=lambda exc: self.root.after(0, self._playback_error, exc),
                speed=self.playback_speed,
            )
            self.is_playing = True
            self.is_paused = False
            self.current_index = 0
            self.playback_engine.start()
            self._log("Playback started")

        self.play_btn.configure(state="disabled")
        self.pause_btn.configure(state="normal")
        self.stop_btn.configure(state="normal")
        self.browse_btn.configure(state="disabled")

    def _broadcast_playback_record(self, record: PowerCadenceRecord):
        if not self.broadcaster or not self.broadcaster.running:
            raise RuntimeError("ANT+ disconnected")
        self.broadcaster.broadcast_power_cadence(record.power, record.cadence)

    def _pause(self):
        """Pause playback"""
        if self.playback_engine:
            self.playback_engine.pause()
        self.is_paused = True
        self.play_btn.configure(state="normal")
        self.pause_btn.configure(state="disabled")
        self._log("Playback paused")

    def _stop(self, *, log: bool = True):
        """Stop playback"""
        if self.playback_engine:
            self.playback_engine.stop()
            self.playback_engine = None
        self.is_playing = False
        self.is_paused = False
        self.current_index = 0

        self.play_btn.configure(state="normal")
        self.pause_btn.configure(state="disabled")
        self.stop_btn.configure(state="disabled")
        self.browse_btn.configure(state="normal")

        self.progress_var.set(0)
        self.current_power_var.set("---")
        self.current_cadence_var.set("---")
        self.power_value_label.configure(fg=self.ACCENT)
        if log:
            self._log("Playback stopped")

    def _update_playback_ui(self, record: PowerCadenceRecord, total_duration: float, index: int = 0):
        """Update UI during playback (called from main thread)"""
        self.current_index = index
        self.current_power_var.set(str(record.power))
        self.current_cadence_var.set(str(record.cadence))
        self.power_value_label.configure(fg=self._color_for_power(record.power))

        progress = (record.timestamp / total_duration * 100) if total_duration > 0 else 0
        self.progress_var.set(progress)

        current_secs = record.timestamp
        curr_h = int(current_secs // 3600)
        curr_m = int((current_secs % 3600) // 60)
        curr_s = int(current_secs % 60)

        total_h = int(total_duration // 3600)
        total_m = int((total_duration % 3600) // 60)
        total_s = int(total_duration % 60)

        self.time_var.set(
            f"{curr_h:02d}:{curr_m:02d}:{curr_s:02d} / "
            f"{total_h:02d}:{total_m:02d}:{total_s:02d}")

    def _playback_finished(self):
        """Called when playback completes"""
        self._log("Playback finished")
        self._stop(log=False)

    def _playback_error(self, exc: Exception):
        """Called when playback fails in the worker thread"""
        self._log(f"Playback error: {exc}")
        messagebox.showerror("Playback Error", str(exc))
        self._stop(log=False)

    # ------------------------------------------------------------------
    # Manual Power methods
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_power_entry(value: str) -> bool:
        if value == "":
            return True
        try:
            v = int(value)
            return 0 <= v <= 2000
        except ValueError:
            return False

    @staticmethod
    def _validate_cadence_entry(value: str) -> bool:
        if value == "":
            return True
        try:
            v = int(value)
            return 0 <= v <= 200
        except ValueError:
            return False

    def _on_power_slider_change(self, value):
        """Slider moved — update entry box"""
        watts = int(float(value))
        self.power_entry.delete(0, tk.END)
        self.power_entry.insert(0, str(watts))
        self._set_manual_state(power=watts)

    def _on_power_entry_change(self, event=None):
        """Entry box changed — update slider"""
        txt = self.power_entry.get().strip()
        if txt == "":
            return
        try:
            watts = max(0, min(2000, int(txt)))
            self.manual_power_var.set(watts)
            self._set_manual_state(power=watts)
        except ValueError:
            pass

    def _on_cadence_slider_change(self, value):
        """Slider moved — update entry box"""
        rpm = int(float(value))
        self.cadence_entry.delete(0, tk.END)
        self.cadence_entry.insert(0, str(rpm))
        self._set_manual_state(cadence=rpm)

    def _on_cadence_entry_change(self, event=None):
        """Entry box changed — update slider"""
        txt = self.cadence_entry.get().strip()
        if txt == "":
            return
        try:
            rpm = max(0, min(200, int(txt)))
            self.manual_cadence_var.set(rpm)
            self._set_manual_state(cadence=rpm)
        except ValueError:
            pass

    @staticmethod
    def _validate_weight_entry(value: str) -> bool:
        if value == "":
            return True
        try:
            v = float(value)
            return 0 < v <= 300
        except ValueError:
            return False

    @staticmethod
    def _validate_wkg_entry(value: str) -> bool:
        if value == "":
            return True
        try:
            v = float(value)
            return 0 <= v <= 30
        except ValueError:
            return False

    def _on_wkg_entry_change(self, event=None):
        """W/kg entry changed — compute watts from W/kg * weight and set power"""
        wkg_txt = self.wkg_entry.get().strip()
        weight_txt = self.weight_entry.get().strip()
        if not wkg_txt or not weight_txt:
            return
        try:
            wkg = float(wkg_txt)
            weight = float(weight_txt)
            watts = max(0, min(2000, int(round(wkg * weight))))
            self._set_manual_power(watts)
        except ValueError:
            pass

    def _set_manual_power(self, watts: int):
        """Quick-set power from preset button"""
        self.manual_power_var.set(watts)
        self.power_entry.delete(0, tk.END)
        self.power_entry.insert(0, str(watts))
        self._set_manual_state(power=watts)

    def _set_manual_state(self, *, power: int | None = None, cadence: int | None = None):
        with self._manual_lock:
            if power is not None:
                self._manual_power = max(0, min(2000, int(power)))
            if cadence is not None:
                self._manual_cadence = max(0, min(200, int(cadence)))

    def _get_manual_state(self) -> tuple[int, int]:
        with self._manual_lock:
            return self._manual_power, self._manual_cadence

    def _start_manual(self):
        """Start manual power broadcast"""
        if self.is_playing:
            messagebox.showwarning("Warning",
                                   "Stop FIT playback before starting manual mode")
            return
        if not self.broadcaster or not self.broadcaster.running:
            messagebox.showwarning("Warning", "Please connect ANT+ first")
            return

        self._on_power_entry_change()
        self._on_cadence_entry_change()
        self.manual_broadcasting = True
        self.manual_start_btn.configure(state="disabled")
        self.manual_stop_btn.configure(state="normal")
        self.manual_engine = ManualBroadcastEngine(
            get_values=self._get_manual_state,
            broadcast=self._broadcast_manual_values,
            on_update=lambda power, cadence: self.root.after(
                0, self._update_manual_ui, power, cadence
            ),
            on_error=lambda exc: self.root.after(0, self._manual_error, exc),
        )
        self.manual_engine.start()
        self._log("Manual broadcast started")

    def _stop_manual(self, *, log: bool = True):
        """Stop manual power broadcast"""
        if self.manual_engine:
            self.manual_engine.stop()
            self.manual_engine = None
        self.manual_broadcasting = False
        self.manual_start_btn.configure(state="normal")
        self.manual_stop_btn.configure(state="disabled")
        self.current_power_var.set("---")
        self.current_cadence_var.set("---")
        self.power_value_label.configure(fg=self.ACCENT)
        if log:
            self._log("Manual broadcast stopped")

    def _broadcast_manual_values(self, power: int, cadence: int):
        if not self.broadcaster or not self.broadcaster.running:
            raise RuntimeError("ANT+ disconnected")
        self.broadcaster.broadcast_power_cadence(power, cadence)

    def _manual_error(self, exc: Exception):
        self._log(f"Manual broadcast error: {exc}")
        messagebox.showerror("Manual Broadcast Error", str(exc))
        self._stop_manual(log=False)

    def _update_manual_ui(self, power: int, cadence: int):
        """Update current-value display for manual mode"""
        self.current_power_var.set(str(power))
        self.current_cadence_var.set(str(cadence))
        self.power_value_label.configure(fg=self._color_for_power(power))

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    def run(self):
        """Start the application"""
        self.root.mainloop()

        # Cleanup on exit
        if self.playback_engine:
            self.playback_engine.stop()
        if self.manual_engine:
            self.manual_engine.stop()
        if self.broadcaster:
            self.broadcaster.stop()


def main():
    """Main entry point"""
    if not fitdecode_available():
        print("Warning: fitdecode library not installed")
        print("FIT file loading will not work until you run: pip install fitdecode")

    app = FitAntPlaybackApp()
    app.run()


if __name__ == "__main__":
    main()
