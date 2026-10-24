from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import match_sample_probe as sample
from prematch_archive import Archive,Observation,API_FOOTBALL,fetch


class SampleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'sample.sqlite3'
        self.secret='fixture-private-key'
        self.fixture={'fixture':{'id':123,'date':'2024-08-16T19:00:00+00:00','status':{'short':'FT'}},
                      'league':{'id':39,'season':2024},'teams':{'home':{'id':33},'away':{'id':36}}}
        self.stats=[{'team':{'id':team},'statistics':[{'type':'expected_goals','value':value}]} for team,value in [(33,'0'),(36,'1.25')]]
        self.lineups=[{'team':{'id':team},'startXI':[{'player':{'id':team*100+i}} for i in range(11)]} for team in [33,36]]

    def observations(self,injuries=None):
        payloads=[[self.fixture],self.stats,self.lineups,injuries or []]
        urls=[sample.FIXTURE_URL]+[API_FOOTBALL+p+'?fixture=123' for p in ['fixtures/statistics','fixtures/lineups','injuries']]
        return [Observation(url,json.dumps({'errors':[],'results':len(rows),'paging':{'total':1},'response':rows}).encode(),datetime.now(timezone.utc)) for url,rows in zip(urls,payloads)]

    def test_four_calls_identity_xg_zero_empty_injuries_and_persisted_reuse(self):
        with patch.object(sample,'fetch',side_effect=self.observations()) as network:
            first=sample.probe(self.secret,self.path)
            second=sample.probe(self.secret,self.path)
        self.assertEqual(network.call_count,4);self.assertEqual(first,second)
        self.assertTrue(first['ok']);self.assertFalse(first['model_eligible'])
        self.assertEqual(first['parts']['statistics']['xg'],{'33':0.0,'36':1.25})
        self.assertEqual(first['parts']['lineups']['count'],22)
        self.assertEqual(first['parts']['injuries']['state'],'empty')
        self.assertNotIn(self.secret,json.dumps(first))
        a=Archive(self.path);self.addCleanup(a.close)
        saved=a.latest('api_football_sample','123:statistics',datetime.now(timezone.utc)+timedelta(seconds=1))
        self.assertFalse(saved['model_eligible']);self.assertIsNone(saved['published_at'])
        self.assertIsNone(a.latest('api_football_sample','123:statistics',datetime(2024,8,16,tzinfo=timezone.utc)))

    def test_partial_failure_is_visible_but_does_not_block_other_types(self):
        obs=self.observations()
        with patch.object(sample,'fetch',side_effect=[obs[0],ValueError(self.secret),obs[2],obs[3]]) as network:
            result=sample.probe(self.secret,self.path)
        self.assertEqual(network.call_count,4)
        self.assertEqual(result['parts']['statistics']['state'],'error')
        self.assertEqual(result['parts']['lineups']['state'],'present')
        self.assertNotIn(self.secret,json.dumps(result))

    def test_wrong_fixture_or_envelope_stops_before_detail_requests(self):
        self.fixture['league']['season']=2025
        with patch.object(sample,'fetch',side_effect=self.observations()) as network:
            result=sample.probe(self.secret,self.path)
        self.assertFalse(result['ok']);self.assertEqual(network.call_count,1)
        a=Archive(self.path);self.addCleanup(a.close)
        self.assertEqual(a.db.execute('SELECT COUNT(*) FROM provider_bundles').fetchone()[0],0)
        bad=Observation(sample.FIXTURE_URL,json.dumps({'errors':{'plan':self.secret},'results':0,'response':[]}).encode(),datetime.now(timezone.utc))
        with self.assertRaises(ValueError):sample.rows(bad)

    def test_missing_malformed_and_duplicate_xg_are_not_zero(self):
        for value in [None,True,'NaN','Infinity',-1,'text']:
            self.assertIsNone(sample.numeric_xg(value))
        self.stats[0]['statistics']=[]
        result=sample.summarize('statistics',self.stats,123)
        self.assertIsNone(result['xg']['33']);self.assertEqual(result['state'],'partial')
        self.stats[1]['statistics']*=2
        with self.assertRaises(ValueError):sample.summarize('statistics',self.stats,123)

    def test_team_lineup_and_injury_identity_rejected(self):
        self.stats[0]['team']['id']=999
        with self.assertRaises(ValueError):sample.summarize('statistics',self.stats,123)
        self.lineups[0]['startXI'][0]=self.lineups[0]['startXI'][1]
        with self.assertRaises(ValueError):sample.summarize('lineups',self.lineups,123)
        with self.assertRaises(ValueError):sample.summarize('injuries',[{'fixture':{'id':456},'team':{'id':33},'player':{'id':1}}],123)

    def test_no_key_no_network_or_database_and_shared_daily_cap(self):
        with patch.object(sample,'fetch') as network:
            self.assertFalse(sample.probe(None,self.path)['ok']);network.assert_not_called()
        self.assertFalse(self.path.exists())
        with patch.object(sample,'fetch',side_effect=ValueError(self.secret)) as network:
            first=sample.probe(self.secret,self.path)
            second=sample.probe('other-key',self.path)
            again=sample.probe(self.secret,self.path)
        self.assertEqual(network.call_count,1);self.assertEqual(first,again)
        self.assertIn('holnap',second['message'])
        self.assertNotIn(self.secret,json.dumps(first))

    def test_allowlist_rejects_injected_or_unbounded_urls(self):
        for suffix in ['fixtures?league=39&season=2026&date=2026-08-16',
                       'fixtures/statistics?fixture=123&redirect=evil','injuries?fixture=0',
                       'injuries?fixture=1#fragment','fixtures/players?fixture=123']:
            with self.assertRaisesRegex(ValueError,'Unapproved'):
                fetch(API_FOOTBALL+suffix,api_key=self.secret)

    def test_actual_runtime_click_and_no_secret_disclosure(self):
        from streamlit.testing.v1 import AppTest
        with patch.object(sample,'fetch',side_effect=self.observations()) as network:
            app=AppTest.from_string('import streamlit as st\nfrom match_sample_probe import render\nrender(st,st.secrets["API_FOOTBALL_KEY"],st.secrets["TEST_DB"])')
            app.secrets['API_FOOTBALL_KEY']=self.secret;app.secrets['TEST_DB']=str(self.path)
            app.run();self.assertFalse(app.exception);network.assert_not_called()
            app.button(key='match_sample_button').click().run()
            self.assertFalse(app.exception);self.assertEqual(network.call_count,4)
            app.button(key='match_sample_button').click().run()
            self.assertFalse(app.exception);self.assertEqual(network.call_count,4)
            rendered=' '.join(str(e.value) for group in [app.info,app.caption,app.success,app.table,app.markdown] for e in group)
            self.assertNotIn(self.secret,rendered);self.assertIn('0.0 / 1.25',rendered)


if __name__=='__main__':unittest.main()
