import tkinter as tk
import sys
import webbrowser
import random
import requests
import concurrent.futures
import threading
import time
import configparser
import os
import shutil
import subprocess
import csv
import json
import tempfile
import asyncio
from bisect import bisect_left
from datetime import datetime

try:
    import sounddevice as sd
    import numpy as np
    _HAS_SOUNDDEVICE = True
except ImportError:
    sd = None
    np = None
    _HAS_SOUNDDEVICE = False

# Nowoczesny TTS: edge-tts (kobiecy głos Zofia, ładne brzmienie)
try:
    import edge_tts
    _HAS_EDGE_TTS = True
    _EDGE_VOICE = "pl-PL-ZofiaNeural"  # polski, kobiecy, neural
except ImportError:
    edge_tts = None
    _HAS_EDGE_TTS = False

try:
    import playsound
    _HAS_PLAYSOUND = True
except ImportError:
    playsound = None
    _HAS_PLAYSOUND = False

def _play_mp3(path):
    """Odtwarza plik MP3 (playsound lub pygame)."""
    if _HAS_PLAYSOUND:
        try:
            playsound.playsound(path, block=True)
            return True
        except Exception:
            pass
    try:
        import pygame
        pygame.mixer.init()
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.1)
        return True
    except Exception:
        pass
    return False

try:
    import pyttsx3
except Exception:
    pyttsx3 = None

# Maks. częstość komunikatów głosowych: raz na minutę
TTS_MIN_INTERVAL_SEC = 60


def _play_beep_sound():
    """Nowoczesny sygnał alarmowy (sounddevice + numpy). Działa w tle, nie blokuje GUI."""
    if not _HAS_SOUNDDEVICE:
        return
    def _do():
        try:
            duration_sec = 0.15
            freq = 880
            rate = 44100
            t = np.linspace(0, duration_sec, int(rate * duration_sec), False)
            wave = np.sin(2 * np.pi * freq * t) * 0.3
            sd.play(wave, rate, blocking=True)
        except Exception:
            pass
    threading.Thread(target=_do, daemon=True).start()

# --- KONFIGURACJA SIECIOWA ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(SCRIPT_DIR, "settings.ini")
HISTORY_CSV_PATH = os.path.join(SCRIPT_DIR, "glucose_history.csv")
FORECAST_STATE_PATH = os.path.join(SCRIPT_DIR, "forecast_state.json")


def load_settings(path):
    defaults = {
        "NETWORK": {
            "IP": "192.168.1.100",
            "Port": "17580",
            "SubnetPrefix": "192.168.1."
        },
        "ALARM": {
            "Hiper": "180",
            "Hipo": "70",
            "BlinkMs": "600",
            "SoundMs": "850",
            "SpeechEnabled": "false",
            "SpeakEachRead": "false",
            "SpeechLang": "pl"
        },
        "DAY": {
            "Start": "07:00",
            "End": "22:00",
            "Hiper": "180",
            "Hipo": "70",
            "BlinkMs": "600",
            "SoundMs": "850",
            "SpeechRate": "150"
        },
        "NIGHT": {
            "Start": "22:00",
            "End": "07:00",
            "Hiper": "200",
            "Hipo": "80",
            "BlinkMs": "800",
            "SoundMs": "1100",
            "SpeechRate": "140"
        },
        "UI": {
            "AlwaysOnTop": "true"
        }
    }

    config = configparser.ConfigParser()
    if os.path.exists(path):
        config.read(path)

    needs_write = False
    for section, values in defaults.items():
        if not config.has_section(section):
            config.add_section(section)
            needs_write = True
        for key, value in values.items():
            if not config.has_option(section, key):
                config.set(section, key, value)
                needs_write = True

    if needs_write:
        with open(path, "w", encoding="utf-8") as f:
            config.write(f)

    return {
        "default_ip": config.get("NETWORK", "IP", fallback=defaults["NETWORK"]["IP"]),
        "port": config.getint("NETWORK", "Port", fallback=17580),
        "subnet_prefix": config.get("NETWORK", "SubnetPrefix", fallback=defaults["NETWORK"]["SubnetPrefix"]),
        "alarm_hiper": config.getint("ALARM", "Hiper", fallback=180),
        "alarm_hipo": config.getint("ALARM", "Hipo", fallback=70),
        "blink_ms": config.getint("ALARM", "BlinkMs", fallback=600),
        "sound_ms": config.getint("ALARM", "SoundMs", fallback=850),
        "speech_enabled": config.getboolean("ALARM", "SpeechEnabled", fallback=False),
        "speak_each_read": config.getboolean("ALARM", "SpeakEachRead", fallback=False),
        "speech_lang": config.get("ALARM", "SpeechLang", fallback="pl"),
        "day_start": config.get("DAY", "Start", fallback="07:00"),
        "day_end": config.get("DAY", "End", fallback="22:00"),
        "day_hiper": config.getint("DAY", "Hiper", fallback=180),
        "day_hipo": config.getint("DAY", "Hipo", fallback=70),
        "day_blink_ms": config.getint("DAY", "BlinkMs", fallback=600),
        "day_sound_ms": config.getint("DAY", "SoundMs", fallback=850),
        "day_speech_rate": config.getint("DAY", "SpeechRate", fallback=150),
        "night_start": config.get("NIGHT", "Start", fallback="22:00"),
        "night_end": config.get("NIGHT", "End", fallback="07:00"),
        "night_hiper": config.getint("NIGHT", "Hiper", fallback=200),
        "night_hipo": config.getint("NIGHT", "Hipo", fallback=80),
        "night_blink_ms": config.getint("NIGHT", "BlinkMs", fallback=800),
        "night_sound_ms": config.getint("NIGHT", "SoundMs", fallback=1100),
        "night_speech_rate": config.getint("NIGHT", "SpeechRate", fallback=140),
        "always_on_top": config.getboolean("UI", "AlwaysOnTop", fallback=True),
    }


SETTINGS = load_settings(SETTINGS_PATH)

