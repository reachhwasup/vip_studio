import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '源码_开源版'))
import app as backend

class BulkRetryTests(unittest.TestCase):
    def test_latest_attempt_only_and_settings_preserved(self):
        jobs = {str(i): dict(key=key, status=status, video_url='/src/'+key+'.mp4', mode='funasr', language='zh', cpu_threads=1) for i,(key,status) in enumerate([('a','error'),('b','error'),('a','done'),('c','error'),('c','running'),('d','error')])}
        with patch.object(backend,'SUBTITLE_JOBS',jobs), patch.object(backend,'local_video_path',return_value=Path('/video.mp4')), patch.object(backend,'enqueue_subtitle_job',return_value={'id':'new'}) as enqueue:
            response=backend.app.test_client().post('/api/subtitles/retry-failed')
        self.assertEqual(response.json['queued'],2)
        self.assertEqual([call.args[1] for call in enqueue.call_args_list],['/src/b.mp4','/src/d.mp4'])
        self.assertEqual(enqueue.call_args.args[2:],('funasr','zh'))
        self.assertEqual(enqueue.call_args.kwargs,{'download':True,'cpu_threads':1})

    def test_missing_video_and_full_queue_reported(self):
        jobs={str(i):dict(key=str(i),status='error',video_url='/src/'+str(i)+'.mp4') for i in range(2)}
        with patch.object(backend,'SUBTITLE_JOBS',jobs),patch.object(backend,'local_video_path',side_effect=[None,Path('/video.mp4')]),patch.object(backend,'enqueue_subtitle_job',side_effect=ValueError('Queue full')):
            response=backend.app.test_client().post('/api/subtitles/retry-failed')
        self.assertEqual(response.json['queued'],0)
        self.assertEqual(response.json['failed'],2)

    def test_empty_queue(self):
        with patch.object(backend,'SUBTITLE_JOBS',{}):
            self.assertEqual(backend.app.test_client().post('/api/subtitles/retry-failed').json['queued'],0)

    def test_library_scope_does_not_retry_other_dramas(self):
        jobs={str(i):dict(key=str(i),status='error',video_url='/src/'+str(i)+'.mp4') for i in range(2)}
        with patch.object(backend,'SUBTITLE_JOBS',jobs),patch.object(backend,'local_video_path',return_value=Path('/video.mp4')),patch.object(backend,'enqueue_subtitle_job',return_value={'id':'new'}) as enqueue:
            client=backend.app.test_client()
            self.assertEqual(client.post('/api/subtitles/retry-failed',json={'urls':['/src/1.mp4']}).json['queued'],1)
            self.assertEqual(enqueue.call_args.args[1],'/src/1.mp4')
            self.assertEqual(client.post('/api/subtitles/retry-failed',json={'urls':[]}).json['queued'],0)
            self.assertEqual(client.post('/api/subtitles/retry-failed',json={'urls':'invalid'}).status_code,400)
            self.assertEqual(enqueue.call_count,1)
