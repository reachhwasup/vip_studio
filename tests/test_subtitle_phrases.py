import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '源码_开源版'))
import subtitles


def cue(a, b, text):
    return dict(start_time=a, end_time=b, text=text)


class AudioPhraseTests(unittest.TestCase):
    def test_audio_agreement_refines_fragments_and_timings(self):
        picture = [dict(cue(1, 2, '如果你来了'),speaker='A'), dict(cue(2, 3, '就给我打电话'),speaker='A')]
        spoken = cue(1.1, 3.1, '如果你来了，就给我打电话。')
        result, joins = subtitles.refine_picture_phrases(picture, [spoken])
        self.assertEqual(result, [dict(cue(1, 3, spoken['text']),speaker='A')])
        self.assertEqual(joins, 1)
        self.assertEqual(len(picture), 2)
        merged, added, review = subtitles.merge_picture_and_speech(result, [spoken])
        self.assertFalse(added)
        self.assertFalse(review)

    def test_disagreements_pauses_speaker_turns_and_bad_timing_stay_separate(self):
        cases = [
            ([cue(1, 2, '你好'), cue(2, 3, '朋友')], cue(1, 3, '你好老友')),
            ([cue(1, 2, '你好'), cue(3, 4, '朋友')], cue(1, 4, '你好朋友')),
            ([cue(1, 2, '你好。'), cue(2, 3, '朋友')], cue(1, 3, '你好朋友')),
            ([cue(1, 2, 'A: Hello'), cue(2, 3, 'B: Yes')], cue(1, 3, 'A Hello B Yes')),
            ([cue(1, 2, 'Hello'), cue(2, 3, 'there')], cue(0, 3, 'Hello there')),
        ]
        for rows, speech in cases:
            with self.subTest(rows=rows):
                self.assertEqual(subtitles.refine_picture_phrases(rows, [speech]), (rows, 0))

    def test_auto_exports_audio_validated_phrase(self):
        with tempfile.TemporaryDirectory() as name:
            video = Path(name) / 'episode.mp4'
            video.touch()
            report = {}
            def audio(video, ffmpeg, tmp, path, language):
                path.write_text('1\n00:00:01,100 --> 00:00:03,100\nHello there, my friend.\n')
            with patch.object(subtitles, '_subtitles_from_picture', return_value=[[1, 2, 'Hello there,'], [2, 3, 'my friend.']]), patch.object(subtitles, '_whisper_missing', return_value=''), patch.object(subtitles, '_subtitles_from_audio', side_effect=audio):
                path, method = subtitles.create_subtitles(video, report=report)
            self.assertEqual(method, 'hybrid')
            self.assertEqual(report['phrase_joins'], 0)
            self.assertTrue(report['review_candidates'])
            self.assertEqual(len(subtitles.import_subtitles(path.read_bytes(), path.name)['segments']), 2)

    def test_whisper_keeps_natural_segment_length(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            def run(command):
                if '-osrt' in command:
                    self.assertNotIn('-ml', command)
                    (folder / 'subtitles.srt').write_text('1\n00:00:01,000 --> 00:00:03,000\nA complete spoken phrase.\n')
            with patch.object(subtitles, '_run', side_effect=run):
                subtitles._subtitles_from_audio(folder / 'video.mp4', 'ffmpeg', folder, folder / 'speech.srt')

class UnknownTurnTests(unittest.TestCase):
    def test_audio_agreement_is_not_proof_that_two_unknown_voices_are_one_turn(self):
        rows=[cue(1,2,'大哥你醒了感觉怎么样'),cue(2.1,3,'我')]
        speech=[cue(1,3,'大哥你醒了感觉怎么样我')]
        self.assertEqual(subtitles.refine_picture_phrases(rows,speech),(rows,0))
