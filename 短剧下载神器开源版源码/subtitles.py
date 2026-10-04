"""Create a Chinese .srt subtitle file for a downloaded video.

Two methods, both running locally (nothing is uploaded):

1. Picture (preferred, macOS): Hongguo videos have their subtitles drawn into the picture.
   Frames are sampled and read with the system's text recognition (subtitle_ocr.swift),
   to recover the displayed text; recognition and sampled timing can be imperfect.
2. Audio (fallback): speech recognition with whisper.cpp, for videos without drawn-in
   subtitles. Timing and wording are approximate.

Environment overrides:
  WHISPER_BIN    path to whisper-cli            (default: whisper-cli on PATH)
  WHISPER_MODEL  path to the ggml model file    (default: ~/.cache/whisper-cpp/ggml-large-v3-turbo.bin)
  WHISPER_VAD    path to the silero VAD model   (default: ~/.cache/whisper-cpp/ggml-silero-v5.1.2.bin)
"""
import collections
import uuid
from subtitle_formats import import_subtitles, normalize_segments, export_subtitles
import unicodedata
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

WHISPER_BIN = os.getenv("WHISPER_BIN", "whisper-cli")
_WHISPER_DIR = Path.home() / ".cache" / "whisper-cpp"
MODEL_PATH = Path(os.getenv("WHISPER_MODEL", str(_WHISPER_DIR / "ggml-large-v3-turbo.bin")))
VAD_MODEL_PATH = Path(os.getenv("WHISPER_VAD", str(_WHISPER_DIR / "ggml-silero-v5.1.2.bin")))
# Steers the model towards punctuated Simplified Chinese.
PROMPT = "以下是普通话的句子，使用简体中文。"

OCR_SOURCE = Path(__file__).resolve().parent / "subtitle_ocr.swift"
OCR_BINARY = Path.home() / ".cache" / "short-drama-downloader" / "subtitle_ocr"
OCR_FPS = 8  # frames read per second of video; timing is accurate to about 1/OCR_FPS seconds
OCR_STACK = 1  # Read each frame separately: stacking can hide short captions from Vision.
OCR_WIDTH = 1280  # frames wider than this are scaled down before reading; small text needs the pixels
PROBE_TOP = 0.45  # the probe pass looks for the subtitle row in the picture below this height
MIN_CUES_PER_MINUTE = 3  # fewer than this from the picture means there are no drawn-in subtitles

# One job at a time: both methods already use every core / the whole GPU.
_lock = threading.Lock()
# Where the subtitles sit in each series' picture, so later episodes skip the search: folder -> (top, height).
_strip_cache: dict = {}


def _run(command: list, capture: bool = False) -> str:
    done = subprocess.run(
        command, stdout=subprocess.PIPE if capture else subprocess.DEVNULL, stderr=subprocess.PIPE,
        text=True, errors="replace",
    )
    if done.returncode != 0:
        tail = (done.stderr or "").strip().splitlines()[-1:] or ["no error output"]
        raise RuntimeError(f"{Path(command[0]).name} failed: {tail[0][:200]}")
    return done.stdout or ""


# ───────────────────────── picture method ─────────────────────────

def _ocr_helper() -> str:
    """Path to the compiled text-recognition helper, building it on first use. Empty if unavailable."""
    bundled = os.getenv("VIP_STUDIO_OCR_BIN", "")
    if bundled and Path(bundled).is_file():
        return bundled
    if sys.platform != "darwin" or not OCR_SOURCE.is_file():
        return ""
    if OCR_BINARY.is_file() and OCR_BINARY.stat().st_mtime >= OCR_SOURCE.stat().st_mtime:
        return str(OCR_BINARY)
    if not shutil.which("swiftc"):
        return ""
    OCR_BINARY.parent.mkdir(parents=True, exist_ok=True)
    try:
        _run(["swiftc", "-O", str(OCR_SOURCE), "-o", str(OCR_BINARY)])
    except RuntimeError as exc:
        print(f"[subtitles] could not build the text-recognition helper: {exc}")
        return ""
    return str(OCR_BINARY)


def _read_frames(
    helper: str, video_path: Path, ffmpeg_bin: str, fps: float, top: float, height: float, folder: Path,
    stack: int = OCR_STACK, width: int = OCR_WIDTH,
) -> list:
    """Sample frames, keep the horizontal strip [top, top + height] of the picture, and read its text.

    Returns one record per sampled frame, in order (frame i shows the picture at i / fps), each
    {"lines": [...]} with boxes as fractions of the strip. Strips are stacked `stack` to an image.
    """
    folder.mkdir()
    strip = f"fps={fps}:round=down,crop=iw:ih*{height:.4f}:0:ih*{top:.4f},scale='min(iw,{width})':-2,tile=1x{stack}"
    _run([ffmpeg_bin, "-y", "-v", "error", "-i", str(video_path), "-vf", strip, "-q:v", "4", str(folder / "%06d.jpg")])
    frames = []
    for output in _run([helper, str(folder)], capture=True).splitlines():
        if not output.strip():
            continue
        cells = [{"lines": []} for _ in range(stack)]
        for line in json.loads(output)["lines"]:
            cell = min(int((line["y"] + line["h"] / 2) * stack), stack - 1)
            cells[cell]["lines"].append(dict(line, y=line["y"] * stack - cell, h=line["h"] * stack))
        frames += cells
    return frames


