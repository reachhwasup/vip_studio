import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码_开源版'))
import app as backend

class SubtitleReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.video=Path(self.temp.name)/'episode.mp4';self.video.touch();self.srt=self.video.with_suffix('.srt');self.srt.write_text('1\n00:00:01,000 --> 00:00:02,000\n你好\n')
        self.original=self.srt.read_bytes();self.resolver=patch.object(backend,'local_video_path',return_value=self.video);self.resolver.start();self.client=backend.app.test_client();self.revision=self.client.get('/api/subtitles/review?url=/src/episode.mp4').json['revision']
    def tearDown(self):self.resolver.stop();self.temp.cleanup()
    def save(self,segments,revision=None):return self.client.post('/api/subtitles/review',json={'url':'/src/episode.mp4','revision':revision or self.revision,'segments':segments})
    def test_save_and_backup(self):
        response=self.save([{'start_time':2,'end_time':3,'text':'再见'}]);self.assertEqual(response.status_code,200);self.assertIn('再见',self.srt.read_text());self.assertEqual(next(Path(self.temp.name).glob('*.backup-*')).read_bytes(),self.original)
    def test_stale_revision_does_not_overwrite(self):
        self.srt.write_text('changed externally');response=self.save([{'start_time':2,'end_time':3,'text':'再见'}]);self.assertEqual(response.status_code,409);self.assertEqual(self.srt.read_text(),'changed externally')
    def test_invalid_times_empty_text_and_overlap_rejected(self):
        for cue in [{'start_time':-1,'end_time':3,'text':'a'},{'start_time':3,'end_time':2,'text':'a'},{'start_time':1,'end_time':2,'text':''},{'start_time':1,'end_time':float('nan'),'text':'a'},{'start_time':False,'end_time':2,'text':'a'}]:
            self.assertEqual(self.save([cue]).status_code,400)
        self.assertEqual(self.save([{'start_time':1,'end_time':3,'text':'a'},{'start_time':2,'end_time':4,'text':'b'}]).status_code,400)
        self.assertEqual(self.srt.read_bytes(),self.original)
    def test_external_symlink_is_rejected(self):
        external=Path(self.temp.name)/'other.srt';external.write_bytes(self.original);self.srt.unlink();self.srt.symlink_to(external)
        self.assertEqual(self.client.get('/api/subtitles/review?url=/src/episode.mp4').status_code,400)
    def test_busy_ocr_keeps_existing_srt(self):
        import subtitles
        with subtitles._lock:
            response=self.save([{'start_time':2,'end_time':3,'text':'a'}])
        self.assertEqual(response.status_code,409);self.assertEqual(self.srt.read_bytes(),self.original)
