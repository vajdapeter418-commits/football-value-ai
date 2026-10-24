"""Deterministic weighted venue Poisson model; baseline remains the default."""
from dataclasses import dataclass, asdict, replace
from functools import lru_cache
import math

from asof_features import (Snapshot, age_weight, effective_n, digest, features, Scaler, utc)
from poisson_model import becsles, goltabla


@dataclass(frozen=True)
class Config:
    mode: str = 'baseline'
    half_life: float = 90.0
    ridge: float = 5.0
    extra_ridge: float = 10.0
    tolerance: float = 1e-8
    max_iterations: int = 500
    blocks: tuple[str, ...] = ()
    version: str = 'config-v1'

    def __post_init__(self):
        if (self.mode not in ('baseline','freshness','core','extras')
                or any(not math.isfinite(x) or x <= 0 for x in
                       (self.half_life,self.ridge,self.extra_ridge,self.tolerance))
                or not 0 <= self.max_iterations <= 500
                or set(self.blocks)-{'xg','set_piece','style','players'}):
            raise ValueError('Invalid model config')


@dataclass(frozen=True)
class Fit:
    parameters: tuple[float, ...]
    converged: bool
    iterations: int
    gradient_norm: float
    objective: float


def poisson_ridge(rows, size, ridge, tolerance=1e-8, max_iterations=500):
    """rows=(sparse design, fixed log offset, observed goals, unnormalised weight).

    Coordinate Newton with Armijo backtracking. Convergence requires the full
    gradient infinity norm <= tolerance; small steps alone never mean convergence.
    """
    if ridge <= 0 or not math.isfinite(ridge):
        raise ValueError('Positive finite ridge required')
    adj = [[] for _ in range(size)]
    for j,(design,offset,y,w) in enumerate(rows):
        if not all(math.isfinite(x) for x in (offset,y,w)) or y < 0 or w <= 0:
            raise ValueError('Invalid Poisson regression observation')
        for i,x in design:
            if not 0 <= i < size or not math.isfinite(x):
                raise ValueError('Invalid design')
            adj[i].append((j,x))
    theta = [0.0]*size
    linear = [r[1] for r in rows]
    def objective():
        return sum(w*(math.exp(v)-y*v) for v,(_,_,y,w) in zip(linear,rows)) + ridge/2*sum(x*x for x in theta)
    def gradient():
        return [ridge*theta[i]+sum(rows[j][3]*x*(math.exp(linear[j])-rows[j][2]) for j,x in col)
                for i,col in enumerate(adj)]
    if not rows:
        return Fit(tuple(theta),False,0,math.inf,math.inf)
    norm = math.inf
    for iteration in range(max_iterations+1):
        g = gradient()
        norm = max(map(abs,g),default=0.0)
        if norm <= tolerance:
            return Fit(tuple(theta),True,iteration,norm,objective())
        if iteration == max_iterations:
            break
        for i,col in enumerate(adj):
            grad = ridge*theta[i]+sum(rows[j][3]*x*(math.exp(linear[j])-rows[j][2]) for j,x in col)
            hess = ridge+sum(rows[j][3]*x*x*math.exp(linear[j]) for j,x in col)
            step = -grad/hess
            if grad == 0:
                continue
            old = theta[i]
            # Local objective difference avoids cancellation in the full objective.
            alpha = 1.0
            for _ in range(60):
                delta = alpha*step
                try:
                    change = ridge*(old*delta+delta*delta/2) + sum(
                        rows[j][3]*(math.exp(linear[j])*math.expm1(x*delta)-rows[j][2]*x*delta)
                        for j,x in col)
                except OverflowError:
                    change = math.inf
                if math.isfinite(change) and change <= 1e-4*grad*delta:
                    theta[i] += delta
                    for j,x in col:
                        linear[j] += x*delta
                    break
                alpha *= 0.5
    return Fit(tuple(theta),False,max_iterations,norm,objective())


@dataclass(frozen=True)
class CoreFit:
    teams: tuple[str, ...]
    fit: Fit
    home_mean: float
    away_mean: float
    weights: tuple[float, ...]

    def lambdas(self, home, away):
        hi,ai = self.teams.index(home)*4,self.teams.index(away)*4
        t = self.fit.parameters
        # team slots: home attack, home allowed, away attack, away allowed.
        return (self.home_mean*math.exp(t[hi]+t[ai+3]),
                self.away_mean*math.exp(t[ai+2]+t[hi+1]))


def fit_core(snap, config=Config(mode='core')):
    # One fit per cutoff/history/config across all fixtures and extra ablations.
    request = replace(snap.request, home='__fit_home', away='__fit_away', kickoff_utc=None)
    normalized = Snapshot(request, snap.matches, (), '')
    core_config = replace(config, mode='core', blocks=(), extra_ridge=10.0)
    return _fit_core(normalized, core_config)


