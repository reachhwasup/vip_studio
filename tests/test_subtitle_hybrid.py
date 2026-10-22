import sys, tempfile, unittest, json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码_开源版'))
import subtitles
import app

def cue(a,b,text): return {'start_time':a,'end_time':b,'text':text}
class HybridTests(unittest.TestCase):
    def test_adds_missing_speech_and_keeps_picture_unchanged(self):
        picture=[cue(1,2,'原句')]
        result,added,review=subtitles.merge_picture_and_speech(picture,[cue(1,2,'原句'),cue(3,4,'遗漏')])
        self.assertEqual([c['text'] for c in result],['原句','遗漏'])
        self.assertEqual(len(added),1);self.assertFalse(review)
        self.assertNotIn('source',picture[0])
    def test_partial_overlap_is_reviewed_not_split_or_duplicated(self):
        result,added,review=subtitles.merge_picture_and_speech([cue(2,3,'原句')],[cue(1,4,'不同的长句')])
        self.assertEqual(len(result),1);self.assertEqual(len(review),1);self.assertFalse(added)
    def test_auto_checks_audio_even_when_picture_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            video=Path(tmp)/'ep.mp4';video.touch();report={}
            def audio(video,ffmpeg,tmp,path,language='zh'):
                path.write_text('1\n00:00:03,000 --> 00:00:04,000\n遗漏\n')
            with patch.object(subtitles,'_subtitles_from_picture',return_value=[[1,2,'原句']]),patch.object(subtitles,'_whisper_missing',return_value=''),patch.object(subtitles,'_subtitles_from_audio',side_effect=audio) as run:
                path,method=subtitles.create_subtitles(video,report=report)
            run.assert_called_once();self.assertEqual(method,'hybrid');self.assertEqual(report['audio_added'],1)
            self.assertIn('遗漏',path.read_text());self.assertTrue(video.with_suffix('.transcript.json').exists())
    def test_audio_only_skips_ocr_and_passes_language(self):
        with tempfile.TemporaryDirectory() as tmp:
            video=Path(tmp)/'ep.mp4';video.touch()
            def audio(video,ffmpeg,tmp,path,language):path.write_text('1\n00:00:01,000 --> 00:00:02,000\nHello\n')
            with patch.object(subtitles,'_subtitles_from_picture') as picture,patch.object(subtitles,'_whisper_missing',return_value=''),patch.object(subtitles,'_subtitles_from_audio',side_effect=audio) as run:
                path,method=subtitles.create_subtitles(video,mode='audio',language='en')
            picture.assert_not_called();self.assertEqual(run.call_args.kwargs['language'],'en');self.assertEqual(method,'audio')
    def test_speech_failure_warns_but_preserves_usable_picture(self):
        with tempfile.TemporaryDirectory() as tmp:
            video=Path(tmp)/'ep.mp4';video.touch();report={}
            with patch.object(subtitles,'_subtitles_from_picture',return_value=[[1,2,'原句']]),patch.object(subtitles,'_whisper_missing',return_value=''),patch.object(subtitles,'_subtitles_from_audio',side_effect=RuntimeError('test failure')):
                path,method=subtitles.create_subtitles(video,report=report)
            self.assertEqual(method,'picture');self.assertTrue(report['warnings']);self.assertIn('原句',path.read_text())
    def test_invalid_modes_rejected_before_queueing(self):
        r=app.app.test_client().post('/api/subtitles/regenerate',json={'url':'/src/ep.mp4','mode':'unknown'})
        self.assertEqual(r.status_code,400)
