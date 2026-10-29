import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '源码_开源版'))
import app as backend
import gz360
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad


class GZ360Tests(unittest.TestCase):
    def setUp(self):
        gz360._cache.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runtime = patch.object(backend.parser_module, 'get_runtime_base_dir', return_value=self.root)
        self.runtime.start()
        self.client = backend.app.test_client()
    def tearDown(self):
        self.runtime.stop()
        self.temp.cleanup()
    def data(self, path, payload):
        if path.endswith('GetVodInfo'):
            return {'vodInfo': {'vod_name':'Example','pic':'https://img2.ms39pn.com/a.jpg'}}
        return {'urls':[{'vurl_id':101,'name':'1','url':'https://cdn.example/1.m3u8'},
                        {'vurl_id':103,'name':'3','url':'https://cdn.example/3.m3u8'}]}
    def test_identifiers_and_host_validation(self):
        for value in ['gz360:123','https://gz360.tv/videoDetail/123?from=search']:
            self.assertEqual(gz360.identify(value), ('123',None))
        self.assertEqual(gz360.identify('gz360:123:456'),('123','456'))
        for value in ['123','https://gz360.tv.evil.test/videoDetail/123','https://elsewhere.test/videoDetail/123','gz360:../x']:
            self.assertIsNone(gz360.identify(value))
    def test_api_uses_public_protocol_without_authentication(self):
        encrypted=AES.new(gz360.KEY,AES.MODE_CBC,gz360.IV).encrypt(pad(b'{"list":[]}',16)).hex()
        response=Mock(json=Mock(return_value={'code':200,'data':encrypted}))
        with patch.object(gz360.requests,'post',return_value=response) as post:
            self.assertEqual(gz360.call('Search/GetConditionList',{'page':2}),{'list':[]})
            request=post.call_args.kwargs['json']['params']
            decoded=json.loads(unpad(AES.new(gz360.KEY,AES.MODE_CBC,gz360.IV).decrypt(bytes.fromhex(request)),16))
            self.assertEqual(decoded,{'page':2})
    def test_search_routes_source_and_requests_50_results(self):
        with patch.object(gz360,'call',return_value={'list':[{'vod_id':'12','vod_name':'A','tags':['短剧']} ]}) as call:
            response=self.client.get('/api/search?source=gz360&page=2&keyword=test')
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json['items'][0]['drama_id'],'gz360:12')
            self.assertEqual(call.call_args.args[1]['pageSize'],50)
            self.assertEqual(call.call_args.args[1]['page'],2)
    def test_detail_preserves_missing_episode_numbers_and_saves_history(self):
        with patch.object(gz360,'call',side_effect=self.data):
            response=self.client.get('/api/episodes?id=gz360:12')
            self.assertEqual(response.status_code,200)
            self.assertEqual([e['ep'] for e in response.json['episodes']],[1,3])
            self.assertNotIn('stream_url',response.json['episodes'][0])
            self.assertEqual(self.client.get('/api/drama-history').json['items'][0]['series_id'],'gz360:12')
    def test_download_resolves_only_source_episode_and_keeps_existing_file(self):
        with patch.object(gz360,'call',side_effect=self.data), patch.object(backend.parser_module,'stream_copy_video_with_ffmpeg',return_value='http://localhost/test.mp4') as stream, patch.object(backend,'add_download_cover'), patch.object(backend,'local_video_path',return_value=None), patch.object(backend,'handle_video_request') as hongguo:
            response=self.client.get('/hg?vid=gz360:12:103')
            self.assertEqual(response.status_code,200)
            self.assertEqual(stream.call_args.args[1],'https://cdn.example/3.m3u8')
            self.assertIn('Episode 003.mp4',stream.call_args.args[3])
            hongguo.assert_not_called()
            with patch.object(backend,'existing_download',return_value={'url':'http://localhost/saved.mp4','already_on_disk':True}):
                response=self.client.get('/hg?vid=gz360:12:103&skip_existing=1')
                self.assertTrue(response.json['already_on_disk'])
                self.assertEqual(stream.call_count,1)
    def test_unavailable_streams_are_rejected(self):
        for episode in [{'app_only':True,'stream_url':'https://example.test/a.mp4'},{'stream_url':'file:///tmp/a.mp4'},{'stream_url':'https://example.test/player.html'}]:
            with self.assertRaises(ValueError): gz360.playable_url(episode)

    def test_empty_source_playlist_has_clear_unavailability_warning(self):
        def data(path,payload):
            return self.data(path,payload) if path.endswith('GetVodInfo') else {'total_vod_vurl':'0','urls':[]}
        with patch.object(gz360,'call',side_effect=data):
            response=self.client.get('/api/episodes?id=gz360:156823')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['episodes'],[])
        self.assertEqual(response.json['total'],0)
        self.assertIn('no episode playback links',response.json['episode_warning'])

    def test_search_does_not_advertise_declared_episode_count_without_playback(self):
        rows=[{'vod_id':'1','vod_name':'Unavailable','d_total':24,'vurlList':[]},
              {'vod_id':'2','vod_name':'Available','d_total':24,'vurlList':[{'vurl_id':10},{'vurl_id':11}]},
              {'vod_id':'3','vod_name':'Unknown','d_total':24}]
        with patch.object(gz360,'call',return_value={'list':rows}):items=gz360.search('',1)
        self.assertEqual(items[0]['episodes'],'No episodes available')
        self.assertFalse(items[0]['downloadable'])
        self.assertEqual(items[0]['availability'],'unavailable')
        self.assertEqual(items[1]['episodes'],'2 episodes')
        self.assertTrue(items[1]['downloadable'])
        self.assertEqual(items[2]['availability'],'unknown')
        self.assertEqual(items[2]['episodes'],'Check episode availability')
