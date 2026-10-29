import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'源码_开源版'))
import app

class AllSourcesTests(unittest.TestCase):
    def test_groups_matching_titles_and_keeps_distinct_names(self):
        def search(keyword,page,source,category):
            return [{'title':' Same  Title ','drama_id':'1','source':source},{'title':'Different '+source,'drama_id':'2','source':source}]
        with patch.object(app,'search_short_drama',side_effect=search):
            items,warnings=app.search_all_sources('',1,'')
        self.assertEqual(len(items),3)
        self.assertEqual(len(items[0]['variants']),2)
        self.assertEqual(warnings,[])
    def test_pagination_never_loses_unique_results(self):
        def search(keyword,page,source,category):
            return [{'title':f'{source}-{page}-{i}','drama_id':str(i),'source':source} for i in range(50)]
        with patch.object(app,'search_short_drama',side_effect=search):
            pages=[app.search_all_sources('',p,'')[0] for p in [1,2,3,4]]
        self.assertEqual([len(p) for p in pages],[50]*4)
        self.assertEqual(len({x['title'] for p in pages for x in p}),200)
    def test_partial_failure_preserves_results_and_warning(self):
        def search(keyword,page,source,category):
            if source=='gz360':raise ValueError('offline')
            return [{'title':'Drama','drama_id':'1','source':source}]
        with patch.object(app,'search_short_drama',side_effect=search):
            response=app.app.test_client().get('/api/search?source=all&page=1')
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.json['items']),1)
        self.assertIn('GZ360',response.json['warnings'][0])
    def test_both_sources_failing_returns_error(self):
        with patch.object(app,'search_short_drama',side_effect=ValueError('offline')):
            self.assertEqual(app.app.test_client().get('/api/search?source=all').status_code,500)

    def test_merged_title_prefers_source_with_playable_episodes(self):
        for gz_available in [True,False]:
            with self.subTest(gz_available=gz_available):
                def search(keyword,page,source,category):
                    playable=(source=='gz360')==gz_available
                    return [{'title':'Same title','drama_id':source,'downloadable':playable,'availability':'available' if playable else 'unavailable'}]
                with patch.object(app,'search_short_drama',side_effect=search):items,warnings=app.search_all_sources('',1,'')
                self.assertEqual(len(items),1);self.assertTrue(items[0]['downloadable'])
                self.assertEqual(items[0]['availability'],'available')
                self.assertEqual(items[0]['source_label'],'GZ360' if gz_available else 'Hongguo')
                self.assertEqual(len(items[0]['variants']),2)
