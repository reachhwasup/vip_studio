import sys,json,tempfile,unittest,time
from pathlib import Path
from unittest.mock import patch,Mock
import requests
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码_开源版'))
import app
p=app.parser_module
SID='7696095984266251326'
def response(vids=None):
 data={'loaderData':{'detail_page':{'seriesDetail':{'series_name':'Drama','vid_list':vids or ['123','456']}}}}
 return Mock(status_code=200,text='<script>window._ROUTER_DATA= '+json.dumps(data)+'</script>',raise_for_status=Mock())
class EpisodeDetailsTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  for name,value in [('_app_series_detail',Mock(side_effect=ValueError('not available'))),('get_runtime_base_dir',lambda:Path(self.tmp.name)),('_SERIES_CACHE',{})]:
   patcher=patch.object(p,name,value);patcher.start();self.addCleanup(patcher.stop)
 def test_retries_connection_failure_and_accepts_marker_spacing(self):
  with patch.object(p.requests,'get',side_effect=[requests.ConnectionError('offline'),response()]) as get,patch.object(p.time,'sleep'):
   detail=p.get_hongguo_series_detail(SID)
  self.assertEqual(detail['vid_list'],['123','456']);self.assertEqual(get.call_count,2)
 def test_network_failure_is_not_reported_as_missing_drama(self):
  with patch.object(p.requests,'get',side_effect=requests.Timeout()),patch.object(p.time,'sleep'):
   result=app.app.test_client().get('/api/episodes?id='+SID)
  self.assertEqual(result.status_code,502);self.assertIn('retry',result.json['error'])
 def test_saved_list_survives_restart_and_temporary_network_outage(self):
  with patch.object(p.requests,'get',return_value=response()):
   result=app.app.test_client().get('/api/episodes?id='+SID)
  self.assertEqual(result.status_code,200)
  history=app.read_drama_history();self.assertEqual(history[0]['vid_list'],['123','456'])
  history[0]['fetched_at']=0
  Path(self.tmp.name,'drama_history.json').write_text(json.dumps(history))
  p._SERIES_CACHE.clear()
  with patch.object(p.requests,'get',side_effect=requests.ConnectionError()):
   result=app.app.test_client().get('/api/episodes?id='+SID)
  self.assertEqual(result.status_code,200);self.assertTrue(result.json['episode_warning']);self.assertEqual(len(result.json['episodes']),2)
 def test_expired_cache_refreshes_with_new_episodes(self):
  p._SERIES_CACHE[SID]={'series_id':SID,'vid_list':['123'],'fetched_at':time.time()-120}
  with patch.object(p.requests,'get',return_value=response(['123','456','789'])):
   self.assertEqual(len(p.get_hongguo_series_detail(SID)['vid_list']),3)
 def test_true_404_and_rate_limit_are_not_retried(self):
  with patch.object(p.requests,'get',return_value=Mock(status_code=404)) as get:
   self.assertIsNone(p.get_hongguo_series_detail(SID));get.assert_called_once()
  error=requests.HTTPError(response=Mock(status_code=429))
  with patch.object(p.requests,'get',side_effect=error) as get:
   with self.assertRaises(p.SeriesDetailUnavailable):p.get_hongguo_series_detail(SID)
   get.assert_called_once()
 def test_corrupt_saved_list_does_not_hide_network_error(self):
  Path(self.tmp.name,'drama_history.json').write_text('invalid')
  with patch.object(p.requests,'get',side_effect=requests.ConnectionError()),patch.object(p.time,'sleep'):
   with self.assertRaises(p.SeriesDetailUnavailable):p.get_hongguo_series_detail(SID)

 def test_signed_app_endpoint_recovers_when_website_is_unavailable(self):
  detail={'series_id':SID,'title':'Recovered','vid_list':['123','456'],'fetched_at':time.time()}
  with patch.object(p.requests,'get',side_effect=requests.ConnectionError()),patch.object(p.time,'sleep'),patch.object(p,'_app_series_detail',return_value=detail):
   result=app.app.test_client().get('/api/episodes?id='+SID)
  self.assertEqual(result.status_code,200);self.assertEqual(len(result.json['episodes']),2)
