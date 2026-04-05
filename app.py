# -*- coding: utf-8 -*-
"""
Monitor glukozy (Juggluco) — wersja Streamlit.

Uruchom z katalogu streamlit_app:
  python3 -m streamlit run app.py

Import `backend` musi widzieć ten sam katalog co app.py (działanie z IDE / innym cwd).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent
_d = str(_APP_DIR)
if _d not in sys.path:
    sys.path.insert(0, _d)

import streamlit as st

try:
    from streamlit_autorefresh import st_autorefresh

    _HAS_AUTOREFRESH = True
except ImportError:
    _HAS_AUTOREFRESH = False

from backend import PORT, SETTINGS, SSL_PORT, StreamlitGlucoseMonitor

MIN_POLL_SEC = 9.0

st.set_page_config(
    page_title="Juggluco — Streamlit",
    page_icon="📈",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
<style>
.big-glucose { font-size: 4.5rem !important; font-weight: 700; line-height: 1.1; }
.arrow-trend { font-size: 2rem; }
.metric-delta { font-size: 1.1rem; color: #aaa; }
.block { padding: 0.5rem 0; }
</style>
""",
    unsafe_allow_html=True,
)

if "mon" not in st.session_state:
    st.session_state.mon = StreamlitGlucoseMonitor()
if "last_tick_ts" not in st.session_state:
    st.session_state.last_tick_ts = 0.0
if "snapshot" not in st.session_state:
    st.session_state.snapshot = None

# Odświeżenie co ~10 s (opcjonalnie — bez pakietu: tylko przycisk „Odśwież teraz”)
if _HAS_AUTOREFRESH:
    st_autorefresh(interval=10000, key="glucose_auto_refresh")
else:
    st.caption(
        "Brak `streamlit-autorefresh` — zainstaluj: `pip install streamlit-autorefresh` "
        "albo odświeżaj przyciskiem poniżej."
    )

now = time.time()
col_a, col_b = st.columns(2)
with col_a:
    if st.button("Odśwież teraz", use_container_width=True):
        st.session_state.force_poll = True
with col_b:
    if st.button("Szukaj telefonu (skan LAN)", use_container_width=True):
        with st.spinner("Skanowanie…"):
            st.session_state.snapshot = st.session_state.mon.force_rescan()
        st.session_state.last_tick_ts = time.time()
        st.rerun()

force = st.session_state.pop("force_poll", False)
need_poll = (
    force
    or st.session_state.snapshot is None
    or (now - st.session_state.last_tick_ts >= MIN_POLL_SEC)
)
if need_poll:
    # Pierwszy odczyt może długo skanować LAN — bez spinnera strona wygląda na „martwą”.
    with st.spinner("Łączenie z Juggluco (ev. skan sieci)…"):
        st.session_state.snapshot = st.session_state.mon.tick()
    st.session_state.last_tick_ts = time.time()

snap = st.session_state.snapshot or {}

st.title("Juggluco Commander — Streamlit")
st.caption(
    f"Konfiguracja: `../settings.ini` · HTTP (API) **:{PORT}** · HTTPS (WWW) **:{SSL_PORT}** · "
    f"podsieć `{SETTINGS['subnet_prefix']}` · IP: **{snap.get('ip', '—')}**"
)

if snap.get("ok") and snap.get("val") is not None:
    val = int(snap["val"])
    alarm = snap.get("alarm")
    hip, hi = snap.get("thresholds") or (70, 180)

    if alarm == "hiper" and not st.session_state.mon._alarm_silenced:
        st.error(f"HIPERGLIKEMIA — {val} mg/dL (próg dzień/noc z profilu: {hi})")
    elif alarm == "hipo" and not st.session_state.mon._alarm_silenced:
        st.warning(f"HIPOGLIKEMIA — {val} mg/dL (próg: {hip})")

    c1, c2 = st.columns([1, 4])
    with c1:
        st.markdown(f'<p class="arrow-trend">{snap.get("arrow", "")}</p>', unsafe_allow_html=True)
    with c2:
        color = "#ffcc00"
        if alarm == "hiper":
            color = "#ff4444" if not st.session_state.mon._alarm_silenced else "#ff8888"
        elif alarm == "hipo":
            color = "#4488ff" if not st.session_state.mon._alarm_silenced else "#88ccff"
        st.markdown(
            f'<p class="big-glucose" style="color:{color}">{val}</p>',
            unsafe_allow_html=True,
        )
    if snap.get("delta_text"):
        st.markdown(f'<p class="metric-delta">Δ {snap["delta_text"]}</p>', unsafe_allow_html=True)

    st.success(snap.get("status", ""))
    st.caption(f"Prognoza: {snap.get('forecast15', '—')} · {snap.get('forecast30', '—')}")

elif not snap.get("ok"):
    st.warning(snap.get("status", "Brak danych"))
    dm = snap.get("disconnect_min") or 0
    if dm >= 1:
        st.caption(f"Bez kontaktu od ~{dm:.1f} min")

if st.button("Kasuj alarm (wycisz mruganie — jak w desktop)", disabled=not snap.get("ok")):
    st.session_state.mon.dismiss_alarm()
    st.rerun()

st.divider()
st.subheader("Panele Juggluco (w przeglądarce, HTTPS)")
ip = snap.get("ip") or st.session_state.mon.current_ip
base = f"https://{ip}:{SSL_PORT}"
endpoints = [
    ("Wykres (Curve)", "/x/curve"),
    ("Raport AGP", "/x/report"),
    ("Statystyki", "/x/stats"),
    ("Wykres zbiorczy", "/x/summarygraph"),
    ("Historia", "/x/history"),
    ("Stream", "/x/stream"),
    ("Insulina / ilości", "/x/amounts"),
    ("Posiłki", "/x/meals"),
    ("Skanowania", "/x/scans"),
]
cols = st.columns(3)
for i, (label, path) in enumerate(endpoints):
    with cols[i % 3]:
        url = f"{base}{path}"
        if getattr(st, "link_button", None):
            st.link_button(label, url, use_container_width=True)
        else:
            st.markdown(f"[{label}]({url})")

st.divider()
with st.expander("Informacja"):
    st.markdown(
        """
Ta wersja działa w przeglądarce (Streamlit), współdzieli z aplikacją desktop  
`glucose_history.csv` i `forecast_state.json` w katalogu **nad** `streamlit_app`.

Odczyt glukozy: **HTTP** na porcie z `Port` w `settings.ini` (domyślnie 17580).  
Linki do paneli Juggluco: **HTTPS** na `SSLPort` (domyślnie 17581).

**Ograniczenia względem tkinter:** brak dźwięku/beepów TTS z desktopu; alarm to komunikat na stronie.  
Odświeżanie co ok. 10 s (automatycznie) lub przycisk „Odśwież teraz”.
"""
    )
