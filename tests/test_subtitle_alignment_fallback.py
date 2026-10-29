import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码_开源版'))
import subtitles

class AlignmentFallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.video=Path(self.tmp.name)/'episode.mp4';self.video.touch()
        self.srt=self.video.with_suffix('.srt');self.srt.write_text('original captions')

    def test_alignment_failure_uses_whisper_and_marks_result_for_review(self):
        def generate(video,ffmpeg,tmp,output,language):output.write_text('1\n00:00:01,000 --> 00:00:03,000\n你好，朋友。\n')
        report={};events=[]
        with patch.object(subtitles,'_subtitles_from_funasr',side_effect=RuntimeError('Chinese alignment changed the recognized words; review the audio with Whisper instead.')),patch.object(subtitles,'_whisper_missing',return_value=''),patch.object(subtitles,'_subtitles_from_audio',side_effect=generate) as whisper,patch.object(subtitles,'_subtitles_from_picture') as ocr:
            path,method=subtitles.create_subtitles(self.video,mode='funasr',report=report,progress=events.append,cpu_threads=1)
        self.assertEqual(method,'audio');self.assertEqual(report['speech_engine'],'whisper');self.assertEqual(report['fallback_from'],'paraformer')
        self.assertEqual(report['quality_state'],'needs_review');self.assertIn('你好',path.read_text());self.assertEqual(next(Path(self.tmp.name).glob('*.backup-*')).read_text(),'original captions')
        whisper.assert_called_once();ocr.assert_not_called();self.assertTrue(any('recovering with Whisper' in str(e) for e in events))

    def test_failed_or_unavailable_fallback_preserves_existing_file(self):
        for reason in ['', 'Whisper missing']:
            with patch.object(subtitles,'_subtitles_from_funasr',side_effect=RuntimeError('Chinese alignment changed the recognized words')),patch.object(subtitles,'_whisper_missing',return_value=reason),patch.object(subtitles,'_subtitles_from_audio',side_effect=RuntimeError('Whisper failed')):
                with self.assertRaises(RuntimeError):subtitles.create_subtitles(self.video,mode='funasr')
            self.assertEqual(self.srt.read_text(),'original captions')

    def test_hybrid_keeps_picture_captions_without_running_second_speech_engine(self):
        with patch.object(subtitles,'_subtitles_from_funasr',side_effect=RuntimeError('Chinese alignment changed the recognized words')),patch.object(subtitles,'_subtitles_from_picture',return_value=[(1,3,'原字幕')]),patch.object(subtitles,'_subtitles_from_audio') as whisper:
            path,method=subtitles.create_subtitles(self.video,mode='hybrid')
        self.assertEqual(method,'picture');self.assertIn('原字幕',path.read_text());whisper.assert_not_called()

    def test_whisper_command_respects_cpu_thread_selection(self):
        commands=[]
        def run(command,*args,**kwargs):
            commands.append(command)
            if '-osrt' in command:Path(command[command.index('-of')+1]).with_suffix('.srt').write_text('1\n00:00:01,000 --> 00:00:02,000\n你好\n')
        output=Path(self.tmp.name)/'result.srt'
        with patch.object(subtitles,'_run',side_effect=run),subtitles._progress_session(lambda _:None,1):subtitles._subtitles_from_audio(self.video,'ffmpeg',Path(self.tmp.name),output)
        command=next(c for c in commands if '-osrt' in c);self.assertEqual(command[command.index('-t')+1],'1')
