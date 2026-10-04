import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '源码_开源版'))
from subtitle_formats import import_subtitles, export_subtitles, normalize_segments
from app import app


class SubtitleFormatTests(unittest.TestCase):
    def parse(self, text, suffix='srt', encoding='utf-8'):
        return import_subtitles(text.encode(encoding), 'captions.' + suffix)['segments']

    def test_srt_optional_numbers_hours_and_fraction_precision(self):
        cues = self.parse('1\n00:00:01,000 --> 00:00:03,500\nFirst caption\n\n00:05.2 --> 00:07.25\nSecond caption\ncontinued')
        self.assertEqual([(x['start_time'], x['end_time']) for x in cues], [(1, 3.5), (5.2, 7.25)])
        self.assertEqual(cues[1]['text'], 'Second caption\ncontinued')

    def test_vtt_metadata_voice_entities(self):
        cues = self.parse('WEBVTT\n\nNOTE ignore this\n00:00.000 --> 00:01.000\nnot dialogue\n\ncue-name\n00:01.000 --> 00:03.000 position:20% align:start\n<v Roger><b>Where &amp; why?</b>\n\nSTYLE\n::cue {color: red}', 'vtt')
        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0]['speaker'], 'Roger')
        self.assertEqual(cues[0]['text'], 'Where & why?')

    def test_ass_format_order_drawings_comments(self):
        text = r'''[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Comment: 0,0:00:01.00,0:00:03.50,Default,Name,0,0,0,,Ignore
Dialogue: 0,0:00:01.00,0:00:03.50,Default,秦风,0,0,0,,{\an8}粗糙是粗糙，\N能成都行
Dialogue: 0,0:00:04.00,0:00:05.00,Default,,0,0,0,,{\p1}m 0 0 l 20 20{\p0}
Dialogue: 0,0:00:06.00,0:00:07.00,Default,,0,0,0,,{\p1}m 0 0{\p0}Hello, there
Format: Start, Text, End, Name
Dialogue: 0:00:08.00,Hello, world,0:00:09.00,Lin'''
        cues = self.parse(text, 'ass')
        self.assertEqual(len(cues), 3)
        self.assertEqual(cues[0]['speaker'], '秦风')
        self.assertEqual(cues[0]['text'], '粗糙是粗糙，\n能成都行')
        self.assertEqual(cues[1]['text'], 'Hello, there')
        self.assertEqual(cues[2]['text'], 'Hello, world')

    def test_json_preserves_translation_original_and_speaker(self):
        text = '{"segments":[{"start_time":1,"end_time":2,"text":"សួស្តី","original_text":"你好","speaker":"Lin"}]}'
        cues = self.parse(text, 'json')
        self.assertEqual(self.parse(export_subtitles(cues, 'json'), 'json'), cues)
        self.assertIn('សួស្តី', export_subtitles(cues, 'srt'))
        self.assertNotIn('你好', export_subtitles(cues, 'srt'))

    def test_speaker_prefixes_need_recurring_names(self):
        lines = ['Lin: First', '[Lin] Second', '【Lin】Third', 'Note: he left']
        text = '\n\n'.join(f'00:0{i}.0 --> 00:0{i+1}.0\n{line}' for i, line in enumerate(lines))
        cues = self.parse(text)
        self.assertEqual([x['speaker'] for x in cues], ['Lin', 'Lin', 'Lin', ''])
        self.assertEqual(cues[-1]['text'], 'Note: he left')
        self.assertEqual(self.parse('00:01 --> 00:02\nLin: One-off')[0]['text'], 'Lin: One-off')

    def test_cleanup_invalid_music_duplicates_and_duration(self):
        rows = [
            {'start_time': 4, 'end_time': 100, 'text': 'Hello\nHello\n[Music]'},
            {'start_time': 4, 'end_time': 6, 'text': 'Hello'},
            {'start_time': 1, 'end_time': 1, 'text': 'invalid'},
            {'start_time': 1, 'end_time': 2, 'text': '[Music]'},
            {'start_time': 1, 'end_time': 2, 'text': '♪ ♫'},
            {'start_time': -1, 'end_time': 2, 'text': 'invalid'},
            {'start_time': float('nan'), 'end_time': 2, 'text': 'invalid'},
        ]
        self.assertEqual(normalize_segments(rows), [{'start_time': 4, 'end_time': 34, 'text': 'Hello', 'speaker': '', 'original_text': ''}])

    def test_encodings(self):
        for encoding, caption in [('utf-8-sig','你好，今天的天气很好。'), ('utf-16','你好，今天的天气很好。'), ('utf-16-le','你好'), ('utf-16-be','你好'), ('gb18030','你好，今天的天气很好。'), ('big5','你好，今天的天氣很好。')]:
            with self.subTest(encoding=encoding):
                self.assertEqual(self.parse('00:01 --> 00:02\n'+caption, encoding=encoding)[0]['text'], caption)

    def test_plain_text_and_malformed_json_refused(self):
        for text, suffix in [('No timings', 'txt'), ('No timings', 'srt'), ('[]','json'), ('{','json'), ('{"segments":{}}','json')]:
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                self.parse(text, suffix)

    def test_times_are_not_shifted_and_exports_are_readable(self):
        cues = self.parse('00:05.2 --> 00:07.25\n<v Lin>Hello')
        for format_name in ['srt','vtt','ass','ssa','json']:
            with self.subTest(format_name=format_name):
                result = self.parse(export_subtitles(cues, format_name), format_name)
                self.assertEqual(result[0]['start_time'], 5.2)
                self.assertEqual(result[0]['end_time'], 7.25)

    def test_api_import_export_errors(self):
        client = app.test_client()
        response = client.post('/api/subtitles/import', data={'file':(io.BytesIO(b'00:01 --> 00:02\nHello'), 'test.srt')})
        self.assertEqual(response.status_code, 200)
        exported = client.post('/api/subtitles/export', json={'segments':response.json['segments'], 'format':'vtt'})
        self.assertEqual(exported.status_code, 200)
        self.assertTrue(exported.data.startswith(b'WEBVTT'))
        self.assertEqual(client.post('/api/subtitles/import').status_code, 400)
        self.assertEqual(client.post('/api/subtitles/export', json={'segments':[], 'format':'srt'}).status_code, 400)
        self.assertEqual(client.post('/api/subtitles/export', json={'segments':[], 'format':{}}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
