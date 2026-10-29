"""Private loopback backend launched by the native VIP Studio application."""
import os
import sys
import json
from pathlib import Path


def main():
    if '--check-cryptography' in sys.argv:
        # Verify the frozen app's required cipher/signing modules without I/O.
        import hashlib
        import importlib
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import pad, unpad
        key, iv, plain = b'0123456789abcdef', b'0000000000000000', b'VIP Studio cipher check'
        encrypted = AES.new(key, AES.MODE_CBC, iv).encrypt(pad(plain, 16))
        if unpad(AES.new(key, AES.MODE_CBC, iv).decrypt(encrypted), 16) != plain:
            raise RuntimeError('Packaged AES verification failed')
        parser = importlib.import_module('1')
        url, headers, body = parser.sign_json_request_with_liushen('https://example.invalid/check?device_id=1&iid=2', {'check': True}, {'device_id': '1', 'install_id': '2', 'platform': 'android'})
        if not url or not headers.get('x-gorgon') or headers.get('x-ss-stub', '').upper() != hashlib.md5(body).hexdigest().upper():
            raise RuntimeError('Packaged request signing verification failed')
        print(json.dumps({'cryptography': True, 'request_signing': True}))
        return
    if '--check-subtitle-encodings' in sys.argv:
        # Exercise dynamic codec lookup inside the frozen executable, without
        # starting a server or accessing the user's videos or configuration.
        from subtitle_formats import import_subtitles
        checked = []
        for encoding, text in [('utf-8-sig', '你好'), ('utf-16', '你好'), ('utf-16-le', '你好'), ('utf-16-be', '你好'), ('gb18030', '你好，今天的天气很好。'), ('big5', '你好，今天的天氣很好。')]:
            data = ('1\n00:00:01,000 --> 00:00:02,000\n' + text + '\n').encode(encoding)
            parsed = import_subtitles(data, 'check.srt')
            if len(parsed['segments']) != 1 or parsed['segments'][0]['text'] != text:
                raise RuntimeError('Packaged subtitle encoding check failed: ' + encoding)
            checked.append(encoding)
        print(json.dumps({'subtitle_encodings': checked, 'ok': True}))
        return
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
