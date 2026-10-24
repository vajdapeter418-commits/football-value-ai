"""Versioned GitHub cloud archive; compare-and-swap writes, no local-only success."""
import base64
from datetime import timedelta
import gzip
import io
import json
import math
import re
from urllib.error import HTTPError
from urllib.parse import urlencode, quote, urlsplit
from urllib.request import Request, build_opener

from forecast_journal import Journal, canonical, digest, now, utc
from prematch_archive import NoRedirect

ZERO='0'*64
MAX_JSON=16*1024*1024


def empty_state():
    j=Journal(':memory:')
    try:return {'format':'forecast-cloud-v1','journal':j.export(),'results':[]}
    finally:j.close()


def restore_journal(exported):
    if (exported.get('format')!='forecast-journal-export-v1'
            or exported.get('count')!=len(exported.get('entries',[]))):
        raise ValueError('Invalid journal export')
    j=Journal(':memory:')
    try:
        for entry in exported['entries']:
            p=entry['payload'];fixture=p['fixture']
            if (utc(p['recorded_at'])<utc(p['observed_at'])
                    or utc(fixture['kickoff_utc'])<=utc(p['recorded_at'])+timedelta(minutes=5)):
                raise ValueError('Invalid forecast chronology')
            boundary=min(utc(p['observed_at']).date(),utc(fixture['kickoff_utc']).date()).isoformat()
            if any(row[4]>=boundary for row in p['history']):
                raise ValueError('Future history in export')
            if len(p['lambdas'])!=2 or any(not math.isfinite(v) or not 0<v<=20 for v in p['lambdas']):
                raise ValueError('Invalid saved model')
            if (len(p['one_x_two'])!=3 or any(not math.isfinite(v) or not 0<=v<=1 for v in p['one_x_two'])
                    or abs(sum(p['one_x_two'])-1)>1e-8 or len(p['top5'])!=5
                    or any(len(x)!=3 or any(type(g) is not int or not 0<=g<=100 for g in x[:2])
                           or not math.isfinite(x[2]) or not 0<=x[2]<=1 for x in p['top5'])):
                raise ValueError('Invalid saved probabilities')
            j.db.execute('INSERT INTO forecast_journal(fixture_key,payload,previous_hash,entry_hash) VALUES(?,?,?,?)',
                         (digest(fixture),canonical(p),entry['previous_hash'],entry['entry_hash']))
        j.db.commit()
        if j.verify()!=exported.get('root_hash'):raise ValueError('Invalid root hash')
        return j
    except Exception:
        j.close();raise


def validate_state(state):
    if state.get('format')!='forecast-cloud-v1':raise ValueError('Invalid archive format')
    j=restore_journal(state['journal']);j.close()
    predictions={e['entry_hash']:e['payload'] for e in state['journal']['entries']}
    previous=ZERO;last_observed=None
    for entry in state['results']:
        p=entry['payload']
        if (entry['previous_hash']!=previous or entry['entry_hash']!=digest({'previous_hash':previous,'payload':p})
                or p['prediction_hash'] not in predictions):raise ValueError('Invalid result chain')
        forecast=predictions[p['prediction_hash']]
        if (utc(p['observed_at'])<utc(forecast['recorded_at'])
                or (last_observed is not None and utc(p['observed_at'])<last_observed)):
            raise ValueError('Backdated result')
        last_observed=utc(p['observed_at'])
        _validate_result(p,forecast)
        previous=entry['entry_hash']
    return state


def _validate_result(p,forecast):
    source=urlsplit(p['source_url'])
    if source.scheme!='https' or not source.netloc or source.username or source.password:
        raise ValueError('Public HTTPS result source required')
    if p['status']=='completed':
        if (not p.get('confirmed_regulation') or len(p['score'])!=2
                or any(type(g) is not int or not 0<=g<=100 for g in p['score'])
                or utc(p['actual_kickoff'])<=utc(forecast['recorded_at'])
                or utc(p['observed_at'])<utc(p['actual_kickoff'])+timedelta(hours=2)):
            raise ValueError('Unconfirmed, premature, or invalid result')
    elif p['status']!='void' or not p.get('reason'):
        raise ValueError('Invalid result status')


def append_result(state,prediction_hash,*,score,source_url,actual_kickoff,
                  confirmed_regulation,status='completed',reason=''):
    validate_state(state)
    forecasts={e['entry_hash']:e['payload'] for e in state['journal']['entries']}
    if prediction_hash not in forecasts:raise ValueError('Unknown prediction')
    p={'prediction_hash':prediction_hash,'score':list(score),'source_url':source_url,
       'actual_kickoff':utc(actual_kickoff).isoformat(),'confirmed_regulation':confirmed_regulation,
       'status':status,'reason':reason,'observed_at':utc(now()).isoformat()}
    _validate_result(p,forecasts[prediction_hash])
    if state['results'] and utc(p['observed_at'])<utc(state['results'][-1]['payload']['observed_at']):
        raise ValueError('Backdated result revision')
    if utc(p['observed_at'])<utc(forecasts[prediction_hash]['recorded_at']):raise ValueError('Backdated result')
    prev=state['results'][-1]['entry_hash'] if state['results'] else ZERO
    state['results'].append({'payload':p,'previous_hash':prev,'entry_hash':digest({'previous_hash':prev,'payload':p})})
    return state


