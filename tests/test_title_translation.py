import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '源码_开源版'))
from title_translation import translate_title
import app as backend


class TitleTranslationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cache = Path(self.temp.name) / 'english_titles.json'
    def tearDown(self):
        self.temp.cleanup()
    def response(self, **changes):
        data = {'responseStatus': 200, 'responseData': {'translatedText': 'Return of the Warrior'}}
        data.update(changes)
        return Mock(json=Mock(return_value=data))
    def test_translation_is_cached_across_calls(self):
        with patch('title_translation.requests.get', return_value=self.response()) as get:
            self.assertEqual(translate_title('战神归来', self.cache), 'Return of the Warrior')
            self.assertEqual(translate_title('战神归来', self.cache), 'Return of the Warrior')
            self.assertEqual(get.call_count, 1)
            self.assertEqual(get.call_args.kwargs['params']['langpair'], 'zh-CN|en')
    def test_english_needs_no_network(self):
        with patch('title_translation.requests.get') as get:
            self.assertEqual(translate_title('The Return', self.cache), 'The Return')
            get.assert_not_called()
    def test_quota_and_invalid_results_are_not_cached(self):
        for response in [self.response(quotaFinished=True), self.response(responseStatus=429), self.response(responseData={'translatedText':'战神归来'}), Mock(json=Mock(return_value=[]))]:
            with patch('title_translation.requests.get', return_value=response):
                with self.assertRaises(ValueError): translate_title('战神归来', self.cache)
            self.assertFalse(self.cache.exists())
    def test_large_title_rejected(self):
        with self.assertRaises(ValueError): translate_title('中'*200, self.cache)
    def test_download_passes_english_name_to_resolver(self):
        with patch.object(backend, 'translate_title', return_value='Warrior Returns'), patch.object(backend, 'handle_video_request', return_value={'url':'https://example.test/video.mp4'}) as resolve, patch.object(backend, 'add_download_cover'), patch.object(backend, 'local_video_path', return_value=None):
            result=backend.app.test_client().get('/hg',query_string={'vid':'123','series':'战神归来','episode':'2','english_title':'1'})
            self.assertEqual(result.status_code,200)
            self.assertEqual(resolve.call_args.kwargs['output_series'],'Warrior Returns')
            self.assertEqual(result.json['original_title'],'战神归来')
            self.assertEqual(result.json['series_name'],'Warrior Returns')
    def test_translation_failure_does_not_start_download(self):
        with patch.object(backend,'translate_title',side_effect=ValueError('Daily limit reached')), patch.object(backend,'handle_video_request') as resolve:
            result=backend.app.test_client().get('/hg?vid=123&series=test&english_title=1')
            self.assertEqual(result.status_code,500)
            resolve.assert_not_called()

    def test_english_filename_is_used_for_direct_episode(self):
        with backend.app.test_request_context('/hg?episode=2'), patch.object(backend.parser_module, 'resolve_video_url', return_value={}) as resolve:
            backend.parser_module.handle_video_request('123', backend.request, output_series='Warrior Returns')
            self.assertEqual(resolve.call_args.kwargs['output_relpath'], 'Warrior Returns/Warrior Returns - Episode 002.mp4')
    def test_english_filename_is_used_for_series_url(self):
        with backend.app.test_request_context('/hg?ep=2'), patch.object(backend.parser_module, 'get_hongguo_series_detail', return_value={'title':'战神归来','vid_list':['1','2']}), patch.object(backend.parser_module, 'resolve_video_url', return_value={}) as resolve:
            backend.parser_module.handle_video_request('https://example.test/series', backend.request, output_series='Warrior Returns')
            self.assertEqual(resolve.call_args.kwargs['output_relpath'], 'Warrior Returns/Warrior Returns - Episode 002.mp4')
