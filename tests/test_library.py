import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '源码_开源版'))
import app as backend


class LibraryTests(unittest.TestCase):
    def test_library_groups_sorts_and_excludes_unfinished_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            folder = root / 'Drama'
            folder.mkdir()
            for name in ['Episode 10.mp4', 'Episode 2.mp4', 'poster.jpg', '.Episode 3.mp4.partial', '.hidden.mp4']:
                (folder / name).write_bytes(b'test')
            (folder / 'empty.mp4').touch()
            (folder / 'link.mp4').symlink_to(folder / 'Episode 2.mp4')
            with patch.object(backend, 'library_roots', return_value=[root, root]):
                response = backend.app.test_client().get('/api/library')
            self.assertEqual(response.status_code, 200)
            items = response.json['items']
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]['title'], 'Drama')
            self.assertEqual([ep['title'] for ep in items[0]['episodes']], ['Episode 2', 'Episode 10'])
            self.assertTrue(items[0]['poster'].endswith('/Drama/poster.jpg'))

    def test_empty_library(self):
        with patch.object(backend, 'library_roots', return_value=[]):
            self.assertEqual(backend.app.test_client().get('/api/library').json, {'items': []})

    def test_open_folder_rejects_escape_and_opens_selected_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            folder = root / 'Drama'
            folder.mkdir()
            with patch.object(backend, 'download_root', return_value=root), patch.object(backend.sys, 'platform', 'darwin'), patch.object(backend.subprocess, 'Popen') as launch:
                client = backend.app.test_client()
                self.assertEqual(client.post('/api/library/open-folder', json={'root': 'key', 'folder': '..'}).status_code, 404)
                launch.assert_not_called()
                self.assertEqual(client.post('/api/library/open-folder', json={'root': 'key', 'folder': 'Drama'}).status_code, 200)
                launch.assert_called_once_with(['open', str(folder)])
                self.assertEqual(client.post('/api/library/open-folder', json=[]).status_code, 400)
