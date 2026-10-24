from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone, date
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from forecast_journal import Journal, digest


class ForecastJournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=str(Path(self.tmp.name)/'journal.sqlite3')
        self.clock=datetime(2026,10,24,12,tzinfo=timezone.utc)
        p=patch('forecast_journal.now',return_value=self.clock);p.start();self.addCleanup(p.stop)
        self.raw=('Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\n'+''.join(
            f"E0,{date(2026,8,1)+timedelta(days=i):%d/%m/%Y},{'A,B,2,1' if i%2==0 else 'C,D,1,2'}\n"
            for i in range(80))).encode()
        self.kw={'fixture_id':'provider-1','home':'A','away':'B','season':'2026/27',
                 'kickoff':self.clock+timedelta(days=1),
                 'source_url':'https://www.football-data.co.uk/mmz4281/2627/E0.csv'}
        self.journal=Journal(self.path);self.addCleanup(self.journal.close)

    def test_frozen_forecast_export_chain_and_original_baseline(self):
        from streamlit_app import feldolgozas,becsles,pontos_eredmenyek
        first=self.journal.capture(self.raw,**self.kw)
        p=first['payload'];_,lh,la,*_=becsles(feldolgozas(self.raw),'A','B')
        self.assertEqual(p['lambdas'],[lh,la]);self.assertEqual(p['top5'],pontos_eredmenyek(lh,la))
        second=self.journal.capture(self.raw,**{**self.kw,'fixture_id':'provider-2','home':'C','away':'D'})
        exported=self.journal.export()
        self.assertEqual(exported['count'],2)
        self.assertEqual(exported['root_hash'],second['entry_hash'])
        self.assertEqual(exported['entries'][1]['previous_hash'],first['entry_hash'])
        self.assertTrue(p['recorded_at']<p['fixture']['kickoff_utc'])
        self.assertEqual(p['history_hash'],digest(p['history']))
        self.assertEqual(json.loads(json.dumps(exported))['root_hash'],self.journal.verify())

    def test_current_day_and_future_results_do_not_affect_prediction(self):
        before=self.journal.capture(self.raw,**self.kw)['payload']
        extra=self.raw+b'E0,24/10/2026,A,B,20,19\nE0,25/10/2026,A,B,18,17\n'
        other=Journal(':memory:');self.addCleanup(other.close)
        after=other.capture(extra,**self.kw)['payload']
        for field in ['history_hash','history','lambdas','top5','one_x_two','counts','model_code_hash']:
            self.assertEqual(before[field],after[field])
        self.assertNotEqual(before['raw_sha256'],after['raw_sha256'])

    def test_no_backdating_close_kickoff_and_naive_times(self):
        for kickoff in [self.clock-timedelta(hours=1),self.clock+timedelta(minutes=5),datetime(2026,10,25)]:
            with self.subTest(kickoff=kickoff),self.assertRaises(ValueError):
                self.journal.capture(self.raw,**{**self.kw,'kickoff':kickoff})
        self.assertEqual(self.journal.export()['count'],0)

    def test_duplicate_cannot_replace_under_changed_id_or_kickoff(self):
        first=self.journal.capture(self.raw,**self.kw)
        for changes in [{},{'fixture_id':'alternate-id'}, {'kickoff':self.clock+timedelta(days=2)}]:
            with self.assertRaisesRegex(ValueError,'already'):
                self.journal.capture(self.raw,**{**self.kw,**changes})
        self.assertEqual(self.journal.export()['count'],1)
        self.assertEqual(self.journal.verify(),first['entry_hash'])

    def test_no_sql_rewrite_and_tampering_is_detected(self):
        self.journal.capture(self.raw,**self.kw)
        for sql in ["UPDATE forecast_journal SET payload='{}'",'DELETE FROM forecast_journal']:
            with self.assertRaises(sqlite3.IntegrityError):self.journal.db.execute(sql)
            self.journal.db.rollback()
        self.journal.db.execute('DROP TRIGGER forecast_no_update')
        self.journal.db.execute("UPDATE forecast_journal SET previous_hash='tampered'")
        self.journal.db.commit()
        with self.assertRaisesRegex(ValueError,'integrity'):self.journal.export()

    def test_commit_time_is_rechecked_and_failed_capture_is_atomic(self):
        with patch('forecast_journal.now',side_effect=[self.clock,self.kw['kickoff']]):
            with self.assertRaisesRegex(ValueError,'commit'):
                self.journal.capture(self.raw,**self.kw)
        self.assertEqual(self.journal.export()['count'],0)
        with patch('forecast_journal.now',side_effect=[self.clock,self.clock-timedelta(seconds=1)]):
            with self.assertRaises(ValueError):self.journal.capture(self.raw,**self.kw)
        self.assertEqual(self.journal.export()['count'],0)

    def test_insufficient_duplicate_history_and_wrong_source_are_rejected(self):
        for raw,changes in [(self.raw,{'home':'Unknown'}),
                            (self.raw,{'source_url':'https://example.com/data.csv'}),
                            (self.raw+b'E0,01/08/2026,A,B,2,1\n',{})]:
            with self.assertRaises(ValueError):self.journal.capture(raw,**{**self.kw,**changes})
        self.assertEqual(self.journal.export()['count'],0)

    def test_concurrent_capture_keeps_only_one_forecast(self):
        def worker(_):
            journal=Journal(self.path)
            try:
                try:journal.capture(self.raw,**self.kw);return True
                except ValueError:return False
            finally:journal.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(worker,range(2))),[False,True])
        self.assertEqual(self.journal.export()['count'],1)


if __name__=='__main__':unittest.main()
