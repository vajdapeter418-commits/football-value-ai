"""Offline archive integrity and temporal-boundary tests; no real API calls."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import json
import sqlite3
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from prematch_archive import (Archive,Observation,FPL,API_FOOTBALL,capture_fpl,
    capture_coverage,validate_fpl,validate_coverage,fetch)


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.a=Archive(Path(self.tmp.name)/'archive.sqlite3')
        self.addCleanup(self.a.close);self.addCleanup(self.tmp.cleanup)
        self.t=datetime(2026,10,24,6,tzinfo=timezone.utc)
        boot={'teams':[{'id':1},{'id':2}], 'elements':[{'id':10,'team':1,
              'status':'d','chance_of_playing_next_round':75,'news_added':None,
              'expected_goals':'1.2','expected_goals_conceded':'0.8'}]}
        fixtures=[{'id':1,'team_h':1,'team_a':2,'kickoff_time':'2026-11-01T15:00:00Z'}]
        self.obs=tuple(Observation(FPL+name+'/',json.dumps(body).encode(),self.t-timedelta(seconds=2))
                       for name,body in [('bootstrap-static',boot),('fixtures',fixtures)])

    def test_capture_preserves_unknowns_and_is_not_model_evidence(self):
        with patch('prematch_archive.fetch',side_effect=self.obs) as network,patch('prematch_archive.now',return_value=self.t):
            result=capture_fpl(self.a,'2026/27')
        self.assertEqual(network.call_count,2)
        self.assertEqual(result['players'],1)
        self.assertFalse(result['model_eligible'])
        saved=self.a.latest('fpl','2026/27',self.t+timedelta(seconds=1))
        self.assertIsNone(saved['published_at']);self.assertFalse(saved['model_eligible'])
        player=saved['observations'][0]['payload']['elements'][0]
        self.assertEqual(player['chance_of_playing_next_round'],75)
        self.assertIsNone(player['news_added'])
        self.assertNotIn('p_unavailable',player)

    def test_asof_equal_future_and_late_import_never_backdates(self):
        with patch('prematch_archive.now',return_value=self.t):
            self.a.save('fpl','2026/27',self.obs)
        self.assertIsNone(self.a.latest('fpl','2026/27',self.t))
        cutoff=self.t+timedelta(seconds=1)
        old=self.a.latest('fpl','2026/27',cutoff)
        with patch('prematch_archive.now',return_value=self.t+timedelta(days=1)):
            self.a.save('fpl','2026/27',self.obs)
        self.assertEqual(old,self.a.latest('fpl','2026/27',cutoff))
        new=self.a.latest('fpl','2026/27',self.t+timedelta(days=2))
        self.assertNotEqual(old['bundle_id'],new['bundle_id'])

    def test_invalid_or_partial_capture_does_not_write_bundle(self):
        with patch('prematch_archive.fetch',side_effect=[self.obs[0],ValueError('outage')]):
            with self.assertRaises(ValueError):capture_fpl(self.a,'2026/27')
        self.assertEqual(self.a.db.execute('SELECT COUNT(*) FROM provider_bundles').fetchone()[0],0)
        with patch('prematch_archive.fetch',side_effect=self.obs):
            with self.assertRaisesRegex(ValueError,'season'):
                capture_fpl(self.a,'2025/26')
        self.assertEqual(self.a.db.execute('SELECT COUNT(*) FROM provider_bundles').fetchone()[0],0)

    def test_atomic_rollback_and_payload_integrity(self):
        self.a.db.execute("CREATE TRIGGER fail_second BEFORE INSERT ON provider_observations WHEN NEW.endpoint LIKE '%/fixtures/' BEGIN SELECT RAISE(ABORT,'test write failure'); END")
        with patch('prematch_archive.now',return_value=self.t):
            with self.assertRaises(sqlite3.IntegrityError):self.a.save('fpl','2026/27',self.obs)
        self.assertEqual(self.a.db.execute('SELECT COUNT(*) FROM provider_bundles').fetchone()[0],0)
        self.a.db.execute('DROP TRIGGER fail_second')
        with patch('prematch_archive.now',return_value=self.t):self.a.save('fpl','2026/27',self.obs)
        self.a.db.execute("UPDATE provider_observations SET body='{}'")
        with self.assertRaisesRegex(ValueError,'integrity'):
            self.a.latest('fpl','2026/27',self.t+timedelta(seconds=1))

    def test_schema_season_and_identity_validation(self):
        self.assertEqual(validate_fpl(self.obs,'2026/27')['teams'],2)
        for season in ['2026/26','26/27','2025/26']:
            with self.assertRaises(ValueError):validate_fpl(self.obs,season)
        with self.assertRaises(ValueError):validate_fpl(self.obs[:1],'2026/27')
        fixture=json.loads(self.obs[1].body);fixture[0]['team_a']=99
        bad=replace(self.obs[1],body=json.dumps(fixture).encode())
        with self.assertRaises(ValueError):validate_fpl((self.obs[0],bad),'2026/27')
        with patch('prematch_archive.now',return_value=self.t-timedelta(days=1)):
            with self.assertRaisesRegex(ValueError,'Future'):self.a.save('fpl','x',self.obs)
        with self.assertRaises(ValueError):self.a.latest('fpl','x',self.t.replace(tzinfo=None))

    def test_missing_api_key_makes_no_request(self):
        with patch.dict('os.environ',{},clear=True),patch('prematch_archive.fetch') as network:
            with self.assertRaisesRegex(ValueError,'API_FOOTBALL_KEY'):capture_coverage(self.a,39,2026)
        network.assert_not_called()

    def test_api_coverage_errors_pagination_and_no_xg_assumption(self):
        data={'errors':[],'results':1,'paging':{'total':1},'response':[
              {'league':{'id':39},'seasons':[{'year':2026,'coverage':{'injuries':True}}]}]}
        obs=Observation(API_FOOTBALL+'leagues?id=39&season=2026',json.dumps(data).encode(),self.t)
        self.assertEqual(validate_coverage(obs,39,2026),{'injuries':True})
        for bad in [dict(data,errors={'plan':'not available'}),dict(data,paging={'total':2}),dict(data,results=0)]:
            with self.assertRaises(ValueError):validate_coverage(replace(obs,body=json.dumps(bad).encode()),39,2026)
        with self.assertRaises(ValueError):validate_coverage(obs,39,2025)

    def test_fetch_rejects_unapproved_targets_before_network(self):
        for url in ['https://example.com/api','http://fantasy.premierleague.com/api/fixtures/',
                    'https://v3.football.api-sports.io.evil/leagues?id=39']:
            with self.assertRaisesRegex(ValueError,'Unapproved'):fetch(url,api_key='test-only')
        with self.assertRaisesRegex(ValueError,'not configured'):
            fetch(API_FOOTBALL+'leagues?id=39&season=2026')


if __name__=='__main__':unittest.main()
