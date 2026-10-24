"""Optional full-score temperature calibration; never changes the default model."""
from dataclasses import dataclass
from datetime import date
import hashlib
import json
import math
from team_strength import outcome


def _logs(lam):
    if not math.isfinite(lam) or not 0 < lam <= 20:
        raise ValueError('Invalid baseline lambda')
    return tuple(-lam+k*math.log(lam)-math.lgamma(k+1) for k in range(101))


def _normalize(logs, temperature):
    if not math.isfinite(temperature) or not .5 <= temperature <= 2:
        raise ValueError('Temperature outside frozen bounds')
    scaled=[v/temperature for v in logs]
    peak=max(scaled)
    logz=peak+math.log(sum(math.exp(v-peak) for v in scaled))
    return tuple(v-logz for v in scaled)


@dataclass(frozen=True)
class Example:
    day: date
    lambdas: tuple[float,float]
    label: tuple[int,int]

    def __post_init__(self):
        if type(self.day) is not date or len(self.lambdas)!=2 or len(self.label)!=2:
            raise ValueError('Invalid calibration example')
        for lam in self.lambdas:_logs(lam)
        if any(type(g) is not int or not 0 <= g <= 100 for g in self.label):
            raise ValueError('Label outside baseline score support')


@dataclass(frozen=True)
class Artifact:
    temperature: float
    training_matches: int
    trained_through: date | None
    training_hash: str
    reason: str
    selection_through: date | None = None
    version: str = 'score-temperature-v1'


def fit(examples, before):
    if type(before) is not date:raise ValueError('Date cutoff required')
    eligible=sorted((e for e in examples if e.day < before),
                    key=lambda e:(e.day,e.lambdas,e.label))
    payload=[(str(e.day),e.lambdas,e.label) for e in eligible]
    digest=hashlib.sha256(json.dumps(payload,separators=(',',':')).encode()).hexdigest()
    last=max((e.day for e in eligible),default=None)
    if len(eligible)<60:
        return Artifact(1.,len(eligible),last,digest,'insufficient_calibration_history')
    prepared=[(_logs(e.lambdas[0]),_logs(e.lambdas[1]),e.label) for e in eligible]
    def objective(t):
        return -sum(_normalize(h,t)[y[0]]+_normalize(a,t)[y[1]] for h,a,y in prepared)/len(prepared)
    low,high=.5,2.
    ratio=(math.sqrt(5)-1)/2
    x=high-ratio*(high-low);y=low+ratio*(high-low)
    fx,fy=objective(x),objective(y)
    for _ in range(40):
        if fx < fy:
            high,y,fy=y,x,fx;x=high-ratio*(high-low);fx=objective(x)
        else:
            low,x,fx=x,y,fy;y=low+ratio*(high-low);fy=objective(y)
    candidates=(1.,.5,2.,(low+high)/2)
    t=min(candidates,key=lambda v:(objective(v),abs(v-1)))
    return Artifact(t,len(eligible),last,digest,'development_nll_fit')


@dataclass(frozen=True)
class Distribution:
    home_logp: tuple[float,...]
    away_logp: tuple[float,...]
    top5: tuple[tuple[int,int,float],...]
    one_x_two: tuple[float,float,float]
    expected_goals: tuple[float,float]

    def nll(self, label):
        if len(label)!=2 or any(type(g) is not int or not 0 <= g <= 100 for g in label):
            raise ValueError('Label outside calibrated support')
        return -self.home_logp[label[0]]-self.away_logp[label[1]]


def apply(lambdas, artifact, prediction_day):
    if type(prediction_day) is not date:raise ValueError('Prediction date required')
    boundaries=[d for d in (artifact.trained_through,artifact.selection_through) if d is not None]
    if any(d >= prediction_day for d in boundaries):
        raise ValueError('Calibration artifact includes current or future information')
    h,a=(_normalize(_logs(v),artifact.temperature) for v in lambdas)
    ph,pa=tuple(map(math.exp,h)),tuple(map(math.exp,a))
    p=[0.,0.,0.]
    for i,x in enumerate(ph):
        for j,y in enumerate(pa):p[0 if i>j else 1 if i==j else 2]+=x*y
    mass=sum(p)
    # Preserve baseline ordering, including deterministic equal-probability ties.
    top=tuple((i,j,ph[i]*pa[j]) for i,j,_ in outcome(lambdas).top5)
    return Distribution(h,a,top,tuple(v/mass for v in p),
                        (sum(i*v for i,v in enumerate(ph)),sum(i*v for i,v in enumerate(pa))))
