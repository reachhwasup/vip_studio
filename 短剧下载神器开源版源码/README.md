# Shared backend and browser app

This directory contains the Python backend and web interface used by the macOS
and Android apps, plus the local browser version. Platform adapters and build
scripts live in `../macos` and `../android`.

With Python 3.11, install `requirements.txt` in a virtual environment and run:

```sh
python app.py 5055
```

Open `http://127.0.0.1:5055`. `start.sh` and `stop.sh` optionally manage the browser
backend in the background. FFmpeg is required for episode downloads.

Use **Settings → Device configuration → Set up Hongguo automatically** to request
service-issued numeric IDs. Manual IDs must contain digits only; Mac serial numbers
and hardware identifiers cannot be used. Existing IDs are preserved when valid.

The browser version also accepts service credentials through `DUANJU_DEVICE_ID` and `DUANJU_INSTALL_ID`. See
`.env.example`. The standalone Android adapter handles its own phone detection and
registration; it does not use the removed legacy registration script.

Configuration and history stay beside the source for local browser runs, or in
the runtime data directory set by each native app. Choose the video folder under
Settings. Do not commit credentials, history, downloaded videos, or logs.

See the [repository README](../README.md) for tests and platform documentation.
The [original Chinese introduction](开源介绍.md) is retained as historical context.
