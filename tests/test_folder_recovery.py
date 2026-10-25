import sys,json,tempfile,unittest,shutil
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码_开源版'))
import app
p=app.parser_module
class FolderRecoveryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name).resolve();self.folder=self.root/'videos';self.folder.mkdir()
  self.runtime=patch.object(p,'get_runtime_base_dir',return_value=self.root);self.runtime.start();self.addCleanup(self.runtime.stop)
  app.write_local_config({'download_path':str(self.folder)})
  self.client=app.app.test_client()
 def test_missing_folder_is_reported_without_recreating_it(self):
  self.folder.rmdir()
  result=self.client.get('/api/download-path?check=1')
  self.assertEqual(result.status_code,200);self.assertFalse(result.json['available']);self.assertFalse(self.folder.exists())
 def test_missing_folder_stops_before_video_request_and_returns_recovery_code(self):
  self.folder.rmdir()
  with patch.object(app,'handle_video_request') as download:
   result=self.client.get('/hg?vid=123&check_download_folder=1')
  self.assertEqual(result.status_code,409);self.assertEqual(result.json['code'],'download_folder_unavailable');download.assert_not_called()
 def test_missing_folder_prevents_starting_ffmpeg(self):
  self.folder.rmdir()
  with patch.object(p.subprocess,'Popen') as ffmpeg:
   with self.assertRaises(p.DownloadFolderUnavailable):p.stream_copy_video_with_ffmpeg('http://localhost','https://example.test/video',None)
   ffmpeg.assert_not_called()
 def test_unwritable_folder_shows_recovery_without_changing_configuration(self):
  before=app.read_local_config()
  with patch.object(p.tempfile,'TemporaryFile',side_effect=PermissionError()):
   result=self.client.get('/api/download-path?check=1')
  self.assertFalse(result.json['available']);self.assertEqual(app.read_local_config(),before)
 def test_reselecting_folder_restores_availability(self):
  self.folder.rmdir();new=self.root/'replacement'
  result=self.client.post('/api/download-path',json={'download_path':str(new)})
  self.assertEqual(result.status_code,200);self.assertTrue(self.client.get('/api/download-path?check=1').json['available'])
 def test_disconnected_folder_during_transfer_is_recoverable(self):
  def disconnected():shutil.rmtree(self.folder);return 1
  process=Mock(stdout=[],wait=Mock(side_effect=disconnected))
  with patch.object(p.subprocess,'Popen',return_value=process):
   with self.assertRaises(p.DownloadFolderUnavailable):p.stream_copy_video_with_ffmpeg('http://localhost','https://example.test/video',None,'ep.mp4')
 def test_default_unconfigured_folder_can_be_created_on_first_use(self):
  app.write_local_config({})
  folder=p.require_download_dir();self.assertTrue(folder.is_dir());self.assertEqual(folder,self.root/'src')
