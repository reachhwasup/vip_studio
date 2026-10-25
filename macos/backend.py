"""Private loopback backend launched by the native VIP Studio application."""
import os
import sys
import json
from pathlib import Path


def main():
    # Keep all subprocesses in a separate group so Quit stops FFmpeg as well.
    if os.getpgrp() != os.getpid():
        os.setsid()
    resources = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    data = Path(os.environ['VIP_STUDIO_DATA_DIR'])
    data.mkdir(parents=True, exist_ok=True)
    os.environ['OPEN_BROWSER'] = '0'
    os.environ['FFMPEG_BIN'] = str(resources / 'ffmpeg')
    os.environ['VIP_STUDIO_OCR_BIN'] = str(resources / 'subtitle_ocr')
    os.environ['PATH'] = '/opt/homebrew/bin:/usr/local/bin:' + os.environ.get('PATH', '/usr/bin:/bin')
    # A new installation saves videos outside the read-only application bundle.
    config = data / 'config.json'
    if not config.exists():
        folder = Path.home() / 'Movies' / 'VIP Studio'
        folder.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps({'download_path': str(folder)}))
        config.chmod(0o600)
    import app
    app.initialize_subtitle_jobs()
    @app.app.get('/api/desktop/activity')
    def desktop_activity():
        from flask import jsonify
        with app.SUBTITLE_JOBS_LOCK:
            jobs_busy = any(job['status'] in ('queued', 'running') for job in app.SUBTITLE_JOBS.values())
        return jsonify({'busy': bool(app.parser_module.DOWNLOAD_PROGRESS) or jobs_busy})
    from werkzeug.serving import make_server
    server = make_server('127.0.0.1', 5056, app.app, threaded=True)
    Path(os.environ['VIP_STUDIO_READY_FILE']).write_text('http://127.0.0.1:5056')
    server.serve_forever()


if __name__ == '__main__':
    main()
