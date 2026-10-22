import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码_开源版'))
import app as backend


class NotificationHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.runtime=patch.object(backend.parser_module,'get_runtime_base_dir',return_value=self.root)
        self.runtime.start()
        self.client=backend.app.test_client()
    def tearDown(self):
        self.runtime.stop()
        self.tmp.cleanup()
    def test_empty_until_first_notification(self):
        self.assertEqual(self.client.get('/api/notifications').json,{'items':[]})
        self.assertFalse((self.root/'notification_history.json').exists())
    def test_saved_recent_first_with_kind_and_time(self):
        self.client.post('/api/notifications',json={'title':'Downloads finished','body':'3 done','kind':'success'})
        response=self.client.post('/api/notifications',json={'title':' Downloads paused ','body':'Network down','kind':'bogus'})
        self.assertEqual(response.status_code,200)
        items=self.client.get('/api/notifications').json['items']
        self.assertEqual(items,response.json['items'])
        self.assertEqual([x['title'] for x in items],['Downloads paused','Downloads finished'])
        self.assertEqual([x['kind'] for x in items],['info','success'])
        self.assertEqual(items[1]['body'],'3 done')
        self.assertGreater(items[0]['created_at'],0)
    def test_title_required_and_text_trimmed(self):
        self.assertEqual(self.client.post('/api/notifications',json={'body':'no title'}).status_code,400)
        self.assertEqual(self.client.post('/api/notifications',data='not json').status_code,400)
        item=self.client.post('/api/notifications',json={'title':'t'*500,'body':'b'*5000}).json['items'][0]
        self.assertEqual((len(item['title']),len(item['body'])),(160,1000))
    def test_parallel_saves_and_limit(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda i:backend.remember_notification(f'n{i}'),range(20)))
        self.assertEqual(len(backend.read_notifications()),20)
        for i in range(110):backend.remember_notification(str(i))
        items=backend.read_notifications()
        self.assertEqual(len(items),100)
        self.assertEqual(items[0]['title'],'109')
    def test_clear(self):
        backend.remember_notification('one')
        self.assertEqual(self.client.delete('/api/notifications').json,{'items':[]})
        self.assertEqual(self.client.get('/api/notifications').json,{'items':[]})
    def test_corrupt_history_not_overwritten_by_new_notification(self):
        path=self.root/'notification_history.json';path.write_text('broken')
        self.assertEqual(self.client.get('/api/notifications').status_code,500)
        self.assertEqual(self.client.post('/api/notifications',json={'title':'one'}).status_code,500)
        self.assertEqual(path.read_text(),'broken')


if __name__=='__main__':unittest.main()
