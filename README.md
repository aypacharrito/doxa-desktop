# Doxa

A personal AI operator for Windows: a desktop app (Python + Tk) that chats with a model on your own PC or with
paid AIs (Claude, ChatGPT, Gemini and others), runs coding jobs through Codex / Claude Code, controls a browser,
and can be reached from your phone.

This is a clean copy of version 1.38.2 with no accounts, keys, chats or personal data. Everything you connect
(AI keys, plugins, phone access) is yours and stays on your PC.

## Install (Windows 10/11)

1. Install [Python 3.12](https://www.python.org/downloads/) (tick "Add python.exe to PATH").
2. Download or clone this repository.
3. Double-click `SETUP_WINDOWS.bat` and pick your graphics option (1 for an NVIDIA RTX card, 2 for other GPUs,
   3 for CPU only). It creates a private `.venv` folder here and installs what Doxa needs.
4. Start Doxa with `START_DOXA.cmd` (setup also puts a Doxa shortcut on the desktop).

Optional extras:

- `INSTALL_BROWSER_AGENT.bat`: browser tasks (uses Microsoft Edge).
- `SETUP_PHONE_ACCESS.bat`: reach Doxa from your phone through a Cloudflare tunnel.
- `mobile/`: the Android/iOS app (Expo). Build it under your own Expo account.

## First run

- **Chat** uses a model on your PC. Load a GGUF model in Settings (the app was tuned on Qwen 9B, Q4_K_M, on an
  8 GB GPU). Without one, connect a paid AI instead.
- **Work** uses paid AIs. Add your own keys in Settings → AI brains. Keys are stored encrypted on your PC
  (Windows DPAPI / Credential Manager), never in this folder.
- **Code** runs Codex or Claude Code with full access to your PC. Sign in to those tools yourself first.
- **Plugins** connect other apps by browser sign-in. Payment plugins are read-only until you allow changes.

Your data lives in `%LOCALAPPDATA%\ForgeMind` (chats, memory, settings, keys). Deleting that folder resets Doxa.

## Good to know

- Doxa's Code mode and chat tools can run commands and edit any file on the PC. Only run it on a PC you own.
- Browser tasks pause for your approval before anything that books, submits or pays.
- The Insurance island and the "Pacifica" CRM connection were built for the original owner's business. They do
  nothing until you connect a CRM of your own, and are safe to remove or repurpose.
- A fresh install on a new PC has not been tested end to end yet. If setup fails, the error message usually names
  the missing piece.

## Tests

```
.venv\Scripts\python.exe tests\run_per_file.py
```

## Changing it

See `CLAUDE.md` for a map of the code. It is written for Claude Code, so you can open this folder in Claude Code
and ask it to change things.
