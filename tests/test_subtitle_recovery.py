import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '源码_开源版'))
import app
from subtitle_jobs import SubtitleJobStore

class SubtitleRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.video = self.root / 'Episode 119.mp4'
        self.video.touch()
        self.store = SubtitleJobStore(self.root / 'subtitle-jobs.sqlite3')
        self.job = {'id':'original-id', 'key':str(self.video.resolve()), 'video_url':'/src/119.mp4', 'subtitle_url':'/src/119.srt', 'status':'running', 'mode':'picture', 'language':'zh', 'progress':62, 'original_srt_mtime_ns':0}
        for name, value in [('SUBTITLE_JOBS',{}), ('SUBTITLE_JOB_STORE',None), ('local_video_path',lambda url: self.video if self.video.exists() and url == '/src/119.mp4' else None)]:
            context = patch.object(app,name,value);context.start();self.addCleanup(context.stop)
        context=patch.object(app.parser_module,'get_runtime_base_dir',return_value=self.root);context.start();self.addCleanup(context.stop)

    def test_restart_preserves_id_and_options_and_resubmits_once(self):
        self.store.save(self.job)
        with patch.object(app.SUBTITLE_REPAIR_POOL,'submit') as submit:
            app.initialize_subtitle_jobs();app.initialize_subtitle_jobs()
        submit.assert_called_once_with(app.run_subtitle_repair,'original-id',self.video)
        recovered = app.SUBTITLE_JOBS['original-id']
        self.assertEqual(recovered['status'],'queued');self.assertIsNone(recovered['progress'])
        self.assertEqual(recovered['mode'],'picture');self.assertEqual(recovered['language'],'zh')
        self.assertEqual(SubtitleJobStore(self.store.path).load()[0]['status'],'queued')
        self.assertFalse(list(self.root.glob('*.json')))

    def test_srt_saved_before_restart_is_recognised_without_ocr(self):
        self.store.save(self.job)
        self.video.with_suffix('.srt').write_text('1\n00:00:01,000 --> 00:00:02,000\nHello\n')
        with patch.object(app.SUBTITLE_REPAIR_POOL,'submit') as submit:app.initialize_subtitle_jobs()
        submit.assert_not_called()
        self.assertEqual(app.SUBTITLE_JOBS['original-id']['status'],'done')
        self.assertEqual(app.SUBTITLE_JOBS['original-id']['captions'],1)

    def test_existing_old_srt_does_not_skip_requested_regeneration(self):
        srt=self.video.with_suffix('.srt');srt.write_text('1\n00:00:01,000 --> 00:00:02,000\nOld\n')
        self.job['original_srt_mtime_ns']=srt.stat().st_mtime_ns;self.store.save(self.job)
        with patch.object(app.SUBTITLE_REPAIR_POOL,'submit') as submit:app.initialize_subtitle_jobs()
        submit.assert_called_once()
        self.assertEqual(app.SUBTITLE_JOBS['original-id']['status'],'queued')

    def test_missing_video_is_reported_without_submitting_work(self):
        self.store.save(self.job);self.video.unlink()
        with patch.object(app.SUBTITLE_REPAIR_POOL,'submit') as submit:app.initialize_subtitle_jobs()
        submit.assert_not_called()
        self.assertEqual(app.SUBTITLE_JOBS['original-id']['status'],'error')
        self.assertIn('folder',app.SUBTITLE_JOBS['original-id']['error'])

    def test_enqueue_and_completion_are_durable(self):
        app.SUBTITLE_JOB_STORE=self.store
        with patch.object(app.SUBTITLE_REPAIR_POOL,'submit'):
            job=app.enqueue_subtitle_job(self.video,'/src/119.mp4',mode='picture')
        self.assertEqual(self.store.load()[0]['id'],job['id'])
        srt=self.video.with_suffix('.srt');srt.write_text('1\n00:00:01,000 --> 00:00:02,000\nHello\n')
        with patch.object(app,'create_subtitles',return_value=(srt,'picture')):app.run_subtitle_repair(job['id'],self.video)
        self.assertEqual(self.store.load()[0]['status'],'done')

    def test_legacy_reconciliation_distinguishes_saved_srt_active_work_and_interruption(self):
        client=app.app.test_client()
        response=client.post('/api/subtitles/reconcile',json={'urls':['/src/119.mp4']})
        self.assertEqual(response.json['jobs']['/src/119.mp4']['status'],'interrupted')
        self.video.with_suffix('.srt').write_text('1\n00:00:01,000 --> 00:00:02,000\nSaved\n')
        response=client.post('/api/subtitles/reconcile',json={'urls':['/src/119.mp4']})
        self.assertEqual(response.json['jobs']['/src/119.mp4']['status'],'done')
        app.SUBTITLE_JOBS['original-id']=dict(self.job)
        response=client.post('/api/subtitles/reconcile',json={'urls':['/src/119.mp4']})
        self.assertEqual(response.json['jobs']['/src/119.mp4']['id'],'original-id')
        self.assertNotIn('key',response.json['jobs']['/src/119.mp4'])
        app.SUBTITLE_JOBS['original-id']['status']='done'
        self.video.with_suffix('.srt').unlink()
        response=client.post('/api/subtitles/reconcile',json={'urls':['/src/119.mp4']})
        self.assertEqual(response.json['jobs']['/src/119.mp4']['status'],'interrupted')
        self.assertEqual(client.post('/api/subtitles/reconcile',json={'urls':['x']*201}).status_code,400)
