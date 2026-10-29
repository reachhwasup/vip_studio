import sys,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码_开源版'))
import app as backend
from subtitle_jobs import SubtitleJobStore
class FolderWaitTests(unittest.TestCase):
    def test_absent_drive_preserves_queue_and_reconnect_submits_once(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();video=root/'episode.mp4'
            job=dict(id='test-wait',key=str(video),video_url='/downloads/offline/episode.mp4',status='running',created_at=1)
            store=SubtitleJobStore(root/'subtitle-jobs.sqlite3');store.save(job)
            with patch.object(backend,'SUBTITLE_JOBS',{}),patch.object(backend,'SUBTITLE_JOB_STORE',None),patch.object(backend.parser_module,'get_runtime_base_dir',return_value=root),patch.object(backend,'local_video_path',return_value=None),patch.object(backend,'download_file_state',return_value='unknown'),patch('subtitles.configure_review_store'),patch.object(backend.SUBTITLE_REPAIR_POOL,'submit') as submit:
                backend.initialize_subtitle_jobs()
                self.assertEqual(backend.SUBTITLE_JOBS[job['id']]['stage'],'Waiting for download folder')
                self.assertEqual(backend.SUBTITLE_JOBS[job['id']]['status'],'queued')
                submit.assert_not_called()
                video.touch()
                with patch.object(backend,'local_video_path',return_value=video):
                    backend.resume_folder_waiting_subtitles();backend.resume_folder_waiting_subtitles()
                submit.assert_called_once()
