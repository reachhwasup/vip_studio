import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '源码_开源版'))
import subtitles
from funasr_worker import sentence_segments


class FunASRTests(unittest.TestCase):
    def test_sentences_use_model_milliseconds_and_punctuation(self):
        rows = sentence_segments([{'text': '你好，朋友。', 'timestamp': [[1200, 1500], [1500, 1800], [1900, 2600], [2600, 3400]]}])
        self.assertEqual(rows, [{'start_time': 1.2, 'end_time': 3.4, 'text': '你好，朋友。'}])

    def test_untimed_or_invalid_output_is_not_given_invented_timestamps(self):
        for result in [{'text': '你好'}, {'sentence_info': [{'text': '你好', 'start': 0, 'end': float('nan')}]}]:
            with self.assertRaises(RuntimeError):
                sentence_segments([result])

    def test_local_mode_skips_ocr_and_whisper_and_backs_up_srt(self):
        with tempfile.TemporaryDirectory() as name:
            video = Path(name) / 'episode.mp4'
            video.touch()
            video.with_suffix('.srt').write_text('old subtitles')
            def generate(video, ffmpeg, tmp, output):
                output.write_text('1\n00:00:01,200 --> 00:00:03,400\n你好，朋友。\n')
            with patch.object(subtitles, '_subtitles_from_funasr', side_effect=generate), patch.object(subtitles, '_subtitles_from_picture') as ocr, patch.object(subtitles, '_subtitles_from_audio') as whisper:
                output, method = subtitles.create_subtitles(video, mode='funasr')
            self.assertEqual(method, 'funasr')
            self.assertIn('你好，朋友。', output.read_text())
            self.assertEqual(next(Path(name).glob('*.backup-*')).read_text(), 'old subtitles')
            ocr.assert_not_called()
            whisper.assert_not_called()

    def test_failed_engine_preserves_existing_subtitles(self):
        with tempfile.TemporaryDirectory() as name:
            video = Path(name) / 'episode.mp4'
            video.touch()
            srt = video.with_suffix('.srt')
            srt.write_text('old subtitles')
            with patch.object(subtitles, '_subtitles_from_funasr', side_effect=RuntimeError('missing model')):
                with self.assertRaises(RuntimeError):
                    subtitles.create_subtitles(video, mode='funasr')
            self.assertEqual(srt.read_text(), 'old subtitles')

    def test_english_is_rejected_for_chinese_checkpoint(self):
        with self.assertRaisesRegex(ValueError, 'Chinese'):
            subtitles.create_subtitles(Path('unused.mp4'), mode='funasr', language='en')

    def test_api_queues_chinese_engine_and_rejects_english(self):
        import app
        with tempfile.TemporaryDirectory() as name:
            video = Path(name) / 'episode.mp4'
            video.touch()
            with patch.object(app, 'SUBTITLE_JOBS', {}), patch.object(app, 'SUBTITLE_JOB_STORE', None), patch.object(app, 'local_video_path', return_value=video), patch.object(app.SUBTITLE_REPAIR_POOL, 'submit') as submit:
                client = app.app.test_client()
                response = client.post('/api/subtitles/regenerate', json={'url': '/src/episode.mp4', 'mode': 'funasr', 'language': 'zh'})
                self.assertEqual(response.status_code, 202)
                self.assertEqual(response.json['mode'], 'funasr')
                submit.assert_called_once()
                self.assertEqual(client.post('/api/subtitles/regenerate', json={'url': '/src/episode.mp4', 'mode': 'funasr', 'language': 'en'}).status_code, 400)

    def test_engine_reports_real_stages_without_fake_percentages(self):
        events = []
        with subtitles._progress_session(events.append):
            subtitles._run([sys.executable, '-c', "print('VIP_ASR_STAGE Loading local Chinese speech models'); print('VIP_ASR_STAGE Building timed Chinese subtitle phrases')"], capture=True)
        self.assertEqual([event['stage'] for event in events], ['Loading local Chinese speech models', 'Building timed Chinese subtitle phrases'])
        self.assertTrue(all(event['progress'] is None for event in events))

    def test_punctuation_keeps_words_on_the_correct_side_of_break(self):
        result = {'text': '我来了，你在哪？', 'timestamp': [[i * 100, i * 100 + 90] for i in range(6)],
                  'sentence_info': [{'text': '我来了你，', 'start': 0, 'end': 390}]}
        rows = sentence_segments([result])
        self.assertEqual([row['text'] for row in rows], ['我来了，你在哪？'])
        self.assertEqual(rows[0]['start_time'], 0.0)

    def test_pause_alone_does_not_split_a_phrase(self):
        with patch('funasr_worker._word_ends', return_value=set()):
            rows = sentence_segments([{'text': '我现在去找朋友', 'timestamp': [[100, 200], [200, 300], [300, 400], [400, 500], [1500, 1600], [1600, 1700], [1700, 1800]]}])
        self.assertEqual([row['text'] for row in rows], ['我现在去找朋友'])
        self.assertEqual(rows[0]['end_time'], 1.8)

    def test_pause_cannot_strand_a_single_character(self):
        rows = sentence_segments([{'text': '成了老子真的练成了。', 'timestamp': [[100, 200]] + [[1000 + i * 100, 1100 + i * 100] for i in range(8)]}])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['text'], '成了老子真的练成了。')

    def test_chinese_words_survive_a_pause_between_their_characters(self):
        text = '你好大的狗胆竟然废了小天。'
        units = list(text[:-1])
        times = [[i * 100, i * 100 + 90] for i in range(len(units))]
        for i in range(7, len(times)):
            times[i] = [times[i][0] + 700, times[i][1] + 700]
        rows = sentence_segments([{'text': text, 'timestamp': times}])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['text'], text)

    def test_word_boundary_pause_keeps_next_short_utterance_separate(self):
        with patch('funasr_worker._word_ends', return_value={1, 2, 3, 4, 5}):
            rows = sentence_segments([{'text': '你也配教爹，', 'timestamp': [[0, 100], [100, 200], [200, 300], [300, 400], [1200, 1400]]}])
        self.assertEqual([row['text'] for row in rows], ['你也配教', '爹，'])
