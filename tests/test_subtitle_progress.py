import sys,tempfile,json,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码_开源版'))
import subtitles
import app
class SubtitleProgressTests(unittest.TestCase):
 def test_ocr_progress_is_streamed_before_final_json_and_does_not_pollute_frames(self):
  records=[json.dumps({'file':f'{i:06}.jpg','lines':[]})+'\n' for i in (1,2)]
  process=Mock(stdout=['VIP_OCR_PROGRESS 0/2\n','{diagnostic message}\n','VIP_OCR_PROGRESS 1/2\n','VIP_OCR_PROGRESS 2/2\n',*records],wait=Mock(return_value=0))
  events=[]
  with subtitles._progress_session(events.append),patch.object(subtitles.subprocess,'Popen',return_value=process):
   output=subtitles._run(['ocr','/tmp/frames_probed'],capture=True)
  self.assertEqual([event['progress'] for event in events],[0,50,100])
  self.assertEqual(events[1]['completed'],1);self.assertEqual(events[1]['total'],2)
  self.assertEqual(len(output.splitlines()),2);self.assertNotIn('VIP_OCR_PROGRESS',output)
 def test_speech_progress_is_not_estimated(self):
  process=Mock(stdout=['loading model\n','whisper_print_progress_callback: progress = 27%\n'],wait=Mock(return_value=0))
  events=[]
  with subtitles._progress_session(events.append),patch.object(subtitles.subprocess,'Popen',return_value=process):subtitles._run(['whisper-cli','-pp'])
  self.assertEqual(events,[{'stage':'Transcribing speech locally','progress':27,'completed':None,'total':None}])
 def test_callback_is_restored_after_failure(self):
  with self.assertRaises(ValueError),subtitles._progress_session(lambda value:None):raise ValueError('failed')
  self.assertIsNone(getattr(subtitles._progress_state,'callback',None))
 def test_job_publishes_live_counts_and_finishes_at_100(self):
  with tempfile.TemporaryDirectory() as tmp:
   video=Path(tmp)/'video.mp4';video.touch();srt=video.with_suffix('.srt')
   srt.write_text('1\n00:00:01,000 --> 00:00:02,000\nHello\n')
   def create(*args,progress,**kwargs):
    progress({'stage':'Reading on-screen captions','progress':50,'completed':1,'total':2})
    status=app.app.test_client().get('/api/subtitles/status?ids=job').json['jobs']['job']
    self.assertEqual(status['status'],'running');self.assertEqual(status['progress'],50);self.assertEqual(status['total'],2)
    return srt,'picture'
   with patch.object(app,'SUBTITLE_JOBS',{'job':{'id':'job','status':'queued'}}),patch.object(app,'create_subtitles',side_effect=create):
    app.run_subtitle_repair('job',video)
    self.assertEqual(app.SUBTITLE_JOBS['job']['progress'],100);self.assertEqual(app.SUBTITLE_JOBS['job']['status'],'done')
