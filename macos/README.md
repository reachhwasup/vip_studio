# VIP Studio for macOS

Apple Silicon, macOS 26 or later. Python, FFmpeg and the macOS Vision OCR helper are bundled. No Terminal or Python installation is needed to run the app. Optional Whisper audio transcription requires a separately installed whisper-cli and model.

## Install and update

Download the DMG from https://github.com/reachhwasup/vip_studio/releases and drag VIP Studio into Applications. Version 1.2.0 is the one-time bootstrap for in-app updates; earlier builds cannot install updates themselves.

After installing 1.2.0, use **VIP Studio → Check for Updates** or **Settings → Mac app → Check for updates**. Sparkle checks the GitHub Releases feed, verifies signed updates, downloads them, and offers Install and Relaunch. Restart waits for active download/subtitle jobs and the subtitle editor to finish. Update checks are manual; no app update is silently installed.

This local build is ad-hoc code signed, not Apple Developer ID notarized. Update archives and the feed are separately signed with an Ed25519 key. macOS may still require approval to open a downloaded app. Developer ID signing and notarization are recommended for wider distribution.

Settings/history: `~/Library/Application Support/VIP Studio`. Default video folder: `~/Movies/VIP Studio`. Logs: `~/Library/Logs/VIP Studio/backend.log`. Native web storage is separate from a browser's queue/preferences. Updating the app does not replace these data folders.

## Features

- Subtitle progress bars in Downloads and Library show live image counts and percent for the active OCR pass, plus speech-engine progress. Waiting jobs stay at zero; preparation and saving use activity indicators.

- If the saved download folder is missing, disconnected, or unwritable, the queue pauses with its episodes pending and opens the folder picker. Selecting a replacement saves it and resumes the queue; cancelling keeps the queue paused.

- Continue / Episodes retries temporary website failures and can use the signed service endpoint or a saved episode list. Saved lists stay in app history; stale lists are labelled so newly released episodes are not mistaken for the complete current catalogue.

- Generated subtitles are saved as SRT without an extra transcript JSON file. Speech comparison suggestions are saved in the app database for the exact SRT revision and survive restarting.

- Subtitles has its own tab: Processing queue shows shared Download/Library jobs and live OCR progress; Preferences controls automatic subtitle creation; Import & timing contains subtitle file preview, synchronization and export. To generate subtitles for a saved video, use Create from Library. Jobs are saved in app data and unfinished work resumes after restarting; SRT files remain with the saved videos.
- Downloads → Episodes at once selects 1–4 simultaneous video downloads (three for new installations). The control stays in sync with Settings. Subtitles run in a separate queue and show progress on each saved video, so OCR and speech processing do not hold video download slots. Keep the app open for subtitle jobs; after a restart, check Library for saved SRT files or regenerate unfinished ones.

- Settings → Device configuration → Set up Hongguo automatically requests numeric device and install IDs from the service and saves them locally. Mac serial numbers and hardware IDs are rejected. Invalid setup pauses the queue so remaining episodes can be retried after correcting the connection.

- Library resumes unfinished episodes and remembers the last 500 playback positions on this device. Start over replays an episode. Playback supports saved SRT captions, speed controls, previous/next episodes and opt-in automatic next episode.
- Library filters include Continue watching and Missing subtitles, with sorting by date, title or episode count.
- Subtitle generation checks on-screen captions plus local speech in Auto mode. Audio-only and picture-only methods are available; the Library remembers method and language. Conflicting speech suggestions remain available in Review & edit.
- Subtitle editing includes Undo/Redo for the current session. Temporary connection failures during generation are retried; jobs are saved in the app database.
- Download Details shows subtitle/poster warnings. Clear all is unavailable while download workers are active.

- Subtitle import and review can stretch/compress timings to correct gradual drift, compare against video duration, and adjust fixed delays. Imported timings can be reset; review edits support Undo. Timing correction is manual.

- Library → episode → Review & edit: edit caption text/speaker/timing, shift captions, and preview next to the video. Saves create backups and reject overlapping times or stale changes.
- Settings → Mac app: enable macOS completion notifications and send a test notification.
- In-app signed updates hosted at `https://github.com/reachhwasup/vip_studio/releases/latest/download/appcast.xml`.

## Rebuild

On an Apple Silicon Mac with Xcode command-line tools, Python 3.11 and FFmpeg:

```sh
python3.11 -m venv macos/.venv
macos/.venv/bin/pip install -r 源码_开源版/requirements.txt pyinstaller
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

### Chinese caption comparison and statement grouping

In Library → Generate or replace subtitles, choose **Compare video text + Chinese audio** to compare on-screen text with local speech. OCR wording and timing are retained when speech disagrees; saved review hints identify disagreements. **Needs review** is separate from ready jobs.

Short clauses stay together across commas and brief pauses. Sentence endings, long readable spans and clear pauses can still create breaks. Automatic OCR joins require close wording and timing matches and reject conflicting named speakers. Recognition cannot reliably identify every speaker change: review the video before accepting a join. Review & edit → **Join next** combines adjacent captions with Undo before saving.

CPU use offers Cool (1 worker), Balanced (2, default), and Faster (4). Existing SRTs change only when regenerated or saved in the editor; regeneration creates a backup.

### Speaker changes and imported captions

Paraformer-only transcription does not identify speakers; it can put two voices into one caption. These jobs are marked for review before translating or dubbing. Video-text comparison now retains OCR caption breaks when speaker identity is unknown, even if speech wording agrees. A shared sentence or short pause is not proof of one speaker. Use video text when available, and review actual speaker changes in AI Transcript before dubbing.

### Subtitle enhancement during downloads

Subtitles → Preferences now controls the method, audio language and CPU use for automatic downloads. **Recommended** uses OCR + Paraformer for Chinese when the installed models are ready, otherwise OCR + Whisper. It preserves unknown speaker boundaries, keeps OCR wording when audio disagrees, saves review hints and marks uncertain results for review. Audio-only models still require speaker review. Processing is local and uses the shared single-worker queue. Settings are saved in the app profile and apply when each video finishes downloading; already queued subtitle jobs keep their settings. Existing SRT files are retained when skipping saved videos; regenerate them in Library to update them.

### One Smart subtitles option

Download Preferences and Library now share **Smart subtitles (recommended)**. It reads video text and checks exactly one audio engine: Paraformer for Chinese when installed, otherwise Whisper. If no readable video captions are found it uses the selected speech engine and marks the result for review. It keeps existing caption breaks when speakers are unknown and saves disagreements for review. The menu also offers **Video text only** and **Audio only**; engine-specific choices are retained only for existing saved overrides and queued jobs. Smart does not run Paraformer and Whisper together, and does not identify speaker turns. Existing per-episode overrides and queued jobs are retained.
