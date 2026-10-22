import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码_开源版'))
import subtitles


def frame(text='', conf=.99, extra=()):
    return {'lines': ([{'text': text, 'conf': conf, 'x': .2, 'w': .6, 'y': .5, 'h': .1}] if text else []) + list(extra)}


def scene(text, x=.5, y=.72, h=.05, w=.1, conf=.99):
    return {'text': text, 'conf': conf, 'x': x, 'w': w, 'y': y, 'h': h}


class SubtitleOCRTests(unittest.TestCase):
    def test_similar_sentences_are_not_lost(self):
        records=[frame('我喜欢你'),frame('我喜欢你'),frame('我不喜欢你'),frame('我不喜欢你')]+[frame() for _ in range(16)]
        cues=subtitles._cues_from_frames(records,8)
        self.assertEqual([c[2] for c in cues],['我喜欢你','我不喜欢你'])
        self.assertLessEqual(cues[0][1],cues[1][0])

    def test_confident_single_frame_caption_is_kept(self):
        cues=subtitles._cues_from_frames([frame('走！')]+[frame() for _ in range(19)],8)
        self.assertEqual(cues,[[0,.5/8,'走！']])

    def test_low_confidence_single_frame_noise_is_dropped(self):
        self.assertEqual(subtitles._cues_from_frames([frame('错字',.6)]+[frame() for _ in range(19)],8),[])

    def test_punctuation_variants_merge(self):
        records=[frame('你好'),frame('你好！')]+[frame() for _ in range(18)]
        self.assertEqual(len(subtitles._cues_from_frames(records,8)),1)

    def test_one_unreadable_frame_does_not_split_caption(self):
        records=[frame('等等'),frame(),frame('等等')]+[frame() for _ in range(17)]
        self.assertEqual(subtitles._cues_from_frames(records,8),[[0,2.5/8,'等等']])

    def test_repeated_lower_confidence_caption_is_kept(self):
        records=[frame('菲菲',.3) for _ in range(3)]+[frame() for _ in range(17)]
        self.assertEqual(subtitles._cues_from_frames(records,8),[[0,2.5/8,'菲菲']])

    def test_isolated_lower_confidence_caption_is_rejected(self):
        records=[frame('杂字',.3)]+[frame() for _ in range(19)]
        self.assertEqual(subtitles._cues_from_frames(records,8),[])

    def test_long_caption_in_short_video_is_not_treated_as_logo(self):
        records=[frame('持续显示的对白') for _ in range(32)]
        self.assertEqual(subtitles._cues_from_frames(records,8),[[0,31.5/8,'持续显示的对白']])

    def test_identical_captions_merge_after_rejected_noise(self):
        records=[frame('你好'),frame('你好'),frame('杂字',.4),frame('你好'),frame('你好')]+[frame() for _ in range(15)]
        self.assertEqual(subtitles._cues_from_frames(records,8),[[0,4.5/8,'你好']])

    def test_one_misread_character_does_not_split_or_repeat_caption(self):
        readings=['敢伤我家肖少爷去兰吧']*3+['敢伤我家肖少爷去三吧']*4+['敢伤我家肖少爷去兰吧']+['敢伤我家肖少爷去三吧']*2
        cues=subtitles._cues_from_frames([frame()]*4+[frame(t) for t in readings]+[frame()]*10,8)
        self.assertEqual(cues,[[3.5/8,13.5/8,'敢伤我家肖少爷去三吧']])

    def test_short_or_numbered_lines_are_never_treated_as_misreadings(self):
        for a,b in (('是我','是你'),('还有3天','还有2天'),('我喜欢你','我不喜欢你')):
            records=[frame(a)]*3+[frame(b)]*3+[frame()]*14
            self.assertEqual([c[2] for c in subtitles._cues_from_frames(records,8)],[a,b])

    def test_scene_text_is_not_added_to_captions(self):
        badge=[scene('保',x=.56,w=.05),scene('BAOAN',x=.6,y=.47,h=.09)]
        records=[frame('没这样的规矩')]*4+[frame('没这样的规矩',extra=badge)]*4+[frame(extra=badge)]*3+[frame('你们想干什么')]*4+[frame()]*10
        self.assertEqual(subtitles._cues_from_frames(records,8),[[0,7.5/8,'没这样的规矩'],[10.5/8,14.5/8,'你们想干什么']])

    def test_caption_split_by_scene_text_reads_as_one_caption(self):
        number=[scene('NCY-Y2024',x=.4,y=.3,h=.08)]
        records=[frame('拿命守护国家',extra=number if i%2 else ()) for i in range(10)]+[frame()]*10
        self.assertEqual(subtitles._cues_from_frames(records,8),[[0,9.5/8,'拿命守护国家']])

    def test_wrapped_captions_keep_both_rows(self):
        second={'text':'第二行','conf':.99,'x':.3,'w':.4,'y':.62,'h':.1}
        records=[frame('第一行',extra=[second])]*6+[frame('单行对白')]*6+[frame()]*8
        self.assertEqual([c[2] for c in subtitles._cues_from_frames(records,8)],['第一行第二行','单行对白'])

    def test_caption_edges_fall_midway_between_samples(self):
        cues=subtitles._cues_from_frames([frame()]*8+[frame('姐')]*2+[frame()]*10,8)
        self.assertEqual(cues,[[7.5/8,9.5/8,'姐']])

    def test_dash_for_one_and_stray_marks_do_not_repeat_caption(self):
        for good,bad in (('一点江湖道义都不讲','-点江湖道义都不讲'),('又怎么样啊','w 又怎么样啊')):
            records=[frame(good)]*5+[frame(bad)]*3+[frame()]*12
            self.assertEqual(subtitles._cues_from_frames(records,8),[[0,7.5/8,good]])

    def test_short_word_missed_for_three_frames_is_one_caption(self):
        records=[frame('说')]*2+[frame()]*3+[frame('说')]+[frame()]*14
        self.assertEqual(subtitles._cues_from_frames(records,8),[[0,5.5/8,'说']])

    def test_line_repeated_after_a_pause_stays_two_captions(self):
        records=[frame('卫国')]*4+[frame()]*5+[frame('卫国')]*4+[frame()]*10
        self.assertEqual(len(subtitles._cues_from_frames(records,8)),2)

    def test_centre_is_read_again_only_where_nothing_was_found(self):
        frames=[frame(),frame('已经读到的对白'),frame(),frame()]
        def run(command,capture=False):
            if capture:
                names=sorted(p.name for p in Path(command[1]).glob('*.jpg'))
                self.assertEqual(names,['000001.jpg','000003.jpg','000004.jpg'])
                short={'text':'哥','conf':1,'x':.4,'w':.2,'y':.3,'h':.3}
                cut={'text':'家肖少爷','conf':1,'x':0,'w':1,'y':.3,'h':.3}
                return '\n'.join(json.dumps({'file':n,'lines':[short] if n=='000003.jpg' else [cut] if n=='000004.jpg' else []}) for n in names)
            for i in range(1,5):Path(command[-1].replace('%06d','%06d'%i)).touch()
            return ''
        with tempfile.TemporaryDirectory() as tmp,patch.object(subtitles,'_run',side_effect=run):
            subtitles._reread_centre('helper',Path('video.mp4'),'ffmpeg',8,.6,.13,Path(tmp)/'centre',frames)
        self.assertEqual([[l['text'] for l in f['lines']] for f in frames],[[],['已经读到的对白'],['哥'],[]])
        line=frames[2]['lines'][0]
        self.assertAlmostEqual(line['x']+line['w']/2,.5);self.assertAlmostEqual(line['w'],.08)


if __name__=='__main__':unittest.main()