def evaluate(state):
    validate_state(state)
    latest={e['payload']['prediction_hash']:e['payload'] for e in state['results']}
    rows=[];pending=void=0
    for entry in state['journal']['entries']:
        p=entry['payload'];result=latest.get(entry['entry_hash'])
        if result is None:pending+=1;continue
        if result['status']=='void':void+=1;continue
        h,a=result['score'];label=(h,a);lh,la=p['lambdas'];y=0 if h>a else 1 if h==a else 2
        rows.append({'fixture':p['fixture'],'actual':label,
                     'top1':int(label==tuple(p['top5'][0][:2])),
                     'top5':int(any(label==tuple(x[:2]) for x in p['top5'])),
                     'nll':lh-h*math.log(lh)+math.lgamma(h+1)+la-a*math.log(la)+math.lgamma(a+1),
                     'brier':sum((v-int(i==y))**2 for i,v in enumerate(p['one_x_two']))})
    return {'evaluated':len(rows),'pending':pending,'void':void,'rows':rows,
            'means':{k:sum(r[k] for r in rows)/len(rows) for k in ('top1','top5','nll','brier')} if rows else {}}


def pack(state):
    validate_state(state)
    raw=canonical(state).encode()
    if len(raw)>MAX_JSON:raise ValueError('Archive size limit reached')
    encoded=canonical({'encoding':'gzip-base64','data':base64.b64encode(gzip.compress(raw,mtime=0)).decode()}).encode()
    if len(encoded)>900000:raise ValueError('Cloud archive file size limit reached')
    return encoded


def unpack(raw):
    wrapper=json.loads(raw)
    if wrapper['encoding']!='gzip-base64':raise ValueError('Invalid archive encoding')
    with gzip.GzipFile(fileobj=io.BytesIO(base64.b64decode(wrapper['data'],validate=True))) as f:
        decoded=f.read(MAX_JSON+1)
    if len(decoded)>MAX_JSON:raise ValueError('Archive size limit reached')
    return validate_state(json.loads(decoded))


class ArchiveMissing(ValueError):
    pass


class GitHubArchive:
    def __init__(self,token,repository,branch='forecast-archive',path='archive/forecast-journal.json'):
        if not token or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository):
            raise ValueError('Archive configuration missing')
        if branch!='forecast-archive' or path!='archive/forecast-journal.json':
            raise ValueError('Unexpected archive location')
        self.token=token;self.branch=branch
        self.repo_url=f'https://api.github.com/repos/{repository}'
        self.endpoint=f'https://api.github.com/repos/{repository}/contents/{quote(path,safe="/")}'

    def _request(self,method,url,body=None):
        headers={'Authorization':'Bearer '+self.token,'Accept':'application/vnd.github+json',
                 'User-Agent':'FootballValueAI/forecast-journal','Content-Type':'application/json'}
        try:
            req=Request(url,data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)
            with build_opener(NoRedirect).open(req,timeout=25) as response:
                raw=response.read(4*1024*1024+1)
                if len(raw)>4*1024*1024:raise ValueError('Archive response too large')
                return json.loads(raw)
        except HTTPError as error:
            if error.code==404:raise ArchiveMissing('Archive resource missing') from None
            if error.code in (409,422):raise ValueError('Archive changed; reload before retrying') from None
            raise ValueError('Archive access failed; check configuration') from None
        except Exception:
            raise ValueError('Archive request failed; reload to check whether a write completed') from None

    def _private(self):
        meta=self._request('GET',self.repo_url)
        if meta.get('private') is not True:raise ValueError('A private archive repository is required')
        return meta

    def initialize(self):
        meta=self._private()
        try:
            return self.load()[0]
        except ArchiveMissing:
            pass
        branch_url=self.repo_url+'/git/ref/heads/'+self.branch
        try:self._request('GET',branch_url)
        except ArchiveMissing:
            default=quote(meta['default_branch'],safe='')
            head=self._request('GET',self.repo_url+'/git/ref/heads/'+default)
            self._request('POST',self.repo_url+'/git/refs',{'ref':'refs/heads/'+self.branch,'sha':head['object']['sha']})
        state=empty_state()
        response=self._request('PUT',self.endpoint,{'message':'Initialize Football Value AI forecast archive',
            'branch':self.branch,'content':base64.b64encode(pack(state)).decode()})
        if not response.get('commit',{}).get('sha'):raise ValueError('Archive initialization not acknowledged')
        return state

    def load(self):
        self._private()
        response=self._request('GET',self.endpoint+'?'+urlencode({'ref':self.branch}))
        if response.get('encoding')!='base64' or not response.get('sha'):
            raise ValueError('Invalid cloud archive response')
        return unpack(base64.b64decode(response['content'])),response['sha']

    def change(self,mutator):
        state,sha=self.load()
        original=json.loads(canonical(state))
        updated=mutator(state)
        for key in ('predictions','results'):
            old=original['journal']['entries'] if key=='predictions' else original['results']
            new=updated['journal']['entries'] if key=='predictions' else updated['results']
            if new[:len(old)]!=old:
                raise ValueError('Cloud history may only be extended')
        encoded=pack(updated)
        response=self._request('PUT',self.endpoint,{'message':'Archive Football Value AI journal',
            'branch':self.branch,'sha':sha,'content':base64.b64encode(encoded).decode()})
        if not response.get('commit',{}).get('sha'):raise ValueError('Cloud save not acknowledged')
        return updated
