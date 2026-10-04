import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码_开源版'))
import app as backend


class DramaHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.runtime=patch.object(backend.parser_module,'get_runtime_base_dir',return_value=self.root)
        self.runtime.start()
    def tearDown(self):
        self.runtime.stop()
        self.tmp.cleanup()
    def test_episodes_save_identity_and_survive_queue_clear(self):
        detail={'series_id':'123','title':'Drama','cover':'cover.jpg','vid_list':['one','two']}
        with patch.object(backend.parser_module,'get_hongguo_series_detail',return_value=detail):
            response=backend.app.test_client().get('/api/episodes?id=123')
        self.assertEqual(response.status_code,200)
        history=backend.app.test_client().get('/api/drama-history').json['items']
        self.assertEqual(history[0]['series_id'],'123')
        self.assertEqual(history[0]['total'],2)
        self.assertTrue((self.root/'drama_history.json').is_file())
    def test_recent_first_deduplicated_and_progress_preserved(self):
        backend.remember_drama({'series_id':'one','title':'One'})
        backend.remember_drama({'series_id':'two','title':'Two'})
        backend.remember_drama(series_id='one',episode=3)
        backend.remember_drama({'series_id':'one','title':'Updated'})
        items=backend.read_drama_history()
        self.assertEqual([x['series_id'] for x in items],['one','two'])
        self.assertEqual(items[0]['downloaded_episodes'],[3])
        self.assertEqual(items[0]['last_episode'],3)
    def test_parallel_updates_and_limit(self):
        backend.remember_drama({'series_id':'one','title':'One'})
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda ep:backend.remember_drama(series_id='one',episode=ep),range(1,10)))
        self.assertEqual(backend.read_drama_history()[0]['downloaded_episodes'],list(range(1,10)))
        for i in range(110):backend.remember_drama({'series_id':str(i),'title':str(i)})
        items=backend.read_drama_history()
        self.assertEqual(len(items),100)
        self.assertEqual(items[0]['series_id'],'109')
    def test_corrupt_history_not_overwritten(self):
        path=self.root/'drama_history.json';path.write_text('broken')
        self.assertEqual(backend.app.test_client().get('/api/drama-history').status_code,500)
        with self.assertRaises(ValueError):backend.remember_drama({'series_id':'one'})
        self.assertEqual(path.read_text(),'broken')


if __name__=='__main__':unittest.main()
