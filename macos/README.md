# VIP Studio for macOS

Apple Silicon, macOS 26 or later. Python, FFmpeg and the macOS Vision OCR helper are bundled. No Terminal or Python installation is needed to run the app. Optional Whisper audio transcription requires a separately installed whisper-cli and model.

## Install and update

Download the DMG from https://github.com/reachhwasup/vip_studio/releases and drag VIP Studio into Applications. Version 1.2.0 is the one-time bootstrap for in-app updates; earlier builds cannot install updates themselves.

After installing 1.2.0, use **VIP Studio → Check for Updates** or **Settings → Mac app → Check for updates**. Sparkle checks the GitHub Releases feed, verifies signed updates, downloads them, and offers Install and Relaunch. Restart waits for active download/subtitle jobs and the subtitle editor to finish. Update checks are manual; no app update is silently installed.

This local build is ad-hoc code signed, not Apple Developer ID notarized. Update archives and the feed are separately signed with an Ed25519 key. macOS may still require approval to open a downloaded app. Developer ID signing and notarization are recommended for wider distribution.

Settings/history: `~/Library/Application Support/VIP Studio`. Default video folder: `~/Movies/VIP Studio`. Logs: `~/Library/Logs/VIP Studio/backend.log`. Native web storage is separate from a browser's queue/preferences. Updating the app does not replace these data folders.

## Features

- Library → episode → Review & edit: edit caption text/speaker/timing, shift captions, and preview next to the video. Saves create backups and reject overlapping times or stale changes.
- Settings → Mac app: enable macOS completion notifications and send a test notification.
- In-app signed updates hosted at `https://github.com/reachhwasup/vip_studio/releases/latest/download/appcast.xml`.

## Rebuild

On an Apple Silicon Mac with Xcode command-line tools, Python 3.11 and FFmpeg:

```sh
python3.11 -m venv macos/.venv
macos/.venv/bin/pip install -r 短剧下载神器开源版源码/requirements.txt pyinstaller
macos/.venv/bin/python macos/build.py
```

The pinned Sparkle distribution is downloaded and checksum-verified when missing. `macos/update-public-key.txt` is public and embedded in the app. The corresponding private key is in the original build Mac's Keychain under account `studio.vip.drama`; it is never put in the repository or application. Do not generate a replacement signing key for an existing release channel without a key migration plan.

## Release

Increment both `CFBundleShortVersionString` and `CFBundleVersion` in `macos/build.py`, then build and run:

```sh
macos/.venv/bin/python macos/release.py
```

This creates the signed ZIP, signed appcast.xml, a legacy latest.json manifest, and SHA256SUMS.txt in `macos/dist/release-VERSION/`. Publish these files together with the DMG on a GitHub Release tagged `vVERSION`. The ZIP filename and release tag must match the enclosure URL in the appcast. Publish a draft with all assets before making it the latest release.

Do not commit config.json, .env, user history, downloaded videos, logs, signing private keys or GitHub credentials. Build outputs, the local release checkout and the virtual environment are ignored by Git.

FFmpeg and its bundled libraries retain their licenses in the app's ThirdPartyNotices folder. FFmpeg source/configuration: https://ffmpeg.org/download.html and the matching Homebrew formula https://github.com/Homebrew/homebrew-core/blob/HEAD/Formula/f/ffmpeg.rb . Sparkle license is included in Sparkle.framework.
