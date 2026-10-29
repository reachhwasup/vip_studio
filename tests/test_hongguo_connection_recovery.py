import concurrent.futures,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码_开源版'))
import app
m=app.parser_module

class ConnectionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'config.json'
        self.old={'device_id':'111','install_id':'222','platform':'android'}
        self.new={'device_id':'333','install_id':'444','platform':'android'}
        self.path.write_text(json.dumps(dict(self.old,download_path='/keep/videos',download_roots={'old':'/keep/videos'})))
        for target,value in [('get_runtime_base_dir',lambda:self.root),('_CONNECTION_RECOVERY_ATTEMPTS',{})]:
            p=patch.object(m,target,value);p.start();self.addCleanup(p.stop)
        p=patch.dict(os.environ,{},clear=True);p.start();self.addCleanup(p.stop)
        for target,value in [('sign_json_request_with_liushen',('url',{},b'{}')),('extract_fallback_api',('fallback',{'valid':True}))]:
            p=patch.object(m,target,return_value=value);p.start();self.addCleanup(p.stop)

    def test_parallel_workers_register_once_and_preserve_other_settings(self):
        with patch.object(m,'register_hongguo',return_value=self.new) as register,patch.object(m,'curl_request',return_value=b'{}'):
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                results=list(pool.map(lambda _:m.recover_video_connection('123',self.old,{}),range(4)))
        register.assert_called_once();self.assertTrue(all(r[2]==self.new for r in results))
        config=json.loads(self.path.read_text());self.assertEqual(config['device_id'],'333')
        self.assertEqual(config['download_path'],'/keep/videos');self.assertEqual(config['download_roots'],{'old':'/keep/videos'})
        self.assertEqual(self.path.stat().st_mode & 0o777,0o600)

    def test_invalid_replacement_is_not_saved_and_recovery_is_throttled(self):
        before=self.path.read_bytes()
        with patch.object(m,'register_hongguo',return_value=self.new) as register,patch.object(m,'curl_request',return_value=b''):
            self.assertIsNone(m.recover_video_connection('123',self.old,{}))
            self.assertIsNone(m.recover_video_connection('123',self.old,{}))
        register.assert_called_once();self.assertEqual(self.path.read_bytes(),before)

    def test_environment_override_is_respected(self):
        with patch.dict(os.environ,{'DUANJU_DEVICE_ID':'777'}),patch.object(m,'register_hongguo') as register:
            self.assertIsNone(m.recover_video_connection('123',self.old,{}))
        register.assert_not_called()

    def test_connection_edited_during_registration_is_preserved(self):
        def register(*_):
            self.path.write_text(json.dumps(dict(self.old,device_id='999')));return self.new
        with patch.object(m,'register_hongguo',side_effect=register),patch.object(m,'curl_request',return_value=b'{}'):
            self.assertIsNone(m.recover_video_connection('123',self.old,{}))
        self.assertEqual(json.loads(self.path.read_text())['device_id'],'999')

    def test_empty_response_can_recover_and_continue_same_episode(self):
        with patch.object(m,'get_device_keys',return_value=self.old),patch.object(m,'curl_request',return_value=b''),patch.object(m,'recover_video_connection',return_value=('fallback',{},self.new)) as recover,patch.object(m,'download_and_decrypt_video',return_value={'ok':True}) as download:
            self.assertEqual(m.resolve_video_url('123',max_retries=1),{'ok':True})
        recover.assert_called_once();self.assertEqual(download.call_args.args[3],self.new)
