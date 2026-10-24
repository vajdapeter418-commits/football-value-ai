"""UI request boundaries, secret redaction and shared quota guards (offline)."""
from contextlib import nullcontext
from datetime import datetime,timedelta,timezone
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from prematch_archive import Archive


class FakeUI(types.ModuleType):
    def __init__(self):
        super().__init__('streamlit')
        self.secrets={'API_FOOTBALL_KEY':'test-secret-not-real'}
        self.clicked=False
        self.output=[]
        self.cache_data=lambda **kwargs:lambda fn:fn
    def header(self,*x,**k):self.output.extend(x)
    write=info=caption=success=warning=table=header
    def selectbox(self,label,values,**kwargs):return values[0]
    def button(self,label,disabled=False,**kwargs):return self.clicked and not disabled
    def spinner(self,*args,**kwargs):return nullcontext()


fake=FakeUI()
with patch.dict(sys.modules,{'streamlit':fake}):
    spec=importlib.util.spec_from_file_location('connection_ui_test',Path(__file__).parents[1]/'api_connection_ui.py')
    ui=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ui)


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'archive.sqlite3'
        self.secret='test-secret-not-real'
        fake.output=[];fake.clicked=False;fake.secrets={'API_FOOTBALL_KEY':self.secret}

    def test_secret_precedence_and_unavailable_configuration(self):
        class Missing:
            def get(self,*args):raise ValueError('do not render me')
        with patch.dict('os.environ',{'API_FOOTBALL_KEY':'environment-only'},clear=True):
            self.assertEqual(ui.configured_key(fake.secrets),self.secret)
            self.assertEqual(ui.configured_key(Missing()),'environment-only')
        with patch.dict('os.environ',{},clear=True):
            self.assertIsNone(ui.configured_key(Missing()))

    def test_no_key_no_network_or_database(self):
        with patch.object(ui,'capture_coverage') as fetch:
            result=ui.diagnostic(None,2026,self.path)
        fetch.assert_not_called();self.assertFalse(result['ok']);self.assertFalse(self.path.exists())

    def test_raw_exception_and_malformed_coverage_are_not_rendered(self):
        with patch.object(ui,'capture_coverage',side_effect=RuntimeError(self.secret)):
            result=ui.diagnostic(self.secret,2026,self.path)
        self.assertNotIn(self.secret,json.dumps(result));self.assertFalse(result['ok'])
        a=Archive(self.path)
        self.assertEqual(a.db.execute('SELECT COUNT(*) FROM api_check_attempts').fetchone()[0],1)
        a.close()
        with patch.object(ui,'reserve_attempt'),patch.object(ui,'capture_coverage',return_value={'coverage':self.secret}):
            result=ui.diagnostic(self.secret,2026,self.path)
        self.assertFalse(result['ok']);self.assertNotIn(self.secret,json.dumps(result))

    def test_only_boolean_coverage_is_exposed(self):
        raw={'coverage':{'injuries':True,'unknown':self.secret,'fixtures':
             {'lineups':False,'statistics_fixtures':self.secret,'statistics_players':True}}}
        with patch.object(ui,'capture_coverage',return_value=raw) as fetch:
            result=ui.diagnostic(self.secret,2026,self.path)
        self.assertTrue(result['ok']);self.assertNotIn(self.secret,json.dumps(result))
        self.assertEqual(list(result['coverage'].values()),[True,False,None,True])
        self.assertEqual(fetch.call_args.kwargs,{'api_key':self.secret})

    def test_cooldown_and_daily_limit_persist_across_connections(self):
        t=datetime(2026,10,24,6,tzinfo=timezone.utc)
        a=Archive(self.path)
        ui.reserve_attempt(a.db,t);a.close()
        b=Archive(self.path);self.addCleanup(b.close)
        with self.assertRaises(ui.CheckLimit):ui.reserve_attempt(b.db,t+timedelta(seconds=59))
        for minute in range(1,5):ui.reserve_attempt(b.db,t+timedelta(minutes=minute))
        with self.assertRaises(ui.CheckLimit):ui.reserve_attempt(b.db,t+timedelta(minutes=6))
        ui.reserve_attempt(b.db,t+timedelta(days=1))
        self.assertEqual(b.db.execute('SELECT COUNT(*) FROM api_check_attempts').fetchone()[0],6)

    def test_initial_render_makes_no_request_click_uses_configured_secret(self):
        result={'ok':True,'checked_at':'2026-10-24T06:00:00+00:00','message':'OK','coverage':{'Sérülések / hiányzók':True}}
        with patch.object(ui,'cached_diagnostic',return_value=result) as check:
            ui.run();check.assert_not_called()
            fake.clicked=True;ui.run();self.assertEqual(check.call_count,1)
        self.assertEqual(check.call_args.kwargs['_api_key'],self.secret)
        self.assertNotIn(self.secret,str(fake.output))


if __name__=='__main__':unittest.main()
