import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码_开源版'))
import subtitles


def frame(text='', conf=.99):
    return {'lines': [{'text': text, 'conf': conf, 'x': .2, 'w': .6, 'y': .5, 'h': .1}] if text else []}


class SubtitleOCRTests(unittest.TestCase):
    def test_similar_sentences_are_not_lost(self):
        records=[frame('我喜欢你'),frame('我喜欢你'),frame('我不喜欢你'),frame('我不喜欢你')]+[frame() for _ in range(16)]
        cues=subtitles._cues_from_frames(records,8)
        self.assertEqual([c[2] for c in cues],['我喜欢你','我不喜欢你'])
        self.assertLessEqual(cues[0][1],cues[1][0])

    def test_confident_single_frame_caption_is_kept(self):
        cues=subtitles._cues_from_frames([frame('走！')]+[frame() for _ in range(19)],8)
        self.assertEqual(cues,[[0,1/8,'走！']])

    def test_low_confidence_single_frame_noise_is_dropped(self):
        self.assertEqual(subtitles._cues_from_frames([frame('错字',.6)]+[frame() for _ in range(19)],8),[])

    def test_punctuation_variants_merge(self):
        records=[frame('你好'),frame('你好！')]+[frame() for _ in range(18)]
        self.assertEqual(len(subtitles._cues_from_frames(records,8)),1)

    def test_one_unreadable_frame_does_not_split_caption(self):
        records=[frame('等等'),frame(),frame('等等')]+[frame() for _ in range(17)]
        self.assertEqual(subtitles._cues_from_frames(records,8),[[0,3/8,'等等']])

    def test_repeated_lower_confidence_caption_is_kept(self):
        records=[frame('菲菲',.3) for _ in range(3)]+[frame() for _ in range(17)]
        self.assertEqual(subtitles._cues_from_frames(records,8),[[0,3/8,'菲菲']])

    def test_isolated_lower_confidence_caption_is_rejected(self):
        records=[frame('杂字',.3)]+[frame() for _ in range(19)]
        self.assertEqual(subtitles._cues_from_frames(records,8),[])

    def test_long_caption_in_short_video_is_not_treated_as_logo(self):
        records=[frame('持续显示的对白') for _ in range(32)]
        self.assertEqual(subtitles._cues_from_frames(records,8),[[0,4,'持续显示的对白']])

    def test_identical_captions_merge_after_rejected_noise(self):
        records=[frame('你好'),frame('你好'),frame('杂字',.4),frame('你好'),frame('你好')]+[frame() for _ in range(15)]
        self.assertEqual(subtitles._cues_from_frames(records,8),[[0,5/8,'你好']])
