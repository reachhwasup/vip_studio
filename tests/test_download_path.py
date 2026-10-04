"""Run with: python3 -m unittest discover -s tests."""
import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '源码_开源版'))
backend = importlib.import_module('app')


class DownloadPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.runtime = patch.object(backend.parser_module, 'get_runtime_base_dir', return_value=self.root)
        self.runtime.start()
        self.client = backend.app.test_client()

    def tearDown(self):
        self.runtime.stop()
        self.temp.cleanup()

    def save_folder(self, name):
        folder = self.root / name
        response = self.client.post('/api/download-path', json={'download_path': str(folder)})
        self.assertEqual(response.status_code, 200)
        return folder

    def test_picker_selection_cancel_and_failure(self):
        for selected in [str(self.root), '']:
            with patch.object(backend, 'choose_download_folder', return_value=selected):
                response = self.client.post('/api/download-path/browse')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['download_path'], selected)
            self.assertEqual(response.json['cancelled'], not bool(selected))
            self.assertNotIn('download_path', backend.read_local_config())
        with patch.object(backend, 'choose_download_folder', side_effect=RuntimeError('Picker unavailable')):
            self.assertEqual(self.client.post('/api/download-path/browse').status_code, 400)
        self.assertFalse(backend.FOLDER_PICKER_LOCK.locked())

    def test_picker_rejects_remote_and_duplicate_requests(self):
        with patch.object(backend, 'choose_download_folder') as picker:
            response = self.client.post('/api/download-path/browse', headers={'Origin': 'https://example.com'})
            self.assertEqual(response.status_code, 403)
            response = self.client.post('/api/download-path/browse', environ_overrides={'REMOTE_ADDR': '192.0.2.1'})
            self.assertEqual(response.status_code, 403)
            with backend.FOLDER_PICKER_LOCK:
                self.assertEqual(self.client.post('/api/download-path/browse').status_code, 409)
            picker.assert_not_called()

    def test_folder_and_credentials_preserve_each_other(self):
        folder = self.save_folder('dramas with spaces')
        self.assertTrue(folder.is_dir())
        response = self.client.post('/api/config', json={'device_id': '123', 'install_id': '456'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(backend.parser_module.get_download_dir(), folder)
        self.save_folder('next')
        self.assertEqual(backend.read_local_config()['device_id'], '123')

    def test_invalid_paths_leave_saved_setting_unchanged(self):
        folder = self.save_folder('valid')
        file = self.root / 'not-a-folder'
        file.write_text('test')
        for value in ['', 'relative/path', str(file), '\x00', None]:
            response = self.client.post('/api/download-path', json={'download_path': value})
            self.assertEqual(response.status_code, 400)
        self.assertEqual(backend.parser_module.get_download_dir(), folder)

    def test_old_links_and_subtitles_after_folder_change(self):
        folder = self.save_folder('first')
        video = folder / 'Episode 001.mp4'
        video.write_bytes(b'video')
        key = backend.parser_module.download_root_key(folder)
        url = f'/downloads/{key}/Episode%20001.mp4'
        self.save_folder('second')
        with self.client.get(url) as response:
            self.assertEqual(response.data, b'video')
        subtitle = video.with_suffix('.srt')
        def create(path, ffmpeg):
            self.assertEqual(path, video)
            subtitle.write_text('captions')
            return subtitle, 'picture'
        result = {'url': 'http://localhost' + url}
        with patch.object(backend, 'create_subtitles', side_effect=create):
            backend.add_subtitles(result)
        with self.client.get(result['subtitle_url']) as response:
            self.assertEqual(response.data, b'captions')
        self.assertEqual(self.client.get(f'/downloads/{key}/../../config.json').status_code, 404)
        outside = self.root / 'private.mp4'
        outside.write_bytes(b'private')
        (folder / 'escape.mp4').symlink_to(outside)
        self.assertEqual(self.client.get(f'/downloads/{key}/escape.mp4').status_code, 404)

    def test_video_pipeline_uses_selected_folder_without_cleanup(self):
        folder = self.save_folder('videos')
        parser = backend.parser_module
        with patch.object(parser.subprocess, 'Popen') as process, patch.object(parser, 'schedule_video_cleanup') as cleanup:
            process.return_value.stdout = []
            def finish_download():
                Path(process.call_args.args[0][-1]).write_bytes(b'completed video')
                return 0
            process.return_value.wait.side_effect = finish_download
            url = parser.stream_copy_video_with_ffmpeg('http://localhost', 'https://example.test/video', None, 'Drama/Episode 001.mp4')
            self.assertEqual((folder / 'Drama/Episode 001.mp4').read_bytes(), b'completed video')
            self.assertFalse(Path(process.call_args.args[0][-1]).exists())
            self.assertIn('/downloads/' + parser.download_root_key(folder) + '/', url)
            cleanup.assert_not_called()


if __name__ == '__main__':
    unittest.main()