def _dialogue_lines(records: list, min_conf: float = 0.5, fps: float = 0.5) -> list:
    """Per frame, the horizontally centred lines, without logos and notices that never change."""
    lines = [
        (i, line) for i, record in enumerate(records) for line in record["lines"]
        if line["conf"] >= min_conf and line["text"].strip() and abs(line["x"] + line["w"] / 2 - 0.5) < 0.25
    ]
    seen = collections.Counter((line["text"].strip(), round(line["y"], 1)) for _, line in lines)
    static = {key for key, count in seen.items() if len(records) / fps >= 30 and count > 0.85 * len(records)}
    return [(i, line) for i, line in lines if (line["text"].strip(), round(line["y"], 1)) not in static]


def _subtitle_strip(records: list) -> tuple:
    """(top, height) of the strip holding the subtitles, as fractions of the probed area; (0, 0) if none."""
    lines = _dialogue_lines(records)
    if not lines or len({i for i, _ in lines}) < 0.15 * len(records):
        return 0.0, 0.0
    centre = lambda line: line["y"] + line["h"] / 2
    rows = collections.Counter(round(centre(line) * 20) for _, line in lines)  # 5%-of-height buckets
    row = rows.most_common(1)[0][0] / 20
    in_row = [line for _, line in lines if abs(centre(line) - row) <= 0.08]
    line_height = sorted(line["h"] for line in in_row)[len(in_row) // 2]
    top = max(0.0, min(line["y"] for line in in_row) - line_height)
    bottom = min(1.0, max(line["y"] + line["h"] for line in in_row) + line_height)
    return top, bottom - top


def _same_line(a: str, b: str) -> bool:
    # Similar-looking sentences can have opposite meanings (我喜欢你 / 我不喜欢你).
    # Only ignore spacing and punctuation, never differing letters or characters.
    def content(text):
        return ''.join(c for c in text if not c.isspace() and not unicodedata.category(c).startswith('P'))
    return a == b or bool(content(a)) and content(a) == content(b)


def _cues_from_frames(records: list, fps: float, min_frames: int = 2) -> list:
    """Merge runs of frames showing the same line into [start, end, text] cues."""
    per_frame = [[] for _ in records]
    for i, line in _dialogue_lines(records, min_conf=0.3, fps=fps):
        per_frame[i].append(line)
    texts = [
        "".join(line["text"].strip() for line in sorted(frame, key=lambda l: (round(l["y"], 2), l["x"])))
        for frame in per_frame
    ]

    confidence = [min((line['conf'] for line in frame), default=0) for frame in per_frame]
    runs = []  # [first frame, last frame, readings]
    for i, text in enumerate(texts):
        if not text:
            continue
        # one unreadable frame inside a run does not end it
        if runs and i - runs[-1][1] <= 2 and _same_line(runs[-1][2].most_common(1)[0][0], text):
            runs[-1][1] = i
            runs[-1][2][text] += 1
        else:
            runs.append([i, i, collections.Counter({text: 1})])

    cues = []
    for first, last, readings in runs:
        # Keep brief, confidently recognised captions; reject isolated OCR noise.
        observations = sum(readings.values())
        best_confidence = max(confidence[first:last + 1])
        if (observations >= min_frames and best_confidence >= 0.5) or observations >= max(3, min_frames) or best_confidence >= 0.85:
            # Frame i shows the picture at i / fps: the line is on screen from `first`, gone by `last + 1`.
            cues.append([first / fps, (last + 1) / fps, readings.most_common(1)[0][0]])
    # Consolidate identical captions separated only by a brief OCR dropout.
    merged = []
    for cue in cues:
        if merged and _same_line(merged[-1][2], cue[2]) and cue[0] - merged[-1][1] <= 2 / fps:
            merged[-1][1] = cue[1]
        else:
            merged.append(cue)
    cues = merged
    for cue, following in zip(cues, cues[1:]):
        cue[1] = min(cue[1], following[0])
    return cues


def _subtitles_from_picture(video_path: Path, ffmpeg_bin: str, tmp: Path) -> list:
    helper = _ocr_helper()
    if not helper:
        return []
    series = video_path.parent
    # Re-detect each episode: subtitle placement can change within a series.
    for attempt in ("probed", "cached"):
        strip = _strip_cache.get(series) if attempt == "cached" else None
        if attempt == "cached" and not strip:
            continue
        if not strip:
            # A sparse look at the lower part of the picture to find where the subtitles sit.
            probe = _read_frames(helper, video_path, ffmpeg_bin, 0.5, PROBE_TOP, 1 - PROBE_TOP, tmp / "probe", stack=4)
            top, height = _subtitle_strip(probe)
            if not height:
                continue
            area = 1 - PROBE_TOP
            strip = (PROBE_TOP + top * area, height * area)
        # Read just that strip, densely.
        frames = _read_frames(helper, video_path, ffmpeg_bin, OCR_FPS, strip[0], strip[1], tmp / f"frames_{attempt}")
        cues = _cues_from_frames(frames, OCR_FPS)
        minutes = len(frames) / OCR_FPS / 60
        if len(cues) >= MIN_CUES_PER_MINUTE * minutes:
            _strip_cache[series] = strip
            return cues
        _strip_cache.pop(series, None)  # the remembered position did not work for this episode; search again
    return []


def _srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def _write_srt(cues: list, srt_path: Path) -> None:
    segments = normalize_segments([{"start_time": a, "end_time": b, "text": text} for a, b, text in cues])
    if not segments:
        raise RuntimeError("No usable timed dialogue was recognised.")
    srt_path.write_text(export_subtitles(segments, "srt"), encoding="utf-8")


# ───────────────────────── audio method ─────────────────────────

def _whisper_missing() -> str:
    if not shutil.which(WHISPER_BIN):
        return "whisper.cpp is not installed (run: brew install whisper.cpp)"
    if not MODEL_PATH.is_file():
        return f"speech model not found at {MODEL_PATH}"
    return ""


def _subtitles_from_audio(video_path: Path, ffmpeg_bin: str, tmp: Path, srt_path: Path) -> None:
    # whisper.cpp wants 16 kHz mono PCM.
    wav_path = tmp / "audio.wav"
    _run([ffmpeg_bin, "-y", "-v", "error", "-i", str(video_path),
          "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav_path)])

    out_base = tmp / "subtitles"
    command = [WHISPER_BIN, "-m", str(MODEL_PATH), "-f", str(wav_path), "-l", "zh", "--prompt", PROMPT,
               "-ml", "16", "-osrt", "-of", str(out_base), "-np"]
    if VAD_MODEL_PATH.is_file():
        # Voice detection keeps lines from starting during silence or music.
        command += ["--vad", "--vad-model", str(VAD_MODEL_PATH)]
    _run(command)

    produced = out_base.with_suffix(".srt")
    if not produced.is_file() or produced.stat().st_size == 0:
        raise RuntimeError("no speech was recognised, so no subtitle file was written")
    parsed = import_subtitles(produced.read_bytes(), produced.name)
    srt_path.write_text(export_subtitles(parsed["segments"], "srt"), encoding="utf-8")


# ───────────────────────── public API ─────────────────────────

def unavailable_reason() -> str:
    """Empty when subtitles can be created, otherwise why they cannot."""
    if _ocr_helper():
        return ""
    return _whisper_missing()


def create_subtitles(video_path: Path, ffmpeg_bin: str = "ffmpeg") -> tuple:
    """Generate and validate before atomically replacing the SRT; preserve a backup."""
    video_path = Path(video_path)
    srt_path = video_path.with_suffix(".srt")
    with _lock, tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        generated = tmp / "generated.srt"
        try:
            cues = _subtitles_from_picture(video_path, ffmpeg_bin, tmp)
        except Exception as exc:
            print(f"[subtitles] reading the picture failed file={video_path.name} error={exc}")
            cues = []
        if cues:
            _write_srt(cues, generated)
            method = "picture"
        else:
            reason = _whisper_missing()
            if reason:
                raise RuntimeError(f"no subtitles were found in the picture, and speech recognition is unavailable: {reason}")
            _subtitles_from_audio(video_path, ffmpeg_bin, tmp, generated)
            method = "audio"
        parsed = import_subtitles(generated.read_bytes(), generated.name)
        if not parsed['segments']:
            raise RuntimeError("No usable captions were found; the existing subtitle file was kept.")
        staged = srt_path.with_name('.' + srt_path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            staged.write_text(export_subtitles(parsed['segments'], "srt"), encoding="utf-8")
            if srt_path.exists():
                backup = srt_path.with_name(srt_path.name + '.backup-' + uuid.uuid4().hex)
                shutil.copy2(srt_path, backup)
            os.replace(staged, srt_path)
        finally:
            staged.unlink(missing_ok=True)
        return srt_path, method
