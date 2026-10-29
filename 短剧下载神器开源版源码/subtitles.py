"""Create a Chinese .srt subtitle file for a downloaded video.

Two methods, both running locally (nothing is uploaded):

1. Picture (preferred, macOS): Hongguo videos have their subtitles drawn into the picture.
   Frames are sampled and read with the system's text recognition (subtitle_ocr.swift),
   to recover the displayed text; recognition and sampled timing can be imperfect.
2. Audio (automatic gap recovery or audio-only): speech recognition with whisper.cpp, for videos without drawn-in
   subtitles. Timing and wording are approximate.

Environment overrides:
  WHISPER_BIN    path to whisper-cli            (default: whisper-cli on PATH)
  WHISPER_MODEL  path to the ggml model file    (default: ~/.cache/whisper-cpp/ggml-large-v3-turbo.bin)
  WHISPER_VAD    path to the silero VAD model   (default: ~/.cache/whisper-cpp/ggml-silero-v5.1.2.bin)
"""
import collections
import hashlib
from difflib import SequenceMatcher
import copy
from contextlib import contextmanager
import re
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

OCR_SOURCE = Path(__file__).resolve().parent / "subtitle_ocr.swift"
OCR_BINARY = Path.home() / ".cache" / "short-drama-downloader" / "subtitle_ocr"
OCR_FPS = 8  # frames read per second of video; a caption's start and end are accurate to about 1/(2*OCR_FPS) seconds
OCR_DROPOUT = 0.4  # seconds a caption may go unread (a flash, a fade, a missed short word) without being split in two
OCR_STACK = 1  # Read each frame separately: stacking can hide short captions from Vision.
OCR_WIDTH = 1280  # frames wider than this are scaled down before reading; small text needs the pixels
OCR_CENTRE = 0.4  # middle share of the strip read again when nothing was found: a lone word is missed in a wide picture
PROBE_TOP = 0.45  # the probe pass looks for the subtitle row in the picture below this height
MIN_CUES_PER_MINUTE = 3  # fewer than this from the picture means there are no drawn-in subtitles

# One job at a time: both methods already use every core / the whole GPU.
_lock = threading.Lock()
# Where the subtitles sit in each series' picture, so later episodes skip the search: folder -> (top, height).
_strip_cache: dict = {}
_analysis_cache: dict = {}


_review_store = None


def configure_review_store(store):
    """Use the app's SQLite job database; never add report files to video folders."""
    global _review_store
    _review_store = store


def analysis_revision(srt):
    return f"{srt.stat().st_mtime_ns}:{hashlib.sha256(srt.read_bytes()).hexdigest()}"


def subtitle_analysis(video_path):
    """Review hints for this exact SRT revision, including across app restarts."""
    video_path = Path(video_path)
    key = str(video_path.resolve())
    srt = video_path.with_suffix('.srt')
    saved = _analysis_cache.get(key)
    try:
        if saved and saved[0] == srt.stat().st_mtime_ns:
            return copy.deepcopy(saved[1])
        if _review_store is not None and _review_store.path.exists():
            return _review_store.load_analysis(key, analysis_revision(srt))
    except (OSError, ValueError):
        pass
    return {}


_progress_state = threading.local()


@contextmanager
def _progress_session(callback, cpu_threads=2):
    previous = getattr(_progress_state, 'callback', None)
    previous_threads = getattr(_progress_state, 'cpu_threads', 2)
    _progress_state.callback = callback
    _progress_state.cpu_threads = cpu_threads
    try:
        yield
    finally:
        _progress_state.callback = previous
        _progress_state.cpu_threads = previous_threads


def _notify_progress(stage, percent=None, completed=None, total=None):
    callback = getattr(_progress_state, 'callback', None)
    if callback:
        callback({'stage': stage, 'progress': percent, 'completed': completed, 'total': total})


def _ocr_stage(command):
    name = Path(command[1]).name
    if name.startswith('probe'):
        return 'Finding caption area'
    if name.startswith('centre'):
        return 'Checking missed captions'
    if name.endswith('cached'):
        return 'Rechecking on-screen captions'
    return 'Reading on-screen captions'