@lru_cache(maxsize=128)
def _fit_core(snap, config):
    matches = snap.matches
    if len(matches) < 60:
        raise ValueError('fewer_than_60_league_matches')
    weights = tuple(age_weight(m,snap.request,config.half_life) for m in matches)
    sw = sum(weights)
    mh = sum(w*m.home_goals for m,w in zip(matches,weights))/sw
    ma = sum(w*m.away_goals for m,w in zip(matches,weights))/sw
    if min(mh,ma) <= 0:
        raise ValueError('nonpositive_weighted_league_mean')
    teams = tuple(sorted({t for m in matches for t in (m.home_id,m.away_id)}))
    ids = {t: i*4 for i,t in enumerate(teams)}
    rows = []
    for m,w in zip(matches,weights):
        h,a = ids[m.home_id],ids[m.away_id]
        rows.extend(((((h,1.0),(a+3,1.0)),math.log(mh),m.home_goals,w),
                     (((a+2,1.0),(h+1,1.0)),math.log(ma),m.away_goals,w)))
    fit = poisson_ridge(rows,len(teams)*4,config.ridge,config.tolerance,config.max_iterations)
    return CoreFit(teams,fit,mh,ma,weights)


def freshness(snap,home,away,config):
    rows = snap.matches
    weights = [age_weight(m,snap.request,config.half_life) for m in rows]
    mh = sum(w*m.home_goals for m,w in zip(rows,weights))/sum(weights)
    ma = sum(w*m.away_goals for m,w in zip(rows,weights))/sum(weights)
    if min(mh,ma) <= 0:
        raise ValueError('nonpositive_weighted_league_mean')
    def rate(team,venue,goals,mu):
        vals = [(getattr(m,goals),w) for m,w in zip(rows,weights)
                if (m.home_id if venue=='H' else m.away_id)==team]
        return (sum(v*w for v,w in vals)+5*mu)/(sum(w for _,w in vals)+5)
    return (rate(home,'H','home_goals',mh)*rate(away,'A','home_goals',mh)/mh,
            rate(away,'A','away_goals',ma)*rate(home,'H','away_goals',ma)/ma)


@dataclass(frozen=True)
class Outcome:
    lambdas: tuple[float, float]
    top5: tuple[tuple[int,int,float], ...]
    one_x_two: tuple[float,float,float]
    tail_mass: float


def outcome(lambdas):
    table = goltabla(*lambdas)
    top = tuple(sorted(table,key=lambda x:(-x[2],x[0],x[1]))[:5])
    p = [0.0]*3
    for h,a,v in table:
        p[0 if h>a else 1 if h==a else 2] += v
    mass = sum(p)
    return Outcome(tuple(lambdas),top,tuple(v/mass for v in p),max(0.0,1.0-mass))


@dataclass(frozen=True)
class ExtraModel:
    scaler: Scaler
    coefficients: tuple[float, ...]
    blocks: tuple[str, ...]
    training_matches: int
    trained_before: object
    config_hash: str
    training_hash: str
    version: str = 'extra-poisson-v1'

    @property
    def artifact_hash(self):
        return digest(asdict(self))


@dataclass(frozen=True)
class TrainingExample:
    """Evaluator-only label boundary. Prediction snapshots contain no target labels."""
    cutoff: object
    label_known_at: object
    core_offset: tuple[float,float]
    home_features: tuple[tuple[str,float | None], ...]
    away_features: tuple[tuple[str,float | None], ...]
    label: tuple[int,int]
    weight: float = 1.0


def train_extra(examples, cutoff, config):
    cutoff = utc(cutoff)
    eligible = [x for x in examples if utc(x.label_known_at) < cutoff and utc(x.cutoff) < cutoff]
    # Require observable features on both sides, never count a wholly absent block as training evidence.
    eligible = [x for x in eligible if any(v is not None for _,v in x.home_features)
                and any(v is not None for _,v in x.away_features)]
    if len(eligible) < 200 or not config.blocks:
        return None
    eligible.sort(key=lambda x:(x.cutoff, digest(asdict(x))))
    boundary = max(utc(x.label_known_at) for x in eligible)
    feature_rows = [dict(f) for x in eligible for f in (x.home_features,x.away_features)]
    scaler = Scaler.fit(feature_rows,boundary)
    rows = []
    for x in eligible:
        for i,f in enumerate((x.home_features,x.away_features)):
            # Frozen inner training transform; boundary is before the OUTER prediction cutoff.
            z,_ = scaler.transform(dict(f),cutoff)
            rows.append((tuple((j,v) for j,v in enumerate(z) if v),
                         math.log(x.core_offset[i]),x.label[i],
                         x.weight * 2**(-((cutoff-utc(x.label_known_at)).total_seconds()/86400)/config.half_life)))
    fit = poisson_ridge(rows,len(scaler.columns),config.extra_ridge,
                        config.tolerance,config.max_iterations)
    if not fit.converged:
        return None
    return ExtraModel(scaler,fit.parameters,config.blocks,len(eligible),boundary,
                      digest(asdict(config)),digest([asdict(x) for x in eligible]))


