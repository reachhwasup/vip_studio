import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码_开源版'))
import app as backend
import subtitles

class SubtitleRepairTests(unittest.TestCase):
    def test_success_backs_up_existing_srt(self):
        with tempfile.TemporaryDirectory() as tmp:
            video=Path(tmp)/'episode.mp4';video.touch();srt=video.with_suffix('.srt');srt.write_text('original')
            with patch.object(subtitles,'_subtitles_from_picture',return_value=[[1,2,'你好']]):
                result,method=subtitles.create_subtitles(video)
            self.assertEqual(method,'picture');self.assertEqual(result,srt)
            self.assertIn('你好',srt.read_text())
            self.assertEqual(next(Path(tmp).glob('*.backup-*')).read_text(),'original')
            self.assertEqual(list(Path(tmp).glob('*.tmp')),[])

    def test_failed_generation_preserves_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            video=Path(tmp)/'episode.mp4';video.touch();srt=video.with_suffix('.srt');srt.write_text('original')
            with patch.object(subtitles,'_subtitles_from_picture',return_value=[]),patch.object(subtitles,'_whisper_missing',return_value='unavailable'):
                with self.assertRaises(RuntimeError):subtitles.create_subtitles(video)
            self.assertEqual(srt.read_text(),'original')

    def test_replace_failure_preserves_original_and_cleans_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            video=Path(tmp)/'episode.mp4';video.touch();srt=video.with_suffix('.srt');srt.write_text('original')
            with patch.object(subtitles,'_subtitles_from_picture',return_value=[[1,2,'你好']]),patch.object(subtitles.os,'replace',side_effect=OSError('write failed')):
                with self.assertRaises(OSError):subtitles.create_subtitles(video)
            self.assertEqual(srt.read_text(),'original');self.assertEqual(list(Path(tmp).glob('*.tmp')),[])

    def test_job_deduplicates_and_reports_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            video=Path(tmp)/'episode.mp4';video.touch();srt=video.with_suffix('.srt');srt.write_text('1\n00:00:01,000 --> 00:00:02,000\n你好\n')
            with patch.object(backend,'SUBTITLE_JOBS',{}),patch.object(backend,'local_video_path',return_value=video),patch.object(backend.SUBTITLE_REPAIR_POOL,'submit') as submit,patch.object(backend,'create_subtitles',return_value=(srt,'picture')):
                client=backend.app.test_client();response=client.post('/api/subtitles/regenerate',json={'url':'/src/episode.mp4'})
                self.assertEqual(response.status_code,202);job=response.json
                duplicate=client.post('/api/subtitles/regenerate',json={'url':'/src/episode.mp4'})
                self.assertEqual(job['id'],duplicate.json['id']);submit.assert_called_once()
                backend.run_subtitle_repair(job['id'],video)
                status=client.get('/api/subtitles/regenerate?id='+job['id']).json
                self.assertEqual(status['status'],'done');self.assertEqual(status['captions'],1)

    def test_rejects_invalid_or_unsaved_video(self):
        client=backend.app.test_client()
        self.assertEqual(client.post('/api/subtitles/regenerate',json=[]).status_code,400)
        with patch.object(backend,'local_video_path',return_value=None):
            self.assertEqual(client.post('/api/subtitles/regenerate',json={'url':'/etc/passwd'}).status_code,404)
        self.assertEqual(client.get('/api/subtitles/regenerate?id=absent').status_code,404)
