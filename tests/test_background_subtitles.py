import sys
import tempfile
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '源码_开源版'))
import app as backend


class BackgroundSubtitleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.video = Path(self.tmp.name) / 'Episode 001.mp4'
        self.video.write_bytes(b'video')
        self.client = backend.app.test_client()
        for target, value in [('SUBTITLE_JOBS', {}), ('local_video_path', lambda url: self.video), ('add_download_cover', lambda *args: None), ('remember_drama', lambda **kwargs: None)]:
            mock = patch.object(backend, target, value); mock.start(); self.addCleanup(mock.stop)

    def test_download_returns_video_and_job_without_calling_inline_subtitles(self):
        with patch.object(backend, 'handle_video_request', return_value={'url': 'http://localhost/src/Episode%20001.mp4'}), patch.object(backend.SUBTITLE_REPAIR_POOL, 'submit') as submit, patch.object(backend, 'add_subtitles') as inline:
            response = self.client.get('/hg?vid=123&subtitles=background')
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json['url'])
            self.assertEqual(response.json['subtitle_job']['status'], 'queued')
            inline.assert_not_called(); submit.assert_called_once()
            duplicate = self.client.get('/hg?vid=123&subtitles=background')
            self.assertEqual(duplicate.json['subtitle_job']['id'], response.json['subtitle_job']['id'])
            submit.assert_called_once()

    def test_existing_srt_is_reused_without_queuing(self):
        self.video.with_suffix('.srt').write_text('existing')
        with patch.object(backend, 'existing_download', return_value={'url': 'http://localhost/src/1.mp4', 'already_on_disk': True}), patch.object(backend.SUBTITLE_REPAIR_POOL, 'submit') as submit:
            response = self.client.get('/hg?vid=123&subtitles=background&skip_existing=1')
            self.assertEqual(response.status_code, 200)
            self.assertIn('subtitle_url', response.json)
            submit.assert_not_called()

    def test_full_subtitle_queue_does_not_fail_saved_video(self):
        backend.SUBTITLE_JOBS.update({str(i): {'key': str(i), 'status': 'queued'} for i in range(200)})
        with patch.object(backend, 'handle_video_request', return_value={'url': 'http://localhost/src/1.mp4'}):
            response = self.client.get('/hg?vid=123&subtitles=background')
        self.assertEqual(response.status_code, 200)
        self.assertIn('subtitle_error', response.json)
        self.assertTrue(response.json['url'])

    def test_library_limit_remains_bounded_and_batch_status_does_not_expose_paths(self):
        backend.SUBTITLE_JOBS.update({str(i): {'key': '/private/' + str(i), 'status': 'queued', 'id': str(i)} for i in range(10)})
        response = self.client.post('/api/subtitles/regenerate', json={'url': '/src/1.mp4'})
        self.assertEqual(response.status_code, 429)
        response = self.client.get('/api/subtitles/status?ids=1,2,missing')
        self.assertEqual(set(response.json['jobs']), {'1', '2'})
        self.assertNotIn('/private', response.get_data(as_text=True))
        self.assertEqual(self.client.get('/api/subtitles/status?ids=' + ','.join(['x'] * 201)).status_code, 400)

    def test_slow_ocr_does_not_block_download_response(self):
        entered, release = threading.Event(), threading.Event()
        def slow_worker(*args):
            entered.set(); release.wait(timeout=5)
        with ThreadPoolExecutor(max_workers=1) as pool, patch.object(backend, 'SUBTITLE_REPAIR_POOL', pool), patch.object(backend, 'run_subtitle_repair', side_effect=slow_worker), patch.object(backend, 'handle_video_request', return_value={'url': 'http://localhost/src/1.mp4'}):
            try:
                response = self.client.get('/hg?vid=123&subtitles=background')
                self.assertEqual(response.status_code, 200)
                self.assertTrue(entered.wait(timeout=1))
                self.assertFalse(release.is_set())
            finally:
                release.set()
