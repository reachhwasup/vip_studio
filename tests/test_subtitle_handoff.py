"""Cross-engine agreement must improve punctuation without moving dialogue."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '源码_开源版'))
import subtitles


def cue(start, end, text, **extra):
    return dict(start_time=start, end_time=end, text=text, **extra)


class HandoffTests(unittest.TestCase):
    def test_adds_verified_sentence_mark_without_moving_or_merging(self):
        picture = [cue(1, 3, '你叫什么名字', speaker='A')]
        result, joins = subtitles.refine_picture_phrases(picture, [cue(1.2, 3.1, '你叫什么名字？')])
        self.assertEqual(result, [cue(1, 3, '你叫什么名字？', speaker='A')])
        self.assertEqual(joins, 0)
        self.assertEqual(picture[0]['text'], '你叫什么名字')

    def test_mismatched_name_or_timing_keeps_original(self):
        picture = [cue(1, 3, '陈浩宇回来')]
        for speech in ([cue(1, 3, '陈浩雨回来！')], [cue(2, 3, '陈浩宇回来！')]):
            self.assertEqual(subtitles.refine_picture_phrases(picture, speech)[0], picture)

    def test_existing_sentence_mark_and_multiline_dialogue_unchanged(self):
        for text in ['别动！', '别动。放下武器', '别动\n放下武器', '甲：别动']:
            picture = [cue(1, 3, text)]
            self.assertEqual(subtitles.refine_picture_phrases(picture, [cue(1, 3, text.rstrip('！') + '？')])[0], picture)

    def test_exact_phrase_across_unknown_speakers_is_not_merged_or_false_disagreement(self):
        picture = [cue(1, 2, '你是谁'), cue(2, 3, '我是陈浩宇')]
        speech = [cue(1, 3, '你是谁？我是陈浩宇。')]
        refined, joins = subtitles.refine_picture_phrases(picture, speech)
        result, added, review = subtitles.merge_picture_and_speech(refined, speech)
        self.assertEqual(joins, 0)
        self.assertEqual(len(result), 2)
        self.assertFalse(added)
        self.assertEqual(len(review), 1)
        self.assertIn('wording matches', review[0]['reason'])
        self.assertNotIn('disagree', review[0]['reason'])

    def test_long_gap_or_wrong_word_still_needs_review(self):
        for picture in ([cue(1, 2, '你是谁'), cue(4, 5, '我是陈浩宇')],
                        [cue(1, 2, '你是谁'), cue(2, 3, '我是陈浩雨')]):
            _, _, review = subtitles.merge_picture_and_speech(picture, [cue(1, picture[-1]['end_time'], '你是谁我是陈浩宇。')])
            self.assertTrue(review)


if __name__ == '__main__':
    unittest.main()
