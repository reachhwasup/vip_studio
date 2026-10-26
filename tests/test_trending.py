import sys
import unittest
import tempfile
import json
import time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码_开源版'))
import app as backend

HTML='''<article><a href="/detail?series_id=123"><img src="https://example.com/cover.jpg"><span class="pc-badge-number-test">1</span></a><a href="/detail?series_id=123"><h2>Drama</h2></a><p class="pc-categories-test"><span>爱情</span></p></article>'''
class TrendingTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.cache=Path(tmp.name)/'trending_cache.json'
        patcher=patch.object(backend,'trending_cache_path',return_value=self.cache)
        patcher.start();self.addCleanup(patcher.stop)

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

    def test_stalled_primary_retries_alternate_ranking_url(self):
        with patch.object(backend,'_trending_cache',(0,[])),patch.object(backend,'fetch_text',side_effect=[backend.requests.Timeout('stalled'),HTML]) as fetch:
            response=backend.app.test_client().get('/api/trending')
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.json['items']),1)
        self.assertEqual(fetch.call_args_list[1].args[0],backend.TRENDING_URL+'?refresh=1')
        self.assertEqual(fetch.call_args_list[0].kwargs['timeout'],(4,6))
        self.assertTrue(self.cache.is_file())

    def test_offline_refresh_keeps_saved_rankings_and_timestamp(self):
        items=backend.parse_trending(HTML);updated=time.time()-3600
        with patch.object(backend,'_trending_cache',(updated,items)),patch.object(backend,'fetch_text',side_effect=backend.requests.ConnectionError('offline')):
            response=backend.app.test_client().get('/api/trending?refresh=1')
        self.assertEqual(response.status_code,200);self.assertTrue(response.json['stale'])
        self.assertEqual(response.json['items'],items);self.assertEqual(response.json['updated_at'],updated)

    def test_restart_can_reuse_saved_rankings_when_source_is_offline(self):
        items=backend.parse_trending(HTML);updated=time.time()-3600
        self.cache.write_text(json.dumps({'items':items,'updated_at':updated}))
        with patch.object(backend,'_trending_cache',(0,[])),patch.object(backend,'fetch_text',side_effect=backend.requests.ConnectionError('offline')):
            response=backend.app.test_client().get('/api/trending')
        self.assertEqual(response.status_code,200);self.assertTrue(response.json['stale'])
        self.assertEqual(response.json['items'][0]['title'],'Drama')

    def test_corrupt_cache_does_not_prevent_fresh_rankings(self):
        self.cache.write_text('not json')
        with patch.object(backend,'_trending_cache',(0,[])),patch.object(backend,'fetch_text',return_value=HTML):
            response=backend.app.test_client().get('/api/trending')
        self.assertEqual(response.status_code,200);self.assertFalse(response.json['stale'])
