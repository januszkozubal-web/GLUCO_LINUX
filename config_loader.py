# -*- coding: utf-8 -*-
"""Wspólna konfiguracja INI — ścieżka względem katalogu nadrzędnego (monitor-boost-github)."""

from __future__ import annotations

import configparser
import os
from typing import Any, Dict

_PARENT = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(_PARENT, "..", "settings.ini")
HISTORY_CSV_PATH = os.path.join(_PARENT, "..", "glucose_history.csv")
FORECAST_STATE_PATH = os.path.join(_PARENT, "..", "forecast_state.json")


def load_settings(path: str) -> Dict[str, Any]:
    defaults = {
        "NETWORK": {
            "IP": "192.168.1.100",
            "Port": "17580",
            "SubnetPrefix": "192.168.1.",
        },
        "ALARM": {
            "Hiper": "180",
            "Hipo": "70",
            "BlinkMs": "600",
            "SoundMs": "850",
            "SpeechEnabled": "false",
            "SpeakEachRead": "false",
            "SpeechLang": "pl",
        },
        "DAY": {
            "Start": "07:00",
            "End": "22:00",
            "Hiper": "180",
            "Hipo": "70",
            "BlinkMs": "600",
            "SoundMs": "850",
            "SpeechRate": "150",
        },
        "NIGHT": {
            "Start": "22:00",
            "End": "07:00",
            "Hiper": "200",
            "Hipo": "80",
            "BlinkMs": "800",
            "SoundMs": "1100",
            "SpeechRate": "140",
        },
        "UI": {
            "AlwaysOnTop": "true",
        },
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
