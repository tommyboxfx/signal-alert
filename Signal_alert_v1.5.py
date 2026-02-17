# -*- coding: utf-8 -*-
"""
PocketOption Signal Alert v1.5 - Windows GUI Sound Alert Client
Connects to the same WebSocket signal server as the PO Autotrader
Plays instant sound alert on DIV_FORMING signals

v1.5: Display fixes + log file + smart popup
- FIX: TF/Exp display - only show TF:M{n} if tf has value, only Exp:{n}m if exp > 0
- FIX: SKIP lines now include BUY/SELL direction
- NEW: Log file (signal_alert_YYYY-MM-DD.log) in BASE_DIR, persists after close
- NEW: Icon next to title text (horn_icon.ico via PIL)
- NEW: Custom popup with pair (bold), TF, WR, payout info + red border
- NEW: Popup auto-closes with countdown timer (configurable 1-5 min, default 2)
- NEW: Popup only for quality alerts (WR >= 55%), low-WR alerts log only
- UI: Window size 580x560 (wider + taller, more log visible)

v1.4: Payout cache fix
- FIX: Payout cache cleared on every update (was stale - old 85% stayed when pair dropped to 22%)
- FIX: No payout data (0%) = SKIP alert (conservative - only alert for confirmed >= 75%)
- Respects _server_filtered flag from webhook server

v1.3: Payout filter
- Only alerts for PO 21 forex pairs with payout >= 75%
- Caches payout data from signal server (same as PO autotrader)
- Skips low-payout signals (Dukascopy-only trades)
- Server connection built-in (zero config)
- Volume slider, sound selection, alert log
"""

import asyncio
import json
import os
import sys
import time
import threading
import winsound
import ctypes
import struct
import math
import wave
import io
import tkinter as tk
from tkinter import ttk, scrolledtext
from datetime import datetime

VERSION = "1.5"

# ═══════════════════════════════════════════════════════════════════════════
# BUILT-IN SERVER CONFIG (no user configuration needed)
# ═══════════════════════════════════════════════════════════════════════════
SERVER_HOST = "46.250.226.38"
SERVER_PORT = 8085
API_KEY = "xK9mP2vL8nQ4wR7jF3hY6bT1cA5eU0iO"

# ═══════════════════════════════════════════════════════════════════════════
# BASE DIR
# ═══════════════════════════════════════════════════════════════════════════
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SETTINGS_FILE = os.path.join(BASE_DIR, "signal_alert_settings.json")

SAMPLE_RATE = 44100

# ═══════════════════════════════════════════════════════════════════════════
# WAV TONE GENERATOR (no external dependencies)
# ═══════════════════════════════════════════════════════════════════════════

def generate_tone(frequency, duration_ms, volume=1.0):
    """Generate raw PCM samples for a sine wave tone"""
    num_samples = int(SAMPLE_RATE * duration_ms / 1000)
    amp = int(32767 * min(1.0, max(0.0, volume)))
    samples = []
    for i in range(num_samples):
        t = i / SAMPLE_RATE
        sample = int(amp * math.sin(2 * math.pi * frequency * t))
        samples.append(struct.pack('<h', max(-32768, min(32767, sample))))
    return b''.join(samples)


def generate_sweep(freq_start, freq_end, duration_ms, volume=1.0):
    """Generate a frequency sweep (for siren effects)"""
    num_samples = int(SAMPLE_RATE * duration_ms / 1000)
    amp = int(32767 * min(1.0, max(0.0, volume)))
    samples = []
    for i in range(num_samples):
        t = i / num_samples
        freq = freq_start + (freq_end - freq_start) * t
        sample = int(amp * math.sin(2 * math.pi * freq * (i / SAMPLE_RATE)))
        samples.append(struct.pack('<h', max(-32768, min(32767, sample))))
    return b''.join(samples)


def silence(duration_ms):
    """Generate silence"""
    num_samples = int(SAMPLE_RATE * duration_ms / 1000)
    return b'\x00\x00' * num_samples


def pcm_to_wav(pcm_data):
    """Wrap raw PCM data into a WAV file in memory"""
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm_data)
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════════════
# SOUND DEFINITIONS (WAV-based, volume controllable)
# ═══════════════════════════════════════════════════════════════════════════

def build_siren(volume=1.0):
    """Police siren - alternating high/low sweep"""
    pcm = b''
    for _ in range(3):
        pcm += generate_sweep(800, 1400, 400, volume)
        pcm += generate_sweep(1400, 800, 400, volume)
    return pcm_to_wav(pcm)


