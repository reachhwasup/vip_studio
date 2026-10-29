import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '源码_开源版'))
import subtitles
from subtitle_jobs import SubtitleJobStore
from funasr_worker import sentence_segments


def cue(start, end, text, **extra):
    return dict(start_time=start, end_time=end, text=text, **extra)


def timed(text, gap_after=None):
    units = [c for c in text if c.isalnum()]
    times = [[i * 140, (i + 1) * 140] for i in range(len(units))]
    if gap_after is not None:
        for i in range(gap_after, len(times)):
            times[i] = [t + 700 for t in times[i]]
    return dict(text=text, timestamp=times)


class StatementTests(unittest.TestCase):
    def test_conditional_statement_survives_comma_and_short_pause(self):
        result = timed('既然是比武，总得有点彩头吧。', 5)
        with patch('funasr_worker._word_ends', return_value={5}):
            rows = sentence_segments([result])
        self.assertEqual([c['text'] for c in rows], [result['text']])

    def test_sentence_end_still_separates_distinct_statements(self):
        self.assertEqual([c['text'] for c in sentence_segments([timed('别动。放下武器！')])], ['别动。', '放下武器！'])

    def test_readability_limit_can_split_long_statement_at_comma(self):
        text = '这是一段需要足够阅读时间的很长很长的叙述' * 2 + '，然后才发生下一件事情。'
        rows = sentence_segments([timed(text)])
        self.assertGreater(len(rows), 1)
        self.assertEqual(''.join(c['text'] for c in rows), text)
        self.assertTrue(rows[0]['text'].endswith('，'))

    def test_ocr_group_preserves_names_even_when_asr_misrecognizes_one(self):
        picture = [cue(1, 2, '陈浩宇请你',speaker='A'), cue(2, 4, '现在马上放下武器',speaker='A')]
        heard = [cue(1, 4, '陈浩雨请你现在马上放下武器。')]
        grouped, joins = subtitles.refine_picture_phrases(picture, heard)
        self.assertEqual(joins, 1)
        self.assertEqual(grouped[0]['text'], '陈浩宇请你现在马上放下武器')
        _, _, review = subtitles.merge_picture_and_speech(grouped, heard)
        self.assertEqual(len(review), 1)

    def test_known_speaker_change_is_never_joined(self):
        picture = [cue(1, 2, '请你现在', speaker='A'), cue(2, 3, '马上放下武器', speaker='B')]
        rows, joins = subtitles.refine_picture_phrases(picture, [cue(1, 3, '请你现在马上放下武器。')])
        self.assertEqual(joins, 0)
        self.assertEqual(rows, picture)

    def test_hybrid_uses_paraformer_with_picture_and_persists_disagreements(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            video = root / 'ep.mp4'; video.touch()
            store = SubtitleJobStore(root / 'jobs.sqlite3')
            def audio(video, ffmpeg, temp, output):
                output.write_text('1\n00:00:01,000 --> 00:00:03,000\n声音里不同的话。\n')
            with patch.object(subtitles, '_review_store', store), patch.object(subtitles, '_analysis_cache', {}), patch.object(subtitles, '_subtitles_from_picture', return_value=[[1, 3, '陈浩宇说原来的话']]), patch.object(subtitles, '_subtitles_from_funasr', side_effect=audio), patch.object(subtitles, '_subtitles_from_audio') as whisper:
                report = {}
                srt, method = subtitles.create_subtitles(video, mode='hybrid', report=report)
                self.assertEqual(method, 'hybrid')
                self.assertIn('陈浩宇', srt.read_text())
                self.assertEqual(report['speech_engine'], 'paraformer')
                self.assertEqual(report['quality_state'], 'needs_review')
                whisper.assert_not_called()
                subtitles._analysis_cache.clear()
                # New SQLite connection + empty memory cache represents a restart.
                with patch.object(subtitles, '_review_store', SubtitleJobStore(store.path)):
                    self.assertEqual(subtitles.subtitle_analysis(video)['review_candidates'], report['review_candidates'])
                    old = srt.stat().st_mtime_ns
                    os.utime(srt, ns=(old + 1000000, old + 1000000))
                    self.assertEqual(subtitles.subtitle_analysis(video), {})
                self.assertFalse(list(root.glob('*.json')))

    def test_hybrid_failure_keeps_ocr_and_marks_review(self):
        with tempfile.TemporaryDirectory() as name:
            video = Path(name) / 'ep.mp4'; video.touch(); report = {}
            with patch.object(subtitles, '_subtitles_from_picture', return_value=[[1, 3, '保留原文']]), patch.object(subtitles, '_subtitles_from_funasr', side_effect=RuntimeError('engine unavailable')):
                srt, _ = subtitles.create_subtitles(video, mode='hybrid', report=report)
            self.assertIn('保留原文', srt.read_text())
            self.assertEqual(report['quality_state'], 'needs_review')
            self.assertTrue(report['warnings'])
