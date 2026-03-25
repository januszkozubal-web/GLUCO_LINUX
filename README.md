# Monitor Boost (Juggluco Commander)

Aplikacja desktopowa w Pythonie (`tkinter`) do monitorowania glukozy z 
Juggluco/Nightscout (`/sgv.json?count=1`) w sieci lokalnej.

## Co robi

- Odczyt glukozy i trendu co 10 sekund.
- Automatyczne wyszukiwanie telefonu w podsieci po utracie połączenia.
- Alarmy hipo/hiper: miganie, dzwiek, powiadomienia systemowe Linux (`notify-send`).
- Opcjonalny TTS (preferowany `edge-tts`, fallback `pyttsx3`).
- Prosty forecast 15/30 min oparty o historie i uczenie online.
- Widok GUI z szybkim dostepem do paneli WWW (`/x/curve`, `/x/report`, itd.).

## Wymagania

- Python 3.10+ (zalecane)
- Linux (testowane na Ubuntu)
- Dostep do telefonu/uslugi Juggluco w tej samej sieci LAN

Instalacja zaleznosci:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Konfiguracja

1. Skopiuj plik przykladowy:
   ```bash
   cp settings.example.ini settings.ini
   ```
2. Ustaw adres/podsiec i progi alarmowe w `settings.ini`.

> `settings.ini`, `glucose_history.csv` i `forecast_state.json` sa plikami lokalnymi i nie powinny byc publikowane.

## Uruchomienie

```bash
python3 monitor_boost.py
```

Lub przez skrypt:

```bash
bash start_monitor.sh
```

## Uwaga - wykluczenie jakiejkolwiek odpowiedzialności 

To narzedzie ma charakter pomocniczy i informacyjny - to tylko ZABAWKA. Nie stanowi wyrobu medycznego ani porady medycznej. Decyzje terapeutyczne podejmuj zgodnie z zaleceniami lekarza i na podstawie certyfikowanych urzadzen.

