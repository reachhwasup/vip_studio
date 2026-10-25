import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '源码_开源版'))
import app

class SubtitleWorkspaceTests(unittest.TestCase):
    def test_shared_job_list_includes_live_and_finished_jobs_without_internal_paths(self):
        jobs = {
            'download': {'id': 'download', 'key': '/private/video.mp4', 'title': 'Episode 1', 'status': 'running', 'progress': 62, 'completed': 248, 'total': 400},
            'library': {'id': 'library', 'key': '/private/video2.mp4', 'title': 'Episode 2', 'status': 'done', 'subtitle_url': '/src/2.srt'},
        }
        with patch.object(app, 'SUBTITLE_JOBS', jobs):
            response = app.app.test_client().get('/api/subtitles/jobs')
        self.assertEqual(response.status_code, 200)
        result = response.json['jobs']
        self.assertEqual([job['id'] for job in result], ['library', 'download'])
        self.assertEqual(result[1]['progress'], 62)
        self.assertEqual(result[1]['completed'], 248)
        self.assertTrue(all('key' not in job for job in result))
        self.assertEqual(jobs['download']['key'], '/private/video.mp4')

    def test_empty_session_returns_empty_jobs(self):
        with patch.object(app, 'SUBTITLE_JOBS', {}):
            response = app.app.test_client().get('/api/subtitles/jobs')
        self.assertEqual(response.json, {'jobs': []})
