import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '源码_开源版'))
import app as backend


class SearchValidationTests(unittest.TestCase):
    def test_invalid_pages_return_json_without_searching(self):
        with patch.object(backend, 'search_short_drama') as search:
            for page in ['abc', '-1', '0', '1.5', True, [], None]:
                with self.subTest(page=page):
                    response = backend.app.test_client().post('/api/search', json={'page': page})
                    self.assertEqual(response.status_code, 400)
                    self.assertIsNotNone(response.json)
            search.assert_not_called()

    def test_invalid_payload_returns_json(self):
        for payload in [[], ['keyword'], 'text', 42]:
            response = backend.app.test_client().post('/api/search', json=payload)
            self.assertEqual(response.status_code, 400)
            self.assertIsNotNone(response.json)

    def test_get_and_post_valid_pages(self):
        with patch.object(backend, 'search_short_drama', return_value=[]) as search:
            client = backend.app.test_client()
            for response in [client.get('/api/search?page=2'), client.post('/api/search', json={'page': 2})]:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json['page'], 2)
            self.assertEqual(search.call_count, 2)

    def test_invalid_get_page(self):
        response = backend.app.test_client().get('/api/search?page=oops')
        self.assertEqual(response.status_code, 400)
        self.assertIsNotNone(response.json)