# Domyślny cel (od tego zacznie szukać)
DEFAULT_IP = SETTINGS["default_ip"]
PORT = SETTINGS["port"]
# --- ALARMY CUKRU (mg/dL) ---
ALARM_HIPER = SETTINGS["alarm_hiper"]   # powyżej = hiperglikemia (czerwony + dźwięk)
ALARM_HIPO = SETTINGS["alarm_hipo"]     # poniżej = hipoglikemia (niebieski + dźwięk)
BLINK_MS = SETTINGS["blink_ms"]         # co ile ms zmiana koloru przy mruganiu
ALARM_SOUND_MS = SETTINGS["sound_ms"]

# Prefiks sieci do skanowania
SUBNET_PREFIX = SETTINGS["subnet_prefix"]


class JugglucoCommander:
    def __init__(self, root):
        self.root = root
        self.root.title("Juggluco Commander")
        self.root.geometry("380x650")
        self.default_bg = "#121212"
        self.root.configure(bg=self.default_bg)
        self.root.attributes("-topmost", SETTINGS["always_on_top"])

        self.current_ip = DEFAULT_IP
        self.last_update = 0
        self.last_val = None
        self.current_blink_ms = BLINK_MS
        self.current_sound_ms = ALARM_SOUND_MS
        self.current_speech_rate = 150
        self._blink_job = None
        self._blink_bg_colors = None
        self._blink_fg_colors = None
        self._blink_idx = 0
        self._alarm_type = None
        self._alarm_sound_job = None
        self._steady_alarm_fg = None
        self._alarm_silenced = False
        self._notified_alarm_type = None
        self._spoken_alarm_type = None
        self._notify_available = shutil.which("notify-send") is not None
        self._speak_lock = threading.Lock()
        self._last_tts_time = 0.0  # throttle: max raz na minutę
        self._last_periodic_speak_time = 0.0  # gadanie co 5 minut
        self.speak_each_reading = SETTINGS["speak_each_read"]
        self.day_profile = self._build_profile("day")
        self.night_profile = self._build_profile("night")

        self.history = []
        self.history_times = []
        self._forecast_horizons = (15, 30)
        self._forecast_models = self._init_forecast_models()
        self._tod_drift = {15: {}, 30: {}}
        self._pending_forecasts = []
        self._last_state_save_ts = 0.0
        self._speech_voice_name = "default"
        self.engine = None
        if pyttsx3 is not None and SETTINGS["speech_enabled"]:
            try:
                self.engine = pyttsx3.init()
                self.engine.setProperty("rate", 150)
                self._prefer_speech_voice(SETTINGS["speech_lang"])
            except Exception:
                self.engine = None

        # --- GŁÓWNY WIDOK (tkinter) ---
        self.frame_main = tk.Frame(root, bg=self.default_bg)
        self.frame_main.pack(pady=10)

        self.lbl_glucose = tk.Label(self.frame_main, text="---", font=("Arial", 90, "bold"), fg="#555", bg=self.default_bg)
        self.lbl_glucose.pack()
        self.lbl_arrow = tk.Label(self.frame_main, text="", font=("Arial", 30), fg="white", bg=self.default_bg)
        self.lbl_arrow.pack()
        self.lbl_delta = tk.Label(self.frame_main, text="", font=("Arial", 14), fg="gray", bg=self.default_bg)
        self.lbl_delta.pack()

        self.lbl_status = tk.Label(root, text=f"Celuję w: {self.current_ip}", font=("Consolas", 9), fg="gray", bg=self.default_bg)
        self.lbl_status.pack(pady=5)

        self.btn_dismiss_alarm = tk.Button(root, text="🔕 Kasuj alarm", bg="#442200", fg="#ffaa00",
                                           font=("Arial", 11, "bold"), relief="flat",
                                           command=self.dismiss_alarm)
        self.btn_dismiss_alarm.pack(pady=6)
        self.var_ontop = tk.BooleanVar(value=SETTINGS["always_on_top"])
        self.cb_top = tk.Checkbutton(root, text="Zawsze na wierzchu", variable=self.var_ontop,
                                    bg=self.default_bg, fg="white", selectcolor="#333",
                                    activebackground=self.default_bg, activeforeground="white",
                                    command=self.toggle_topmost)
        self.cb_top.pack(pady=5)
        self.btn_speak_reads = tk.Button(root, text="🗣️ Gadanie co 5 min: OFF", bg="#1d2d1d", fg="#a8f0a8",
                                        font=("Arial", 10, "bold"), relief="flat", command=self.toggle_speak_each_reading)
        self._update_speak_read_btn_text()
        self.btn_speak_reads.pack(pady=5, fill="x", padx=10)

        self.lbl_menu = tk.Label(root, text="--- STATYSTYKI I DANE ---", font=("Arial", 8, "bold"), fg="#444", bg=self.default_bg)
        self.lbl_menu.pack(pady=(15, 5))

        self.frame_btns = tk.Frame(root, bg=self.default_bg)
        self.frame_btns.pack(fill="both", padx=10, pady=5)
        buttons_config = [
            ("📈 Wykres (Curve)", "/x/curve"),
            ("📋 Raport AGP", "/x/report"),
            ("📊 Statystyki", "/x/stats"),
            ("📉 Wykres Zbiorczy", "/x/summarygraph"),
            ("📜 Historia", "/x/history"),
            ("📡 Strumień (Stream)", "/x/stream"),
            ("💉 Ilości/Insulina", "/x/amounts"),
            ("🍽️ Posiłki (Meals)", "/x/meals"),
            ("🔍 Skanowania", "/x/scans"),
        ]
        for i, (text, endpoint) in enumerate(buttons_config):
            btn = tk.Button(self.frame_btns, text=text, bg="#2a2a2a", fg="white", font=("Arial", 10),
                            relief="flat", command=lambda ep=endpoint: self.open_browser(ep))
            btn.grid(row=i // 2, column=i % 2, sticky="nsew", padx=3, pady=3)
        self.frame_btns.columnconfigure(0, weight=1)
        self.frame_btns.columnconfigure(1, weight=1)

        self.frame_forecast = tk.Frame(root, bg=self.default_bg)
        self.frame_forecast.pack(fill="x", padx=10, pady=(2, 6))
        self.lbl_forecast15 = tk.Label(self.frame_forecast, text="trend 15m: --", anchor="w",
                                       font=("Arial", 9), fg="#6e6e6e", bg=self.default_bg)
        self.lbl_forecast15.pack(fill="x")
        self.lbl_forecast30 = tk.Label(self.frame_forecast, text="trend 30m: --", anchor="w",
                                       font=("Arial", 9), fg="#6e6e6e", bg=self.default_bg)
        self.lbl_forecast30.pack(fill="x")

        self.btn_scan = tk.Button(root, text="🔎 Wymuś szukanie telefonu", bg="#004400", fg="#0f0",
                                 command=lambda: threading.Thread(target=self.force_scan, daemon=True).start())
        self.btn_scan.pack(fill="x", padx=10, pady=15)

        self._bg_widgets = [
            self.root, self.frame_main, self.lbl_glucose, self.lbl_arrow, self.lbl_delta,
            self.lbl_status, self.lbl_menu, self.frame_btns, self.frame_forecast,
            self.lbl_forecast15, self.lbl_forecast30, self.cb_top,
        ]

        # Kanwa z kropkami przy stracie kontaktu (po 1 min → po 10 min żółto)
        self._disconnect_since = None  # timestamp pierwszego braku kontaktu
        self._dots_canvas = tk.Canvas(
            root, bg=self.default_bg, highlightthickness=0,
            width=340, height=220,
        )
        self._dots_canvas.place_forget()
        self._dots_positions = []  # lista (x, y) losowych kropek

        # Efekt startowy: zamazany ekran, potem zamazanie znika, zostają liczby
        self._startup_overlay = tk.Frame(root, bg="#c8c8c8", highlightthickness=0)
        self._startup_overlay.place(in_=self.frame_main, x=0, y=0, relwidth=1, relheight=1)

        self._load_history_csv(days=21)
        self._load_forecast_state()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        threading.Thread(target=self.logic_loop, daemon=True).start()
        self.root.after(300, self._start_fade_in)

    def _start_fade_in(self):
        """Efekt startowy: zamazanie (jasny overlay) znika, zostają liczby."""
        overlay = getattr(self, "_startup_overlay", None)
        if overlay is None:
            return
        # Kroki od jasnego (#c8c8c8) do tła (#121212)
        steps = [
            "#c8c8c8", "#b0b0b0", "#989898", "#808080", "#686868",
            "#505050", "#404040", "#303030", "#252525", "#1a1a1a", self.default_bg,
        ]
        step_idx = [0]

        def next_step():
            if step_idx[0] >= len(steps):
                overlay.place_forget()
                return
            overlay.config(bg=steps[step_idx[0]])
            step_idx[0] += 1
            self.root.after(55, next_step)

        next_step()

    def open_browser(self, endpoint):
        """Otwiera URL w przeglądarce (Firefox/Chromium), nie przez xdg-open (R/postfix)."""
        if not self.current_ip:
            return
        url = f"http://{self.current_ip}:{PORT}{endpoint}"
        for name in ("firefox", "chromium", "chromium-browser", "google-chrome", "brave-browser"):
            path = shutil.which(name)
            if path:
                try:
                    subprocess.Popen([path, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    print(f"Otwieram: {url}")
                    return
                except Exception:
                    pass
        try:
            webbrowser.open(url)
            print(f"Otwieram: {url}")
        except Exception:
            pass

    def toggle_topmost(self):
        """Przełącza tryb 'zawsze na wierzchu'."""
        self.root.attributes("-topmost", self.var_ontop.get())

    def _update_speak_read_btn_text(self):
        """Aktualizuje etykietę przycisku: gadanie co 5 min (tylko to)."""
        state = "ON" if self.speak_each_reading else "OFF"
        self.btn_speak_reads.config(text=f"🗣️ Gadanie co 5 min: {state}")

    def toggle_speak_each_reading(self):
        """Włącza/wyłącza mówienie każdego odczytu."""
        self.speak_each_reading = not self.speak_each_reading
        self._update_speak_read_btn_text()
        if self.speak_each_reading:
            self.speak_value("Włączono gadanie co 5 minut")
        else:
            self.speak_value("Wyłączono gadanie")

    def send_linux_notify(self, title, message, urgency="normal"):
        """Wysyła dymek systemowy (Linux notify-send)."""
        if not self._notify_available:
            return
        try:
            subprocess.Popen(
                ["notify-send", title, message, "-u", urgency],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception:
            pass

    def speak_value(self, text, force_interval=False):
        """Czyta tekst lektorem (edge-tts – kobiecy głos, max raz na minutę) w osobnym wątku.
        force_interval=True pomija limit 60 s (np. dla gadania co 5 min)."""
        now = time.time()
        if not force_interval and (now - self._last_tts_time < TTS_MIN_INTERVAL_SEC):
            return
        if not _HAS_EDGE_TTS and self.engine is None:
            return
        threading.Thread(target=self._speak_thread, args=(text, force_interval), daemon=True).start()

    def _prefer_speech_voice(self, lang_code="pl"):
        """Wybiera głos pyttsx3 po języku (fallback gdy brak edge-tts)."""
        if self.engine is None:
            return
        wanted = (lang_code or "pl").lower()
        try:
            voices = self.engine.getProperty("voices") or []
        except Exception:
            return
        best_voice = None
        for voice in voices:
            voice_id = str(getattr(voice, "id", "")).lower()
            voice_name = str(getattr(voice, "name", "")).lower()
            raw_langs = getattr(voice, "languages", None) or []
            langs = []
            for lang in raw_langs:
                if isinstance(lang, bytes):
                    langs.append(lang.decode("utf-8", "ignore").lower())
                else:
                    langs.append(str(lang).lower())
            lang_match = any(wanted in lang for lang in langs)
            name_match = wanted in voice_name or ("pol" in voice_name and wanted == "pl")
            id_match = wanted in voice_id or ("pol" in voice_id and wanted == "pl")
            if lang_match or name_match or id_match:
                best_voice = voice
                break
        if best_voice is not None:
            try:
                self.engine.setProperty("voice", best_voice.id)
                self._speech_voice_name = str(getattr(best_voice, "name", best_voice.id))
                print(f"[TTS] Fallback pyttsx3: {self._speech_voice_name}")
            except Exception:
                pass

    def _edge_tts_speak_async(self, text, path):
        """Generuje mowę edge-tts do pliku (async)."""
        communicate = edge_tts.Communicate(text, _EDGE_VOICE)
        asyncio.run(communicate.save(path))

    def _speak_thread(self, text, force_interval=False):
        """Odtwarza TTS: najpierw edge-tts (Zofia), potem fallback pyttsx3. Limit: raz na minutę (chyba że force_interval)."""
        try:
            with self._speak_lock:
                now = time.time()
                if not force_interval and (now - self._last_tts_time < TTS_MIN_INTERVAL_SEC):
                    return
                done = False
                if _HAS_EDGE_TTS:
                    try:
                        fd, path = tempfile.mkstemp(suffix=".mp3")
                        os.close(fd)
                        self._edge_tts_speak_async(text, path)
                        if os.path.exists(path):
                            if _play_mp3(path):
                                done = True
                        try:
                            os.unlink(path)
                        except Exception:
                            pass
                    except Exception:
                        pass
                if not done and self.engine is not None:
                    try:
                        self.engine.say(text)
                        self.engine.runAndWait()
                        done = True
                    except Exception:
                        pass
                if done:
                    self._last_tts_time = time.time()
        except Exception:
            pass

    def _send_alarm_alerts(self, alarm_type, val):
        """Jednorazowe powiadomienia po wejściu w alarm."""
        if self._notified_alarm_type != alarm_type:
            if alarm_type == "hiper":
                self.send_linux_notify("HIPERGLIKEMIA!", f"Cukier: {val} mg/dL", "critical")
            else:
                self.send_linux_notify("HIPOGLIKEMIA!", f"Cukier: {val} mg/dL", "critical")
            self._notified_alarm_type = alarm_type

        if (not self.speak_each_reading) and (not self._alarm_silenced) and self._spoken_alarm_type != alarm_type:
            if alarm_type == "hiper":
                self.speak_value(f"Uwaga, wysoki cukier. {val}")
            else:
                self.speak_value(f"Uwaga, niski cukier. {val}")
            self._spoken_alarm_type = alarm_type

    def _parse_hhmm_to_minutes(self, value, fallback):
        try:
            h, m = str(value).strip().split(":")
            h = int(h) % 24
            m = int(m) % 60
            return h * 60 + m
        except Exception:
            return fallback

    def _build_profile(self, name):
        prefix = name.lower()
        if prefix == "night":
            start = self._parse_hhmm_to_minutes(SETTINGS["night_start"], 22 * 60)
            end = self._parse_hhmm_to_minutes(SETTINGS["night_end"], 7 * 60)
            return {
                "name": "night",
                "start_min": start,
                "end_min": end,
                "hiper": SETTINGS["night_hiper"],
                "hipo": SETTINGS["night_hipo"],
                "blink_ms": SETTINGS["night_blink_ms"],
                "sound_ms": SETTINGS["night_sound_ms"],
                "speech_rate": SETTINGS["night_speech_rate"],
            }
        start = self._parse_hhmm_to_minutes(SETTINGS["day_start"], 7 * 60)
        end = self._parse_hhmm_to_minutes(SETTINGS["day_end"], 22 * 60)
        return {
            "name": "day",
            "start_min": start,
            "end_min": end,
            "hiper": SETTINGS["day_hiper"],
            "hipo": SETTINGS["day_hipo"],
            "blink_ms": SETTINGS["day_blink_ms"],
            "sound_ms": SETTINGS["day_sound_ms"],
            "speech_rate": SETTINGS["day_speech_rate"],
        }

    def _time_in_range(self, minute_now, start_min, end_min):
        if start_min <= end_min:
            return start_min <= minute_now < end_min
        return minute_now >= start_min or minute_now < end_min

    def _get_active_profile(self, ts=None):
        now_ts = ts if ts is not None else time.time()
        dt = datetime.fromtimestamp(now_ts)
        minute_now = dt.hour * 60 + dt.minute
        if self._time_in_range(minute_now, self.night_profile["start_min"], self.night_profile["end_min"]):
            return self.night_profile
        return self.day_profile

    def _apply_profile_tuning(self, profile):
        self.current_blink_ms = profile["blink_ms"]
        self.current_sound_ms = profile["sound_ms"]
        if self.engine is not None and self.current_speech_rate != profile["speech_rate"]:
            try:
                self.engine.setProperty("rate", profile["speech_rate"])
                self.current_speech_rate = profile["speech_rate"]
            except Exception:
                pass

    def _init_forecast_models(self):
        base_weights = {"trend": 0.45, "analog": 0.40, "tod": 0.15}
        base_errors = {"trend": 18.0, "analog": 20.0, "tod": 24.0}
        models = {}
        for h in (15, 30):
            models[h] = {
                "weights": dict(base_weights),
                "errors": dict(base_errors),
            }
        return models

    def _load_history_csv(self, days=21):
        if not os.path.exists(HISTORY_CSV_PATH):
            return
        cutoff = time.time() - days * 24 * 3600
        try:
            with open(HISTORY_CSV_PATH, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        ts = float(row.get("ts", "0"))
                        val = int(row.get("val", "0"))
                    except Exception:
                        continue
                    if ts < cutoff:
                        continue
                    profile = row.get("profile", "day")
                    self.history.append({"ts": ts, "val": val, "profile": profile})
                    self.history_times.append(ts)
        except Exception:
            pass

    def _append_history_csv(self, ts, val, profile_name):
        file_exists = os.path.exists(HISTORY_CSV_PATH)
        try:
            with open(HISTORY_CSV_PATH, "a", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(["ts", "val", "profile"])
                writer.writerow([f"{ts:.3f}", int(val), profile_name])
        except Exception:
            pass

    def _append_history_point(self, ts, val, profile_name):
        if self.history:
            last = self.history[-1]
            if abs(ts - last["ts"]) < 55 and int(val) == int(last["val"]):
                return False
        self.history.append({"ts": ts, "val": int(val), "profile": profile_name})
        self.history_times.append(ts)
        self._append_history_csv(ts, val, profile_name)
        self._trim_history(max_days=21)
        return True

    def _trim_history(self, max_days=21):
        if not self.history:
            return
        cutoff = self.history[-1]["ts"] - max_days * 24 * 3600
        trim_count = 0
        for item in self.history:
            if item["ts"] < cutoff:
                trim_count += 1
            else:
                break
        if trim_count > 0:
            self.history = self.history[trim_count:]
            self.history_times = self.history_times[trim_count:]

    def _load_forecast_state(self):
        if not os.path.exists(FORECAST_STATE_PATH):
            return
        try:
            with open(FORECAST_STATE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for h in self._forecast_horizons:
                key = str(h)
                if key not in data:
                    continue
                node = data[key]
                if "weights" in node:
                    for name in ("trend", "analog", "tod"):
                        if name in node["weights"]:
                            self._forecast_models[h]["weights"][name] = float(node["weights"][name])
                if "errors" in node:
                    for name in ("trend", "analog", "tod"):
                        if name in node["errors"]:
                            self._forecast_models[h]["errors"][name] = float(node["errors"][name])
                if "tod_drift" in node and isinstance(node["tod_drift"], dict):
                    loaded = {}
                    for k, v in node["tod_drift"].items():
                        try:
                            loaded[int(k)] = float(v)
                        except Exception:
                            pass
                    self._tod_drift[h] = loaded
        except Exception:
            pass

    def _save_forecast_state(self, force=False):
        now = time.time()
        if (not force) and (now - self._last_state_save_ts < 120):
            return
        payload = {}
        for h in self._forecast_horizons:
            payload[str(h)] = {
                "weights": self._forecast_models[h]["weights"],
                "errors": self._forecast_models[h]["errors"],
                "tod_drift": {str(k): v for k, v in self._tod_drift[h].items()},
            }
        try:
            with open(FORECAST_STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=True, indent=2)
            self._last_state_save_ts = now
        except Exception:
            pass

    def _slot_index(self, ts, slot_minutes=30):
        dt = datetime.fromtimestamp(ts)
        return (dt.hour * 60 + dt.minute) // slot_minutes

    def _value_at_timestamp(self, ts):
        if not self.history:
            return None
        idx = bisect_left(self.history_times, ts)
        if idx <= 0:
            return float(self.history[0]["val"])
        if idx >= len(self.history):
            return float(self.history[-1]["val"])
        left = self.history[idx - 1]
        right = self.history[idx]
        t1 = left["ts"]
        t2 = right["ts"]
        if t2 <= t1:
            return float(left["val"])
        ratio = (ts - t1) / (t2 - t1)
        return float(left["val"] + (right["val"] - left["val"]) * ratio)

    def _window_points(self, end_ts, window_min):
        start_ts = end_ts - window_min * 60.0
        points = [p for p in self.history if start_ts <= p["ts"] <= end_ts]
        if len(points) < 3:
            return None
        return points

    def _slope_in_window(self, end_ts, window_min):
        points = self._window_points(end_ts, window_min)
        if not points:
            return None
        x0 = points[0]["ts"]
        sum_w = sum_x = sum_y = sum_xx = sum_xy = 0.0
        duration = max(1.0, points[-1]["ts"] - x0)
        for p in points:
            x = (p["ts"] - x0) / 60.0
            y = float(p["val"])
            w = 0.6 + 0.4 * ((p["ts"] - x0) / duration)
            sum_w += w
            sum_x += w * x
            sum_y += w * y
            sum_xx += w * x * x
            sum_xy += w * x * y
        denom = (sum_w * sum_xx - sum_x * sum_x)
        if abs(denom) < 1e-9:
            return None
        return (sum_w * sum_xy - sum_x * sum_y) / denom

    def _recent_volatility(self, end_ts, window_min=30):
        points = self._window_points(end_ts, window_min)
        if not points or len(points) < 4:
            return 0.0
        jumps = []
        for i in range(1, len(points)):
            dt_min = (points[i]["ts"] - points[i - 1]["ts"]) / 60.0
            if dt_min <= 0:
                continue
            dv = abs(points[i]["val"] - points[i - 1]["val"]) / dt_min
            jumps.append(dv)
        if not jumps:
            return 0.0
        jumps.sort()
        mid = len(jumps) // 2
        return jumps[mid]

    def _pattern_signature(self, center_ts, lookback_min=30, step_min=5):
        sampled = []
        for m in range(lookback_min, -1, -step_min):
            v = self._value_at_timestamp(center_ts - m * 60.0)
            if v is None:
                return None
            sampled.append(float(v))
        if len(sampled) < 4:
            return None
        deltas = [sampled[i + 1] - sampled[i] for i in range(len(sampled) - 1)]
        scale = max(1.0, max(abs(d) for d in deltas))
        return [d / scale for d in deltas]

    def _predict_trend_expert(self, now_ts, val, horizon_min):
        slope_short = self._slope_in_window(now_ts, 12)
        slope_long = self._slope_in_window(now_ts, 35)
        if slope_short is None and slope_long is None:
            return None
        if slope_short is None:
            slope_short = slope_long
        if slope_long is None:
            slope_long = slope_short
        accel = slope_short - slope_long
        vol = self._recent_volatility(now_ts, 30)
        damping = max(0.40, 1.0 - min(vol / 22.0, 0.55))
        projected_delta = (slope_short * horizon_min + 0.35 * accel * horizon_min) * damping
        return max(40.0, min(420.0, float(val) + projected_delta))

    def _predict_analog_expert(self, now_ts, val, horizon_min, profile_name):
        now_pattern = self._pattern_signature(now_ts, lookback_min=30, step_min=5)
        if now_pattern is None:
            return None

        def build_candidates(require_same_profile):
            cands = []
            min_ts = now_ts - 21 * 24 * 3600
            max_anchor = now_ts - horizon_min * 60.0 - 60.0
            step = 6
            for idx in range(len(self.history) - 1, -1, -step):
                p = self.history[idx]
                t_anchor = p["ts"]
                if t_anchor < min_ts:
                    break
                if t_anchor > max_anchor:
                    continue
                if require_same_profile and p.get("profile") != profile_name:
                    continue
                pattern = self._pattern_signature(t_anchor, lookback_min=30, step_min=5)
                if pattern is None or len(pattern) != len(now_pattern):
                    continue
                base = self._value_at_timestamp(t_anchor)
                future = self._value_at_timestamp(t_anchor + horizon_min * 60.0)
                if base is None or future is None:
                    continue
                dist = 0.0
                for a, b in zip(pattern, now_pattern):
                    d = a - b
                    dist += d * d
                cands.append((dist, future - base))
                if len(cands) >= 80:
                    break
            return cands

        candidates = build_candidates(require_same_profile=True)
        if len(candidates) < 5:
            candidates = build_candidates(require_same_profile=False)
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0])
        top = candidates[:6]
        if top and top[0][0] > 6.0:
            return None
        w_sum = 0.0
        d_sum = 0.0
        for dist, delta in top:
            w = 1.0 / (0.25 + dist)
            w_sum += w
            d_sum += w * delta
        if w_sum <= 0:
            return None
        return max(40.0, min(420.0, float(val) + d_sum / w_sum))

    def _predict_tod_expert(self, now_ts, val, horizon_min):
        slot = self._slot_index(now_ts, slot_minutes=30)
        drift = self._tod_drift[horizon_min].get(slot, 0.0)
        return max(40.0, min(420.0, float(val) + drift))

    def _combine_forecast(self, horizon_min, preds):
        model = self._forecast_models[horizon_min]
        weights = model["weights"]
        available = {}
        for name, pred in preds.items():
            if pred is None:
                continue
            available[name] = pred
        if not available:
            return None, "niska"
        w_sum = 0.0
        p_sum = 0.0
        for name, pred in available.items():
            w = weights.get(name, 0.0)
            w_sum += w
            p_sum += w * pred
        if w_sum <= 0:
            return None, "niska"
        final = p_sum / w_sum

        vals = sorted(available.values())
        spread = vals[-1] - vals[0] if len(vals) > 1 else 0.0
        avg_err = 0.0
        for name in available:
            avg_err += model["errors"].get(name, 20.0)
        avg_err /= len(available)
        if spread < 10 and avg_err < 12:
            conf = "wysoka"
        elif spread < 20 and avg_err < 18:
            conf = "srednia"
        else:
            conf = "niska"
        return max(40.0, min(420.0, final)), conf

    def _update_forecast_learning(self, now_ts, actual_val):
        if not self._pending_forecasts:
            return
        still_pending = []
        changed = False
        for item in self._pending_forecasts:
            if now_ts < item["due_ts"]:
                still_pending.append(item)
                continue
            changed = True
            horizon = item["horizon"]
            model = self._forecast_models[horizon]
            due_actual = self._value_at_timestamp(item["due_ts"])
            if due_actual is None:
                due_actual = float(actual_val)
            for name, pred in item["experts"].items():
                if pred is None:
                    continue
                old_err = model["errors"].get(name, 20.0)
                err = abs(due_actual - pred)
                model["errors"][name] = 0.90 * old_err + 0.10 * err

            inv = {}
            for name in ("trend", "analog", "tod"):
                e = model["errors"].get(name, 20.0)
                inv[name] = 1.0 / (2.5 + e)
            total = sum(inv.values())
            if total > 0:
                for name in inv:
                    model["weights"][name] = inv[name] / total

            slot = item["slot"]
            realized_delta = due_actual - item["base_val"]
            old_drift = self._tod_drift[horizon].get(slot, 0.0)
            self._tod_drift[horizon][slot] = 0.92 * old_drift + 0.08 * realized_delta
        self._pending_forecasts = still_pending
        if changed:
            self._save_forecast_state(force=False)

    def _update_forecast_labels(self, forecasts, profile):
        f15 = forecasts.get(15)
        f30 = forecasts.get(30)
        text15 = "trend 15m: --"
        text30 = "trend 30m: --"
        if f15 and f15["final"] is not None:
            text15 = f"trend 15m: ~{int(round(f15['final']))} ({f15['conf']})"
        if f30 and f30["final"] is not None:
            text30 = f"trend 30m: ~{int(round(f30['final']))} ({f30['conf']})"

        fg = "#6e6e6e"
        danger = False
        for f in (f15, f30):
            if not f or f["final"] is None:
                continue
            if f["final"] <= profile["hipo"] or f["final"] >= profile["hiper"]:
                danger = True
                break
        if danger:
            fg = "#8c7676"
        self.lbl_forecast15.config(text=text15, fg=fg)
        self.lbl_forecast30.config(text=text30, fg=fg)

    def _compute_forecasts(self, now_ts, val, profile_name):
        result = {}
        for h in self._forecast_horizons:
            preds = {
                "trend": self._predict_trend_expert(now_ts, val, h),
                "analog": self._predict_analog_expert(now_ts, val, h, profile_name),
                "tod": self._predict_tod_expert(now_ts, val, h),
            }
            final, conf = self._combine_forecast(h, preds)
            result[h] = {"final": final, "conf": conf, "experts": preds}
        return result

    def _queue_forecast_targets(self, now_ts, base_val, forecasts):
        slot = self._slot_index(now_ts, slot_minutes=30)
        for h in self._forecast_horizons:
            pack = forecasts.get(h)
            if not pack:
                continue
            self._pending_forecasts.append(
                {
                    "created_ts": now_ts,
                    "due_ts": now_ts + h * 60.0,
                    "horizon": h,
                    "slot": slot,
                    "base_val": float(base_val),
                    "experts": pack["experts"],
                }
            )

    def on_close(self):
        """Zamyka aplikację z zapisem stanu."""
        self._save_forecast_state(force=True)
        self.root.destroy()

    def check_ip(self, ip_suffix):
        """Sprawdza jeden adres IP"""
        target = f"{SUBNET_PREFIX}{ip_suffix}"
        url = f"http://{target}:{PORT}/sgv.json?count=1"
        try:
            # Bardzo krótki timeout (0.4s) dla szybkiego skanu
            resp = requests.get(url, timeout=0.4)
            if resp.status_code == 200:
                return target
        except:
            pass
        return None

    def scan_network(self):
        """Skanuje sieć 192.168.2.1-254"""
        self.root.after(0, lambda: self.lbl_status.config(text="🔍 Skanuję sieć WiFi...", fg="#ff8800"))
        
        found_ip = None
        # 60 wątków na raz - przeskanuje sieć w sekundę
        with concurrent.futures.ThreadPoolExecutor(max_workers=60) as executor:
            futures = {executor.submit(self.check_ip, i): i for i in range(1, 255)}
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result:
                    found_ip = result
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
        return found_ip

    def get_glucose_data(self, ip):
        """Pobiera dane JSON"""
        try:
            url = f"http://{ip}:{PORT}/sgv.json?count=1"
            resp = requests.get(url, timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                if len(data) > 0:
                    raw_val = data[0].get('sgv')
                    val = int(raw_val) if raw_val is not None else None
                    direction = data[0].get('direction', '')
                    return val, direction
        except:
            return None, None
        return None, None

    def force_scan(self):
        """Ręczne wymuszenie skanowania"""
        new_ip = self.scan_network()
        if new_ip:
            self.current_ip = new_ip
            self.logic_loop_step(force=True)

    def logic_loop(self):
        """Główna pętla w tle"""
        while True:
            self.logic_loop_step()
            time.sleep(10) # Odświeżanie co 10 sekund

    def _update_disconnect_dots(self):
        """Po 1 min bez kontaktu: wstawia losowe żółte kropki; po 10 min całość żółta. Wywoływane z wątku GUI."""
        if self._disconnect_since is None:
            self._dots_canvas.place_forget()
            self._dots_canvas.delete("all")
            self._dots_positions.clear()
            return
        now = time.time()
        elapsed = now - self._disconnect_since
        if elapsed < 60:
            self._dots_canvas.place_forget()
            self._dots_canvas.delete("all")
            self._dots_positions.clear()
            return
        # Od 1 min do 11 min: 0 → 1
        progress = min(1.0, (elapsed - 60) / 600.0)
        w = self._dots_canvas.winfo_reqwidth()
        h = self._dots_canvas.winfo_reqheight()
        if w <= 1:
            w, h = 340, 220
        target_count = int(progress * 550)
        r = 10
        while len(self._dots_positions) < target_count:
            x = random.uniform(r, max(r, w - r - 1))
            y = random.uniform(r, max(r, h - r - 1))
            self._dots_positions.append((x, y))
        self._dots_canvas.place(in_=self.frame_main, x=0, y=0, relwidth=1, relheight=1)
        self._dots_canvas.delete("all")
        for (x, y) in self._dots_positions:
            self._dots_canvas.create_oval(x - r, y - r, x + r, y + r, fill="#DDDD00", outline="#AAAA00")

    def logic_loop_step(self, force=False):
        # 1. Próba pobrania ze znanego IP
        val, direction = self.get_glucose_data(self.current_ip)

        if val:
            # SUKCES – zeruj stan rozłączenia i kropki
            self._disconnect_since = None
            self.root.after(0, self._update_disconnect_dots)
            arrow = self.parse_arrow(direction)
            self.root.after(0, lambda v=val, a=arrow: self.update_gui_success(v, a))
        else:
            # PORAŻKA - zapamiętaj czas rozłączenia, potem skanuj
            if self._disconnect_since is None:
                self._disconnect_since = time.time()
            self.root.after(0, lambda: self.lbl_status.config(text=f"Brak kontaktu z {self.current_ip}", fg="red"))
            self.root.after(0, lambda: self.lbl_glucose.config(fg="#333"))
            self.root.after(0, self._update_disconnect_dots)

            new_ip = self.scan_network()

            if new_ip:
                self.current_ip = new_ip
                val, direction = self.get_glucose_data(self.current_ip)
                if val:
                    self._disconnect_since = None
                    self.root.after(0, self._update_disconnect_dots)
                    arrow = self.parse_arrow(direction)
                    self.root.after(0, lambda v=val, a=arrow: self.update_gui_success(v, a))
            else:
                self.root.after(0, lambda: self.lbl_status.config(text="❌ Telefon nieosiągalny", fg="red"))
                self.root.after(0, self._update_disconnect_dots)

    def parse_arrow(self, direction):
        # Kierunki jako znaki ASCII, żeby nigdy nie pokazywało się ® (brak glifu Unicode w czcionce)
        if direction == "Flat": return "="
        if "SingleUp" in direction: return "^"
        if "DoubleUp" in direction: return "^^"
        if "FortyFiveUp" in direction: return "/^"
        if "SingleDown" in direction: return "v"
        if "DoubleDown" in direction: return "vv"
        if "FortyFiveDown" in direction: return "\\v"
        return ""

    def _stop_blink(self):
        """Wyłącza mruganie poziomu cukru."""
        if self._blink_job:
            self.root.after_cancel(self._blink_job)
            self._blink_job = None
        self._blink_bg_colors = None
        self._blink_fg_colors = None
        self._alarm_type = None

    def _stop_alarm_sound(self):
        """Zatrzymuje ciągły dźwięk alarmu."""
        if self._alarm_sound_job:
            self.root.after_cancel(self._alarm_sound_job)
            self._alarm_sound_job = None

    def _set_background(self, color):
        """Ustawia wspólne tło dla głównych elementów."""
        for w in self._bg_widgets:
            w.config(bg=color)

    def _reset_normal_visuals(self):
        """Przywraca normalny wygląd (bez alarmu)."""
        self._set_background(self.default_bg)
        self.lbl_arrow.config(fg="white")

    def _apply_blink_visuals(self):
        """Stosuje bieżący krok migania tłem + odwrócony kolor tekstu."""
        if self._blink_bg_colors is None or self._blink_fg_colors is None:
            return
        bg = self._blink_bg_colors[self._blink_idx]
        fg = self._blink_fg_colors[1 - self._blink_idx]
        self._set_background(bg)
        self.lbl_glucose.config(fg=fg)
        self.lbl_arrow.config(fg=fg)
        self.lbl_delta.config(fg=fg)

    def _do_blink_step(self):
        """Jedno mignięcie w ramach alarmu (przełącza kolor)."""
        if self._blink_bg_colors is None:
            return
        self._blink_idx = 1 - self._blink_idx
        self._apply_blink_visuals()
        self._blink_job = self.root.after(self.current_blink_ms, self._do_blink_step)

    def _start_blink(self, is_hiper):
        """Uruchamia mruganie tłem: czerwony przy hiper, niebieski przy hipo."""
        alarm_type = "hiper" if is_hiper else "hipo"
        if self._blink_job and self._alarm_type == alarm_type:
            return
        self._stop_blink()
        self._alarm_type = alarm_type
        if is_hiper:
            self._steady_alarm_fg = "#FF2222"
            self._blink_bg_colors = ("#660000", "#FF2222")
            self._blink_fg_colors = ("#FFD0D0", "#330000")
        else:
            self._steady_alarm_fg = "#2288FF"
            self._blink_bg_colors = ("#002266", "#2288FF")
            self._blink_fg_colors = ("#CFE6FF", "#001533")
        self._blink_idx = 0
        self._apply_blink_visuals()
        self._blink_job = self.root.after(self.current_blink_ms, self._do_blink_step)

    def _play_alarm_sound(self):
        """Odtwarza alarm w pętli, dopóki alarm trwa i nie jest skasowany."""
        if self._alarm_sound_job is not None or self._alarm_silenced:
            return

        def beep():
            if self._alarm_silenced or self._alarm_type is None:
                self._stop_alarm_sound()
                return
            if _HAS_SOUNDDEVICE:
                _play_beep_sound()
            else:
                self.root.bell()
            self._alarm_sound_job = self.root.after(self.current_sound_ms, beep)
        beep()

    def dismiss_alarm(self):
        """Kasuje alarm: wyłącza mruganie i dźwięk, poziom w stałym kolorze (czerwony/niebieski)."""
        self._alarm_silenced = True
        steady = self._steady_alarm_fg
        self._stop_alarm_sound()
        self._stop_blink()
        self._reset_normal_visuals()
        if steady:
            self.lbl_glucose.config(fg=steady)

    def update_gui_success(self, val, arrow):
        now_ts = time.time()
        self._disconnect_since = None
        self.root.after(0, self._update_disconnect_dots)
        profile = self._get_active_profile(now_ts)
        self._apply_profile_tuning(profile)

        added = self._append_history_point(now_ts, val, profile["name"])
        self._update_forecast_learning(now_ts, val)
        forecasts = self._compute_forecasts(now_ts, val, profile["name"])
        self._update_forecast_labels(forecasts, profile)
        if added:
            self._queue_forecast_targets(now_ts, val, forecasts)

        self.lbl_glucose.config(text=str(val))
        self.lbl_arrow.config(text=arrow)
        self.lbl_status.config(
            text=f"Połączono: {self.current_ip}\nprofil: {profile['name']}",
            fg="#00CC44",
        )

        if self.last_val is not None:
            diff = val - self.last_val
            sign = "+" if diff > 0 else ""
            delta_color = "#888" if abs(diff) < 10 else "#FFFFFF"
            self.lbl_delta.config(text=f"{sign}{diff} mg/dL", fg=delta_color)
        else:
            self.lbl_delta.config(text="")
        self.last_val = val

        # Głos ON = tylko co 5 minut (nigdy przy każdym odczycie)
        if self.speak_each_reading and (now_ts - self._last_periodic_speak_time >= 300):
            self.speak_value(f"Cukier {val}", force_interval=True)
            self._last_periodic_speak_time = now_ts

        if val >= profile["hiper"]:
            self._send_alarm_alerts("hiper", val)
            if self._alarm_silenced:
                self._stop_alarm_sound()
                self._stop_blink()
                self._reset_normal_visuals()
                self.lbl_glucose.config(fg="#FF2222")
            else:
                self._start_blink(is_hiper=True)
                self._play_alarm_sound()
        elif val <= profile["hipo"]:
            self._send_alarm_alerts("hipo", val)
            if self._alarm_silenced:
                self._stop_alarm_sound()
                self._stop_blink()
                self._reset_normal_visuals()
                self.lbl_glucose.config(fg="#2288FF")
            else:
                self._start_blink(is_hiper=False)
                self._play_alarm_sound()
        else:
            self._alarm_silenced = False  # wyjście z progu – następny alarm znów dzwoni
            self._notified_alarm_type = None
            self._spoken_alarm_type = None
            self._stop_alarm_sound()
            self._stop_blink()
            self._reset_normal_visuals()
            self.lbl_glucose.config(fg="#FFFF00")

def _minimize_terminal_window():
    """Minimalizuje okno terminala, z którego uruchomiono aplikację (Linux: wmctrl)."""
    try:
        ppid = os.getppid()
        result = subprocess.run(
            ["wmctrl", "-l", "-p"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode != 0:
            return
        for line in result.stdout.strip().splitlines():
            parts = line.split(None, 3)
            if len(parts) < 4:
                continue
            wid, _pid, _host, title = parts[0], parts[1], parts[2], parts[3]
            try:
                if int(_pid) == ppid:
                    subprocess.run(
                        ["wmctrl", "-ir", wid, "-b", "add,hidden"],
                        capture_output=True,
                        timeout=1,
                    )
                    break
            except ValueError:
                continue
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass


if __name__ == "__main__":
    root = tk.Tk()
    app = JugglucoCommander(root)
    root.after(400, _minimize_terminal_window)  # po chwili minimalizuj terminal
    root.mainloop()
