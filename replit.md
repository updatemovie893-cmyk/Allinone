# Telegram Tracking Tool

## Overview
A Telegram-based information collection tool. Users interact via a Telegram bot to generate unique tracking links. When someone opens a tracking link, they can consent to share device fingerprint, location, camera photos, and audio recordings — all sent to the link creator via Telegram.

## Tech Stack
- **Language**: Python 3.12
- **Framework**: Flask 3.0.0
- **Telegram**: python-telegram-bot 20.3
- **HTTP**: requests 2.31.0
- **Server**: Flask dev server (Gunicorn for production)

## Project Structure
```
okallinone.py   # Main file: Flask server + Telegram bot + HTML template
Procfile        # Production Gunicorn command
requirements. txt  # Python dependencies (note: space in filename)
```

## Configuration
All credentials must be set as environment secrets:
- `BOT_TOKEN` - Telegram bot token (from BotFather)
- `ADMIN_CHAT_ID` - Your Telegram user ID
- `BASE_URL` - Public URL of the deployed app (for generating tracking links)

## Running
- Development: `python3 okallinone.py` on port 5000
- Production: `gunicorn okallinone:flask_app --bind 0.0.0.0:$PORT`

## Key Routes
- `GET /` - Landing page
- `GET /track/<token>` - Tracking page (consent-based data collection)
- `POST /capture_fingerprint` - Receive device fingerprint
- `POST /capture_photo` - Receive photo
- `POST /capture_audio` - Receive audio
- `POST /capture_location` - Receive GPS location
- `POST /capture_combined_*` - Combined media + fingerprint endpoints

## Notes
- If `BOT_TOKEN` is not set, Flask runs alone without the bot
- The bot uses in-memory `tracking_links` dict; data is lost on restart
- Line endings were fixed from `\r` (Windows) to `\n` (Unix)
- Missing `import json` was added
