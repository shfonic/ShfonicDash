"""
Tests for sessionlog.grading — the session-grade / pace-rating scoring
module.

Shared test: lives canonically in ShfonicDash/tests/ and is copied
into the companion repo by sync_shared.py.

grade() is exercised with hand-built facts dicts (the records row
contract); session_facts() agreement with parser.scan_session() is
covered in test_parser.py, which owns the CSV fixtures.
"""

import json
from datetime import datetime

import pytest

from sessionlog import grading
from sessionlog.grading import grade, letter, prior_bests, session_facts


def _facts(**overrides):
    """A solid all-round session; tests override what they probe."""
    base = {
        'game':            'f1_25',
        'session_type':    'practice',
        'lap_count':       12,
        'valid_lap_count': 12,
        'clean_lap_count': 12,
        'clean_std_dev':   0.30,
        'theo_time':       88.0,
        'rewind_count':    0,
        'best_lap_time':   88.2,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Letters
# ---------------------------------------------------------------------------

class TestLetter:
    @pytest.mark.parametrize('score,expected', [
        (100,  'A+'), (97, 'A+'), (95, 'A'), (90.9, 'A-'), (90, 'A-'),
        (88,   'B+'), (85, 'B'),  (81, 'B-'),
        (78,   'C+'), (74, 'C'),  (71, 'C-'),
        (68,   'D+'), (65, 'D'),  (60, 'D-'),
        (59.9, 'F'),  (0,  'F'),
    ])
    def test_bands(self, score, expected):
        assert letter(score) == expected


# ---------------------------------------------------------------------------
# grade() — categories, guards, weighting
# ---------------------------------------------------------------------------

class TestGrade:
    def test_strong_session_grades_a(self):
        g = grade(_facts(), prior_best=88.5)   # 0.2s under prior PB
        assert g['letter'].startswith('A')
        assert g['pace_rating'] >= 90
        assert 'New personal best.' in g['explanation']

    def test_invalid_laps_cap_the_grade(self):
        clean = grade(_facts())
        dirty = grade(_facts(valid_lap_count=9, clean_lap_count=9))
        assert dirty['score'] < clean['score']
        assert clean['capped'] is False
        assert dirty['capped'] is True          # 25% invalid → A- ceiling
        assert dirty['score'] == pytest.approx(93.3)
        # Execution is reported uncapped, cleanliness separately.
        assert dirty['execution']['score'] > dirty['score']
        assert dirty['cleanliness']['detail'] == \
            '9 of 12 laps clean (3 invalidated)'
        assert '3 of 12 laps were invalidated' in dirty['explanation']

    def test_rewinds_score_the_mistakes_category(self):
        g = grade(_facts(rewind_count=6, clean_lap_count=8))
        mistakes = next(c for c in g['components'] if c['key'] == 'mistakes')
        assert mistakes['score'] < 50
        assert '6 rewinds' in mistakes['detail']

    def test_collisions_score_the_mistakes_category_too(self):
        def _mistakes(**overrides):
            g = grade(_facts(**overrides))
            return next(c for c in g['components'] if c['key'] == 'mistakes')
        clean     = _mistakes()
        collided  = _mistakes(collision_count=2)
        assert collided['score'] < clean['score']
        assert '2 collisions' in collided['detail']
        assert clean['detail'] == 'no rewinds or collisions'
        # Same incident rate scores the same whether rewind or contact.
        assert (_mistakes(collision_count=2)['score']
                == _mistakes(rewind_count=2)['score'])

    def test_execution_is_weighted_average_of_components(self):
        g = grade(_facts(), prior_best=88.5)
        assert len(g['components']) == 4
        assert sum(c['weight'] for c in g['components']) == pytest.approx(1.0)
        recomputed = sum(c['score'] * c['weight'] for c in g['components'])
        assert g['execution']['score'] == pytest.approx(recomputed)
        # Fully clean session → overall is the uncapped execution score.
        assert g['score'] == pytest.approx(recomputed)

    def test_missing_prior_best_drops_improvement_and_renormalises(self):
        g = grade(_facts())
        assert [c['key'] for c in g['components']] == [
            'pace', 'consistency', 'mistakes']
        assert sum(c['weight'] for c in g['components']) == pytest.approx(1.0)
        # …and the dropped pillar is reported with its reason.
        assert g['unscored'] == [{
            'key': 'improvement', 'label': 'PB comparison',
            'reason': 'no prior personal best at this combination'}]

    def test_pb_weight_scales_with_session_objective(self):
        # Idea 10: PB comparison matters most in a hotlap, less in
        # qualifying, least in practice — and races drop it entirely.
        def _imp_weight(**overrides):
            g = grade(_facts(**overrides), prior_best=88.5)
            return next(c['weight'] for c in g['components']
                        if c['key'] == 'improvement')
        w_hotlap   = _imp_weight(session_type='hotlap')
        w_quali    = _imp_weight(session_type='qualifying', cons_lap_count=5)
        w_practice = _imp_weight(session_type='practice')
        assert w_hotlap > w_quali > w_practice

    def test_subtype_weight_refines_the_type(self, config_file):
        # A session_subtype key overlays the session_type key's weights.
        config_file({'weights_by_type': {
            'sprint_qualifying': {'improvement': 0.45}}})
        def _imp_weight(subtype):
            g = grade(_facts(session_type='qualifying', cons_lap_count=5,
                             session_subtype=subtype), prior_best=88.5)
            return next(c['weight'] for c in g['components']
                        if c['key'] == 'improvement')
        assert _imp_weight('sprint_qualifying') > _imp_weight('')

    def test_pace_rating_is_the_pace_subscore(self):
        g = grade(_facts())
        pace = next(c for c in g['components'] if c['key'] == 'pace')
        assert g['pace_rating'] == round(pace['score'])

    def test_clean_session_with_big_theo_gap_splits_the_two_ratings(self):
        # "Session Grade A, Pace Rating 78" — clean but pace left on the table.
        g = grade(_facts(best_lap_time=88.0 + 0.65))
        assert g['pace_rating'] < 80
        assert g['cleanliness']['score'] == 100
        assert g['cleanliness']['letter'] == 'A+'

    def test_race_consistency_curve_is_looser(self):
        practice = grade(_facts(clean_std_dev=0.8))
        race     = grade(_facts(clean_std_dev=0.8, session_type='race'))
        p = next(c['score'] for c in practice['components'] if c['key'] == 'consistency')
        r = next(c['score'] for c in race['components'] if c['key'] == 'consistency')
        assert r > p

    def test_new_pb_scores_100_for_improvement(self):
        g = grade(_facts(), prior_best=90.0)
        imp = next(c for c in g['components'] if c['key'] == 'improvement')
        assert imp['score'] == 100.0
        assert 'new personal best' in imp['detail']

    def test_off_pb_pace_scores_lower(self):
        g = grade(_facts(best_lap_time=89.8, theo_time=89.6), prior_best=88.2)
        imp = next(c for c in g['components'] if c['key'] == 'improvement')
        assert imp['score'] < 75


def _race_facts(**overrides):
    overrides.setdefault('session_type', 'race')
    return _facts(**overrides)


class TestRaceGrading:
    """Races grade with race semantics: pace vs the prior best race lap,
    Race Discipline instead of Cleanliness, rewinds-only mistakes and
    no PB-comparison pillar (2nd-race AI-coach feedback)."""

    def test_race_pace_scores_against_prior_race_best(self):
        g = grade(_race_facts(), prior_best=88.2)     # level with it → 100
        pace = next(c for c in g['components'] if c['key'] == 'pace')
        assert pace['score'] == 100.0
        assert 'best race lap' in pace['detail']
        assert g['pace_kind'] == 'race'
        slower = grade(_race_facts(best_lap_time=89.7), prior_best=88.2)
        assert slower['pace_rating'] < g['pace_rating']

    def test_first_race_at_combo_falls_back_to_theoretical(self):
        g = grade(_race_facts())
        assert g['pace_kind'] == 'theoretical'
        pace = next(c for c in g['components'] if c['key'] == 'pace')
        assert 'theoretical' in pace['detail']

    def test_non_race_pace_kind_is_theoretical(self):
        g = grade(_facts(), prior_best=88.5)
        assert g['pace_kind'] == 'theoretical'

    def test_races_never_score_pb_comparison(self):
        # Not a component, and not "missing" either — it doesn't apply.
        for g in (grade(_race_facts(), prior_best=88.5),
                  grade(_race_facts())):
            assert 'improvement' not in [c['key'] for c in g['components']]
            assert 'improvement' not in [u['key'] for u in g['unscored']]

    def test_race_mistakes_counts_rewinds_only(self):
        base     = grade(_race_facts())
        contacts = grade(_race_facts(collision_count=4))
        m_base     = next(c for c in base['components']
                          if c['key'] == 'mistakes')
        m_contacts = next(c for c in contacts['components']
                          if c['key'] == 'mistakes')
        assert m_contacts['score'] == m_base['score']
        assert m_base['detail'] == 'no rewinds'

    def test_race_discipline_from_incidents(self):
        clean = grade(_race_facts())
        assert clean['cleanliness']['label'] == 'Race Discipline'
        assert clean['cleanliness']['kind'] == 'standards'
        assert clean['cleanliness']['score'] == 100.0
        assert (clean['cleanliness']['detail']
                == 'no contacts, penalties or flashbacks')
        crashy = grade(_race_facts(collision_count=2, penalty_count=1,
                                   rewind_count=1, clean_lap_count=11))
        d = crashy['cleanliness']['detail']
        assert '2 contacts' in d and '1 penalty' in d and '1 flashback' in d
        assert crashy['cleanliness']['score'] < clean['cleanliness']['score']

    def test_invalid_laps_do_not_move_race_discipline(self):
        a = grade(_race_facts())
        b = grade(_race_facts(valid_lap_count=6, clean_lap_count=6))
        assert a['cleanliness']['score'] == b['cleanliness']['score']

    def test_missing_rewind_data_drops_that_component_only(self):
        g = grade(_race_facts(collision_count=2, rewind_count=None))
        d = g['cleanliness']['detail']
        assert '2 contacts' in d and '(rewind data unavailable)' in d
        assert 'flashback' not in d

    def test_race_cap_keys_off_incidents_not_invalids(self):
        # Invalid-heavy but incident-free race: uncapped …
        dirty = grade(_race_facts(valid_lap_count=6, clean_lap_count=6))
        assert dirty['capped'] is False
        # … incident-heavy race with zero invalid laps: capped.
        crashy = grade(_race_facts(collision_count=6, penalty_count=3))
        assert crashy['capped'] is True
        assert crashy['score'] < crashy['execution']['score']

    def test_race_explanation_references_the_race_lap(self):
        g = grade(_race_facts(best_lap_time=89.0), prior_best=88.2)
        assert 'best race lap' in g['explanation']
        assert 'personal best' not in g['explanation']
        pb = grade(_race_facts(best_lap_time=88.0), prior_best=88.2)
        assert 'New best race lap.' in pb['explanation']

    def test_race_focus_targets_incidents_then_race_pace(self):
        crashy = grade(_race_facts(collision_count=6))
        assert 'zero-incident race' in crashy['focus']
        slow = grade(_race_facts(best_lap_time=89.7), prior_best=88.2)
        assert 'best race lap' in slow['focus']

    def test_sprint_race_uses_race_semantics_too(self):
        g = grade(_facts(session_type='sprint_race'), prior_best=88.2)
        assert g['pace_kind'] == 'race'
        assert g['cleanliness']['label'] == 'Race Discipline'


class TestPracticeQualiCleanliness:
    """Practice/qualifying Cleanliness counts rewound laps as not clean
    (avoid unnecessary rewinds), falling back to the plain invalid share
    when the rewind count is untrustworthy."""

    def test_rewound_laps_count_against_cleanliness(self):
        g = grade(_facts(clean_lap_count=9, rewind_count=3))
        assert g['cleanliness']['kind'] == 'cleanliness'
        assert g['cleanliness']['detail'] == '9 of 12 laps clean (3 rewound)'
        assert g['cleanliness']['score'] < 100.0

    def test_falls_back_to_invalid_share_without_rewind_data(self):
        g = grade(_facts(rewind_count=None))
        assert g['cleanliness']['detail'] == '12 of 12 laps valid'
        assert g['cleanliness']['score'] == 100.0

    def test_hotlap_keeps_the_invalid_share(self):
        g = grade(_facts(session_type='hotlap', valid_lap_count=9,
                         clean_lap_count=9))
        assert g['cleanliness']['detail'] == '9 of 12 laps valid'
        assert g['cleanliness']['label'] == 'Cleanliness'


class TestGuards:
    def test_none_and_short_sessions_are_ungraded(self):
        assert grade(None) is None
        assert grade({}) is None
        assert grade(_facts(lap_count=2)) is None

    def test_few_clean_laps_drop_consistency_and_pace(self):
        g = grade(_facts(lap_count=5, valid_lap_count=5, clean_lap_count=2))
        keys = [c['key'] for c in g['components']]
        assert 'consistency' not in keys
        assert 'pace' not in keys
        assert 'mistakes' in keys
        assert g['cleanliness'] is not None
        assert {u['reason'] for u in g['unscored']
                if u['key'] in ('pace', 'consistency')} == {'only 2 clean laps'}

    def test_missing_std_dev_drops_consistency_only(self):
        g = grade(_facts(clean_std_dev=None))
        keys = [c['key'] for c in g['components']]
        assert 'consistency' not in keys
        assert 'pace' in keys

    def test_qualifying_with_one_representative_lap_is_ungraded(self):
        # A lone out–push–in run: consistency / execution have nothing to
        # compare against. The dashboard shows a note instead of a grade.
        facts = _facts(session_type='qualifying', lap_count=3,
                       valid_lap_count=3, clean_lap_count=3,
                       cons_lap_count=1, clean_std_dev=None)
        assert grade(facts) is None
        # Two representative laps → graded again.
        assert grade(_facts(session_type='qualifying',
                            cons_lap_count=2)) is not None
        # Other session types are unaffected by the gate.
        assert grade(_facts(session_type='practice',
                            cons_lap_count=1)) is not None
        # Rows scanned before schema v7 (no cons_lap_count) grade as before.
        assert grade(_facts(session_type='qualifying')) is not None

    def test_none_rewind_count_drops_mistakes(self):
        # Pre-v0.1.133 files report rewind_count as None (spurious rewinds
        # around pit stops) — Mistakes must renormalise away, not score 0.
        g = grade(_facts(rewind_count=None))
        assert 'mistakes' not in [c['key'] for c in g['components']]
        assert any(u['key'] == 'mistakes' and 'unavailable' in u['reason']
                   for u in g['unscored'])

    def test_explanation_is_evidence_only(self):
        # No intent words — the wording states data, not why it happened.
        g = grade(_facts(valid_lap_count=7, clean_lap_count=7,
                         clean_std_dev=1.3, rewind_count=5))
        for word in ('tried', 'struggled', 'pushed too', 'careless'):
            assert word not in g['explanation'].lower()

    def test_clean_session_explanation(self):
        g = grade(_facts())
        assert 'No significant deductions' in g['explanation']


# ---------------------------------------------------------------------------
# Execution / Cleanliness / Overall split (AI-coach feedback)
# ---------------------------------------------------------------------------

class TestExecutionCleanlinessOverall:
    def test_heavy_invalids_cap_but_dont_dominate(self):
        # Strong underlying driving, over half the laps invalidated:
        # execution stays visible but the Overall reads incomplete.
        g = grade(_facts(valid_lap_count=5, clean_lap_count=5,
                         best_lap_time=88.1), prior_best=88.3)
        assert g['capped'] is True
        assert g['execution']['letter'].startswith('A')
        assert g['cleanliness']['letter'].startswith('D')
        assert g['letter'] == 'B-'                # 40–60% invalid → B- ceiling
        assert g['score'] == pytest.approx(83.2)

    def test_forty_percent_invalid_reads_b_not_b_plus(self):
        # 4th-session AI-coach feedback: 60% valid laps graded Overall
        # B+ — "pretty complete session" — beside coaching about the
        # invalidations. 25–40% invalid now caps at B.
        g = grade(_facts(lap_count=5, valid_lap_count=3, clean_lap_count=3,
                         best_lap_time=88.1), prior_best=88.3)
        assert g['capped'] is True
        assert g['letter'] == 'B'
        assert g['score'] == pytest.approx(86.6)

    def test_small_invalid_share_is_uncapped(self):
        g = grade(_facts(valid_lap_count=11, clean_lap_count=11))
        assert g['capped'] is False               # ≤10% invalid → no ceiling
        assert g['score'] == pytest.approx(g['execution']['score'])

    def test_coaching_style_explanation(self):
        g = grade(_facts(valid_lap_count=5, clean_lap_count=5,
                         best_lap_time=88.1), prior_best=88.3)
        text = g['explanation']
        assert 'New personal best.' in text
        assert 'Excellent execution, but poor lap completion.' in text
        assert ('yet more than half of your laps were invalidated before '
                'that speed could be converted into consistent clean laps') in text

    def test_explanation_mirrors_the_grade_split(self):
        g = grade(_facts(valid_lap_count=9, clean_lap_count=9))
        assert g['explanation'].startswith(
            'Excellent execution, but a few invalid laps.')
        assert 'yet 3 of 12 laps were invalidated' in g['explanation']

    def test_focus_targets_the_weakest_area(self):
        # Poor completion → a streak objective sized from this session.
        g = grade(_facts(valid_lap_count=3, clean_lap_count=3, lap_count=7,
                         clean_std_dev=None, theo_time=None))
        assert g['focus'] == 'Complete five consecutive clean laps.'
        # All strong → no manufactured objective, just carry it forward.
        g = grade(_facts())
        assert g['focus'] == 'Repeat this level of execution over a longer run.'

    def test_pb_comparison_label(self):
        g = grade(_facts(best_lap_time=88.5, theo_time=88.3), prior_best=88.2)
        pb = next(c for c in g['components'] if c['key'] == 'improvement')
        assert pb['label'] == 'PB comparison'
        assert 'off prior personal best' in pb['detail']


# ---------------------------------------------------------------------------
# Round-3 coach feedback: confidence-aware consistency, focus ladder,
# data-supported summary wording
# ---------------------------------------------------------------------------

class TestConfidenceAwareConsistency:
    def test_small_sample_scores_at_half_weight(self):
        # 3 clean laps with one outlier: std dev is real but fragile —
        # marked low-confidence and weighted at half.
        g = grade(_facts(lap_count=7, valid_lap_count=3, clean_lap_count=3,
                         clean_std_dev=2.694))
        cons = next(c for c in g['components'] if c['key'] == 'consistency')
        pace = next(c for c in g['components'] if c['key'] == 'pace')
        assert 'low confidence — only 3 clean laps' in cons['detail']
        # Nominal weights are 0.25 vs 0.20; halved, consistency now
        # carries less than pace.
        assert cons['weight'] < pace['weight']

    def test_full_sample_keeps_full_weight(self):
        g = grade(_facts(clean_std_dev=2.694))     # 12 clean laps
        cons = next(c for c in g['components'] if c['key'] == 'consistency')
        pace = next(c for c in g['components'] if c['key'] == 'pace')
        assert 'low confidence' not in cons['detail']
        assert cons['weight'] > pace['weight']

    def test_threshold_is_tunable(self, tmp_path, monkeypatch):
        path = tmp_path / 'grading.json'
        path.write_text(json.dumps({'consistency_confidence_laps': 3}),
                        encoding='utf-8')
        monkeypatch.setattr(grading, 'CONFIG_PATH', str(path))
        grading.reload_config()
        try:
            g = grade(_facts(lap_count=7, valid_lap_count=3,
                             clean_lap_count=3, clean_std_dev=2.694))
            cons = next(c for c in g['components']
                        if c['key'] == 'consistency')
            assert 'low confidence' not in cons['detail']
        finally:
            grading.reload_config()


class TestFocusLadder:
    def test_invalid_laps_outrank_everything(self):
        g = grade(_facts(valid_lap_count=5, clean_lap_count=5,
                         clean_std_dev=1.5, best_lap_time=89.0))
        assert g['focus'] == 'Complete seven consecutive clean laps.'

    def test_pace_conversion_outranks_consistency(self):
        g = grade(_facts(best_lap_time=88.7, clean_std_dev=1.5))
        assert g['focus'].startswith('Combine your best sectors in one lap')

    def test_consistency_next(self):
        g = grade(_facts(clean_std_dev=1.5))
        assert g['focus'] == 'Bring your clean-lap spread under 1.1s.'

    def test_rewinds_next(self):
        g = grade(_facts(rewind_count=4, clean_lap_count=8))
        assert g['focus'] == 'Finish every lap without using a rewind.'


class TestSummaryWording:
    def test_limited_by_names_the_pillars(self):
        # Weak pace and consistency, all laps valid — no "usual level".
        g = grade(_facts(best_lap_time=90.0, clean_std_dev=2.0))
        assert g['explanation'].startswith(
            'Execution was limited primarily by ')
        assert 'usual level' not in g['explanation']
        assert 'consistency' in g['explanation']
        assert 'pace execution' in g['explanation']

    def test_strong_pace_leads_the_evidence(self):
        # The coach's case: speed present, completion poor.
        g = grade(_facts(valid_lap_count=5, clean_lap_count=5,
                         best_lap_time=88.1), prior_best=88.3)
        assert 'Your pace remained strong, finishing' in g['explanation']

    def test_headline_says_strong_pace_when_only_thin_data_drags_execution(self):
        # Round 4: pace 100, mistakes 100, PB fine — the only weak pillar
        # is a low-confidence 3-lap std dev, so don't call the execution
        # merely "reasonable"; say what the numbers support.
        g = grade(_facts(lap_count=7, valid_lap_count=3, clean_lap_count=3,
                         clean_std_dev=2.694, best_lap_time=88.0),
                  prior_best=87.869)   # 0.131s off the PB, not a new one
        assert g['explanation'].startswith(
            'Strong pace, but poor lap completion.')


# ---------------------------------------------------------------------------
# grading.json config overrides
# ---------------------------------------------------------------------------

@pytest.fixture
def config_file(tmp_path, monkeypatch):
    """Point CONFIG_PATH at a tmp file; write dict → active config."""
    path = tmp_path / 'grading.json'
    monkeypatch.setattr(grading, 'CONFIG_PATH', str(path))
    grading.reload_config()
    yield lambda data: (path.write_text(json.dumps(data), encoding='utf-8'),
                        grading.reload_config())
    grading.reload_config()


class TestConfig:
    def test_no_file_means_defaults(self, config_file):
        assert grading.config()['weights'] == grading.DEFAULT_CONFIG['weights']

    def test_weight_override_changes_the_score(self, config_file):
        before = grade(_facts(clean_std_dev=1.3))['score']
        config_file({'weights': {'consistency': 0.90}})
        after = grade(_facts(clean_std_dev=1.3))['score']
        assert after < before   # scrappy consistency now weighs heavier

    def test_overall_caps_override_replaces_the_table(self, config_file):
        config_file({'overall_caps': [[1.0, 50.0]]})
        g = grade(_facts())      # fully clean, strong execution
        assert g['capped'] is True
        assert g['score'] == 50.0
        assert g['execution']['score'] > 90   # underlying score untouched

    def test_curve_variant_override_merges_alone(self, config_file):
        # Tuning one variant must not clobber the others in that category.
        config_file({'curves': {'consistency': {'default': [[0.0, 100], [5.0, 100]]}}})
        g = grade(_facts(clean_std_dev=2.0))
        cons = next(c for c in g['components'] if c['key'] == 'consistency')
        assert cons['score'] == 100.0
        assert 'race' in grading.config()['curves']['consistency']

    def test_game_session_type_curve_key(self, config_file):
        config_file({'curves': {'pace': {'f1_25:practice': [[0.0, 42], [9.0, 42]]}}})
        g = grade(_facts())   # game f1_25, session_type practice
        assert g['pace_rating'] == 42

    def test_min_laps_override(self, config_file):
        config_file({'min_laps': 10})
        assert grade(_facts(lap_count=9)) is None

    def test_race_pace_curve_and_race_caps_are_tunable(self, config_file):
        config_file({
            'curves': {'race_pace': {'default': [[0.0, 55], [9.0, 55]]}},
            'overall_caps_race': [[9.0, 42.0]],
        })
        g = grade(_facts(session_type='race'), prior_best=88.2)
        assert g['pace_rating'] == 55
        assert g['capped'] is True
        assert g['score'] == 42.0

    def test_standards_curve_is_tunable(self, config_file):
        config_file({'curves': {'standards': {'default': [[0.0, 61], [9.0, 61]]}}})
        g = grade(_facts(session_type='race'))
        assert g['cleanliness']['score'] == 61

    def test_trend_outlier_ratio_is_tunable(self, config_file):
        config_file({'trend_outlier_ratio': 3.0})
        recs = [_record(f'{i:02d}.csv', i + 1, b) for i, b in
                enumerate([93.5, 93.0, 187.5, 93.2, 93.1])]
        t = grading.trend(recs)
        assert len(t['gaps']) == 5

    def test_trend_incident_rate_is_tunable(self, config_file):
        config_file({'trend_incident_rate': 0})   # 0 disables the guard
        recs = [_record(f'{i:02d}.csv', i + 1, b) for i, b in
                enumerate([93.5, 93.0, 95.4, 93.2])]
        recs[2].update(lap_count=4, collision_count=10, rewind_count=5)
        assert len(grading.trend(recs)['gaps']) == 4

    def test_bad_json_falls_back_to_defaults(self, tmp_path, monkeypatch):
        path = tmp_path / 'grading.json'
        path.write_text('{not json', encoding='utf-8')
        monkeypatch.setattr(grading, 'CONFIG_PATH', str(path))
        grading.reload_config()
        try:
            assert grading.config()['min_laps'] == grading.DEFAULT_CONFIG['min_laps']
            assert grade(_facts()) is not None
        finally:
            grading.reload_config()


# ---------------------------------------------------------------------------
# trend — direction of travel across recent comparable sessions
# ---------------------------------------------------------------------------

class TestTrend:
    def _records(self, bests):
        return [_record(f'{i:02d}.csv', i + 1, b) for i, b in enumerate(bests)]

    def test_shrinking_pb_gap_is_improving(self):
        t = grading.trend(self._records([89.0, 88.55, 88.3, 88.12, 88.0]))
        assert (t['direction'], t['arrow']) == ('improving', '↗')
        assert [round(g, 3) for _, g in t['gaps']] == [1.0, 0.55, 0.3, 0.12, 0.0]

    def test_growing_pb_gap_is_declining(self):
        t = grading.trend(self._records([88.0, 88.1, 88.5, 88.9, 89.2]))
        assert (t['direction'], t['arrow']) == ('declining', '↘')

    def test_flat_gaps_are_stable(self):
        t = grading.trend(self._records([88.0, 88.05, 88.02, 88.06, 88.03]))
        assert (t['direction'], t['arrow']) == ('stable', '→')

    def test_needs_three_timed_sessions(self):
        assert grading.trend(self._records([88.0, 88.5])) is None
        records = self._records([88.0, None, 88.5])
        assert grading.trend(records) is None

    def test_window_uses_newest_sessions_only(self):
        # Ancient slow sessions outside the window must not inflate the
        # improvement; only the newest trend_sessions count.
        bests = [95.0, 94.0, 88.2, 88.2, 88.2, 88.2, 88.2]
        assert grading.trend(self._records(bests))['direction'] == 'stable'

    def test_implausible_best_is_dropped_from_the_window(self):
        # A corrupt index row (a CSV scanned mid-download) once put a
        # +94s gap in the trend — impossible values never enter gaps.
        t = grading.trend(self._records([93.5, 93.0, 187.5, 93.2, 93.1]))
        gaps = [round(g, 3) for _, g in t['gaps']]
        assert len(gaps) == 4
        assert max(gaps) < 1.0

    def test_outlier_filtering_can_leave_too_few_sessions(self):
        assert grading.trend(self._records([93.0, 187.5, 93.2])) is None

    def test_legitimately_slow_wet_session_survives(self):
        # +30% on the median (a wet race) is within the 1.5× guard.
        t = grading.trend(self._records([93.0, 93.5, 121.0, 93.2, 93.1]))
        assert len(t['gaps']) == 5

    def test_incident_compromised_session_is_dropped(self):
        # A crash-heavy race whose best lap is ALSO off the typical pace
        # measured the incidents, not the driver — it must not read as
        # decline (3rd-race AI-coach feedback).
        recs = self._records([93.5, 93.0, 95.4, 93.2])
        recs[2].update(lap_count=4, collision_count=10, penalty_count=0,
                       rewind_count=5)
        t = grading.trend(recs)
        assert len(t['gaps']) == 3
        assert t['direction'] == 'improving'

    def test_incident_heavy_but_on_pace_session_stays(self):
        # Incidents alone don't disqualify pace evidence: a best lap on
        # the typical pace is real even in a messy race.
        recs = self._records([93.5, 93.0, 93.2, 93.1])
        recs[2].update(lap_count=4, collision_count=7, penalty_count=3,
                       rewind_count=1)
        assert len(grading.trend(recs)['gaps']) == 4

    def test_clean_slow_sessions_still_read_as_decline(self):
        # The incident guard must not hide genuine loss of pace.
        recs = self._records([93.0, 93.1, 95.0, 95.2, 95.4])
        for r in recs:
            r.update(lap_count=10, collision_count=0, penalty_count=0,
                     rewind_count=0)
        assert grading.trend(recs)['direction'] == 'declining'


# ---------------------------------------------------------------------------
# driver_profile — repeatability at one combo
# ---------------------------------------------------------------------------

class TestDriverProfile:
    def _records(self, bests, stds=None):
        stds = stds or [None] * len(bests)
        return [dict(_record(f'{i:02d}.csv', i + 1, b), clean_std_dev=s)
                for i, (b, s) in enumerate(zip(bests, stds))]

    def test_profile_values(self):
        p = grading.driver_profile(self._records(
            [92.0, 91.6, 92.4, 92.2, 91.9],
            [0.3, 0.4, 0.5, 0.4, 0.4]))
        assert p['pb'] == 91.6
        assert p['avg_best'] == pytest.approx(92.02)
        assert p['sessions'] == 5
        lo, hi = p['typical']
        assert 91.6 <= lo <= hi <= 92.4
        assert p['avg_std'] == pytest.approx(0.4)
        assert p['stars'] == 4                    # avg 0.40 ≤ 0.45
        assert grading.stars_text(p['stars']) == '★★★★☆'

    def test_small_history_still_profiles_what_it_can(self):
        # Always show the profile — but only the fields the data supports.
        p = grading.driver_profile(self._records([92.0, 91.6]))
        assert p['pb'] == 91.6
        assert p['sessions'] == 2
        assert p['typical'] is None       # needs 3+ sessions
        assert p['stars'] is None
        assert grading.driver_profile([]) is None

    def test_stars_need_three_sessions_with_std_data(self):
        p = grading.driver_profile(self._records([92.0, 91.6, 92.4]))
        assert p['stars'] is None
        p = grading.driver_profile(self._records([92.0, 91.6, 92.4],
                                                 [0.3, 0.4, 0.4]))
        assert p['stars'] == 4

    def test_on_pace_percentage(self):
        records = self._records([92.0, 91.6, 92.4])
        for r, (cons, band) in zip(records, [(6, 5), (6, 5), (4, 3)]):
            r['cons_lap_count'] = cons
            r['cons_band_count'] = band
        p = grading.driver_profile(records)
        assert p['on_pace_pct'] == pytest.approx(100 * 13 / 16)

    def test_on_pace_needs_ten_eligible_laps(self):
        records = self._records([92.0, 91.6, 92.4])
        for r in records:
            r['cons_lap_count'] = 3
            r['cons_band_count'] = 3
        assert grading.driver_profile(records)['on_pace_pct'] is None

    def test_baseline_tracks_the_typical_pace(self):
        # Session bests improving chronologically → baseline improving.
        p = grading.driver_profile(self._records(
            [93.0, 92.8, 92.4, 92.1, 91.9]))
        b = p['baseline']
        assert (b['direction'], b['arrow']) == ('improving', '↗')
        assert b['from'] == pytest.approx(92.9)   # older half average
        assert b['to'] == pytest.approx(92.0)     # newer half average
        assert b['shift'] == pytest.approx(-0.9)

    def test_baseline_stable_and_minimum(self):
        p = grading.driver_profile(self._records([92.0, 92.05, 91.98]))
        assert p['baseline']['direction'] == 'stable'
        assert grading.driver_profile(
            self._records([92.0, 91.9]))['baseline'] is None

    def test_baseline_ignores_incident_compromised_sessions(self):
        # Same guard as trend(): a crash-heavy race with an off-pace
        # best must not drag the typical-pace baseline into "declining"
        # when the surrounding sessions are on pace.
        recs = self._records([93.5, 93.0, 95.4, 93.2])
        recs[2].update(lap_count=4, collision_count=10, rewind_count=5)
        p = grading.driver_profile(recs)
        assert p['baseline']['direction'] == 'improving'
        assert p['sessions'] == 4    # profile itself still counts it

    def test_confidence_is_the_weaker_sample_rating(self):
        # The coach's examples: 14 sessions / 216 clean laps → ★★★★☆;
        # 4 sessions / 28 clean laps → 2 stars.
        records = self._records([92.0 + i * 0.01 for i in range(14)])
        for r in records:
            r['clean_lap_count'] = 216 // 14 + 1   # ≈216 total
        conf = grading.driver_profile(records)['confidence']
        assert conf['stars'] == 4                  # sessions cap it at 4
        records = self._records([92.0, 92.1, 92.2, 92.3])
        for r in records:
            r['clean_lap_count'] = 7
        conf = grading.driver_profile(records)['confidence']
        assert conf == {'stars': 2, 'sessions': 4, 'clean_laps': 28}


# ---------------------------------------------------------------------------
# milestones — personal firsts/records
# ---------------------------------------------------------------------------

def _mrec(filename, day, best, s2=None, streak=None, laps=None, valid=None):
    r = _record(filename, day, best)
    r['best_s2'] = s2
    r['clean_streak'] = streak
    r['lap_count'] = laps
    r['valid_lap_count'] = valid
    return r


class TestMilestones:
    def test_new_pb_with_improvement_amount(self):
        ms = grading.milestones(_mrec('b.csv', 2, 91.603),
                                [_mrec('a.csv', 1, 92.152)])
        assert ms[0]['icon'] == '🏆'
        assert ms[0]['detail'] == '1:31.603 — improved by 0.549s'

    def test_sector_record_only_when_pb_did_not_fall(self):
        prior = [_mrec('a.csv', 1, 91.6, s2=38.0)]
        # PB fell → no separate sector milestone.
        ms = grading.milestones(_mrec('b.csv', 2, 91.5, s2=37.8), prior)
        assert [m['icon'] for m in ms] == ['🏆']
        # PB stood, S2 record fell → sector milestone.
        ms = grading.milestones(_mrec('c.csv', 3, 91.8, s2=37.8), prior)
        assert ms[0]['icon'] == '⭐'
        assert ms[0]['title'] == 'Best S2 on record'

    def test_longest_clean_streak(self):
        ms = grading.milestones(_mrec('b.csv', 2, 92.0, streak=8),
                                [_mrec('a.csv', 1, 91.6, streak=5)])
        assert any(m['icon'] == '🔥' and '8 clean laps' in m['detail']
                   for m in ms)

    def test_first_session_under_ten_percent_invalid(self):
        prior = [_mrec('a.csv', 1, 91.6, laps=10, valid=6)]
        ms = grading.milestones(_mrec('b.csv', 2, 92.0, laps=12, valid=12),
                                prior)
        assert any(m['icon'] == '🎯' for m in ms)
        # …but not again once it has been done before.
        prior.append(_mrec('b.csv', 2, 92.0, laps=12, valid=12))
        ms = grading.milestones(_mrec('c.csv', 3, 92.1, laps=12, valid=12),
                                prior)
        assert not any(m['icon'] == '🎯' for m in ms)

    def test_first_session_at_a_combo_sets_no_milestones(self):
        assert grading.milestones(_mrec('a.csv', 1, 91.6), []) == []

    def test_first_a_grade_execution(self):
        # Full grading facts: current session executes at A, the prior
        # session did not (scrappy consistency and pace).
        strong = dict(_facts(), filename='b.csv', date=datetime(2026, 6, 2))
        weak   = dict(_facts(clean_std_dev=2.0, best_lap_time=90.0),
                      filename='a.csv', date=datetime(2026, 6, 1))
        ms = grading.milestones(strong, [weak])
        first_a = next(m for m in ms if m['icon'] == '🏅')
        assert first_a['title'] == 'First A-range execution'
        # Detail quotes no score/letter — the milestone comparison is
        # graded without the PB pillar and must not clash with the
        # session's displayed grade.
        assert first_a['detail'] == 'execution grade A- or better'
        # …and never again once an A-execution session exists.
        ms = grading.milestones(dict(strong, filename='c.csv'),
                                [weak, strong])
        assert not any(m['icon'] == '🏅' for m in ms)


class TestLatestMilestone:
    def test_picks_newest_across_combos(self):
        monaco = [_record('m1.csv', 1, 70.0), _record('m2.csv', 2, 69.5,
                                                      track='Monaco')]
        monaco[0]['track'] = 'Monaco'
        silverstone = [_record('s1.csv', 3, 92.0), _record('s2.csv', 5, 91.6)]
        latest = grading.latest_milestone(monaco + silverstone)
        record, ms = latest
        assert record['filename'] == 's2.csv'
        assert ms[0]['icon'] == '🏆'

    def test_none_without_history(self):
        assert grading.latest_milestone([_record('a.csv', 1, 92.0)]) is None


# ---------------------------------------------------------------------------
# prior_bests — bulk chronological PB lookup
# ---------------------------------------------------------------------------

def _record(filename, day, best, track='Silverstone', session_type='practice'):
    return {
        'filename': filename, 'date': datetime(2026, 6, day),
        'game': 'f1_25', 'car_class': 'formula1_2026',
        'track': track, 'session_type': session_type,
        'best_lap_time': best,
    }


class TestPriorBests:
    def test_running_best_is_strictly_before_each_session(self):
        records = [
            _record('c.csv', 3, 87.9),
            _record('a.csv', 1, 89.0),
            _record('b.csv', 2, 88.1),
        ]
        pbs = prior_bests(records)
        assert pbs['a.csv'] is None
        assert pbs['b.csv'] == 89.0
        assert pbs['c.csv'] == 88.1

    def test_combos_are_independent(self):
        records = [
            _record('a.csv', 1, 89.0),
            _record('b.csv', 2, 95.0, track='Monza'),
        ]
        assert prior_bests(records)['b.csv'] is None

    def test_sessions_missing_combo_keys_are_skipped(self):
        records = [_record('a.csv', 1, 89.0, track=None)]
        assert 'a.csv' not in prior_bests(records)

    def test_sessions_without_a_best_dont_advance_the_pb(self):
        records = [
            _record('a.csv', 1, 89.0),
            _record('b.csv', 2, None),
            _record('c.csv', 3, 88.0),
        ]
        assert prior_bests(records)['c.csv'] == 89.0


# ---------------------------------------------------------------------------
# session_facts — facts from a fully parsed session
# ---------------------------------------------------------------------------

def _lap(num, time, s1=None, s2=None, s3=None, valid=True, rewinds=0):
    return {'num': num, 'time': time, 's1': s1, 's2': s2, 's3': s3,
            'valid': valid, 'rewinds': rewinds}


class TestSessionFacts:
    def test_counts_and_derived_values(self):
        session = {
            'game': 'f1_25', 'session_type': 'practice',
            'laps': [
                _lap(1, 90.0, 30.0, 30.0, 30.0),
                _lap(2, 88.0, 29.5, 29.3, 29.2),
                _lap(3, 92.0, valid=False),
                _lap(4, 89.0, rewinds=2),
                _lap(5, 95.0, 29.8, 29.9, 29.8),
            ],
            'events': [{'lap_num': 5, 'lap_time': 12.0, 'type': 'pit_in',
                        'distance': None}],
        }
        facts = session_facts(session)
        assert facts['lap_count'] == 5
        assert facts['valid_lap_count'] == 4
        assert facts['clean_lap_count'] == 3
        assert facts['rewind_count'] == 2
        assert facts['best_lap_time'] == 88.0
        assert facts['theo_time'] == pytest.approx(29.5 + 29.3 + 29.2)
        # Consistency over clean laps minus the pit lap: [90.0, 88.0]
        assert facts['clean_std_dev'] == pytest.approx(2 ** 0.5)

    def test_rewind_events_reconcile_the_count(self):
        # A flashback on a lap whose L row was never logged (e.g. a
        # race's final lap) is invisible to the per-lap column but is
        # in the event stream — grading must agree with coaching.
        session = {
            'session_type': 'race',
            'laps': [_lap(n, 90.0 + n) for n in range(1, 5)],
            'events': [{'lap_num': 5, 'lap_time': 95.2, 'type': 'rewind',
                        'distance': None, 't': 481.6, 'detail': None}],
        }
        assert session_facts(session)['rewind_count'] == 1

    def test_rewind_events_never_lower_the_lap_column_count(self):
        session = {
            'laps': [_lap(1, 90.0, rewinds=2), _lap(2, 91.0), _lap(3, 90.5)],
            'events': [{'lap_num': 1, 'lap_time': 50.0, 'type': 'rewind',
                        'distance': None, 't': 50.0, 'detail': None}],
        }
        assert session_facts(session)['rewind_count'] == 2

    def test_theo_needs_two_full_sector_clean_laps(self):
        session = {'laps': [_lap(1, 90.0, 30.0, 30.0, 30.0),
                            _lap(2, 91.0)], 'events': []}
        assert session_facts(session)['theo_time'] is None

    def test_untimed_laps_are_ignored(self):
        session = {'laps': [_lap(1, None), _lap(2, 90.0)], 'events': []}
        facts = session_facts(session)
        assert facts['lap_count'] == 1
        assert facts['clean_std_dev'] is None
