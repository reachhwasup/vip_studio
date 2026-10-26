import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import requests
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '源码_开源版'))
import app as backend

class ThumbnailTests(unittest.TestCase):
    def setUp(self):
        backend._thumbnail_cache.clear()
        self.client = backend.app.test_client()
        self.url = 'https://p6-novel.byteimg.com/novel-pic/test.image'

    def get(self, url=None):
        return self.client.get('/api/thumbnail', query_string={'url': url or self.url})

    def test_image_cached_and_served_with_image_type(self):
        with patch.object(backend, 'fetch_cover_image', return_value=(b'picture', '.jpg')) as fetch:
            for _ in range(2):
                response = self.get()
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data, b'picture')
                self.assertEqual(response.mimetype, 'image/jpeg')
            self.assertEqual(fetch.call_count, 1)

    def test_transient_failure_retries_and_failure_is_not_cached(self):
        with patch.object(backend, 'fetch_cover_image', side_effect=[requests.Timeout(), requests.Timeout(), (b'ok', '.png')]) as fetch:
            response = self.get()
            self.assertEqual(response.status_code, 502)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertEqual(self.get().status_code, 200)
            self.assertEqual(fetch.call_count, 3)

    def test_rejects_non_catalogue_hosts_without_network(self):
        with patch.object(backend.requests, 'get') as fetch:
            for url in ['http://127.0.0.1/private', 'https://byteimg.com.evil.test/image', 'https://example.com/image']:
                self.assertEqual(self.get(url).status_code, 400)
            fetch.assert_not_called()

    def test_cache_is_bounded(self):
        with patch.object(backend, 'fetch_cover_image', return_value=(b'picture', '.webp')):
            for i in range(130):self.get(self.url + str(i))
        self.assertEqual(len(backend._thumbnail_cache), 128)
