import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone, date
import json
import unittest
from unittest.mock import patch
from forecast_journal import Journal, canonical
from forecast_cloud import (GitHubArchive, ArchiveMissing, empty_state, restore_journal,
                            validate_state, append_result, evaluate, pack, unpack)


class CloudForecastTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,24,12,tzinfo=timezone.utc)
        self.kickoff=self.now+timedelta(days=1)
        raw=('Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\n'+''.join(
            f"E0,{date(2026,8,1)+timedelta(days=i):%d/%m/%Y},{'A,B,2,1' if i%2==0 else 'C,D,1,2'}\n"
            for i in range(80))).encode()
        self.raw=raw
        j=Journal(':memory:')
        try:
            with patch('forecast_journal.now',return_value=self.now):
                self.entry=j.capture(raw,fixture_id='test-1',home='A',away='B',season='2026/27',
                    kickoff=self.kickoff,source_url='https://www.football-data.co.uk/mmz4281/2627/E0.csv')
            self.state={'format':'forecast-cloud-v1','journal':j.export(),'results':[]}
        finally:j.close()
        self.archive=GitHubArchive('fixture-token','owner/private-repo')

    def result(self,state,score=(1,1),**kw):
        return append_result(state,self.entry['entry_hash'],score=score,
            source_url='https://example.com/final',actual_kickoff=self.kickoff,
            confirmed_regulation=True,**kw)

    def test_cloud_roundtrip_survives_new_journal_instance(self):
        state=unpack(pack(self.state));j=restore_journal(state['journal'])
        try:self.assertEqual(j.export(),state['journal'])
        finally:j.close()
        self.assertEqual(state['journal']['root_hash'],self.entry['entry_hash'])

    def test_settlement_scores_saved_prediction_and_preserves_it(self):
        original=canonical(self.state['journal'])
        with patch('forecast_cloud.now',return_value=self.kickoff+timedelta(hours=3)):
            state=self.result(self.state)
        report=evaluate(state)
        self.assertEqual(report['evaluated'],1);self.assertEqual(report['pending'],0)
        self.assertEqual(report['means']['top1'],int(self.entry['payload']['top5'][0][:2]==(1,1)))
        self.assertEqual(canonical(state['journal']),original)
        self.assertGreater(report['means']['nll'],0)
        with patch('forecast_cloud.now',return_value=self.kickoff+timedelta(hours=4)):
            self.result(state,score=(2,1))
        self.assertEqual(len(state['results']),2)
        self.assertEqual(evaluate(state)['evaluated'],1)
        self.assertEqual(evaluate(state)['rows'][0]['actual'],(2,1))

    def test_pending_void_and_premature_or_backdated_results(self):
        self.assertEqual(evaluate(self.state)['pending'],1)
        for clock in [self.now,self.kickoff+timedelta(minutes=119)]:
            with patch('forecast_cloud.now',return_value=clock),self.assertRaises(ValueError):
                self.result(self.state)
        with patch('forecast_cloud.now',return_value=self.kickoff+timedelta(hours=3)):
            self.result(self.state,status='void',reason='Cancelled')
        self.assertEqual(evaluate(self.state)['void'],1)
        with patch('forecast_cloud.now',return_value=self.kickoff+timedelta(hours=2)),self.assertRaises(ValueError):
            self.result(self.state)

    def test_broken_backup_rejected(self):
        broken=deepcopy(self.state);broken['journal']['entries'][0]['payload']['lambdas'][0]+=1
        with self.assertRaises(ValueError):validate_state(broken)
        broken=deepcopy(self.state);broken['journal']['root_hash']='invalid'
        with self.assertRaises(ValueError):pack(broken)

    def test_github_write_uses_expected_sha_and_safe_branch(self):
        responses=[{'private':True},{'encoding':'base64','sha':'expected',
                    'content':base64.b64encode(pack(self.state)).decode()}, {'commit':{'sha':'new'}}]
        with patch.object(self.archive,'_request',side_effect=responses) as req:
            updated=self.archive.change(lambda s:s)
        self.assertEqual(updated,self.state)
        args=req.call_args_list[-1].args
        self.assertEqual(args[0],'PUT');self.assertEqual(args[2]['sha'],'expected')
        self.assertEqual(args[2]['branch'],'forecast-archive')
        self.assertNotIn('fixture-token',json.dumps(args[2]))

    def test_conflict_does_not_report_saved_or_retry_overwrite(self):
        responses=[{'private':True},{'encoding':'base64','sha':'expected',
                    'content':base64.b64encode(pack(self.state)).decode()},ValueError('Archive changed')]
        with patch.object(self.archive,'_request',side_effect=responses) as req:
            with self.assertRaises(ValueError):self.archive.change(lambda s:s)
        self.assertEqual(req.call_count,3)

    def test_backup_cannot_remove_existing_history(self):
        responses=[{'private':True},{'encoding':'base64','sha':'expected',
                    'content':base64.b64encode(pack(self.state)).decode()}]
        with patch.object(self.archive,'_request',side_effect=responses) as req:
            with self.assertRaisesRegex(ValueError,'extended'):
                self.archive.change(lambda _:empty_state())
        self.assertEqual(req.call_count,2)

    def test_public_repository_is_refused_before_archive_read(self):
        with patch.object(self.archive,'_request',return_value={'private':False}) as req:
            with self.assertRaisesRegex(ValueError,'private'):self.archive.load()
        self.assertEqual(req.call_count,1)

    def test_clock_cannot_backdate_a_later_forecast(self):
        j=restore_journal(self.state['journal'])
        try:
            with patch('forecast_journal.now',return_value=self.now-timedelta(days=1)):
                with self.assertRaisesRegex(ValueError,'previous forecast'):
                    j.capture(self.raw,fixture_id='test-2',home='C',away='D',season='2026/27',
                        kickoff=self.kickoff,source_url='https://www.football-data.co.uk/mmz4281/2627/E0.csv')
            self.assertEqual(j.export()['count'],1)
        finally:j.close()

    def test_http_error_never_discloses_token_or_response(self):
        from urllib.error import HTTPError
        from unittest.mock import MagicMock
        opener=MagicMock()
        opener.open.side_effect=HTTPError(self.archive.endpoint,403,'fixture-token',{},None)
        with patch('forecast_cloud.build_opener',return_value=opener):
            with self.assertRaises(ValueError) as caught:self.archive._request('GET',self.archive.endpoint)
        self.assertNotIn('fixture-token',str(caught.exception))
        request=opener.open.call_args.args[0]
        self.assertNotIn('fixture-token',request.full_url)
        self.assertEqual(request.get_header('Authorization'),'Bearer fixture-token')

    def test_initialize_creates_empty_private_branch_without_resetting_data(self):
        responses=[{'private':True,'default_branch':'main'}, {'private':True},ArchiveMissing('file'),
                   ArchiveMissing('branch'), {'object':{'sha':'base'}},{'ref':'created'},{'commit':{'sha':'init'}}]
        with patch.object(self.archive,'_request',side_effect=responses) as req:
            state=self.archive.initialize()
        self.assertEqual(state,empty_state())
        self.assertEqual(req.call_args_list[-2].args[0],'POST')
        self.assertEqual(req.call_args_list[-1].args[0],'PUT')
        self.assertNotIn('sha',req.call_args_list[-1].args[2])


if __name__=='__main__':unittest.main()
