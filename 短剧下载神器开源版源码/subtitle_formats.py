"""Timed subtitle import/export. Times are timeline positions; no trim offset is applied."""
import collections
import html
import json
import math
import re
from pathlib import Path
from charset_normalizer import from_bytes

FORMATS = {'.srt', '.vtt', '.ass', '.ssa', '.json'}
TIME = r'(?:\d+:)?\d{1,2}:\d{1,2}(?:[.,]\d+)?'
TIMING = re.compile(r'^\s*(' + TIME + r')\s*-->\s*(' + TIME + r')(?:\s+.*)?$')
PREFIX = re.compile(r'^\s*(?:\[([^\]\n]{1,30})\]|【([^】\n]{1,30})】|([^:\n：]{1,30})[:：])\s*(\S.*)$')
SOUND = re.compile(r'^(?:music|background music|instrumental|silence|applause|laughter|laughing|sighs?|sighing|gasps?|gasping|screams?|screaming|crying|sobbing|footsteps|door (?:opens|closes|slams)|phone ringing|thunder|wind|音乐|音樂|背景音乐|背景音樂|掌声|掌聲|笑声|笑聲|叹气|嘆氣|脚步声|腳步聲|敲门声|敲門聲|铃声|鈴聲|哭声|哭聲|静音|靜音)$', re.I)


def decode_subtitles(data):
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        return data.decode('utf-16'), 'UTF-16'
    try:
        if b'\x00' not in data:
            return data.decode('utf-8-sig'), 'UTF-8'
    except UnicodeDecodeError:
        pass
    if b'\x00' in data:
        for encoding in ('utf-16-le', 'utf-16-be'):
            try:
                text = data.decode(encoding)
                if '-->' in text or '[Events]' in text or '"segments"' in text:
                    return text, encoding.upper()
            except UnicodeDecodeError:
                pass
    match = from_bytes(data, cp_isolation=['gb18030', 'big5']).best()
    if match is None:
        raise ValueError('Could not read this encoding. Save the file as UTF-8 and try again.')
    return str(match), match.encoding.upper()


def seconds(value):
    if isinstance(value, bool):
        raise ValueError('Invalid time')
    if isinstance(value, (int, float)):
        result = float(value)
    else:
        parts = str(value).replace(',', '.').split(':')
        if len(parts) not in (2, 3):
            raise ValueError('Invalid timestamp')
        numbers = [float(x) for x in parts]
        if any(x < 0 for x in numbers) or numbers[-1] >= 60 or (len(parts) == 3 and numbers[-2] >= 60):
            raise ValueError('Invalid timestamp')
        result = sum(n * 60 ** i for i, n in enumerate(reversed(numbers)))
    if not math.isfinite(result) or result < 0:
        raise ValueError('Invalid time')
    return result


def clean_text(text, ass=False):
    text = str(text or '')
    if ass:
        drawing = False
        output = []
        for part in re.split(r'(\{[^}]*\})', text):
            if part.startswith('{'):
                modes = re.findall(r'\\p(\d+)\b', part)
                if modes:
                    drawing = int(modes[-1]) > 0
            elif not drawing:
                output.append(part)
        text = ''.join(output).replace(r'\N', '\n').replace(r'\n', '\n').replace(r'\h', ' ')
    text = re.sub(r'<[^>]*>', '', text)
    return html.unescape(text).strip()


def sound_only(line):
    value = line.strip()
    if not value or re.fullmatch(r'[♪♫♬\s]+', value):
        return True
    # Brackets alone do not imply sound: retain dialogue and unidentified labels.
    if (value.startswith('[') and value.endswith(']')) or (value.startswith('(') and value.endswith(')')) or (value.startswith('【') and value.endswith('】')):
        return bool(SOUND.fullmatch(value[1:-1].strip()))
    return False


def parse_timed(text):
    cues = []
    current = None
    blocked = False
    for line in text.splitlines():
        if not line.strip():
            current = None
            blocked = False
            continue
        if re.match(r'^WEBVTT(?:\s|$)', line):
            continue
        if re.match(r'^(NOTE(?:\s|$)|STYLE\s*$|REGION\s*$)', line):
            blocked = True
            current = None
            continue
        if blocked:
            continue
        timing = TIMING.match(line)
        if timing:
            if current and current['text'].split('\n')[-1].strip().isdigit():
                current['text'] = '\n'.join(current['text'].split('\n')[:-1])
            current = {'start_time': timing[1], 'end_time': timing[2], 'text': ''}
            cues.append(current)
        elif current is not None:
            current['text'] += ('\n' if current['text'] else '') + line
    return cues


def parse_ass(text):
    fields = []
    events = False
    cues = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('['):
            events = line.lower() == '[events]'
        if not events or line.startswith(';'):
            continue
        if line.lower().startswith('format:'):
            fields = [x.strip().lower() for x in line.split(':', 1)[1].split(',')]
        elif line.lower().startswith('dialogue:'):
            columns = fields or ['layer', 'start', 'end', 'style', 'name', 'marginl', 'marginr', 'marginv', 'effect', 'text']
            # Text can contain commas, even with a reordered Format declaration.
            if not all(x in columns for x in ('start', 'end', 'text')):
                continue
            index = columns.index('text')
            values = line.split(':', 1)[1].lstrip().split(',', index)
            if len(values) <= index:
                continue
            tail = values.pop().rsplit(',', len(columns) - index - 1) if index < len(columns) - 1 else [values.pop()]
            values += tail
            if len(values) != len(columns):
                continue
            row = dict(zip(columns, values))
            cues.append({'start_time': row['start'], 'end_time': row['end'], 'text': clean_text(row['text'], ass=True), 'speaker': row.get('name', '').strip()})
    return cues


