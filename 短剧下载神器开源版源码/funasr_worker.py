"""Isolated local Chinese ASR worker; invoked with the optional FunASR Python."""
import argparse
import json
import math
import os
import re
from pathlib import Path

MODEL_ROOT = Path.home() / '.cache' / 'short-drama-downloader' / 'funasr'


def _word_ends(text):
    # The optional runtime already uses Jieba for Chinese punctuation. If it
    # is unavailable, punctuation remains the safe boundary fallback.
    try:
        import jieba
    except ImportError:
        return set()
    return {end for _, _, end in jieba.tokenize(text)}


def sentence_segments(results):
    """Attach punctuation to ASR token timestamps, preserving the exact text.

    FunASR's sentence splitter can count punctuation tokens differently from
    Chinese character timestamps. Align surface units explicitly; reject a
    mismatch instead of distributing words over VAD intervals.
    """
    segments = []
    for result in results:
        text = str(result.get('text') or '').strip()
        units = list(re.finditer(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*|[^\W_]", text))
        timestamps = result.get('timestamp') or []
        if not units or len(units) != len(timestamps):
            raise RuntimeError('Chinese text and speech timestamps could not be aligned; the existing subtitles were kept.')
        times = []
        for pair in timestamps:
            try:
                start, end = float(pair[0]), float(pair[1])
            except (IndexError, TypeError, ValueError):
                raise RuntimeError('The Chinese model returned invalid speech timestamps.')
            if not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end:
                raise RuntimeError('The Chinese model returned invalid speech timestamps.')
            if times and start < times[-1][1] - 50:
                raise RuntimeError('The Chinese model returned overlapping speech timestamps.')
            times.append((start, end))
        first = 0
        word_ends = _word_ends(text)
        for i, unit in enumerate(units):
            next_start = units[i + 1].start() if i + 1 < len(units) else len(text)
            suffix = text[unit.end():next_start]
            # Commas belong inside a readable statement. A pause alone is
            # weaker evidence than punctuation, especially inside conditional
            # sentences. Keep clear short responses/speaker calls separate.
            count = i - first + 1
            span = times[i][1] - times[first][0]
            terminal = bool(re.search(r'[。！？.!?]', suffix))
            clause = bool(re.search(r'[，；,;]', suffix)) and (span >= 6500 or count >= 36)
            gap = times[i + 1][0] - times[i][1] if i + 1 < len(times) else 0
            following = text[next_start:] if i + 1 < len(units) else ''
            next_clause = re.split(r'[，。！？；,.!?;]', following, maxsplit=1)[0].strip()
            short_turn = next_clause in {'爹', '爸', '妈', '娘', '哥', '姐', '师父', '喂', '嗯', '哼', '住手', '慢着', '等等'}
            boundary = unit.end() in word_ends and count >= 2
            pause = boundary and (gap >= 1200 and count >= 4 or gap >= 600 and short_turn)
            if terminal or clause or pause or i + 1 == len(units):
                segments.append({
                    'start_time': round(times[first][0] / 1000, 3),
                    'end_time': round(times[i][1] / 1000, 3),
                    'text': text[units[first].start():next_start].strip(),
                })
                first = i + 1
    if not segments:
        raise RuntimeError('Paraformer returned no timed sentences; the existing subtitles were kept.')
    return segments


def progress(stage):
    print('VIP_ASR_STAGE ' + stage, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('audio')
    parser.add_argument('output')
    args = parser.parse_args()
    progress('Loading local Chinese speech models')
    from funasr import AutoModel
    threads = max(1, min(4, int(os.getenv('VIP_SUBTITLE_THREADS', '2'))))
    common = dict(device='cpu', ncpu=threads, disable_update=True)
    recognizer = AutoModel(model=str(MODEL_ROOT / 'paraformer-zh'), **common)
    detector = AutoModel(model=str(MODEL_ROOT / 'fsmn-vad'), max_single_segment_time=15000, **common)
    punctuator = AutoModel(model=str(MODEL_ROOT / 'ct-punc'), **common)
    aligner = AutoModel(model=str(MODEL_ROOT / 'fa-zh'), **common)
    import soundfile as sf
    audio, rate = sf.read(args.audio, dtype='float32')
    if rate != 16000 or audio.ndim != 1:
        raise RuntimeError('Expected 16 kHz mono audio.')
    progress('Detecting Chinese speech sections')
    detected = detector.generate(input=audio)
    spans = detected[0].get('value', []) if detected else []
    segments = []
    print(f'VIP_ASR_PROGRESS 0/{len(spans)}', flush=True)
    for index, (start, end) in enumerate(spans):
        chunk = audio[int(start * rate / 1000):int(end * rate / 1000)]
        recognized = recognizer.generate(input=chunk)
        raw = str(recognized[0].get('text') or '').strip() if recognized else ''
        if raw:
            punctuated = punctuator.generate(input=raw)
            aligned = aligner.generate(input=(chunk, raw), data_type=('sound', 'text'))
            if not punctuated or not aligned:
                raise RuntimeError('Chinese phrase alignment failed; the existing subtitles were kept.')
            text = punctuated[0]['text']
            # Alignment may normalize text; reject changed words instead of
            # assigning a timestamp to a different recognized character.
            content = lambda value: ''.join(m.group() for m in re.finditer(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*|[^\W_]", value))
            if content(text) != content(aligned[0]['text']):
                raise RuntimeError('Chinese alignment changed the recognized words; review the audio with Whisper instead.')
            times = [[a + start, b + start] for a, b in aligned[0]['timestamp']]
            segments.extend(sentence_segments([{'text': text, 'timestamp': times}]))
        print(f'VIP_ASR_PROGRESS {index + 1}/{len(spans)}', flush=True)
    if not segments:
        raise RuntimeError('No Chinese speech was recognised; the existing subtitles were kept.')
    progress('Building timed Chinese subtitle phrases')
    Path(args.output).write_text(json.dumps(segments, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
