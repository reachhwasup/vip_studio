import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '源码_开源版'))
import app as backend


class DownloadCoverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.runtime = patch.object(backend.parser_module, 'get_runtime_base_dir', return_value=self.root)
        self.runtime.start()
        self.video = self.root / 'src' / 'Drama' / 'Episode 001.mp4'
        self.video.parent.mkdir(parents=True)
        self.video.write_bytes(b'unchanged video')
        self.url = '/src/Drama/Episode%20001.mp4'

    def tearDown(self):
        self.runtime.stop()
        self.tmp.cleanup()

    def test_saves_sidecar_and_serves_without_modifying_video(self):
        with patch.object(backend, 'fetch_cover_image', return_value=(b'poster', '.jpg')):
            result = {'url': self.url, 'pic': 'https://p3-novel.byteimg.com/poster'}
            backend.add_download_cover(result)
        self.assertEqual((self.video.parent / 'poster.jpg').read_bytes(), b'poster')
        self.assertEqual(self.video.read_bytes(), b'unchanged video')
        with backend.app.test_client().get(result['cover_url']) as response:
            self.assertEqual(response.data, b'poster')

    def test_reuses_saved_cover_and_prevents_traversal(self):
        self.video.with_suffix('.png').write_bytes(b'existing')
        with patch.object(backend, 'fetch_cover_image') as fetch:
            result = {'url': self.url}
            backend.add_download_cover(result)
            fetch.assert_not_called()
        self.assertTrue(result['cover_url'].endswith('.png'))
        self.assertIsNone(backend.local_video_path('/src/../private.mp4'))

    def test_failure_is_nonfatal_and_falls_back_to_api_picture(self):
        with patch.object(backend, 'fetch_cover_image', side_effect=[ValueError('bad first'), (b'poster', '.webp')]):
            result = {'url': self.url, 'pic': 'fallback'}
            backend.add_download_cover(result, 'preferred')
            self.assertIn('cover_url', result)
        (self.video.parent / 'poster.webp').unlink()
        with patch.object(backend, 'fetch_cover_image', side_effect=ValueError('bad')):
            result = {'url': self.url, 'pic': 'fallback'}
            backend.add_download_cover(result)
            self.assertEqual(result['cover_error'], 'bad')
            self.assertTrue(self.video.exists())

    def test_whole_series_concurrent_downloads_fetch_cover_once(self):
        from concurrent.futures import ThreadPoolExecutor
        urls = []
        for number in range(1, 5):
            (self.video.parent / f'Episode {number:03}.mp4').write_bytes(b'video')
            urls.append(f'/src/Drama/Episode%20{number:03}.mp4')
        def save(url):
            result = {'url': url, 'pic': 'https://p3-novel.byteimg.com/poster'}
            backend.add_download_cover(result)
            return result['cover_url']
        with patch.object(backend, 'fetch_cover_image', return_value=(b'poster', '.jpg')) as fetch:
            with ThreadPoolExecutor(max_workers=4) as pool:
                covers = list(pool.map(save, urls))
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(set(covers), {'/src/Drama/poster.jpg'})
        self.assertEqual(len(list(self.video.parent.glob('*.jpg'))), 1)

    def test_migrates_identical_legacy_covers_and_keeps_old_links(self):
        other = self.video.parent / 'Episode 002.mp4'
        other.write_bytes(b'video')
        for video in [self.video, other]:
            video.with_suffix('.jpg').write_bytes(b'old poster')
        with patch.object(backend, 'fetch_cover_image') as fetch:
            result = {'url': self.url}
            backend.add_download_cover(result)
            fetch.assert_not_called()
        self.assertEqual(result['cover_url'], '/src/Drama/poster.jpg')
        self.assertEqual([x.name for x in self.video.parent.glob('*.jpg')], ['poster.jpg'])
        with backend.app.test_client().get('/src/Drama/Episode%20002.jpg') as response:
            self.assertEqual(response.data, b'old poster')

    def test_existing_shared_poster_is_never_downloaded_again(self):
        (self.video.parent / 'poster.png').write_bytes(b'custom existing poster')
        with patch.object(backend, 'fetch_cover_image') as fetch:
            result = {'url': self.url, 'pic': 'new cover'}
            backend.add_download_cover(result)
            fetch.assert_not_called()
        self.assertEqual(result['cover_url'], '/src/Drama/poster.png')
        self.assertEqual((self.video.parent / 'poster.png').read_bytes(), b'custom existing poster')

    def test_only_public_catalogue_images_are_fetched(self):
        with patch.object(backend.requests, 'get') as get:
            for url in ['http://127.0.0.1/private', 'https://byteimg.com.evil.test/x', 'file:///tmp/x', 'https://byteimg.com:8080/x']:
                with self.assertRaises(ValueError):
                    backend.fetch_cover_image(url)
            get.assert_not_called()
        response = MagicMock()
        response.__enter__.return_value = response
        response.is_redirect = False
        response.iter_content.return_value = [b'<!doctype html>error']
        with patch.object(backend.requests, 'get', return_value=response), self.assertRaises(ValueError):
            backend.fetch_cover_image('https://p3-novel.byteimg.com/image')

    def test_single_episode_request_saves_api_cover(self):
        with patch.object(backend, 'handle_video_request', return_value={'url': self.url, 'pic': 'https://p3-novel.byteimg.com/poster'}), patch.object(backend, 'fetch_cover_image', return_value=(b'poster', '.jpg')):
            response = backend.app.test_client().get('/hg?vid=single-episode')
        self.assertEqual(response.status_code, 200)
        self.assertIn('cover_url', response.json)


if __name__ == '__main__':
    unittest.main()
