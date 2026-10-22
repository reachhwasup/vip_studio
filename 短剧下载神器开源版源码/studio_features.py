"""Local subtitle review APIs. Saving uses optimistic concurrency and a backup."""
import html
import hashlib
import json
import math
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from flask import request, jsonify, Response
from subtitle_formats import import_subtitles, export_subtitles
from subtitles import _lock


def revision(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def register_studio_features(app, local_video_path):
    @app.get('/api/subtitles/track')
    def subtitle_track():
        video = local_video_path(request.args.get('url', ''))
        if video is None:
            return jsonify({'error': 'Saved video not found.'}), 404
        srt = video.with_suffix('.srt')
        if srt.is_symlink() or not srt.is_file():
            return jsonify({'error': 'No saved subtitle file for this episode.'}), 404
        try:
            if srt.stat().st_size > 5 * 1024 * 1024:
                return jsonify({'error': 'Subtitle file exceeds the 5 MB playback limit.'}), 400
            segments = import_subtitles(srt.read_bytes(), srt.name)['segments']
            for cue in segments:
                cue['text'] = html.escape(cue['text'], quote=False)
                cue['speaker'] = html.escape(cue.get('speaker', ''), quote=False)
            return Response(export_subtitles(segments, 'vtt'), mimetype='text/vtt', headers={'Cache-Control': 'no-store'})
        except (OSError, ValueError):
            return jsonify({'error': 'Could not read these subtitles. Review or regenerate them in Library.'}), 400

    @app.route('/api/subtitles/review', methods=['GET', 'POST'])
    def review_subtitles():
        payload = request.args if request.method == 'GET' else request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get('url'), str):
            return jsonify({'error': 'Choose a saved episode.'}), 400
        video = local_video_path(payload['url'])
        if video is None:
            return jsonify({'error': 'Saved video not found.'}), 404
        srt = video.with_suffix('.srt')
        if srt.is_symlink():
            return jsonify({'error': 'Linked subtitle files cannot be edited.'}), 400
        # Do not block requests behind a long OCR job.
        if not _lock.acquire(blocking=False):
            return jsonify({'error': 'Subtitle generation is active. Please try again when it finishes.'}), 409
        try:
            if not srt.is_file():
                return jsonify({'error': 'Create subtitles for this episode first.'}), 404
            if srt.stat().st_size > 5 * 1024 * 1024:
                return jsonify({'error': 'Subtitle file exceeds the 5 MB editor limit.'}), 400
            current = revision(srt)
            if request.method == 'GET':
                result = import_subtitles(srt.read_bytes(), srt.name)
                analysis = {}
                report_path = video.with_suffix('.transcript.json')
                if report_path.is_file() and not report_path.is_symlink() and report_path.stat().st_size <= 10 * 1024 * 1024:
                    try:
                        metadata = json.loads(report_path.read_text(encoding='utf-8'))
                        analysis = metadata.get('analysis', {}) if isinstance(metadata, dict) else {}
                    except (OSError, ValueError):
                        pass
                return jsonify({'segments': result['segments'], 'revision': current, 'analysis': analysis})
            if payload.get('revision') != current:
                return jsonify({'error': 'Subtitles changed since you opened them. Close and reopen the editor before saving.'}), 409
            segments = payload.get('segments')
            if not isinstance(segments, list) or not 1 <= len(segments) <= 5000:
                return jsonify({'error': 'Keep between 1 and 5,000 captions.'}), 400
            checked = []
            for i, cue in enumerate(segments):
                if not isinstance(cue, dict):
                    return jsonify({'error': f'Caption {i + 1} is invalid.'}), 400
                start, end, text = cue.get('start_time'), cue.get('end_time'), cue.get('text')
                valid_time = all(isinstance(t, (int, float)) and not isinstance(t, bool) and math.isfinite(t) for t in (start, end))
                if not valid_time or start < 0 or end <= start or end - start > 30 or not isinstance(text, str) or not text.strip() or len(text) > 10000:
                    return jsonify({'error': f'Caption {i + 1}: enter text and a valid time range of up to 30 seconds.'}), 400
                checked.append({'start_time': start, 'end_time': end, 'text': text.strip(), 'speaker': str(cue.get('speaker') or '')})
            checked.sort(key=lambda cue: (cue['start_time'], cue['end_time']))
            for previous, following in zip(checked, checked[1:]):
                if following['start_time'] < previous['end_time']:
                    return jsonify({'error': 'Caption times overlap. Adjust their start and end times before saving.'}), 400
            content = export_subtitles(checked, 'srt')
            if len(content.encode('utf-8')) > 5 * 1024 * 1024:
                return jsonify({'error': 'Edited subtitles exceed 5 MB.'}), 400
            backup = srt.with_name(srt.name + '.backup-' + uuid.uuid4().hex)
            descriptor, staged = tempfile.mkstemp(prefix='.' + srt.name, suffix='.tmp', dir=srt.parent)
            try:
                with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
                    handle.write(content)
                shutil.copy2(srt, backup)
                os.replace(staged, srt)
            finally:
                Path(staged).unlink(missing_ok=True)
            return jsonify({'revision': revision(srt), 'captions': len(checked), 'segments': checked, 'backup_created': True})
        except (OSError, ValueError) as exc:
            return jsonify({'error': str(exc)}), 500
        finally:
            _lock.release()