def build_ship_horn(volume=1.0):
    """Ship horn - deep sustained blast"""
    pcm = b''
    pcm += generate_tone(150, 900, volume)
    pcm += silence(150)
    pcm += generate_tone(150, 900, volume)
    return pcm_to_wav(pcm)


def build_bell(volume=1.0):
    """Bell - sharp high dings"""
    pcm = b''
    for _ in range(4):
        pcm += generate_tone(2000, 120, volume)
        pcm += silence(80)
        pcm += generate_tone(2500, 80, volume)
        pcm += silence(150)
    return pcm_to_wav(pcm)


def build_alarm(volume=1.0):
    """Classic alarm - rapid beeping"""
    pcm = b''
    for _ in range(10):
        pcm += generate_tone(1000, 100, volume)
        pcm += silence(60)
    return pcm_to_wav(pcm)


def build_triple_beep(volume=1.0):
    """Triple beep - simple 3x notification"""
    pcm = b''
    for _ in range(3):
        pcm += generate_tone(1200, 250, volume)
        pcm += silence(150)
    return pcm_to_wav(pcm)


def build_air_raid(volume=1.0):
    """Air raid siren - slow rising and falling"""
    pcm = b''
    for _ in range(2):
        pcm += generate_sweep(400, 1200, 1200, volume)
        pcm += generate_sweep(1200, 400, 1200, volume)
    return pcm_to_wav(pcm)


def build_foghorn(volume=1.0):
    """Foghorn - very deep powerful blast"""
    pcm = b''
    pcm += generate_sweep(80, 120, 1200, volume)
    pcm += silence(300)
    pcm += generate_sweep(80, 120, 800, volume)
    return pcm_to_wav(pcm)


def build_bugle(volume=1.0):
    """Bugle charge - ascending fanfare"""
    pcm = b''
    notes = [523, 659, 784, 1047, 784, 1047]  # C5 E5 G5 C6 G5 C6
    durations = [200, 200, 200, 400, 150, 500]
    for freq, dur in zip(notes, durations):
        pcm += generate_tone(freq, dur, volume)
        pcm += silence(30)
    return pcm_to_wav(pcm)


SOUNDS = {
    "Siren": build_siren,
    "Ship Horn": build_ship_horn,
    "Bell": build_bell,
    "Alarm": build_alarm,
    "Triple Beep": build_triple_beep,
    "Air Raid": build_air_raid,
    "Foghorn": build_foghorn,
    "Bugle": build_bugle,
}


def play_sound(sound_name, volume=1.0, repeat=1):
    """Play sound in background thread"""
    def _play():
        build_func = SOUNDS.get(sound_name, build_siren)
        wav_data = build_func(volume)
        for i in range(repeat):
            winsound.PlaySound(wav_data, winsound.SND_MEMORY)
            if i < repeat - 1:
                time.sleep(0.2)
    threading.Thread(target=_play, daemon=True).start()


# ═══════════════════════════════════════════════════════════════════════════
# 21 PO FOREX PAIRS
# ═══════════════════════════════════════════════════════════════════════════

VALID_FOREX_SYMBOLS = {
    "EURUSD", "GBPUSD", "AUDUSD", "USDCHF", "USDCAD", "USDJPY",
    "EURJPY", "GBPJPY", "AUDJPY", "CHFJPY", "CADJPY",
    "EURGBP", "EURCHF", "EURAUD", "EURCAD",
    "GBPCHF", "GBPAUD", "GBPCAD",
    "AUDCHF", "AUDCAD",
    "CADCHF"
}

def is_valid_forex(symbol):
    return symbol.upper().replace("/", "").replace(" ", "") in VALID_FOREX_SYMBOLS

def format_pair(symbol):
    clean = symbol.upper().replace("/", "").replace(" ", "")
    if len(clean) == 6:
        return clean[:3] + "/" + clean[3:]
    return symbol


# ═══════════════════════════════════════════════════════════════════════════
# SETTINGS
# ═══════════════════════════════════════════════════════════════════════════

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {
        "sound": "Siren",
        "volume": 80,
        "repeat": 1,
        "show_popup": True,
        "popup_timeout": 2
    }

def save_settings(settings):
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=4)
    except:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# GUI APPLICATION
# ═══════════════════════════════════════════════════════════════════════════

class SignalAlertApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"Signal Alert v{VERSION}")
        self.root.geometry("580x560")
        self.root.resizable(False, False)
        self.root.configure(bg="#1a1a2e")

        # Try to set icon
        self.icon_path = os.path.join(BASE_DIR, "horn_icon.ico")
        try:
            if os.path.exists(self.icon_path):
                self.root.iconbitmap(self.icon_path)
        except:
            pass

        self.settings = load_settings()
        self.connected = False
        self.ws_thread = None
        self.stop_event = threading.Event()
        self.alert_count = 0
        self.payout_cache = {}  # v1.3: Payout cache from signal server
        self.min_payout = 75    # v1.3: Minimum payout to alert
        self.min_wr_popup = 55  # v1.5: Minimum WR for popup
        self.popup_window = None  # v1.5: Track current popup

        # v1.5: Init log file
        self._init_log_file()

        self._build_gui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _init_log_file(self):
        today = datetime.now().strftime("%Y-%m-%d")
        self.log_file_path = os.path.join(BASE_DIR, f"signal_alert_{today}.log")
        self.log_file_date = today

    def _build_gui(self):
        style = ttk.Style()
        style.theme_use('clam')

        bg = "#1a1a2e"
        accent = "#e94560"

        style.configure("Title.TLabel", background=bg, foreground=accent, font=("Segoe UI", 16, "bold"))
        style.configure("BG.TFrame", background=bg)
        style.configure("Status.TLabel", background=bg, foreground="#888", font=("Segoe UI", 10))
        style.configure("Connected.TLabel", background=bg, foreground="#00ff88", font=("Segoe UI", 10, "bold"))
        style.configure("Alert.TLabel", background=bg, foreground=accent, font=("Segoe UI", 11, "bold"))
        style.configure("Connect.TButton", font=("Segoe UI", 10, "bold"))
        style.configure("Test.TButton", font=("Segoe UI", 9))
        style.configure("Vol.TLabel", background=bg, foreground="#e0e0e0", font=("Segoe UI", 9))

        # Main container
        main = ttk.Frame(self.root, style="BG.TFrame", padding=15)
        main.pack(fill="both", expand=True)

        # v1.5: Title row with icon
        title_row = ttk.Frame(main, style="BG.TFrame")
        title_row.pack(pady=(0, 10))
        try:
            from PIL import Image, ImageTk
            icon_img = Image.open(self.icon_path).resize((28, 28), Image.LANCZOS)
            self.title_icon = ImageTk.PhotoImage(icon_img)
            ttk.Label(title_row, image=self.title_icon, background="#1a1a2e").pack(side="left", padx=(0, 8))
        except:
            pass
        ttk.Label(title_row, text="PocketOption Signal Alert", style="Title.TLabel").pack(side="left")

        # ─── Alert Settings ───
        alert_frame = ttk.LabelFrame(main, text=" Alert Settings ", padding=10)
        alert_frame.pack(fill="x", pady=(0, 8))

        row3 = ttk.Frame(alert_frame)
        row3.pack(fill="x", pady=2)
        ttk.Label(row3, text="Sound:", width=8).pack(side="left")
        self.sound_var = tk.StringVar(value=self.settings.get("sound", "Siren"))
        self.sound_combo = ttk.Combobox(row3, textvariable=self.sound_var,
                                         values=list(SOUNDS.keys()), state="readonly", width=15)
        self.sound_combo.pack(side="left", padx=(0, 8))

        ttk.Button(row3, text="Test", command=self._test_sound, style="Test.TButton", width=6).pack(side="left", padx=(0, 4))
        ttk.Button(row3, text="Test Signal", command=self._test_signal, style="Test.TButton", width=10).pack(side="left", padx=(0, 10))

        ttk.Label(row3, text="Repeat:").pack(side="left")
        self.repeat_var = tk.StringVar(value=str(self.settings.get("repeat", 1)))
        ttk.Combobox(row3, textvariable=self.repeat_var,
                      values=["1", "2", "3"], state="readonly", width=3).pack(side="left")

        # Volume slider row
        row_vol = ttk.Frame(alert_frame)
        row_vol.pack(fill="x", pady=(6, 2))
        ttk.Label(row_vol, text="Volume:", width=8).pack(side="left")
        self.volume_var = tk.IntVar(value=self.settings.get("volume", 80))
        self.volume_slider = ttk.Scale(row_vol, from_=5, to=100, variable=self.volume_var,
                                        orient="horizontal", command=self._on_volume_change)
        self.volume_slider.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.vol_label = ttk.Label(row_vol, text=f"{self.volume_var.get()}%", width=5)
        self.vol_label.pack(side="left")

        # Popup checkbox + timeout
        row4 = ttk.Frame(alert_frame)
        row4.pack(fill="x", pady=2)
        self.popup_var = tk.BooleanVar(value=self.settings.get("show_popup", True))
        ttk.Checkbutton(row4, text="Show popup on alert (WR>=55%)", variable=self.popup_var).pack(side="left")
        ttk.Label(row4, text="  Timeout:").pack(side="left")
        self.popup_timeout_var = tk.StringVar(value=str(self.settings.get("popup_timeout", 2)))
        ttk.Combobox(row4, textvariable=self.popup_timeout_var,
                      values=["1", "2", "3", "5"], state="readonly", width=3).pack(side="left", padx=(2, 0))
        ttk.Label(row4, text="min").pack(side="left")

        # ─── Connect / Status ───
        ctrl_frame = ttk.Frame(main, style="BG.TFrame")
        ctrl_frame.pack(fill="x", pady=(0, 8))

        self.connect_btn = ttk.Button(ctrl_frame, text="Connect", command=self._toggle_connection,
                                       style="Connect.TButton", width=20)
        self.connect_btn.pack(side="left")

        self.status_label = ttk.Label(ctrl_frame, text="Disconnected", style="Status.TLabel")
        self.status_label.pack(side="left", padx=15)

        self.count_label = ttk.Label(ctrl_frame, text="", style="Alert.TLabel")
        self.count_label.pack(side="right")

        # ─── Alert Log ───
        log_frame = ttk.LabelFrame(main, text=" Alert Log ", padding=5)
        log_frame.pack(fill="both", expand=True)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=8, bg="#0a0a1a", fg="#00ff88",
                                                    font=("Consolas", 10), state="disabled",
                                                    insertbackground="#00ff88", wrap="word")
        self.log_text.pack(fill="both", expand=True)

    def _on_volume_change(self, val):
        self.vol_label.configure(text=f"{int(float(val))}%")

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        # GUI
        self.log_text.config(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")
        # v1.5: File logging
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self.log_file_date:
            self._init_log_file()
        try:
            with open(self.log_file_path, 'a', encoding='utf-8') as f:
                f.write(line + "\n")
        except:
            pass

    def _set_status(self, text, connected=False):
        if connected:
            self.status_label.configure(text=text, style="Connected.TLabel")
        else:
            self.status_label.configure(text=text, style="Status.TLabel")

    def _test_sound(self):
        vol = self.volume_var.get() / 100.0
        play_sound(self.sound_var.get(), vol, 1)

    def _test_signal(self):
        self._on_alert("EUR/USD", "BUY", wr=80, tf="5", exp=6, payout=85)

    def _get_current_settings(self):
        return {
            "sound": self.sound_var.get(),
            "volume": self.volume_var.get(),
            "repeat": int(self.repeat_var.get()),
            "show_popup": self.popup_var.get(),
            "popup_timeout": int(self.popup_timeout_var.get())
        }

    # ─── v1.5: Custom popup with countdown ───

    def _show_popup(self, pair, dir_text, wr=0, tf="", exp=0, payout=0):
        # Close previous popup if still open
        if self.popup_window and self.popup_window.winfo_exists():
            try:
                self.popup_window.destroy()
            except:
                pass

        timeout_min = int(self.popup_timeout_var.get())
        timeout_sec = timeout_min * 60

        popup = tk.Toplevel(self.root)
        self.popup_window = popup
        popup.title(f"SIGNAL ALERT - {pair}")
        popup.overrideredirect(True)  # No title bar - we draw our own
        popup.attributes('-topmost', True)
        popup.configure(bg="#e94560")  # Red border effect

        # Center on screen
        pw, ph = 420, 280
        sx = popup.winfo_screenwidth() // 2 - pw // 2
        sy = popup.winfo_screenheight() // 2 - ph // 2
        popup.geometry(f"{pw}x{ph}+{sx}+{sy}")

        # Inner frame (dark bg inside red border)
        inner = tk.Frame(popup, bg="#1a1a2e")
        inner.pack(fill="both", expand=True, padx=3, pady=3)

        # Direction color
        dir_color = "#00ff88" if dir_text == "BUY" else "#ff4444"

        # Title bar with close button
        title_bar = tk.Frame(inner, bg="#0a0a1a")
        title_bar.pack(fill="x")
        tk.Label(title_bar, text="TRADING SIGNAL", bg="#0a0a1a", fg="#e94560",
                 font=("Segoe UI", 10, "bold")).pack(side="left", padx=10, pady=4)
        close_btn = tk.Label(title_bar, text=" X ", bg="#0a0a1a", fg="#888",
                             font=("Segoe UI", 10, "bold"), cursor="hand2")
        close_btn.pack(side="right", padx=5, pady=4)
        close_btn.bind("<Button-1>", lambda e: popup.destroy())

        # Make title bar draggable
        def start_drag(e):
            popup._drag_x = e.x
            popup._drag_y = e.y
        def do_drag(e):
            x = popup.winfo_x() + e.x - popup._drag_x
            y = popup.winfo_y() + e.y - popup._drag_y
            popup.geometry(f"+{x}+{y}")
        title_bar.bind("<Button-1>", start_drag)
        title_bar.bind("<B1-Motion>", do_drag)

        # Direction
        tk.Label(inner, text=dir_text, bg="#1a1a2e", fg=dir_color,
                 font=("Segoe UI", 22, "bold")).pack(pady=(12, 2))

        # Pair name - BOLD and big
        tk.Label(inner, text=pair, bg="#1a1a2e", fg="#ffffff",
                 font=("Segoe UI", 28, "bold")).pack(pady=(0, 8))

        # Info line: WR, TF, Payout
        info_parts = []
        if wr:
            info_parts.append(f"WR: {wr}%")
        if tf:
            info_parts.append(f"TF: M{tf}")
        if exp and exp > 0:
            info_parts.append(f"Exp: {exp}m")
        if payout > 0:
            info_parts.append(f"Payout: {payout}%")
        if info_parts:
            tk.Label(inner, text="  |  ".join(info_parts), bg="#1a1a2e", fg="#aaaaaa",
                     font=("Segoe UI", 11)).pack(pady=(0, 5))

        # Countdown label
        countdown_var = tk.StringVar()
        countdown_label = tk.Label(inner, textvariable=countdown_var, bg="#1a1a2e", fg="#666666",
                                   font=("Segoe UI", 9))
        countdown_label.pack(side="bottom", pady=(0, 8))

        # Countdown timer
        remaining = [timeout_sec]

        def tick():
            if not popup.winfo_exists():
                return
            remaining[0] -= 1
            if remaining[0] <= 0:
                try:
                    popup.destroy()
                except:
                    pass
                return
            mins = remaining[0] // 60
            secs = remaining[0] % 60
            countdown_var.set(f"Auto-close in {mins}:{secs:02d}")
            popup.after(1000, tick)

        mins = remaining[0] // 60
        secs = remaining[0] % 60
        countdown_var.set(f"Auto-close in {mins}:{secs:02d}")
        popup.after(1000, tick)

    def _toggle_connection(self):
        if self.connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        settings = self._get_current_settings()
        save_settings(settings)

        self.stop_event.clear()
        self.connected = True
        self.connect_btn.configure(text="Disconnect")
        self._set_status("Connecting...", False)
        self._log("Connecting to signal server...")

        self.ws_thread = threading.Thread(target=self._ws_loop, daemon=True)
        self.ws_thread.start()

    def _disconnect(self):
        self.stop_event.set()
        self.connected = False
        self.connect_btn.configure(text="Connect")
        self._set_status("Disconnected", False)
        self._log("Disconnected")

    def _on_alert(self, pair, direction, wr=0, tf="", exp=0, payout=0):
        self.alert_count += 1
        dir_text = "BUY" if direction.upper() in ["BUY", "CALL"] else "SELL"

        # v1.5: Only show WR/TF/Exp parts that have actual data
        extra = ""
        parts = []
        if wr:
            parts.append(f"WR:{wr}%")
        if tf:
            parts.append(f"TF:M{tf}")
        if exp and exp > 0:
            parts.append(f"Exp:{exp}m")
        if parts:
            extra = " | " + " ".join(parts)
        if payout > 0:
            extra += f" | Pay:{payout}%"
        self._log(f"ALERT #{self.alert_count}  {dir_text} {pair}{extra}")

        self.count_label.configure(text=f"Alerts: {self.alert_count}")

        # Sound plays for all alerts
        vol = self.volume_var.get() / 100.0
        repeat = int(self.repeat_var.get())
        play_sound(self.sound_var.get(), vol, repeat)

        # v1.5: Popup only for quality alerts (WR >= 55%)
        if self.popup_var.get() and wr >= self.min_wr_popup:
            self._show_popup(pair, dir_text, wr, tf, exp, payout)
        elif self.popup_var.get() and wr > 0 and wr < self.min_wr_popup:
            self._log(f"  (no popup - WR {wr}% < {self.min_wr_popup}%)")

        # Flash window to taskbar
        try:
            self.root.attributes('-topmost', True)
            self.root.after(200, lambda: self.root.attributes('-topmost', False))
        except:
            pass

    def _ws_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._ws_client())
        except Exception as e:
            self.root.after(0, lambda: self._log(f"Connection error: {e}"))
            self.root.after(0, lambda: self._set_status("Error", False))
        finally:
            loop.close()

    async def _ws_client(self):
        import websockets

        uri = f"ws://{SERVER_HOST}:{SERVER_PORT}"

        while not self.stop_event.is_set():
            try:
                async with websockets.connect(uri) as ws:
                    await ws.send(json.dumps({"api_key": API_KEY}))
                    response = await ws.recv()
                    resp_data = json.loads(response)

                    if "error" in resp_data:
                        self.root.after(0, lambda: self._log(f"Auth failed: {resp_data.get('error')}"))
                        self.root.after(0, lambda: self._set_status("Auth failed", False))
                        self.root.after(0, self._disconnect)
                        return

                    self.root.after(0, lambda: self._set_status("Connected", True))
                    self.root.after(0, lambda: self._log("Connected! Waiting for signals..."))

                    while not self.stop_event.is_set():
                        try:
                            message = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        except asyncio.TimeoutError:
                            continue

                        try:
                            data = json.loads(message)
                            sig_type = data.get('type', '')
                            sig_data = data.get('data', {})

                            # v1.4: Cache payout updates from signal server
                            # CLEAR entire cache first (prevents stale data when pair drops off)
                            if sig_type == 'pocketoptions':
                                new_cache = {}
                                pairs = sig_data.get('pairs', [])
                                for p in pairs:
                                    pp = p.get('pair', '')
                                    pv = p.get('payout', 0)
                                    if pp and pv > 0:
                                        if '/' not in pp and len(pp) == 6:
                                            pp = pp[:3] + '/' + pp[3:]
                                        new_cache[pp.upper()] = pv
                                self.payout_cache = new_cache
                                continue

                            if sig_type != 'div_alert':
                                continue

                            alert_type = sig_data.get('alert', '')
                            symbol = sig_data.get('symbol', '')
                            direction = sig_data.get('direction', '')

                            if alert_type != 'DIV_FORMING':
                                continue
                            if not is_valid_forex(symbol):
                                continue
                            if not sig_data.get('_server_filtered', True):
                                continue

                            pair = format_pair(symbol)

                            # v1.5: Include direction in SKIP log lines
                            dir_text = "BUY" if direction.upper() in ["BUY", "CALL"] else "SELL"

                            # v1.4: Payout check - skip if unknown (0%) OR below minimum
                            payout = self.payout_cache.get(pair.upper(), 0)
                            if payout < self.min_payout:
                                reason = f"no data" if payout == 0 else f"{payout}%"
                                self.root.after(0, lambda d=dir_text, p=pair, r=reason:
                                    self._log(f"SKIP {d} {p} - payout {r} < {self.min_payout}%"))
                                continue

                            backtest = sig_data.get('backtest', {})
                            by_time = backtest.get('by_time', {})
                            current_best = by_time.get('current_best', {})
                            wr = current_best.get('wr', 0)
                            tf = current_best.get('tf', '')
                            exp = current_best.get('expiry', 0)

                            self.root.after(0, lambda p=pair, d=direction, w=wr, t=tf, e=exp, pv=payout:
                                            self._on_alert(p, d, w, t, e, pv))

                        except json.JSONDecodeError:
                            pass

            except Exception as e:
                if self.stop_event.is_set():
                    break
                self.root.after(0, lambda: self._set_status("Reconnecting...", False))
                self.root.after(0, lambda: self._log(f"Connection lost. Reconnecting in 5s..."))
                await asyncio.sleep(5)

    def _on_close(self):
        try:
            settings = self._get_current_settings()
            save_settings(settings)
        except:
            pass
        self.stop_event.set()
        # Close popup if open
        if self.popup_window and self.popup_window.winfo_exists():
            try:
                self.popup_window.destroy()
            except:
                pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    if hasattr(sys, 'frozen'):
        import multiprocessing
        multiprocessing.freeze_support()

    app = SignalAlertApp()
    app.run()

if __name__ == "__main__":
    main()