def normalize_segments(cues):
    candidates = []
    for cue in cues:
        if not isinstance(cue, dict):
            continue
        try:
            start, end = seconds(cue.get('start_time')), seconds(cue.get('end_time'))
        except (ValueError, TypeError):
            continue
        start, end = round(start, 3), round(min(end, start + 30), 3)
        if end <= start:
            continue
        text = str(cue.get('text') or '')
        voice = re.search(r'<v(?:\.[^\s>]+)*\s+([^>]+)>', text, re.I)
        speaker = str(cue.get('speaker') or (html.unescape(voice[1]).strip() if voice else ''))
        lines = [line.strip() for line in clean_text(text).splitlines() if not sound_only(line)]
        if not lines:
            continue
        original = clean_text(cue.get('original_text', ''))
        candidates.append(dict(start_time=start, end_time=end, text='\n'.join(lines), original_text=original, speaker=speaker))
    matches = [PREFIX.match(line) for cue in candidates if not cue['speaker'] for line in cue['text'].splitlines()]
    names = collections.Counter(next(x for x in m.groups()[:3] if x) for m in matches if m)
    recurring = {name for name, count in names.items() if count >= 2}
    use_prefixes = sum(names[name] for name in recurring) >= 3
    output, seen = [], set()
    for cue in candidates:
        # Split lines by speaker, retaining the exact timeline position for each line.
        groups = []
        for line in cue['text'].splitlines():
            speaker = cue['speaker']
            match = PREFIX.match(line) if use_prefixes and not speaker else None
            if match:
                name = next(x for x in match.groups()[:3] if x)
                if name in recurring:
                    speaker, line = name, match[4]
            key = (cue['start_time'], line, speaker, cue['original_text'])
            if key in seen or sound_only(line):
                continue
            seen.add(key)
            if groups and groups[-1]['speaker'] == speaker:
                groups[-1]['text'] += '\n' + line
            else:
                groups.append(dict(cue, text=line, speaker=speaker))
        output.extend(groups)
    return sorted(output, key=lambda cue: cue['start_time'])


def import_subtitles(data, filename):
    suffix = Path(filename).suffix.lower()
    if suffix not in FORMATS:
        raise ValueError('Choose a timed .srt, .vtt, .ass, .ssa or .json file. Plain text without timings is not supported.')
    text, encoding = decode_subtitles(data)
    if suffix == '.json':
        try:
            payload = json.loads(text)
        except (ValueError, TypeError) as exc:
            raise ValueError('Invalid subtitle JSON.') from exc
        if not isinstance(payload, dict) or not isinstance(payload.get('segments'), list):
            raise ValueError('Subtitle JSON must contain a segments array.')
        cues = payload['segments']
    elif suffix in {'.ass', '.ssa'}:
        cues = parse_ass(text)
    else:
        cues = parse_timed(text)
    segments = normalize_segments(cues)
    if not segments:
        raise ValueError('No usable timed dialogue found in this file.')
    return {'segments': segments, 'encoding': encoding, 'format': suffix[1:]}


def timestamp(value, dot=False):
    ms = round(float(value) * 1000)
    return '%02d:%02d:%02d%s%03d' % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, '.' if dot else ',', ms % 1000)


def export_subtitles(segments, format_name):
    if format_name == 'json':
        return json.dumps({'segments': segments}, ensure_ascii=False, indent=2)
    if format_name not in {'srt', 'vtt', 'ass', 'ssa'}:
        raise ValueError('Unsupported export format.')
    if format_name in {'ass', 'ssa'}:
        version = 'v4.00' if format_name == 'ssa' else 'v4.00+'
        layer = 'Marked' if format_name == 'ssa' else 'Layer'
        marker = 'Marked=0' if format_name == 'ssa' else '0'
        header = f'[Script Info]\nScriptType: {version}\n\n[Events]\nFormat: {layer}, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
        def ass_time(t):
            return timestamp(t, True)[:-1]
        def ass_text(t):
            return str(t).replace('\\', '＼').replace('{', '｛').replace('}', '｝').replace('\n', r'\N')
        return header + ''.join(f"Dialogue: {marker},{ass_time(c['start_time'])},{ass_time(c['end_time'])},Default,{ass_text(c.get('speaker', '')).replace(',', '，')},0,0,0,,{ass_text(c['text'])}\n" for c in segments)
    blocks = []
    for i, cue in enumerate(segments, 1):
        text = html.escape(cue['text'], quote=False)
        speaker = html.escape(cue.get('speaker', ''), quote=False)
        if speaker:
            text = f'<v {speaker}>{text}</v>' if format_name == 'vtt' else f'{speaker}: {text}'
        blocks.append(f"{i}\n{timestamp(cue['start_time'], format_name == 'vtt')} --> {timestamp(cue['end_time'], format_name == 'vtt')}\n{text}\n")
    return ('WEBVTT\n\n' if format_name == 'vtt' else '') + '\n'.join(blocks)
