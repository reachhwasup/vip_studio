import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码_开源版'))
import app as backend

class DownloadSubtitleSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.config=Path(self.tmp.name)/'config.json';self.video=Path(self.tmp.name)/'episode.mp4';self.video.write_bytes(b'fixture')
        self.client=backend.app.test_client()
        patches=[patch.object(backend,'get_config_path',return_value=self.config),patch.object(backend,'SUBTITLE_JOBS',{}),patch.object(backend,'local_video_path',return_value=self.video),patch.object(backend,'add_download_cover'),patch.object(backend,'remember_drama'),patch.object(backend,'handle_video_request',return_value={'url':'http://localhost/src/episode.mp4'}),patch.object(backend.SUBTITLE_REPAIR_POOL,'submit')]
        for p in patches:p.start();self.addCleanup(p.stop)

    def test_audio_only_setting_resolves_for_new_downloads(self):
        data = dict(mode='speech', language='zh', cpu_threads=1)
        with patch('subtitles.preferred_download_mode', return_value='hybrid'):
            response = self.client.post('/api/subtitles/download-settings', json=data)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['effective_mode'], 'funasr')
            job = self.client.get('/hg?vid=123&subtitles=background').json['subtitle_job']
        self.assertEqual(job['mode'], 'funasr')
        self.assertEqual(job['cpu_threads'], 1)

    def test_recommended_download_uses_installed_chinese_engine(self):
        with patch('subtitles.preferred_download_mode',return_value='hybrid'):
            response=self.client.get('/hg?vid=123&subtitles=background')
        self.assertEqual(response.status_code,200)
        job=response.json['subtitle_job'];self.assertEqual((job['mode'],job['language'],job['cpu_threads']),('hybrid','zh',2))

    def test_saved_download_choices_reach_new_worker_jobs(self):
        data=dict(mode='picture',language='zh',cpu_threads=1)
        self.assertEqual(self.client.post('/api/subtitles/download-settings',json=data).json['settings'],data)
        self.assertEqual(self.client.get('/api/subtitles/download-settings').json['settings'],data)
        job=self.client.get('/hg?vid=123&subtitles=background').json['subtitle_job']
        self.assertEqual((job['mode'],job['cpu_threads']),('picture',1))

    def test_recommended_falls_back_when_models_missing(self):
        with patch('subtitles.preferred_download_mode',return_value='auto'):
            self.assertEqual(self.client.get('/api/subtitles/download-settings').json['effective_mode'],'auto')

    def test_non_chinese_recommended_does_not_use_chinese_only_model(self):
        self.client.post('/api/subtitles/download-settings',json=dict(mode='recommended',language='en',cpu_threads=2))
        with patch('subtitles.preferred_download_mode',return_value='hybrid'):
            self.assertEqual(backend.download_subtitle_settings(resolve=True)['mode'],'auto')

    def test_invalid_settings_do_not_overwrite_previous_choices(self):
        valid=dict(mode='picture',language='zh',cpu_threads=1)
        self.client.post('/api/subtitles/download-settings',json=valid)
        for data in [dict(mode='hybrid',language='en',cpu_threads=2),dict(mode='picture',language='zh',cpu_threads=True),dict(mode='bad',language='zh',cpu_threads=2)]:
            self.assertEqual(self.client.post('/api/subtitles/download-settings',json=data).status_code,400)
        self.assertEqual(self.client.get('/api/subtitles/download-settings').json['settings'],valid)

    def test_queued_jobs_keep_their_settings_after_preferences_change(self):
        self.client.post('/api/subtitles/download-settings',json=dict(mode='picture',language='zh',cpu_threads=1))
        first=self.client.get('/hg?vid=123&subtitles=background').json['subtitle_job']
        self.client.post('/api/subtitles/download-settings',json=dict(mode='hybrid',language='zh',cpu_threads=2))
        same=self.client.get('/hg?vid=123&subtitles=background').json['subtitle_job']
        self.assertEqual(first['id'],same['id']);self.assertEqual(same['mode'],'picture');self.assertEqual(same['cpu_threads'],1)
