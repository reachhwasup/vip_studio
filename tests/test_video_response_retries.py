import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码_开源版'))
import app
m=app.parser_module
class VideoResponseTests(unittest.TestCase):
    def setUp(self):
        recovery = patch.object(m, 'recover_video_connection', return_value=None)
        recovery.start(); self.addCleanup(recovery.stop)

    def test_empty_then_valid_response_recovers(self):
        with patch.object(m,'get_device_keys',return_value={'device_id':'1','install_id':'2'}),patch.object(m,'sign_json_request_with_liushen',return_value=('url',{},b'{}')),patch.object(m,'curl_request',side_effect=[b'',b'{}']),patch.object(m,'extract_fallback_api',return_value=('fallback',{})),patch.object(m,'download_and_decrypt_video',return_value={'ok':True}),patch.object(m.time,'sleep') as sleep:
            self.assertEqual(m.resolve_video_url('123'),{'ok':True})
            sleep.assert_called_once_with(2)

    def test_empty_and_non_json_fail_without_raw_body_or_json_error(self):
        for body in [b'',b'<html>private response</html>']:
            with patch.object(m,'get_device_keys',return_value={'device_id':'1','install_id':'2'}),patch.object(m,'sign_json_request_with_liushen',return_value=('url',{},b'{}')),patch.object(m,'curl_request',return_value=body) as fetch,patch.object(m.time,'sleep') as sleep:
                with self.assertRaisesRegex(Exception,'Hongguo video service temporarily unavailable') as error:m.resolve_video_url('123')
                self.assertEqual(fetch.call_count,3)
                self.assertEqual([c.args[0] for c in sleep.call_args_list],[2,4])
                self.assertNotIn('private response',str(error.exception))
                self.assertNotIn('JSON parse',str(error.exception))

    def test_api_identifies_server_response_instead_of_network_failure(self):
        with patch.object(app,'handle_video_request',side_effect=m.VideoServiceUnavailable('Hongguo returned no video data.')):
            response=app.app.test_client().get('/hg?vid=123')
        self.assertEqual(response.status_code,503)
        self.assertEqual(response.json['code'],'hongguo_video_unavailable')
