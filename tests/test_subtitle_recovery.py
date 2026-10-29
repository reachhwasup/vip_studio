import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码_开源版'))
import app as backend

class RecoveryTests(unittest.TestCase):
    def test_missing_without_history_108_of_184(self):
        with tempfile.TemporaryDirectory() as folder:
            paths={}
            for i in range(184):
                video=Path(folder)/f'{i}.mp4';video.write_bytes(b'video');paths[f'/src/{i}.mp4']=video
                if i<108:video.with_suffix('.srt').write_text('saved')
            with patch.object(backend,'SUBTITLE_JOBS',{}),patch.object(backend,'local_video_path',side_effect=paths.get),patch.object(backend,'enqueue_subtitle_job',return_value={'id':'job'}) as enqueue:
                response=backend.app.test_client().post('/api/subtitles/recover',json={'urls':list(paths)})
            self.assertEqual(response.json['queued'],76)
            self.assertEqual(response.json['saved'],108)
            self.assertEqual(enqueue.call_count,76)

    def test_active_dedup_and_failed_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            a=Path(folder)/'a.mp4';b=Path(folder)/'b.mp4'
            a.touch();b.touch()
            jobs={'a':dict(key=str(a.resolve()),status='running'),'b':dict(key=str(b.resolve()),status='error',mode='funasr',language='zh',cpu_threads=1)}
            with patch.object(backend,'SUBTITLE_JOBS',jobs),patch.object(backend,'local_video_path',side_effect=lambda u:{'/a':a,'/b':b}.get(u)),patch.object(backend,'enqueue_subtitle_job',return_value={'id':'job'}) as enqueue:
                r=backend.app.test_client().post('/api/subtitles/recover',json={'urls':['/a','/b','/b','/missing']})
            self.assertEqual((r.json['queued'],r.json['active'],r.json['failed']),(1,1,1))
            self.assertEqual(enqueue.call_args.args[2:],('funasr','zh'))
            self.assertEqual(enqueue.call_args.kwargs['cpu_threads'],1)

    def test_invalid_request_does_not_enqueue(self):
        with patch.object(backend,'enqueue_subtitle_job') as enqueue:
            for body in [{},{'urls':['//evil']},{'urls':[],'mode':'bad'}]:
                self.assertEqual(backend.app.test_client().post('/api/subtitles/recover',json=body).status_code,400)
            enqueue.assert_not_called()
