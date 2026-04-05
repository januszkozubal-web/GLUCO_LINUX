# -*- coding: utf-8 -*-
"""
Logika odczytu Juggluco (bez tkinter) — współdzieli glucose_history.csv i forecast_state.json
z katalogiem nadrzędnym (ta sama ścieżka co wersja desktop).
"""

from __future__ import annotations

import concurrent.futures
import csv
import json
import os
import time
from bisect import bisect_left
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

from config_loader import (
    FORECAST_STATE_PATH,
    HISTORY_CSV_PATH,
    SETTINGS_PATH,
    load_settings,
)

SETTINGS = load_settings(SETTINGS_PATH)
# Tylko startowy odczyt — w Streamlit moduł żyje długo; port/IP z INI odświeża _refresh_network_settings()
PORT = SETTINGS["port"]
SSL_PORT = SETTINGS["ssl_port"]
SUBNET_PREFIX = SETTINGS["subnet_prefix"]


class StreamlitGlucoseMonitor:
    """Stan i logika zgodna z monitor_boost.JugglucoCommander (bez GUI)."""

    def __init__(self) -> None:
        self.current_ip = SETTINGS["default_ip"]
        self.last_val: Optional[int] = None
        self._disconnect_since: Optional[float] = None
        self._alarm_silenced = False
        self._notified_alarm_type: Optional[str] = None
        self._spoken_alarm_type: Optional[str] = None

        self.history: List[Dict[str, Any]] = []
        self.history_times: List[float] = []
        self._forecast_horizons = (15, 30)
        self._forecast_models = self._init_forecast_models()
        self._tod_drift: Dict[int, Dict[int, float]] = {15: {}, 30: {}}
        self._pending_forecasts: List[Dict[str, Any]] = []
        self._last_state_save_ts = 0.0

        self.day_profile = self._build_profile("day")
        self.night_profile = self._build_profile("night")

        self._load_history_csv(days=21)
        self._load_forecast_state()
        self._last_ini_ip: Optional[str] = None
        self._port = int(SETTINGS["port"])
        self._subnet_prefix = SETTINGS["subnet_prefix"]
        self._ssl_port = int(SETTINGS["ssl_port"])
        # Ręczne nadpisania z UI Streamlit (sesja) — mają pierwszeństwo nad odczytem z INI
        self._manual_ip: Optional[str] = None
        self._manual_subnet: Optional[str] = None
        self._manual_port: Optional[int] = None

    def set_manual_network(
        self,
        ip: Optional[str] = None,
        subnet: Optional[str] = None,
        port: Optional[int] = None,
    ) -> None:
        """Ustawia nadpisania na bieżącą sesję (np. IP 192.168.2.116 gdy INI ma jeszcze .1.)."""
        self._manual_ip = (ip or "").strip() or None
        self._manual_subnet = (subnet or "").strip() or None
        self._manual_port = port

    def clear_manual_network(self) -> None:
        self._manual_ip = None
        self._manual_subnet = None
        self._manual_port = None

    def has_manual_network_override(self) -> bool:
        return (
            self._manual_ip is not None
            or self._manual_subnet is not None
            or self._manual_port is not None
        )

    def _refresh_network_settings(self) -> None:
        """Za każdym tickiem — jak nowy start monitor_boost.py (INI może się zmienić bez restartu Streamlit)."""
        s = load_settings(SETTINGS_PATH)
        self._port = int(s["port"])
        self._subnet_prefix = s["subnet_prefix"]
        self._ssl_port = int(s["ssl_port"])
        ini_ip = s["default_ip"]

        if self._manual_port is not None:
            self._port = int(self._manual_port)
        if self._manual_subnet is not None:
            self._subnet_prefix = self._manual_subnet

        if self._manual_ip is not None:
            self.current_ip = self._manual_ip
            self._last_ini_ip = ini_ip
        else:
            if ini_ip != self._last_ini_ip:
                self.current_ip = ini_ip
                self._last_ini_ip = ini_ip

    # --- sieć ---
    def check_ip(self, ip_suffix: int) -> Optional[str]:
        target = f"{self._subnet_prefix}{ip_suffix}"
        url = f"http://{target}:{self._port}/sgv.json?count=1"
        try:
            resp = requests.get(url, timeout=0.4)
            if resp.status_code == 200:
                return target
        except Exception:
            pass
        return None

    def scan_network(self) -> Optional[str]:
        found_ip = None
        with concurrent.futures.ThreadPoolExecutor(max_workers=60) as executor:
            futures = {executor.submit(self.check_ip, i): i for i in range(1, 255)}
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result:
                    found_ip = result
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
        return found_ip

    def get_glucose_data(self, ip: str) -> Tuple[Optional[int], Optional[str]]:
        try:
            url = f"http://{ip}:{self._port}/sgv.json?count=1"
            resp = requests.get(url, timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                if len(data) > 0:
                    raw_val = data[0].get("sgv")
                    val = int(raw_val) if raw_val is not None else None
                    direction = data[0].get("direction", "")
                    return val, str(direction) if direction is not None else ""
        except Exception:
            return None, None
        return None, None

    @staticmethod
    def parse_arrow(direction: str) -> str:
        if direction == "Flat":
            return "="
        if "SingleUp" in direction:
            return "^"
        if "DoubleUp" in direction:
            return "^^"
        if "FortyFiveUp" in direction:
            return "/^"
        if "SingleDown" in direction:
            return "v"
        if "DoubleDown" in direction:
            return "vv"
        if "FortyFiveDown" in direction:
            return "\\v"
        return ""

    def _parse_hhmm_to_minutes(self, value: str, fallback: int) -> int:
        try:
            h, m = str(value).strip().split(":")
            h = int(h) % 24
            m = int(m) % 60
            return h * 60 + m
        except Exception:
            return fallback

    def _build_profile(self, name: str) -> Dict[str, Any]:
        if name.lower() == "night":
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

    @staticmethod
    def _time_in_range(minute_now: int, start_min: int, end_min: int) -> bool:
        if start_min <= end_min:
            return start_min <= minute_now < end_min
        return minute_now >= start_min or minute_now < end_min

    def _get_active_profile(self, ts: Optional[float] = None) -> Dict[str, Any]:
        now_ts = ts if ts is not None else time.time()
        dt = datetime.fromtimestamp(now_ts)
        minute_now = dt.hour * 60 + dt.minute
        if self._time_in_range(
            minute_now,
            self.night_profile["start_min"],
            self.night_profile["end_min"],
        ):
            return self.night_profile
        return self.day_profile

    # --- historia ---
    def _load_history_csv(self, days: int = 21) -> None:
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

    def _append_history_csv(self, ts: float, val: int, profile_name: str) -> None:
        file_exists = os.path.exists(HISTORY_CSV_PATH)
        try:
            with open(HISTORY_CSV_PATH, "a", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(["ts", "val", "profile"])
                writer.writerow([f"{ts:.3f}", int(val), profile_name])
        except Exception:
            pass

    def _append_history_point(self, ts: float, val: int, profile_name: str) -> bool:
        if self.history:
            last = self.history[-1]
            if abs(ts - last["ts"]) < 55 and int(val) == int(last["val"]):
                return False
        self.history.append({"ts": ts, "val": int(val), "profile": profile_name})
        self.history_times.append(ts)
        self._append_history_csv(ts, val, profile_name)
        self._trim_history(max_days=21)
        return True

    def _trim_history(self, max_days: int = 21) -> None:
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

    # --- prognoza (jak w desktop) ---
    def _init_forecast_models(self) -> Dict[int, Dict[str, Any]]:
        base_weights = {"trend": 0.45, "analog": 0.40, "tod": 0.15}
        base_errors = {"trend": 18.0, "analog": 20.0, "tod": 24.0}
        models: Dict[int, Dict[str, Any]] = {}
        for h in (15, 30):
            models[h] = {
                "weights": dict(base_weights),
                "errors": dict(base_errors),
            }
        return models

    def _load_forecast_state(self) -> None:
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
                    loaded: Dict[int, float] = {}
                    for k, v in node["tod_drift"].items():
                        try:
                            loaded[int(k)] = float(v)
                        except Exception:
                            pass
                    self._tod_drift[h] = loaded
        except Exception:
            pass

    def save_forecast_state(self, force: bool = False) -> None:
        now = time.time()
        if (not force) and (now - self._last_state_save_ts < 120):
            return
        payload: Dict[str, Any] = {}
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

    def _slot_index(self, ts: float, slot_minutes: int = 30) -> int:
        dt = datetime.fromtimestamp(ts)
        return (dt.hour * 60 + dt.minute) // slot_minutes

    def _value_at_timestamp(self, ts: float) -> Optional[float]:
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

    def _window_points(self, end_ts: float, window_min: int) -> Optional[List[Dict[str, Any]]]:
        start_ts = end_ts - window_min * 60.0
        points = [p for p in self.history if start_ts <= p["ts"] <= end_ts]
        if len(points) < 3:
            return None
        return points

    def _slope_in_window(self, end_ts: float, window_min: int) -> Optional[float]:
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
        denom = sum_w * sum_xx - sum_x * sum_x
        if abs(denom) < 1e-9:
            return None
        return (sum_w * sum_xy - sum_x * sum_y) / denom

    def _recent_volatility(self, end_ts: float, window_min: int = 30) -> float:
        points = self._window_points(end_ts, window_min)
        if not points or len(points) < 4:
            return 0.0
        jumps: List[float] = []
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

    def _pattern_signature(self, center_ts: float, lookback_min: int = 30, step_min: int = 5) -> Optional[List[float]]:
        sampled: List[float] = []
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

    def _predict_trend_expert(self, now_ts: float, val: int, horizon_min: int) -> Optional[float]:
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

    def _predict_analog_expert(
        self, now_ts: float, val: int, horizon_min: int, profile_name: str
    ) -> Optional[float]:
        now_pattern = self._pattern_signature(now_ts, lookback_min=30, step_min=5)
        if now_pattern is None:
            return None

        def build_candidates(require_same_profile: bool) -> List[Tuple[float, float]]:
            cands: List[Tuple[float, float]] = []
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

    def _predict_tod_expert(self, now_ts: float, val: int, horizon_min: int) -> float:
        slot = self._slot_index(now_ts, slot_minutes=30)
        drift = self._tod_drift[horizon_min].get(slot, 0.0)
        return max(40.0, min(420.0, float(val) + drift))

    def _combine_forecast(
        self, horizon_min: int, preds: Dict[str, Optional[float]]
    ) -> Tuple[Optional[float], str]:
        model = self._forecast_models[horizon_min]
        weights = model["weights"]
        available: Dict[str, float] = {}
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

    def _update_forecast_learning(self, now_ts: float, actual_val: int) -> None:
        if not self._pending_forecasts:
            return
        still_pending: List[Dict[str, Any]] = []
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

            inv: Dict[str, float] = {}
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
            self.save_forecast_state(force=False)

    def _compute_forecasts(self, now_ts: float, val: int, profile_name: str) -> Dict[int, Dict[str, Any]]:
        result: Dict[int, Dict[str, Any]] = {}
        for h in self._forecast_horizons:
            preds = {
                "trend": self._predict_trend_expert(now_ts, val, h),
                "analog": self._predict_analog_expert(now_ts, val, h, profile_name),
                "tod": self._predict_tod_expert(now_ts, val, h),
            }
            final, conf = self._combine_forecast(h, preds)
            result[h] = {"final": final, "conf": conf, "experts": preds}
        return result

    def _queue_forecast_targets(
        self, now_ts: float, base_val: int, forecasts: Dict[int, Dict[str, Any]]
    ) -> None:
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

    def tick(self) -> Dict[str, Any]:
        """Jeden krok: pobierz dane lub skanuj sieć. Zwraca słownik do UI."""
        self._refresh_network_settings()
        val, direction = self.get_glucose_data(self.current_ip)
        if val is not None:
            self._disconnect_since = None
            arrow = self.parse_arrow(direction or "")
            return self._process_success(val, arrow)

        if self._disconnect_since is None:
            self._disconnect_since = time.time()

        new_ip = self.scan_network()
        if new_ip:
            self.current_ip = new_ip
            val, direction = self.get_glucose_data(self.current_ip)
            if val is not None:
                self._disconnect_since = None
                arrow = self.parse_arrow(direction or "")
                return self._process_success(val, arrow)

        return {
            "ok": False,
            "status": f"Brak kontaktu z {self.current_ip} (skan nie znalazł telefonu)",
            "ip": self.current_ip,
            "port": self._port,
            "ssl_port": self._ssl_port,
            "val": None,
            "arrow": "",
            "delta_text": "",
            "profile_name": "",
            "forecast15": "—",
            "forecast30": "—",
            "alarm": None,
            "disconnect_min": (
                (time.time() - self._disconnect_since) / 60.0 if self._disconnect_since else 0.0
            ),
        }

    def dismiss_alarm(self) -> None:
        self._alarm_silenced = True

    def _process_success(self, val: int, arrow: str) -> Dict[str, Any]:
        now_ts = time.time()
        profile = self._get_active_profile(now_ts)

        added = self._append_history_point(now_ts, val, profile["name"])
        self._update_forecast_learning(now_ts, val)
        forecasts = self._compute_forecasts(now_ts, val, profile["name"])

        f15 = forecasts.get(15)
        f30 = forecasts.get(30)
        text15 = "trend 15m: —"
        text30 = "trend 30m: —"
        if f15 and f15.get("final") is not None:
            text15 = f"trend 15m: ~{int(round(f15['final']))} ({f15['conf']})"
        if f30 and f30.get("final") is not None:
            text30 = f"trend 30m: ~{int(round(f30['final']))} ({f30['conf']})"

        if added:
            self._queue_forecast_targets(now_ts, val, forecasts)

        delta_text = ""
        if self.last_val is not None:
            diff = val - self.last_val
            sign = "+" if diff > 0 else ""
            delta_text = f"{sign}{diff} mg/dL"
        self.last_val = val

        alarm: Optional[str] = None
        if val >= profile["hiper"]:
            alarm = "hiper"
            if not self._alarm_silenced:
                pass
        elif val <= profile["hipo"]:
            alarm = "hipo"
            if not self._alarm_silenced:
                pass
        else:
            self._alarm_silenced = False
            self._notified_alarm_type = None
            self._spoken_alarm_type = None

        return {
            "ok": True,
            "status": f"Połączono: {self.current_ip} · profil: {profile['name']}",
            "ip": self.current_ip,
            "port": self._port,
            "ssl_port": self._ssl_port,
            "val": val,
            "arrow": arrow,
            "delta_text": delta_text,
            "profile_name": profile["name"],
            "forecast15": text15,
            "forecast30": text30,
            "alarm": alarm,
            "thresholds": (profile["hipo"], profile["hiper"]),
            "disconnect_min": 0.0,
        }

    def force_rescan(self) -> Dict[str, Any]:
        """Ręczne skanowanie (przycisk)."""
        self._refresh_network_settings()
        found = self.scan_network()
        if found:
            self.current_ip = found
        return self.tick()
