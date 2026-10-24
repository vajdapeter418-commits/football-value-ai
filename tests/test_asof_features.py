import math
import unittest
from dataclasses import replace, asdict
from datetime import date, timedelta, datetime, timezone
from asof_features import (snapshot, STRICT, ExtraStat, Scaler, features, player_losses,
                           target_id, budapest, smoothed_log_rate, Match)
from team_strength import Config, ExtraModel, predict, train_extra, TrainingExample
from asof_features import digest
from helpers import league, request, evidence


class AsOfTests(unittest.TestCase):
    def test_current_day_and_future_exclusion_keeps_targets(self):
        matches=league(102)
        r=request(date(2025,4,11))
        original=snapshot(matches,r)
        changed=[replace(m,home_goals=19,away_goals=18) if m.match_date>=r.target_date else m for m in matches]
        revised=snapshot(changed,r)
        self.assertEqual(original,revised)
        self.assertEqual(predict(original,'A','B',Config(mode='core')),
                         predict(revised,'A','B',Config(mode='core')))
        # Target day records are still in the evaluation source (labels differ).
        self.assertTrue(any(m.match_date==r.target_date for m in changed))
        self.assertNotEqual([m for m in matches if m.match_date==r.target_date],
                            [m for m in changed if m.match_date==r.target_date])
        futureless=[m for m in matches if m.match_date<=r.target_date]
        self.assertEqual(original,snapshot(futureless,r))
        past=list(matches);past[0]=replace(past[0],home_goals=14)
        self.assertNotEqual(predict(original,'A','B').baseline,
                            predict(snapshot(past,r),'A','B').baseline)

    def test_strict_publication_capture_equality_late_import_and_versions(self):
        r=request(policy=STRICT)
        t=r.prediction_cutoff
        m=replace(league(1)[0],kickoff_utc=t-timedelta(days=3),
                  completed_at=t-timedelta(days=3,hours=-2),evidence=evidence(t-timedelta(days=2)))
        self.assertEqual(len(snapshot([m],r).matches),1)
        self.assertEqual(len(snapshot([replace(m,evidence=None)],r).matches),0)
        for pub,cap in ((t-timedelta(days=1),t+timedelta(seconds=1)),(t,t),
                        (t+timedelta(seconds=1),t+timedelta(seconds=2))):
            e=replace(m.evidence,published_at=pub,captured_at=cap)
            self.assertFalse(snapshot([replace(m,evidence=e)],r).matches)
        corrected=replace(m,home_goals=9,evidence=evidence(t+timedelta(days=1),version=2))
        self.assertEqual(snapshot([m,corrected],r),snapshot([m],r))
        later=replace(r,prediction_cutoff=t+timedelta(days=2),target_date=r.target_date+timedelta(days=2))
        self.assertEqual(snapshot([m,corrected],later).matches[0].home_goals,9)
        self.assertEqual(m.home_goals,0)
        self.assertFalse(snapshot(league(),r).matches)

    def test_duplicates_invalid_and_status(self):
        m=league(1)[0];r=request()
        self.assertEqual(len(snapshot([m,m],r).matches),1)
        with self.assertRaises(ValueError): snapshot([m,replace(m,home_goals=8)],r)
        with self.assertRaises(ValueError): snapshot([m,replace(m,match_id='other',home_goals=8)],r)
        for field in ('completed','regulation'):
            self.assertFalse(snapshot([replace(m,**{field:False})],r).matches)
        for goal in (-1,math.nan,math.inf,1.5):
            with self.assertRaises(ValueError): replace(m,home_goals=goal)
        with self.assertRaises(ValueError): replace(m,home_id=m.away_id)
        with self.assertRaises(ValueError): replace(r,prediction_cutoff=datetime(2025,1,1))

    def test_budapest_utc_boundary_and_dst(self):
        self.assertIn('2025-01-02T00:30',budapest(datetime(2025,1,1,23,30,tzinfo=timezone.utc)))
        self.assertTrue(budapest(datetime(2025,3,30,0,30,tzinfo=timezone.utc)).endswith('+01:00'))
        self.assertTrue(budapest(datetime(2025,3,30,1,30,tzinfo=timezone.utc)).endswith('+02:00'))
        self.assertTrue(budapest(datetime(2025,10,26,0,30,tzinfo=timezone.utc)).endswith('+02:00'))
        self.assertTrue(budapest(datetime(2025,10,26,1,30,tzinfo=timezone.utc)).endswith('+01:00'))

    def xg_stats(self,matches,kind='total_xg_for',definition='total_xg_v1'):
        return tuple(ExtraStat(m.match_id,m.league,m.season,team,venue,kind,value,
                              evidence(record=m.match_id+venue),definition,'match')
                     for m in matches for team,venue,value in
                     ((m.home_id,'H',2.0 if m.home_id=='A' else 1.0),
                      (m.away_id,'A',2.0 if m.away_id=='B' else 1.0)))

    def test_xg_smoothing_definitions_provider_and_future_stats(self):
        matches=league(10);r=request()
        stats=self.xg_stats(matches)
        snap=snapshot(matches,r,stats)
        fh,fa=features(snap,('xg',))
        self.assertGreater(fh['xg.att'],0)
        weights=[2**(-(r.target_date-m.match_date).days/90) for m in matches]
        mu=sum(w*(2 if m.home_id=='A' else 1) for m,w in zip(matches,weights))/sum(weights)
        own=[w for m,w in zip(matches,weights) if m.home_id=='A']
        expected=math.log((2*sum(own)+5*mu)/(sum(own)+5)/mu)
        self.assertAlmostEqual(fh['xg.att'],expected)
        self.assertIsNone(fh['xg.allowed'])
        future=replace(stats[0],value=99,evidence=evidence(r.prediction_cutoff+timedelta(days=1),version=2))
        self.assertEqual(snap,snapshot(matches,r,(*stats,future)))
        # Total xG is never added on top of set-piece xG.
        both,_=features(snap,('xg','set_piece'))
        self.assertIsNone(both['xg.att'])
        for bad in (replace(stats[0],evidence=replace(stats[0].evidence,source='other')),
                    replace(stats[0],evidence=replace(stats[0].evidence,units='corners')),
                    replace(stats[0],definition='different')):
            with self.assertRaises(ValueError):
                features(snapshot(matches,r,(bad,*stats[1:])),('xg',))
        zeros=tuple(replace(s,value=0) for s in stats)
        self.assertIsNone(features(snapshot(matches,r,zeros),('xg',))[0]['xg.att'])

    def test_scaler_unknown_clipping_and_past_only(self):
        r=request();boundary=r.prediction_cutoff-timedelta(days=1)
        scaler=Scaler.fit([{'xg.att':1,'xg.flat':2},{'xg.att':3,'xg.flat':2}],boundary)
        z,u=scaler.transform({'xg.att':100,'xg.flat':2},r.prediction_cutoff)
        self.assertEqual(z,(3,0))
        z,u=scaler.transform({},r.prediction_cutoff)
        self.assertEqual(z,(0,0));self.assertEqual(u,(True,True))
        with self.assertRaises(ValueError): scaler.transform({},boundary)

    def test_neutral_missing_and_actual_extra_effect(self):
        matches=league();r=request();cfg=Config(mode='extras',blocks=('xg',))
        plain=snapshot(matches,r)
        stats=self.xg_stats(matches)
        snap=snapshot(matches,r,stats)
        fh,fa=features(snap,cfg.blocks)
        scaler=Scaler.fit([{'xg.att':0,'xg.allowed':0},{'xg.att':1,'xg.allowed':1}],
                          r.prediction_cutoff-timedelta(days=1))
        model=ExtraModel(scaler,(.02,.02),cfg.blocks,200,scaler.trained_before,
                         digest(asdict(cfg)),'fixture-training-only')
        off=predict(snap,'A','B',cfg)
        on=predict(snap,'A','B',cfg,model)
        self.assertNotEqual(on.extra_delta,(0,0))
        self.assertNotEqual(on.raw_lambdas,off.raw_lambdas)
        self.assertNotEqual(on.candidate.lambdas,off.candidate.lambdas)
        missing=predict(plain,'A','B',cfg,model)
        self.assertEqual(missing.extra_delta,(0,0))
        self.assertEqual(missing.candidate,predict(plain,'A','B',Config(mode='core')).candidate)
        self.assertIsNone(train_extra([],r.prediction_cutoff,cfg))
        example=TrainingExample(r.prediction_cutoff-timedelta(days=3),r.prediction_cutoff-timedelta(days=2),
                                (1.1,1.0),(('xg.att',1.0),),(('xg.att',2.0),),(2,1))
        self.assertIsNone(train_extra([example]*199,r.prediction_cutoff,cfg))
        trained=train_extra([example]*200,r.prediction_cutoff,cfg)
        self.assertIsNotNone(trained)
        self.assertTrue(any(x!=0 for x in trained.coefficients))
        future=replace(example,label_known_at=r.prediction_cutoff)
        self.assertEqual(trained,train_extra([example]*200+[future],r.prediction_cutoff,cfg))
        bad=replace(model,trained_before=r.prediction_cutoff)
        self.assertEqual(predict(snap,'A','B',cfg,bad).fallback_reason,'invalid_or_future_extra_model')

    def player_stats(self,r):
        vals={'minutes':90,'unavailable':1,'att':3,'def':2,'replacement_att':1,'replacement_def':1}
        return tuple(ExtraStat(target_id(r),'E0','selected','A','H','player_'+k,v,
                    evidence(units='minutes' if k=='minutes' else 'probability' if k=='unavailable' else 'rating'),
                    'higher_is_better_v1','pre_match',player_id='p1',position='FWD') for k,v in vals.items())

    def test_player_missing_replacement_chance_minutes_and_late_lineup(self):
        r=request();stats=self.player_stats(r);matches=league()
        snap=snapshot(matches,r,stats)
        self.assertEqual(player_losses(snap,'A')['FWD'],(2,1))
        self.assertEqual(player_losses(snapshot(matches,r,(*stats,*stats)),'A')['FWD'],(2,1))
        self.assertIsNone(player_losses(snapshot(matches,r,stats[:-1]),'A')['FWD'])
        chance=tuple(replace(s,kind='player_fpl_chance',value=75) if s.kind=='player_unavailable' else s for s in stats)
        self.assertIsNone(player_losses(snapshot(matches,r,chance),'A')['FWD'])
        actual=tuple(replace(s,kind='player_actual_minutes') if s.kind=='player_minutes' else s for s in stats)
        self.assertIsNone(player_losses(snapshot(matches,r,actual),'A')['FWD'])
        late=tuple(replace(s,evidence=replace(s.evidence,captured_at=r.prediction_cutoff)) for s in stats)
        self.assertEqual(player_losses(snapshot(matches,r,late),'A'),{})
        future_rating=replace(stats[2],value=999,evidence=evidence(r.prediction_cutoff+timedelta(days=1),2,units='rating'))
        self.assertEqual(snapshot(matches,r,(*stats,future_rating)),snap)
