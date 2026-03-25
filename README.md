# Monitor Boost (Juggluco Commander)

Lekka aplikacja desktopowa w Pythonie (`tkinter`) do monitorowania glukozy z endpointu Juggluco/Nightscout (`/sgv.json?count=1`) w sieci lokalnej.

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

## Uwaga medyczna

To narzedzie ma charakter pomocniczy i informacyjny. Nie stanowi wyrobu medycznego ani porady medycznej. Decyzje terapeutyczne podejmuj zgodnie z zaleceniami lekarza i na podstawie certyfikowanych urzadzen.

## Publikacja na GitHub

W katalogu projektu:

```bash
git init
git add .
git commit -m "Prepare Monitor Boost for GitHub publication"
gh repo create monitor-boost --public --source=. --remote=origin --push
```

Jesli nie masz `gh`, utworz repo recznie na GitHub i potem:

```bash
git remote add origin https://github.com/<twoj_login>/monitor-boost.git
git branch -M main
git push -u origin main
```
