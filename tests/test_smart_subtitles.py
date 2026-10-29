import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码_开源版'))
import subtitles
import app

class SmartSubtitleTests(unittest.TestCase):
    def test_chinese_uses_only_paraformer_when_installed(self):
        with tempfile.TemporaryDirectory() as folder:
            video=Path(folder)/'episode.mp4';video.touch();report={}
            def speech(video,ffmpeg,tmp,output):output.write_text('1\n00:00:01,000 --> 00:00:03,000\n你好朋友。\n')
            with patch.object(subtitles,'preferred_download_mode',return_value='hybrid'),patch.object(subtitles,'_subtitles_from_picture',return_value=[(1,3,'你好朋友')]) as ocr,patch.object(subtitles,'_subtitles_from_funasr',side_effect=speech) as chinese,patch.object(subtitles,'_subtitles_from_audio') as whisper:
                subtitles.create_subtitles(video,mode='recommended',report=report)
            ocr.assert_called_once();chinese.assert_called_once();whisper.assert_not_called()
            self.assertEqual(report['requested_mode'],'recommended');self.assertEqual(report['mode'],'hybrid')

    def test_missing_chinese_engine_falls_back_to_one_whisper_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            video=Path(folder)/'episode.mp4';video.touch()
            def speech(video,ffmpeg,tmp,output,language):output.write_text('1\n00:00:01,000 --> 00:00:03,000\n你好朋友。\n')
            with patch.object(subtitles,'preferred_download_mode',return_value='auto'),patch.object(subtitles,'_subtitles_from_picture',return_value=[(1,3,'你好朋友')]),patch.object(subtitles,'_whisper_missing',return_value=''),patch.object(subtitles,'_subtitles_from_funasr') as chinese,patch.object(subtitles,'_subtitles_from_audio',side_effect=speech) as whisper:
                subtitles.create_subtitles(video,mode='recommended')
            chinese.assert_not_called();whisper.assert_called_once()

    def test_other_languages_do_not_use_chinese_only_model(self):
        with patch.object(subtitles,'preferred_download_mode') as choose:
            self.assertEqual(subtitles.resolve_subtitle_mode('recommended','en'),'auto');choose.assert_not_called()
        self.assertEqual(subtitles.resolve_subtitle_mode('picture','zh'),'picture')

    def test_library_accepts_the_same_smart_choice_as_downloads(self):
        with tempfile.TemporaryDirectory() as folder:
            video=Path(folder)/'episode.mp4';video.touch()
            with patch.object(app,'local_video_path',return_value=video),patch.object(app,'SUBTITLE_JOBS',{}),patch.object(app.SUBTITLE_REPAIR_POOL,'submit'):
                response=app.app.test_client().post('/api/subtitles/regenerate',json=dict(url='/src/episode.mp4',mode='recommended',language='zh',cpu_threads=2))
            self.assertIn(response.status_code,(200,202));self.assertEqual(response.json['mode'],'recommended')

    def test_audio_only_auto_selects_engine_and_retains_legacy_overrides(self):
        for installed, expected in [('hybrid', 'funasr'), ('auto', 'audio')]:
            with patch.object(subtitles, 'preferred_download_mode', return_value=installed):
                self.assertEqual(subtitles.resolve_subtitle_mode('speech', 'zh'), expected)
                self.assertEqual(subtitles.resolve_subtitle_mode('speech', 'en'), 'audio')
        for mode in ('hybrid', 'auto', 'funasr', 'audio', 'picture'):
            self.assertEqual(subtitles.resolve_subtitle_mode(mode, 'zh'), mode)

    def test_audio_only_skips_video_text_and_runs_one_chinese_engine(self):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder)/'episode.mp4'; video.touch(); report = {}
            def speech(video, ffmpeg, tmp, output):
                output.write_text('1\n00:00:01,000 --> 00:00:03,000\n你好朋友。\n')
            with patch.object(subtitles, 'preferred_download_mode', return_value='hybrid'), patch.object(subtitles, '_subtitles_from_picture') as picture, patch.object(subtitles, '_subtitles_from_funasr', side_effect=speech) as chinese, patch.object(subtitles, '_subtitles_from_audio') as whisper:
                subtitles.create_subtitles(video, mode='speech', report=report)
            picture.assert_not_called(); whisper.assert_not_called(); chinese.assert_called_once()
            self.assertEqual(report['requested_mode'], 'speech')
