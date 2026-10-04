import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码_开源版'))
import app as backend

HTML='''<article><a href="/detail?series_id=123"><img src="https://example.com/cover.jpg"><span class="pc-badge-number-test">1</span></a><a href="/detail?series_id=123"><h2>Drama</h2></a><p class="pc-categories-test"><span>爱情</span></p></article>'''
class TrendingTests(unittest.TestCase):
    def test_parser_deduplicates_ranked_articles(self):
        items=backend.parse_trending(HTML+HTML)
        self.assertEqual(len(items),1)
        self.assertEqual(items[0]['title'],'Drama')
        self.assertEqual(items[0]['rank'],1)
        self.assertEqual(items[0]['drama_id'],'123')
    def test_cache_and_refresh(self):
        with patch.object(backend,'_trending_cache',(0,[])),patch.object(backend,'fetch_text',return_value=HTML) as fetch:
            client=backend.app.test_client()
            self.assertEqual(client.get('/api/trending').status_code,200)
            self.assertEqual(client.get('/api/trending').status_code,200)
            self.assertEqual(fetch.call_count,1)
            self.assertEqual(client.get('/api/trending?refresh=1').status_code,200)
            self.assertEqual(fetch.call_count,2)
    def test_invalid_source_returns_error(self):
        with patch.object(backend,'_trending_cache',(0,[])),patch.object(backend,'fetch_text',return_value='no ranking'),patch.object(backend.app.logger,'exception'):
            response=backend.app.test_client().get('/api/trending')
            self.assertEqual(response.status_code,502)
            self.assertIn('error',response.json)
