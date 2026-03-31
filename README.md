# Telegram Group Leaver

A desktop tool to bulk-leave Telegram groups and channels. Features a clean web UI served locally — no data leaves your machine.

## Features

- Login with your Telegram phone number (OTP + optional 2FA)
- View all your groups, supergroups, and channels
- Select all or pick specific ones to leave
- Rate-limit aware — auto-pauses on flood wait errors with retries
- Runs entirely on `localhost` — your session never goes to a remote server

## How It Works

The app runs a local Flask server (`app.py`) that communicates with Telegram via the [Telethon](https://github.com/LonamiWebs/Telethon) MTProto library. A browser UI at `http://localhost:8080` lets you authenticate and manage your groups.

## Setup

### Requirements

- Python 3.8+
- A Telegram API ID and API Hash — get them free at [my.telegram.org](https://my.telegram.org)

### Install & Run

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/telegram-group-leaver.git
cd telegram-group-leaver

# Install dependencies
pip install -r requirements.txt

# Run
python app.py
```

Then open `http://localhost:8080` in your browser.

On first launch you will be asked to enter your **API ID** and **API Hash** (saved locally to `config.json`, which is gitignored).

### Build as a standalone EXE (Windows)

```bat
build.bat
```

The executable will be at `dist\TelegramGroupLeaver.exe`. No Python installation needed to run it.

## Security Notes

- Your `config.json` (API credentials) and `*.session` (Telegram session) files are **gitignored** and never committed.
- The server only binds to `127.0.0.1` — it is not accessible from outside your machine.
- No credentials or session data are sent to any third party.

## Tech Stack

- **Backend:** Python, Flask, Telethon
- **Frontend:** Vanilla HTML/CSS/JS (single `index.html`)
- **Packaging:** PyInstaller

## License

MIT