def _run(command: list, capture: bool = False) -> str:
    environment = dict(os.environ)
    threads = str(getattr(_progress_state, 'cpu_threads', 2))
    for name in ('VIP_SUBTITLE_THREADS', 'OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
        environment[name] = threads
    streaming = getattr(_progress_state, 'callback', None) and (capture or '-pp' in command)
    if streaming:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace', env=environment)
        output, errors = [], collections.deque(maxlen=10)
        for line in process.stdout:
            ocr = re.match(r'VIP_OCR_PROGRESS ([0-9]+)/([0-9]+)', line.strip())
            speech = re.search(r'progress\s*=\s*([0-9]+)%', line)
            asr_progress = re.match(r'VIP_ASR_PROGRESS ([0-9]+)/([0-9]+)', line.strip())
            if asr_progress:
                completed, total = map(int, asr_progress.groups())
                if total > 0 and 0 <= completed <= total:
                    _notify_progress(f'Transcribing Chinese phrases ({completed}/{total} speech sections)', round(completed / total * 100, 1))
            elif line.startswith('VIP_ASR_STAGE '):
                _notify_progress(line.strip().removeprefix('VIP_ASR_STAGE '), None)
            elif ocr:
                completed, total = map(int, ocr.groups())
                if total > 0 and 0 <= completed <= total:
                    _notify_progress(_ocr_stage(command), round(completed / total * 100, 1), completed, total)
            elif '-pp' in command and speech:
                _notify_progress('Transcribing speech locally', min(100, int(speech.group(1))))
            elif capture and line.lstrip().startswith('{'):
                try:
                    record = json.loads(line)
                except ValueError:
                    errors.append(line.strip())
                else:
                    if isinstance(record, dict) and 'file' in record and isinstance(record.get('lines'), list):
                        output.append(line)
            else:
                errors.append(line.strip())
        close = getattr(process.stdout, 'close', None)
        if callable(close):
            close()
        if process.wait() != 0:
            raise RuntimeError(f"{Path(command[0]).name} failed: {(errors[-1] if errors else 'no error output')[:200]}")
        return ''.join(output)
    done = subprocess.run(
        command, stdout=subprocess.PIPE if capture else subprocess.DEVNULL, stderr=subprocess.PIPE,
        text=True, errors="replace", env=environment,
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

    Returns one record per sampled frame, in order, each {"lines": [...]} with boxes as fractions of
    the strip. Frame i shows the picture at i / fps: rounding up makes ffmpeg keep the last source
    frame at or before that instant. Strips are stacked `stack` to an image.
    """
    folder.mkdir()
    strip = f"fps={fps}:round=up,crop=iw:ih*{height:.4f}:0:ih*{top:.4f},scale='min(iw,{width})':-2,tile=1x{stack}"
    _notify_progress('Extracting video frames', None)
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


def _reread_centre(helper: str, video_path: Path, ffmpeg_bin: str, fps: float, top: float, height: float, folder: Path, frames: list) -> None:
    """Read the middle of the strip again in frames where no centred text was found.

    Text recognition overlooks a one- or two-character caption in a wide picture for several
    frames, which makes short captions start late, end early or go missing. It reads them when
    given only the middle of the strip. Readings are added to `frames` in whole-strip fractions.
    """
    centred = lambda line: abs(line["x"] + line["w"] / 2 - 0.5) < 0.25
    empty = {i for i, frame in enumerate(frames) if not any(centred(line) for line in frame["lines"])}
    if not empty:
        return
    folder.mkdir()
    left = (1 - OCR_CENTRE) / 2
    crop = f"fps={fps}:round=up,crop=iw*{OCR_CENTRE}:ih*{height:.4f}:iw*{left}:ih*{top:.4f}"
    _notify_progress('Preparing a check for missed captions', None)
    _run([ffmpeg_bin, "-y", "-v", "error", "-i", str(video_path), "-vf", crop, "-q:v", "4", str(folder / "%06d.jpg")])
    for image in folder.glob("*.jpg"):
        if int(image.stem) - 1 not in empty:
            image.unlink()
    for output in _run([helper, str(folder)], capture=True).splitlines():
        if not output.strip():
            continue
        record = json.loads(output)
        index = int(Path(record["file"]).stem) - 1
        for line in record["lines"]:
            # Text running off either side is the middle of a longer line, not a short caption.
            if index < len(frames) and line["x"] > 0.04 and line["x"] + line["w"] < 0.96:
                frames[index]["lines"].append(dict(line, x=left + line["x"] * OCR_CENTRE, w=line["w"] * OCR_CENTRE))


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


def _caption_rows(lines: list) -> list:
    """Keep the lines on the caption row; drop signs, badges and other text that is part of the scene.

    Captions keep one size, one centre and one row (two for wrapped captions) through a video.
    Text in the scene that drifts into the strip is a different size, off-centre or off that row.
    """
    sure = [line for _, line in lines if line["conf"] >= 0.5] or [line for _, line in lines]
    if len(sure) < 8:
        return lines
    middle = lambda values: sorted(values)[len(values) // 2]
    across = lambda line: line["x"] + line["w"] / 2
    down = lambda line: line["y"] + line["h"] / 2
    height = middle([line["h"] for line in sure])
    sized = lambda line: 0.6 * height <= line["h"] <= 1.6 * height
    bins = collections.Counter(round(down(line) / (height / 2)) for line in sure if sized(line))
    main, most = bins.most_common(1)[0]
    on_row = [line for line in sure if sized(line) and abs(down(line) / (height / 2) - main) <= 1]
    centre, row = middle([across(line) for line in on_row]), middle([down(line) for line in on_row])
    # A second row counts only when it is the next line up or down and used regularly.
    rows = [row] + [b * height / 2 for b, count in bins.items() if 0.8 * height <= abs(b * height / 2 - row) <= 1.6 * height and count >= 0.2 * most]
    return [
        (i, line) for i, line in lines
        if sized(line) and abs(across(line) - centre) <= 0.1 and any(abs(down(line) - r) <= 0.5 * height for r in rows)
    ]


def _content(text: str) -> str:
    return ''.join(c for c in text if not c.isspace() and not unicodedata.category(c).startswith('P'))


def _same_line(a: str, b: str) -> bool:
    # Only ignore spacing and punctuation, never differing letters or characters.
    return a == b or bool(_content(a)) and _content(a) == _content(b)


def _same_caption(a: str, b: str) -> bool:
    """Two readings of one caption: the same line, or the same line with a character misread.

    A caption on screen is sometimes read differently from frame to frame (去三吧 / 去兰吧), with
    一 taken for a dash, or with a stray mark from the picture at either end. The sentence keeps
    its length when that happens, so a different length is a different sentence
    (我喜欢你 / 我不喜欢你) and is kept. Numbers are never treated as misreadings (还有3天 / 还有2天).
    """
    if _same_line(a, b):
        return True
    a, b = (_content(re.sub(r'[-－—–─]', '一', text)) for text in (a, b))
    if a == b:
        return True
    if len(a) != len(b):
        # A letter or symbol or two picked up beside a Chinese caption is not part of it.
        short, long = sorted((a, b), key=len)
        extra = long[:-len(short)] if long.endswith(short) else long[len(short):] if long.startswith(short) else ''
        return len(short) >= 3 and 0 < len(extra) <= 2 and extra.isascii() and not extra.isdigit() and not short.isascii()
    if len(a) < 3:
        return False
    differing = [(x, y) for x, y in zip(a, b) if x != y]
    return len(differing) <= max(1, len(a) // 8) and not any(x.isdigit() or y.isdigit() for x, y in differing)


def _cues_from_frames(records: list, fps: float, min_frames: int = 2) -> list:
    """Merge runs of frames showing the same caption into [start, end, text] cues."""
    per_frame = [[] for _ in records]
    for i, line in _caption_rows(_dialogue_lines(records, min_conf=0.3, fps=fps)):
        per_frame[i].append(line)
    texts = [
        "".join(line["text"].strip() for line in sorted(frame, key=lambda l: (round(l["y"], 2), l["x"])))
        for frame in per_frame
    ]
    confidence = [min((line['conf'] for line in frame), default=0) for frame in per_frame]
    dropout = max(1, round(OCR_DROPOUT * fps))  # frames a caption may go unread inside one cue
    # The reading seen most often wins; confidence only settles a tie.
    reading = lambda run: max(run["seen"], key=lambda text: (run["seen"][text], run["sure"][text]))

    runs = []
    for i, text in enumerate(texts):
        if not text:
            continue
        if runs and i - runs[-1]["last"] - 1 <= dropout and _same_caption(reading(runs[-1]), text):
            run = runs[-1]
        else:
            run = {"first": i, "last": i, "seen": collections.Counter(), "sure": collections.Counter(), "best": 0}
            runs.append(run)
        run["last"] = i
        run["seen"][text] += 1
        run["sure"][text] += confidence[i]
        run["best"] = max(run["best"], confidence[i])

    kept = []
    for run in runs:
        # Keep brief, confidently recognised captions; reject isolated OCR noise.
        observations = sum(run["seen"].values())
        if not ((observations >= min_frames and run["best"] >= 0.5) or observations >= max(3, min_frames) or run["best"] >= 0.85):
            continue
        # The same caption again after rejected noise or a brief dropout is still one caption.
        if kept and run["first"] - kept[-1]["last"] - 1 <= dropout and _same_caption(reading(kept[-1]), reading(run)):
            kept[-1]["last"] = run["last"]
            kept[-1]["seen"] += run["seen"]
            kept[-1]["sure"] += run["sure"]
        else:
            kept.append(run)

    # A caption first read in frame `first` appeared between that sample and the one before, and one
    # last read in frame `last` went between that sample and the next: place each edge midway.
    cues = [[max(0.0, (run["first"] - 0.5) / fps), (run["last"] + 0.5) / fps, reading(run)] for run in kept]
    for cue, following in zip(cues, cues[1:]):
        cue[1] = min(cue[1], following[0])
    return cues


def _subtitles_from_picture(video_path: Path, ffmpeg_bin: str, tmp: Path) -> list:
    helper = _ocr_helper()
    if not helper:
        return []
    series = video_path.parent
    best_cues = []
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
        _reread_centre(helper, video_path, ffmpeg_bin, OCR_FPS, strip[0], strip[1], tmp / f"centre_{attempt}", frames)
        cues = _cues_from_frames(frames, OCR_FPS)
        if len(cues) > len(best_cues):
            best_cues = cues
        minutes = len(frames) / OCR_FPS / 60
        if len(cues) >= MIN_CUES_PER_MINUTE * minutes:
            _strip_cache[series] = strip
            return cues
        _strip_cache.pop(series, None)  # the remembered position did not work for this episode; search again
    return best_cues


def _srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def _write_srt(cues: list, srt_path: Path) -> None:
    segments = normalize_segments([{"start_time": a, "end_time": b, "text": text} for a, b, text in cues])
    if not segments:
        raise RuntimeError("No usable timed dialogue was recognised.")
    srt_path.write_text(export_subtitles(segments, "srt"), encoding="utf-8")


# ───────────────────────── audio method ─────────────────────────

FUNASR_PYTHON = Path(os.getenv('FUNASR_PYTHON', str(Path.home() / '.local/share/short-drama-downloader/funasr-venv/bin/python')))
FUNASR_ROOT = Path.home() / '.cache' / 'short-drama-downloader' / 'funasr'


def _funasr_missing() -> str:
    if not FUNASR_PYTHON.is_file():
        return 'The optional Chinese speech engine is not installed.'
    if any(not (FUNASR_ROOT / name / 'model.pt').is_file() for name in ('paraformer-zh', 'fsmn-vad', 'ct-punc', 'fa-zh')):
        return 'The Chinese speech models have not finished downloading.'
    return ''


def _subtitles_from_funasr(video_path, ffmpeg_bin, tmp, srt_path):
    reason = _funasr_missing()
    if reason:
        raise RuntimeError(reason)
    wav = tmp / 'funasr-audio.wav'
    output = tmp / 'funasr-result.json'
    _notify_progress('Preparing audio for Chinese transcription', None)
    _run([ffmpeg_bin, '-y', '-v', 'error', '-i', str(video_path), '-vn',
          '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(wav)])
    _run([str(FUNASR_PYTHON), str(Path(__file__).with_name('funasr_worker.py')), str(wav), str(output)], capture=True)
    rows = normalize_segments(json.loads(output.read_text(encoding='utf-8')))
    if not rows:
        raise RuntimeError('No Chinese speech was recognised; the existing subtitles were kept.')
    srt_path.write_text(export_subtitles(rows, 'srt'), encoding='utf-8')


def _whisper_missing() -> str:
    if not shutil.which(WHISPER_BIN):
        return "whisper.cpp is not installed (run: brew install whisper.cpp)"
    if not MODEL_PATH.is_file():
        return f"speech model not found at {MODEL_PATH}"
    return ""


def _subtitles_from_audio(video_path: Path, ffmpeg_bin: str, tmp: Path, srt_path: Path, language: str = "zh") -> None:
    # whisper.cpp wants 16 kHz mono PCM.
    wav_path = tmp / "audio.wav"
    _notify_progress('Preparing audio', None)
    _run([ffmpeg_bin, "-y", "-v", "error", "-i", str(video_path),
          "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav_path)])

    out_base = tmp / "subtitles"
    command = [WHISPER_BIN, "-m", str(MODEL_PATH), "-f", str(wav_path), "-l", language,
               "-osrt", "-of", str(out_base), "-pp"]
    if VAD_MODEL_PATH.is_file():
        # Voice detection keeps lines from starting during silence or music.
        command += ["--vad", "--vad-model", str(VAD_MODEL_PATH)]
    _notify_progress('Transcribing speech locally', 0)
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


def refine_picture_phrases(picture, speech):
    """Use speech boundaries only when the complete on-screen wording agrees.

    Never distribute words proportionally or merge based only on a short gap.
    Disagreements remain untouched for the existing speech review workflow.
    """
    result = [dict(cue) for cue in picture]
    grouped = 0
    for spoken in speech:
        start, end = spoken['start_time'], spoken['end_time']
        if not 0 < end - start <= 8:
            continue
        indexes = [i for i, cue in enumerate(result)
                   if cue['start_time'] < end and cue['end_time'] > start]
        if len(indexes) == 1:
            i = indexes[0]
            row = result[i]
            # Borrow punctuation only for the same complete Chinese utterance.
            # Keep OCR's actual characters, spaces, speaker and timestamps.
            if (abs(row['start_time'] - start) <= 0.6
                    and abs(row['end_time'] - end) <= 0.6
                    and re.search(r'[\u3400-\u9fff]', row['text'])
                    and _content(row['text']) == _content(spoken['text'])
                    and not re.search(r'[.!?。！？។…]', row['text'])
                    and not re.search(r'\n|^(?:[-–—]\s|[^:：]{1,24}[:：])', row['text'])
                    and not re.search(r'\n|^(?:[-–—]\s|[^:：]{1,24}[:：])', spoken['text'])):
                # Only add a final sentence mark; internal punctuation can imply
                # unverified sentence/speaker boundaries.
                ending = re.search(r'([。！？!?])["”’\')]*$', spoken['text'])
                if ending:
                    result[i] = dict(row, text=row['text'].rstrip('，,；; ') + ending.group(1))
            continue
        if len(indexes) < 2:
            continue
        rows = [result[i] for i in indexes]
        # Both sources must agree about the whole phrase and its time window.
        if abs(rows[0]['start_time'] - start) > 0.6 or abs(rows[-1]['end_time'] - end) > 0.6:
            continue
        if any(not -0.05 <= b['start_time'] - a['end_time'] <= 0.5
               for a, b in zip(rows, rows[1:])):
            continue
        if any(re.search(r'[.!?。！？។…]["”’\')]*$', row['text']) for row in rows[:-1]):
            continue
        # Dialogue markers may signal a speaker change not represented by ASR.
        if any(re.match(r'^(?:[-–—]\s|[^:：]{1,24}[:：])', row['text']) for row in rows):
            continue
        if len({row.get('speaker') for row in rows if row.get('speaker')}) > 1:
            continue
        if not all(row.get('speaker') for row in rows):
            continue
        original = ''.join(row['text'] for row in rows)
        source, heard = _content(original), _content(spoken['text'])
        if source != heard and (min(len(source), len(heard)) < 10 or SequenceMatcher(None, source, heard).ratio() < 0.88):
            continue
        # Keep the displayed wording and timing. Borrow punctuation only when
        # every recognized word agrees, never an ASR spelling of a person's name.
        if source == heard:
            text = spoken['text']
        elif re.search(r'[\u3400-\u9fff]', original):
            text = original
        else:
            text = ' '.join(row['text'] for row in rows)
        merged = dict(rows[0], end_time=rows[-1]['end_time'], text=text)
        result[indexes[0]:indexes[-1] + 1] = [merged]
        grouped += len(rows) - 1
    return result, grouped


def merge_picture_and_speech(picture, speech):
    """Keep OCR timings intact; add whole spoken cues only in uncovered intervals.

    Partly overlapping speech is retained as a review candidate, not squeezed into
    an arbitrary gap that could assign words to the wrong moment.
    """
    merged = [dict(cue, source='picture') for cue in picture]
    added, review = [], []
    for cue in speech:
        overlaps = [x for x in merged if x['start_time'] < cue['end_time'] and x['end_time'] > cue['start_time']]
        if not overlaps:
            item = dict(cue, source='audio')
            merged.append(item); added.append(item)
        elif not any(_content(x['text']) == _content(cue['text']) for x in overlaps):
            # One spoken phrase can span multiple OCR captions without changing
            # speaker boundaries. An exact full-window match is agreement.
            ordered = sorted(overlaps, key=lambda x: (x['start_time'], x['end_time']))
            if (abs(ordered[0]['start_time'] - cue['start_time']) <= 0.6
                    and abs(ordered[-1]['end_time'] - cue['end_time']) <= 0.6
                    and all(-0.05 <= b['start_time'] - a['end_time'] <= 0.5
                            for a, b in zip(ordered, ordered[1:]))
                    and _content(''.join(x['text'] for x in ordered)) == _content(cue['text'])):
                if not all(x.get('speaker') for x in ordered) or len({x.get('speaker') for x in ordered}) > 1:
                    review.append(dict(cue, reason='Speech wording matches these on-screen captions. Their separate caption breaks were retained; review speaker turns before joining or dubbing.'))
                continue
            review.append(dict(cue, reason='Speech and on-screen captions overlap or disagree. Review against the video.'))
    merged.sort(key=lambda x: (x['start_time'], x['end_time']))
    return merged, added, review


def statement_issues(cues):
    """Flag likely fragments and crowded captions; do not guess missing words."""
    issues = []
    for index, cue in enumerate(cues):
        text = cue['text'].strip()
        duration = cue['end_time'] - cue['start_time']
        reason = None
        if duration > 8 or len(_content(text)) / max(duration, 0.1) > 25:
            reason = 'Caption may be too long or too fast to read.'
        if index + 1 < len(cues):
            following = cues[index + 1]
            gap = following['start_time'] - cue['end_time']
            unfinished = re.search(r'(?:既然|如果|因为|为了|等到|虽然|但是|竟|直|把|被|的|要|将|就)$', text.rstrip('，, '))
            if unfinished and 0 <= gap <= 1.2:
                reason = 'This caption may end mid-statement. Compare it with the next caption and use Join next if they belong together.'
        if reason:
            issues.append(dict(cue, reason=reason))
    return issues


SUBTITLE_MODES = ('recommended', 'speech', 'auto', 'picture', 'audio', 'funasr', 'hybrid')

def preferred_download_mode():
    """Cheap capability check; never compile OCR or load models in a download request."""
    return 'hybrid' if not _funasr_missing() else 'auto'


def resolve_subtitle_mode(mode, language='zh'):
    """Download and Library share one smart choice; use just one speech engine."""
    if mode not in ('recommended', 'speech'):
        return mode  # Retain explicit engine choices from existing saved jobs.
    selected = preferred_download_mode() if language == 'zh' else 'auto'
    if mode == 'speech':
        return 'funasr' if selected == 'hybrid' else 'audio'
    return selected


def capabilities():
    reason = _whisper_missing()
    return {'speech_available': not reason, 'speech_reason': reason, 'ocr_available': bool(_ocr_helper()), 'funasr_available': not _funasr_missing(), 'funasr_reason': _funasr_missing()}


def create_subtitles(video_path: Path, ffmpeg_bin: str = "ffmpeg", mode: str = 'auto',
                     language: str = 'zh', report=None, progress=None, cpu_threads=2) -> tuple:
    """OCR plus speech gap recovery, or explicit OCR/audio; save only valid results."""
    requested_mode = mode
    mode = resolve_subtitle_mode(mode, language)
    if mode not in ('auto', 'picture', 'audio', 'funasr', 'hybrid') or language not in ('zh', 'en', 'auto'):
        raise ValueError('Choose a supported subtitle mode and spoken language.')
    if mode in ('funasr', 'hybrid') and language != 'zh':
        raise ValueError('Choose Chinese as the spoken language for Paraformer.')
    if isinstance(cpu_threads, bool) or cpu_threads not in (1, 2, 4):
        raise ValueError('Choose a supported CPU mode.')
    report = report if report is not None else {}
    report.update(warnings=[], phrase_joins=0, audio_added=0, review_candidates=[], mode=mode, requested_mode=requested_mode, language=language)
    progress = progress or (lambda stage: None)
    video_path = Path(video_path)
    srt_path = video_path.with_suffix('.srt')
    with _lock, _progress_session(progress, cpu_threads), tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        generated = tmp / 'generated.srt'
        cues = []
        if mode not in ('audio', 'funasr'):
            progress('Reading on-screen captions')
            try:
                cues = _subtitles_from_picture(video_path, ffmpeg_bin, tmp)
            except Exception:
                report['warnings'].append('On-screen caption recognition failed; speech recognition will be tried in automatic mode.')
        picture = normalize_segments([{'start_time': a, 'end_time': b, 'text': text} for a, b, text in cues])
        speech = []
        if mode == 'funasr':
            report['warnings'].append('Paraformer does not identify speaker turns. A caption can contain two voices; review speaker boundaries before translating or dubbing. Use video text when available to retain its caption breaks.')
        if mode == 'hybrid' and not picture:
            report['warnings'].append('No on-screen captions were recognised; speech could not be cross-checked against the picture.')
        if mode in ('funasr', 'hybrid'):
            try:
                _subtitles_from_funasr(video_path, ffmpeg_bin, tmp, generated)
                speech = import_subtitles(generated.read_bytes(), generated.name)['segments']
                report['speech_engine'] = 'paraformer'
            except Exception as exc:
                if not picture:
                    raise
                report['warnings'].append('Chinese speech comparison failed; kept on-screen captions. ' + str(exc))
        elif mode != 'picture':
            reason = _whisper_missing()
            if reason:
                if not picture:
                    raise RuntimeError('Speech recognition is unavailable: ' + reason)
                report['warnings'].append('Audio was not checked: ' + reason + '. Missing spoken captions may remain.')
            else:
                progress('Transcribing speech locally')
                try:
                    audio_path = tmp / 'speech.srt'
                    _subtitles_from_audio(video_path, ffmpeg_bin, tmp, audio_path, language=language)
                    speech = import_subtitles(audio_path.read_bytes(), audio_path.name)['segments']
                    report['speech_engine'] = 'whisper'
                except Exception as exc:
                    if not picture:
                        raise
                    report['warnings'].append('Speech transcription failed; kept the on-screen captions. ' + str(exc))
        progress('Checking and combining captions')
        if picture and speech:
            refined, joins = refine_picture_phrases(picture, speech)
            report['phrase_joins'] = joins
            combined, added, review = merge_picture_and_speech(refined, speech)
            report.update(audio_added=len(added), review_candidates=review)
            method = 'hybrid'
        elif picture:
            combined = [dict(x, source='picture') for x in picture]; method = 'picture'
        else:
            combined = [dict(x, source='audio') for x in speech]; method = 'funasr' if mode in ('funasr', 'hybrid') else 'audio'
        if not combined:
            raise RuntimeError('No usable dialogue was recognised; the existing subtitles were kept.')
        report.update(picture_captions=len(picture), speech_captions=len(speech), method=method)
        report['quality_issues'] = statement_issues(combined)
        report['quality_state'] = 'needs_review' if report['review_candidates'] or report['quality_issues'] or report['warnings'] else 'ready'
        generated.write_text(export_subtitles(combined, 'srt'), encoding='utf-8')
        parsed = import_subtitles(generated.read_bytes(), generated.name)
        if not parsed['segments']:
            raise RuntimeError("No usable captions were found; the existing subtitle file was kept.")
        progress('Saving subtitle file')
        staged = srt_path.with_name('.' + srt_path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            staged.write_text(export_subtitles(parsed['segments'], "srt"), encoding="utf-8")
            if srt_path.exists():
                backup = srt_path.with_name(srt_path.name + '.backup-' + uuid.uuid4().hex)
                shutil.copy2(srt_path, backup)
            os.replace(staged, srt_path)
        finally:
            staged.unlink(missing_ok=True)
        # Save review hints against this exact SRT, without extra media sidecars.
        key = str(video_path.resolve())
        if key not in _analysis_cache and len(_analysis_cache) >= 100:
            _analysis_cache.pop(next(iter(_analysis_cache)))
        _analysis_cache[key] = (srt_path.stat().st_mtime_ns, copy.deepcopy(report))
        if _review_store is not None and _review_store.path.exists():
            try:
                _review_store.save_analysis(key, analysis_revision(srt_path), report)
            except Exception as exc:
                report['warnings'].append('Review hints could not be saved for restart: ' + str(exc))
                report['quality_state'] = 'needs_review'
                _analysis_cache[key] = (srt_path.stat().st_mtime_ns, copy.deepcopy(report))
        return srt_path, method