@dataclass(frozen=True)
class Prediction:
    baseline: Outcome
    candidate: Outcome
    core_lambdas: tuple[float,float]
    raw_lambdas: tuple[float,float]
    raw_ratios: tuple[float,float]
    applied_ratios: tuple[float,float]
    extra_delta: tuple[float,float]
    clipped: tuple[bool,bool]
    raw_counts: tuple[int,int,int]
    effective_counts: tuple[float,float,float]
    cutoff: str
    snapshot_hash: str
    config_hash: str
    model_version: str
    policy: str
    fallback_reason: str | None
    active_signals: tuple[str, ...]
    missing_signals: tuple[str, ...]
    unknown_features: tuple[str, ...]
    extra_model_hash: str | None
    solver: tuple[bool,int,float] | None
    team_parameters: tuple[tuple[str,float,float,float,float], ...]


def predict(snap: Snapshot, home: str, away: str, config=Config(), extra_model=None):
    if home == away or (home,away) != (snap.request.home,snap.request.away):
        raise ValueError('Prediction identity mismatch')
    rows = [m.legacy() for m in snap.matches]
    _,lh,la,nh,na = becsles(rows,home,away) if rows else (_ for _ in ()).throw(ValueError('empty_snapshot'))
    baseline = outcome((lh,la))
    weights = [age_weight(m,snap.request,config.half_life) for m in snap.matches]
    counts = (len(rows),nh,na)
    eff = (effective_n(weights),
           effective_n(w for m,w in zip(snap.matches,weights) if m.home_id==home),
           effective_n(w for m,w in zip(snap.matches,weights) if m.away_id==away))
    core = raw = (lh,la)
    delta = (0.0,0.0)
    reason,solver,params = None,None,()
    active,unknown = [],[]
    model_hash = None
    missing = list(('xg','set_piece','style','players'))
    if config.mode != 'baseline':
        try:
            if len(rows)<60 or min(nh,na)<3:
                raise ValueError('insufficient_history_60_3_3')
            if config.mode == 'freshness':
                core = freshness(snap,home,away,config)
                active.append('freshness')
            else:
                fit = fit_core(snap,config)
                solver = (fit.fit.converged,fit.fit.iterations,fit.fit.gradient_norm)
                if not fit.fit.converged:
                    raise ValueError('solver_not_converged')
                core = fit.lambdas(home,away)
                params = tuple((t,*fit.fit.parameters[i*4:i*4+4]) for i,t in enumerate(fit.teams))
                active.extend(('freshness','opponent_strength'))
            if config.mode == 'extras' and config.blocks:
                fh,fa = features(snap,config.blocks,config.half_life)
                unknown = sorted({k for f in (fh,fa) for k,v in f.items() if v is None})
                if extra_model is not None:
                    if (extra_model.training_matches < 200 or extra_model.blocks != config.blocks
                            or extra_model.config_hash != digest(asdict(config))
                            or utc(extra_model.trained_before) >= snap.request.prediction_cutoff
                            or len(extra_model.coefficients) != len(extra_model.scaler.columns)
                            or any(not math.isfinite(b) for b in extra_model.coefficients)):
                        raise ValueError('invalid_or_future_extra_model')
                    zs = [extra_model.scaler.transform(f,snap.request.prediction_cutoff)[0] for f in (fh,fa)]
                    delta = tuple(sum(b*z for b,z in zip(extra_model.coefficients,zz)) for zz in zs)
                    model_hash = extra_model.artifact_hash
                    for block in config.blocks:
                        if any(k.startswith(block+'.') and v is not None for f in (fh,fa) for k,v in f.items()):
                            active.append(block)
                            missing.remove(block)
                else:
                    missing.extend(b+':no_trained_archived_model' for b in config.blocks)
            raw = tuple(c*math.exp(d) for c,d in zip(core,delta))
            ratios = tuple(x/b for x,b in zip(raw,(lh,la)))
            if any(not math.isfinite(x) or x<=0 for x in raw+ratios):
                raise ValueError('nonfinite_candidate')
            applied = tuple(max(.75,min(1.25,x)) for x in ratios)
            final = tuple(b*r for b,r in zip((lh,la),applied))
            candidate = outcome(final)  # preserves explicit 0 < lambda <= 20 contract
        except (ValueError,ArithmeticError) as error:
            reason = str(error) or type(error).__name__
            raw = core = (lh,la)
            delta = (0.0,0.0)
            active = []
            ratios = applied = (1.0,1.0)
            candidate = baseline
    else:
        ratios = applied = (1.0,1.0)
        candidate = baseline
    return Prediction(baseline,candidate,tuple(core),tuple(raw),ratios,applied,delta,
                      tuple(x!=y for x,y in zip(ratios,applied)),counts,eff,
                      snap.request.prediction_cutoff.isoformat(),snap.snapshot_hash,
                      digest(asdict(config)),snap.request.model_version,snap.request.policy,reason,
                      tuple(active),tuple(missing),tuple(unknown),model_hash,solver,params)
