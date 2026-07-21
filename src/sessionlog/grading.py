"""
Shfonic Dash sessionlog — session grading (shared library; canonical
home is ShfonicDash/src/sessionlog/, vendored into the companion
app by sync_shared.py — see the package docstring).

Scores how well a session was EXECUTED relative to the driver's own
ability — never outright pace, raw lap time, or finishing position. A
beginner and an esports driver can both earn an A.

Three grades come out of grade() (structure per AI-coach feedback), and
their DEFINITIONS are session-aware — the words stay, the scoring
philosophy adapts to the session objective:
  Execution    (A+…F) — how well you drove when driving: weighted blend
                        of the execution pillars (weights in
                        DEFAULT_CONFIG). Races drop the PB-comparison
                        pillar entirely — a race lap is never chasing
                        the PB (fuel, tyres, dirty air, defending).
  Cleanliness  (A+…F) — hotlap/time trial: share of timed laps the game
                        invalidated. Practice/qualifying: share of laps
                        not CLEAN (invalidated or rewound). Races: the
                        grade becomes **Race Discipline** — contacts,
                        penalties and rewinds per lap; invalid laps,
                        being overtaken and pace play no part. The dict
                        carries `label`/`kind` so UIs name it right.
  Overall      (A+…F) — the execution score CAPPED by a ceiling: the
                        invalid-lap share (overall_caps) for non-races,
                        the incident rate (overall_caps_race) for races
                        — "Execution A-, Cleanliness D, Overall B"
Plus:
  Pace Rating  (0–100) — "how close did you get to your potential
                          today?" (the pace-execution subscore,
                          surfaced separately: a clean-but-cruising
                          session can be an A with a low pace rating).
                          For races this is scored against the prior
                          best RACE lap at the combo (`pace_kind` says
                          which reference applied — UIs show it as
                          Race Pace when 'race').

Execution pillars, each scored 0–100 (config keys in brackets):
  Pace execution [pace]        — gap between fastest clean lap and
                                 theoretical best; RACES score against
                                 the prior best race lap at the combo
                                 instead (curve `race_pace`), falling
                                 back to theoretical for a first race
                                 there (`pace_kind` reports which)
  Consistency [consistency]    — spread of clean lap times, pooled
                                 within tyre stints (pit / SC laps
                                 excluded; a compound change is not
                                 inconsistency)
  PB comparison [improvement]  — fastest clean lap vs the PB *before*
                                 this session (proximity, not literal
                                 improvement — being 0.3s off your PB
                                 still scores well). Not applied to
                                 races (not even as `unscored`).
  Mistakes [mistakes]          — rewinds/flashbacks + car contacts per
                                 lap (collision events, v0.1.135+).
                                 Races count rewinds only: contacts and
                                 penalties are scored once, in Race
                                 Discipline (spins are not in the log
                                 format yet — see TODO.md)

A pillar with no data (no prior PB, too few clean laps, …) drops out,
the remaining weights renormalise, and grade() reports it in
`unscored` with the reason — it never scores a fake neutral. Sessions
under min_laps timed laps are ungraded (grade() returns None).

The scoring curves are piecewise-linear and adaptive per session type
(race curves are looser: fuel burn, tyre wear and traffic legitimately
spread race laps). Weights, lap minimums and every curve are tunable
without code changes via an optional `grading.json` next to the
sessionlog package (gitignored; see CONFIG_PATH below). The file
overrides only what it names — same shape as DEFAULT_CONFIG below, e.g.

  {"weights": {"consistency": 0.30},
   "weights_by_type": {"race": {"improvement": 0.02}},
   "curves": {"consistency": {"default": [[0.2, 100], [0.8, 70], [1.5, 40]],
              "f1_25:race": [[0.4, 100], [1.2, 70]]}}}

Curve variant keys resolve "<game>:<session_type>" → "<session_type>" →
"default". Weights needn't sum to 1 — the applied set is renormalised.
weights_by_type overlays 'weights' per session objective (session_type
key first, session_subtype key refines) — shipped defaults scale the
PB-comparison weight from hotlap (high) down to race (minimal).

Input is a "facts" dict whose keys deliberately match the session_db row
contract, so a DB record can be graded directly; for a fully parsed
session dict use session_facts() to build the same shape. Keys read:
  game, session_type, lap_count, valid_lap_count, clean_lap_count,
  clean_std_dev, theo_time, rewind_count, collision_count,
  penalty_count, best_lap_time
rewind_count may be None (pre-v0.1.133 files log spurious rewinds around
pit stops) — Mistakes then renormalises away like any missing category.

Pure stdlib, no ui import — testable off-device (tests/test_grading.py).
"""

import json
import os
from statistics import median, quantiles

from .parser import (
    _stint_indices,
    consistency_excluded_laps,
    cooldown_laps,
    format_lap_time,
    format_sector_time,
    stint_std_dev,
)

# grading.json lives NEXT TO the sessionlog package, not inside it: the
# vendored copy of the package is overwritten wholesale by sync_shared.py,
# so a tuning file inside it would be lost. Parent-of-package is the app
# root in the companion (where grading.json already lived) and src/ on the
# Pi (gitignored in both). Apps/tests may reassign CONFIG_PATH before the
# first config() call.
CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'grading.json')

# Everything tunable in one place. Curve anchors are sorted [x, score]
# points, interpolated between and clamped to the end scores outside.
DEFAULT_CONFIG = {
    'min_laps':       3,   # fewer timed laps than this → ungraded
    'min_clean_laps': 3,   # consistency / pace need this many clean laps

    # Qualifying with fewer representative (consistency-eligible) laps
    # than this is ungraded: a single out–push–in run gives execution
    # grading nothing to compare against (the dashboard shows a note
    # instead). Other session types are unaffected.
    'min_rep_laps_quali': 2,

    # Below this many clean laps, one bad lap dominates the std dev, so
    # consistency is scored at HALF weight and marked low-confidence —
    # the small sample is already punished once via Cleanliness.
    'consistency_confidence_laps': 5,

    # Trend window: how many recent comparable sessions to look at, and
    # how much the average PB gap must move between the window's halves
    # (seconds) to call it improving/declining rather than stable.
    'trend_sessions':  5,
    'trend_threshold': 0.10,

    # Trend plausibility guard: sessions whose best lap is outside
    # [median/ratio, median*ratio] of the combo history are dropped
    # before gaps are computed — a corrupt index row (e.g. a CSV scanned
    # mid-download) must never put a "+94s" gap in the trend. Median-
    # relative so it is track-length independent and robust to the
    # outlier itself; a legitimately wet session at +30% survives.
    'trend_outlier_ratio': 1.5,

    # Trend incident guard: a session this incident-heavy (contacts +
    # penalties + rewinds per timed lap) whose best lap is ALSO off the
    # combo's typical pace (> median × 1%) is excluded from pace-trend
    # windows — its slow best measures the incidents, not the driver's
    # pace, and it must not read as decline. Both conditions are
    # required: an incident-heavy race that still delivered a
    # representative best lap is real pace evidence and stays, and a
    # CLEAN slow session is genuine decline and stays. 0 disables.
    'trend_incident_rate': 1.0,

    # Driver-profile repeatability stars: first [max_avg_std_dev, stars]
    # row the combo's average clean-lap std dev fits under; 1 star past
    # the last threshold.
    'repeatability_stars': [
        [0.25, 5],
        [0.45, 4],
        [0.70, 3],
        [1.10, 2],
    ],

    # Driver-profile confidence: how stable the profile is. Stars from
    # the first [max_count, stars] row each figure fits under (5 past
    # the end); the overall confidence is the WEAKER of the two — many
    # laps across few sessions is still a thin profile, and vice versa.
    'profile_confidence': {
        'sessions':   [[2, 1], [4, 2], [9, 3], [19, 4]],
        'clean_laps': [[14, 1], [39, 2], [89, 3], [199, 4]],
    },

    # Execution category weights (relative — the applied set renormalises).
    'weights': {
        'consistency': 0.25,
        'pace':        0.20,
        'improvement': 0.15,
        'mistakes':    0.10,
    },

    # Per-session-objective weight overrides, overlaid on 'weights'.
    # Keys are session_type or session_subtype (subtype wins). Shipped
    # defaults implement the PB-comparison ladder: chasing your PB is
    # the whole point of a hotlap, useful context in qualifying, and
    # noise in practice. Races don't appear here — the improvement
    # pillar is dropped for them entirely in grade() (RACE_TYPES), not
    # merely down-weighted.
    'weights_by_type': {
        'hotlap':      {'improvement': 0.30},
        'qualifying':  {'improvement': 0.18},
        'practice':    {'improvement': 0.10},
    },

    # Overall ceiling from the invalid-lap share: first [max_invalid_frac,
    # max_score] row whose threshold the session is within. The cap scores
    # sit just under a letter boundary so they read as that letter's top:
    # ≤10% invalid uncapped, ≤25% A-, ≤40% B, ≤60% B-, ≤80% C, else D.
    # (40% invalid used to cap at B+ — 4th-session AI-coach feedback: a
    # 60%-valid session reading "pretty complete" was too generous.)
    'overall_caps': [
        [0.10, 100.0],
        [0.25, 93.3],
        [0.40, 86.6],
        [0.60, 83.2],
        [0.80, 76.6],
        [1.00, 66.6],
    ],

    # Race Overall ceiling, keyed on INCIDENTS per timed lap (contacts +
    # penalties + rewinds — the Race Discipline input) instead of the
    # invalid-lap share: a race with zero invalid laps but ten contacts
    # must not read as flawless. Same just-under-a-letter cap scores.
    'overall_caps_race': [
        [0.05, 100.0],
        [0.15, 93.3],
        [0.30, 89.9],
        [0.60, 86.6],
        [1.00, 76.6],
        [2.00, 66.6],
    ],

    'curves': {
        # x = std dev of clean lap times, seconds
        'consistency': {
            'default': [[0.15, 100], [0.35, 90], [0.60, 75], [1.20, 50], [2.50, 20]],
            'race':    [[0.30, 100], [0.60, 90], [1.00, 75], [2.00, 50], [3.50, 20]],
        },
        # x = fastest clean lap − theoretical best, seconds
        'pace': {
            'default': [[0.0, 100], [0.10, 98], [0.35, 90], [0.70, 75], [1.50, 50], [3.00, 25]],
            'race':    [[0.0, 100], [0.30, 95], [0.80, 85], [1.50, 70], [3.00, 50], [5.00, 25]],
        },
        # x = fastest clean lap − prior best RACE lap at the combo,
        # seconds (races only; the theoretical lap is nearly irrelevant
        # in race conditions). Matching the prior best scores 100 —
        # equalling your race pace under fuel/tyres/traffic IS the job.
        'race_pace': {
            'default': [[0.0, 100], [0.30, 95], [0.80, 85], [1.50, 70], [3.00, 50], [5.00, 25]],
        },
        # x = (fastest clean lap − prior PB) as a % of the prior PB
        # (percentage, not seconds, so a 70 s Monaco lap and a 140 s Spa
        # lap are held to the same standard). Negative = new PB.
        'improvement': {
            'default': [[0.0, 100], [0.2, 90], [0.5, 75], [1.0, 60], [2.0, 45], [4.0, 25]],
        },
        # x = rewinds per timed lap (rate, so long sessions aren't
        # punished for having more laps in which to rewind)
        'mistakes': {
            'default': [[0.0, 100], [0.10, 85], [0.25, 65], [0.50, 45], [1.00, 25], [2.00, 10]],
        },
        # x = share of timed laps invalidated (0–1) → Cleanliness score
        # (hotlap/TT; practice/quali feed the not-clean share instead —
        # invalidated OR rewound — through the same curve)
        'cleanliness': {
            'default': [[0.0, 100], [0.10, 92], [0.25, 82], [0.40, 72], [0.60, 62], [0.80, 45], [1.00, 25]],
        },
        # x = incidents per timed lap (contacts + penalties + rewinds)
        # → the race Race Discipline score. "How cleanly did you
        # race?" — being overtaken, finishing low and pace are not
        # incidents and play no part.
        'standards': {
            'default': [[0.0, 100], [0.05, 92], [0.15, 80], [0.30, 65], [0.60, 45], [1.00, 25]],
        },
    },
}

# Session types graded with race semantics (race pace, Race
# Discipline, rewinds-only mistakes; no PB-comparison pillar).
RACE_TYPES = ('race', 'sprint_race')

CATEGORY_ORDER = ('pace', 'consistency', 'improvement', 'mistakes')

# Display names; the config/dict keys stay stable ('improvement' is shown
# as PB comparison — it measures proximity to the prior PB, and the name
# "Improvement" read as a contradiction when a good-but-slower lap
# scored 80+).
CATEGORY_LABELS = {
    'pace':        'Pace execution',
    'consistency': 'Consistency',
    'improvement': 'PB comparison',
    'mistakes':    'Mistakes',
}

_config_cache = None


def config():
    """DEFAULT_CONFIG with any grading.json overrides applied (cached)."""
    global _config_cache
    if _config_cache is None:
        overrides = {}
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                overrides = loaded
        except (OSError, ValueError):
            pass   # no file / bad JSON → pure defaults
        _config_cache = _merge_config(overrides)
    return _config_cache


def reload_config():
    """Drop the cached config so the next grade() re-reads grading.json."""
    global _config_cache
    _config_cache = None


def _merge_config(overrides):
    """Overlay a grading.json dict onto the defaults, section-aware:
    scalars replace, weights merge per category, curves merge per
    category then per variant key (so one variant can be tuned alone)."""
    cfg = {
        'min_laps':       overrides.get('min_laps', DEFAULT_CONFIG['min_laps']),
        'min_clean_laps': overrides.get('min_clean_laps',
                                        DEFAULT_CONFIG['min_clean_laps']),
        'min_rep_laps_quali': overrides.get(
            'min_rep_laps_quali', DEFAULT_CONFIG['min_rep_laps_quali']),
        'consistency_confidence_laps': overrides.get(
            'consistency_confidence_laps',
            DEFAULT_CONFIG['consistency_confidence_laps']),
        'trend_sessions':  overrides.get('trend_sessions',
                                         DEFAULT_CONFIG['trend_sessions']),
        'trend_threshold': overrides.get('trend_threshold',
                                         DEFAULT_CONFIG['trend_threshold']),
        'trend_outlier_ratio': overrides.get(
            'trend_outlier_ratio', DEFAULT_CONFIG['trend_outlier_ratio']),
        'trend_incident_rate': overrides.get(
            'trend_incident_rate', DEFAULT_CONFIG['trend_incident_rate']),
        'weights': dict(DEFAULT_CONFIG['weights']),
        'overall_caps': [list(row) for row in DEFAULT_CONFIG['overall_caps']],
        'overall_caps_race': [list(row) for row in
                              DEFAULT_CONFIG['overall_caps_race']],
        'curves':  {k: dict(v) for k, v in DEFAULT_CONFIG['curves'].items()},
    }
    caps = overrides.get('overall_caps')
    if isinstance(caps, list) and caps:
        cfg['overall_caps'] = caps
    caps_race = overrides.get('overall_caps_race')
    if isinstance(caps_race, list) and caps_race:
        cfg['overall_caps_race'] = caps_race
    stars = overrides.get('repeatability_stars')
    cfg['repeatability_stars'] = (
        stars if isinstance(stars, list) and stars
        else [list(row) for row in DEFAULT_CONFIG['repeatability_stars']])
    cfg['profile_confidence'] = {
        k: [list(row) for row in v]
        for k, v in DEFAULT_CONFIG['profile_confidence'].items()}
    conf = overrides.get('profile_confidence')
    if isinstance(conf, dict):
        for k in cfg['profile_confidence']:
            if isinstance(conf.get(k), list) and conf[k]:
                cfg['profile_confidence'][k] = conf[k]
    weights = overrides.get('weights')
    if isinstance(weights, dict):
        for k in cfg['weights']:
            if isinstance(weights.get(k), (int, float)):
                cfg['weights'][k] = float(weights[k])
    cfg['weights_by_type'] = {k: dict(v) for k, v in
                              DEFAULT_CONFIG['weights_by_type'].items()}
    wbt = overrides.get('weights_by_type')
    if isinstance(wbt, dict):
        for key, cats in wbt.items():
            if isinstance(cats, dict):
                merged = cfg['weights_by_type'].setdefault(key, {})
                for c, v in cats.items():
                    if c in DEFAULT_CONFIG['weights'] \
                            and isinstance(v, (int, float)):
                        merged[c] = float(v)
    curves = overrides.get('curves')
    if isinstance(curves, dict):
        for name in cfg['curves']:
            variants = curves.get(name)
            if isinstance(variants, dict):
                cfg['curves'][name].update(variants)
    return cfg


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def grade(facts, prior_best=None):
    """
    Grade one session.

    facts      — session_db record, or session_facts(parsed_session).
    prior_best — best clean lap (seconds) across earlier sessions at the
                 same game / car class / track / session type, or None
                 when there is no history (session_db.prior_best(), or
                 prior_bests() for a bulk lookup).

    Returns None when ungradeable (no facts, < min_laps timed laps, or
    a qualifying session with fewer than min_rep_laps_quali
    representative laps — one out–push–in run gives execution grading
    nothing to compare against), else a dict:
      score       float 0–100 — the OVERALL score: execution capped by
                  the invalid-lap ceiling (overall_caps), or for races
                  the incident-rate ceiling (overall_caps_race)
      letter      'A+' … 'F' — overall letter
      capped      bool — True when the ceiling lowered it
      execution   {score, letter} | None — the active pillars weighted
                  and renormalised (races: pace / consistency /
                  mistakes; others add improvement)
      cleanliness {score, letter, detail, label, kind} | None — the
                  session-aware secondary grade: hotlap/TT invalid
                  share ('Cleanliness'/'cleanliness'), practice/quali
                  not-clean share ('Cleanliness'/'cleanliness'), races
                  incidents per lap ('Race Discipline'/'standards')
      pace_rating int 0–100 | None — the pace subscore (Pace Rating)
      pace_kind   'race' | 'theoretical' | None — what the pace pillar
                  was scored against ('race' = prior best race lap at
                  the combo; UIs label the rating Race Pace then)
      components  [{key, label, score, weight, detail}, ...] — applied
                  EXECUTION pillars only, in CATEGORY_ORDER; weight is
                  the renormalised share; detail states the evidence
      unscored    [{key, label, reason}, ...] — active execution
                  pillars that had no data this session, with why (so
                  the breakdown always accounts for every pillar that
                  applies to the session type)
      explanation coaching-style summary (evidence only — states what
                  the data shows, never intent)
      focus       one achievable objective for the next session, aimed
                  at the weakest area (never "find more lap time")
    """
    if not facts:
        return None
    cfg = config()
    lap_count = facts.get('lap_count')
    if not lap_count or lap_count < cfg['min_laps']:
        return None

    game        = (facts.get('game') or '').strip()
    stype       = (facts.get('session_type') or '').strip().lower()
    is_race     = stype in RACE_TYPES

    # Qualifying with a single representative lap (a lone out–push–in
    # run) — nothing for consistency / execution to compare against.
    # The dashboard states why instead of showing a grade. Rows scanned
    # before schema v7 have no cons_lap_count → grade as before.
    if stype == 'qualifying':
        rep = facts.get('cons_lap_count')
        if rep is not None and rep < cfg['min_rep_laps_quali']:
            return None

    valid_count = facts.get('valid_lap_count')
    clean_count = facts.get('clean_lap_count') or 0
    std         = facts.get('clean_std_dev')
    theo        = facts.get('theo_time')
    best        = facts.get('best_lap_time')
    rewinds     = facts.get('rewind_count')

    def _curve(name):
        variants = cfg['curves'][name]
        return (variants.get(f'{game}:{stype}')
                or variants.get(stype)
                or variants['default'])

    raw = {}      # execution category key → (score, detail)

    low_confidence = False
    if std is not None and clean_count >= cfg['min_clean_laps']:
        detail = f"std dev {std:.3f}s over clean laps"
        if clean_count < cfg['consistency_confidence_laps']:
            low_confidence = True
            detail += (f" (low confidence — only {clean_count} clean laps, "
                       "scored at half weight)")
        raw['consistency'] = (_interp(_curve('consistency'), std), detail)

    # Pace — races score against the prior best race lap at the combo
    # (equalling your race pace under fuel/tyres/traffic IS the job; the
    # theoretical lap is nearly irrelevant there), falling back to the
    # theoretical gap for a first race at the combo. pace_kind records
    # which reference applied so UIs can label the rating Race Pace.
    gap = None
    pace_kind = None
    if best is not None and clean_count >= cfg['min_clean_laps']:
        if is_race and prior_best is not None and prior_best > 0:
            gap = max(0.0, best - prior_best)
            detail = (f"new best race lap, {prior_best - best:.3f}s under "
                      "the previous"
                      if best < prior_best else
                      f"fastest clean lap +{gap:.3f}s off your best race "
                      "lap here")
            raw['pace'] = (_interp(_curve('race_pace'), gap), detail)
            pace_kind = 'race'
        elif theo is not None:
            gap = max(0.0, best - theo)
            raw['pace'] = (_interp(_curve('pace'), gap),
                           f"fastest clean lap +{gap:.3f}s off theoretical best")
            pace_kind = 'theoretical'

    # PB comparison — never scored for races: a race lap is not chasing
    # the PB, so proximity to it says nothing about execution there.
    # pb_delta is still computed so the explanation can report a new
    # best race lap.
    pb_delta = None
    if prior_best is not None and best is not None and prior_best > 0:
        pb_delta = best - prior_best
        if not is_race:
            pct = 100.0 * pb_delta / prior_best
            detail = (f"new personal best, {-pb_delta:.3f}s under the previous"
                      if pb_delta < 0 else
                      f"fastest clean lap +{pb_delta:.3f}s off prior personal "
                      "best")
            raw['improvement'] = (_interp(_curve('improvement'),
                                          max(0.0, pct)), detail)

    # Mistakes — races count rewinds only: contacts and penalties are
    # scored once, in Race Discipline, not twice.
    collisions = facts.get('collision_count') or 0
    penalties  = facts.get('penalty_count') or 0
    if rewinds is not None:
        mistake_events = rewinds if is_race else rewinds + collisions
        rate = mistake_events / lap_count
        parts = []
        if rewinds:
            parts.append(f"{rewinds} rewind{'s' if rewinds != 1 else ''}")
        if collisions and not is_race:
            parts.append(f"{collisions} collision"
                         f"{'s' if collisions != 1 else ''}")
        if not parts:
            detail = ("no rewinds" if is_race
                      else "no rewinds or collisions")
        else:
            detail = " and ".join(parts)
        raw['mistakes'] = (_interp(_curve('mistakes'), rate), detail)

    # Execution — how well you drove when driving. Weights adapt to the
    # session objective (weights_by_type: session_type first, subtype
    # refines), and a low-confidence consistency sample counts at half
    # weight (see DEFAULT_CONFIG).
    weights = dict(cfg['weights'])
    subtype = (facts.get('session_subtype') or '').strip().lower()
    for key in (stype, subtype):
        if key and key in cfg['weights_by_type']:
            weights.update(cfg['weights_by_type'][key])
    if low_confidence:
        weights['consistency'] *= 0.5
    execution  = None
    components = []
    total_w = sum(weights[k] for k in raw)
    if raw and total_w > 0:
        exec_score = sum(weights[k] * s for k, (s, _) in raw.items()) / total_w
        execution  = {'score': exec_score, 'letter': letter(exec_score)}
        components = [
            {'key': k, 'label': CATEGORY_LABELS[k], 'score': s,
             'weight': weights[k] / total_w, 'detail': d}
            for k, (s, d) in ((k, raw[k]) for k in CATEGORY_ORDER if k in raw)
        ]

    # Pillars that had no data — reported, not silently dropped, so the
    # breakdown always matches the session type's pillar definition
    # (races never list PB comparison: it doesn't apply, it isn't
    # missing).
    active = tuple(k for k in CATEGORY_ORDER
                   if k != 'improvement' or not is_race)
    reasons = {
        'pace':        (f"only {clean_count} clean laps"
                        if clean_count < cfg['min_clean_laps'] or best is None
                        else "sector data unavailable"),
        'consistency': (f"only {clean_count} clean laps"
                        if clean_count < cfg['min_clean_laps']
                        else "not enough comparable clean laps"),
        'improvement': "no prior personal best at this combination",
        'mistakes':    "rewind data unavailable",
    }
    unscored = [{'key': k, 'label': CATEGORY_LABELS[k], 'reason': reasons[k]}
                for k in active if k not in raw]

    # Secondary grade — session-aware:
    #   hotlap/TT        Cleanliness from the invalid-lap share
    #   practice/quali   Cleanliness from the not-clean share (invalid
    #                    OR rewound; plain invalid share when the rewind
    #                    count is untrustworthy, see session_facts)
    #   race             Race Discipline from incidents per lap —
    #                    contacts + penalties + rewinds. Invalid laps,
    #                    being overtaken and pace play no part.
    cleanliness    = None
    invalid_frac   = None
    incident_rate  = None
    if valid_count is not None:
        invalid_frac = (lap_count - valid_count) / lap_count
    if is_race:
        incidents = collisions + penalties + (rewinds or 0)
        incident_rate = incidents / lap_count
        if not incidents:
            detail = "no contacts, penalties or flashbacks"
        else:
            parts = []
            if collisions:
                parts.append(f"{collisions} contact"
                             f"{'s' if collisions != 1 else ''}")
            if penalties:
                parts.append(f"{penalties} penalt"
                             f"{'ies' if penalties != 1 else 'y'}")
            if rewinds:
                parts.append(f"{rewinds} flashback"
                             f"{'s' if rewinds != 1 else ''}")
            detail = (", ".join(parts[:-1]) + " and " + parts[-1]
                      if len(parts) > 1 else parts[0])
            detail += f" over {lap_count} laps"
        if rewinds is None:
            detail += " (rewind data unavailable)"
        cs = _interp(_curve('standards'), incident_rate)
        cleanliness = {'score': cs, 'letter': letter(cs), 'detail': detail,
                       'label': 'Race Discipline', 'kind': 'standards'}
    elif (stype in ('practice', 'qualifying') and valid_count is not None
            and facts.get('clean_lap_count') is not None
            and rewinds is not None):
        unclean_frac = (lap_count - clean_count) / lap_count
        n_invalid    = lap_count - valid_count
        rew_laps     = valid_count - clean_count
        detail = f"{clean_count} of {lap_count} laps clean"
        extras = []
        if n_invalid:
            extras.append(f"{n_invalid} invalidated")
        if rew_laps > 0:
            extras.append(f"{rew_laps} rewound")
        if extras:
            detail += " (" + ", ".join(extras) + ")"
        cs = _interp(_curve('cleanliness'), unclean_frac)
        cleanliness = {'score': cs, 'letter': letter(cs), 'detail': detail,
                       'label': 'Cleanliness', 'kind': 'cleanliness'}
    elif valid_count is not None:
        cs = _interp(_curve('cleanliness'), invalid_frac)
        cleanliness = {'score': cs, 'letter': letter(cs),
                       'detail': f"{valid_count} of {lap_count} laps valid",
                       'label': 'Cleanliness', 'kind': 'cleanliness'}

    if execution is None and cleanliness is None:
        return None

    # Overall — execution capped by the session's ceiling (invalid-lap
    # share, or the incident rate for races), so incidents bound the
    # grade without dominating the underlying score.
    capped = False
    if execution is not None:
        score = execution['score']
        if is_race and incident_rate is not None:
            cap = _overall_cap(cfg['overall_caps_race'], incident_rate)
        elif not is_race and invalid_frac is not None:
            cap = _overall_cap(cfg['overall_caps'], invalid_frac)
        else:
            cap = None
        if cap is not None and score > cap:
            score  = cap
            capped = True
    else:
        score = cleanliness['score']

    pace_rating = round(raw['pace'][0]) if 'pace' in raw else None

    return {
        'score':       score,
        'letter':      letter(score),
        'capped':      capped,
        'execution':   execution,
        'cleanliness': cleanliness,
        'pace_rating': pace_rating,
        'pace_kind':   pace_kind if 'pace' in raw else None,
        'components':  components,
        'unscored':    unscored,
        'explanation': _explanation(raw, execution, cleanliness, lap_count,
                                    valid_count, std, gap, pb_delta, rewinds,
                                    low_confidence, is_race=is_race,
                                    pace_kind=pace_kind,
                                    collisions=collisions,
                                    penalties=penalties),
        'focus':       _focus(raw, cleanliness, invalid_frac, valid_count,
                              std, theo, rewinds, is_race=is_race,
                              incident_rate=incident_rate,
                              pace_kind=pace_kind, prior_best=prior_best),
    }


def session_facts(session):
    """
    Build the grade() facts dict from a fully parsed session (parser.parse()).
    Produces the same values scan_session() precomputes into the DB row, so
    the dashboard and the picker agree on every grade.
    """
    laps  = session.get('laps') or []
    timed = [lap for lap in laps if lap.get('time') is not None]
    valid = [lap for lap in timed if lap.get('valid', True)]
    clean = [lap for lap in valid if not lap.get('rewinds', 0)]

    last_lap = max((lap['num'] for lap in timed if lap.get('num') is not None),
                   default=None)
    pit_sc    = consistency_excluded_laps(
        session.get('events') or [], last_lap, session.get('session_type'),
        [(lap.get('num'), lap.get('time')) for lap in clean])
    sidx      = _stint_indices(lap.get('tyre_compound') for lap in timed)
    eligible  = [(lap['num'], lap['time'], sidx[i])
                 for i, lap in enumerate(timed)
                 if lap.get('valid', True) and not lap.get('rewinds', 0)
                 and lap.get('num') not in pit_sc]
    cooldowns = cooldown_laps([(num, t) for num, t, _ in eligible],
                              session.get('session_type'), pit_sc)
    cons   = [(t, s) for num, t, s in eligible if num not in cooldowns]
    stints = {}
    for t, s in cons:
        stints.setdefault(s, []).append(t)
    cons_times = [t for t, _ in cons]

    band = 0
    if cons_times:
        cutoff = min(cons_times) * 1.01          # parser._PACE_BAND
        band = sum(1 for t in cons_times if t <= cutoff)

    full = [lap for lap in clean
            if lap.get('s1') is not None and lap.get('s2') is not None
            and lap.get('s3') is not None]
    theo = None
    if len(full) >= 2:
        theo = (min(lap['s1'] for lap in full) + min(lap['s2'] for lap in full)
                + min(lap['s3'] for lap in full))

    # All three session-best sectors on one clean lap (matches
    # parser._scan_facts: 3+ full laps or it is trivially true).
    perfect = 0
    if len(full) >= 3:
        eps = 0.0005
        m1 = min(lap['s1'] for lap in full)
        m2 = min(lap['s2'] for lap in full)
        m3 = min(lap['s3'] for lap in full)
        perfect = int(any(lap['s1'] <= m1 + eps and lap['s2'] <= m2 + eps
                          and lap['s3'] <= m3 + eps for lap in full))

    # Grid slot — same G-row source as pace.net_positions.
    driver = (session.get('driver_name') or '').strip().lower()
    start_position = None
    if driver:
        for g in session.get('grid') or []:
            if (g.get('name') or '').strip().lower() == driver:
                try:
                    start_position = int((g.get('position') or '').strip())
                except (ValueError, AttributeError):
                    pass
                break

    streak = best_streak = 0
    for lap in timed:
        clean_lap = lap.get('valid', True) and not lap.get('rewinds', 0)
        streak = streak + 1 if clean_lap else 0
        best_streak = max(best_streak, streak)

    # Pre-v0.1.133 files log spurious rewinds around pit stops — treat the
    # count as unknown so Mistakes renormalises away (matches scan_session).
    # Reconciled with rewind EVENTS: a flashback on a lap whose L row was
    # never logged (e.g. a race's final lap) is invisible to the per-lap
    # column but must still count — grading and coaching have to agree.
    rewind_count = None
    if session.get('rewinds_reliable', True):
        rewind_count = max(sum(lap.get('rewinds', 0) for lap in timed),
                           sum(1 for e in session.get('events') or []
                               if e.get('type') == 'rewind'))

    return {
        'game':            session.get('game'),
        'session_type':    session.get('session_type'),
        'session_subtype': session.get('session_subtype') or '',
        'lap_count':       len(timed),
        'valid_lap_count': len(valid),
        'clean_lap_count': len(clean),
        'clean_std_dev':   stint_std_dev(stints.values()),
        'theo_time':       theo,
        'rewind_count':    rewind_count,
        'collision_count': sum(1 for e in session.get('events') or []
                               if e.get('type') == 'collision'),
        'penalty_count':   sum(1 for e in session.get('events') or []
                               if e.get('type') == 'penalty'),
        'clean_streak':    best_streak,
        'cons_lap_count':  len(cons_times),
        'cons_band_count': band,
        'perfect_lap':     perfect,
        'start_position':  start_position,
        'position':        session.get('position'),
        'best_lap_time':   min((lap['time'] for lap in clean), default=None),
    }


def prior_bests(records):
    """
    Bulk prior-PB lookup for grading a whole session list in one pass.

    records — session_db-shaped dicts (date as datetime|None).
    Returns {filename: prior_best | None}: for each session, the best
    clean lap across strictly earlier sessions at the same game / car
    class / track / session type. Sessions missing any combo key are
    absent from the result (no history is knowable for them).
    """
    groups = {}
    for r in records:
        key = (r.get('game'), r.get('car_class'), r.get('track'),
               r.get('session_type'))
        if all(key):
            groups.setdefault(key, []).append(r)

    out = {}
    for recs in groups.values():
        recs = sorted(recs, key=_chrono_key)
        best = None
        for r in recs:
            out[r['filename']] = best
            t = r.get('best_lap_time')
            if t is not None and (best is None or t < best):
                best = t
    return out


def _pace_trend_rows(records, cfg):
    """Combo-history rows fit to measure PACE over time, oldest → newest.

    Two guards, both median-relative so they are track-length
    independent and robust to the outliers themselves:
      - plausibility (trend_outlier_ratio): best lap outside
        [median/ratio, median*ratio] is a corrupt row, dropped;
      - incidents (trend_incident_rate): a session that incident-heavy
        (contacts + penalties + rewinds per timed lap) whose best is
        ALSO off the typical pace (> median × 1%) measured the
        incidents, not the pace — dropped so it can't read as decline.
        An incident-heavy session with a representative best stays
        (real pace evidence), and a clean slow session stays (real
        decline).
    """
    timed = sorted((r for r in records if r.get('best_lap_time') is not None),
                   key=_chrono_key)
    ratio = cfg['trend_outlier_ratio']
    if timed and ratio and ratio > 1:
        med   = median(r['best_lap_time'] for r in timed)
        timed = [r for r in timed
                 if med / ratio <= r['best_lap_time'] <= med * ratio]
    max_rate = cfg['trend_incident_rate']
    if timed and max_rate and max_rate > 0:
        med  = median(r['best_lap_time'] for r in timed)
        kept = []
        for r in timed:
            laps = r.get('lap_count')
            incidents = ((r.get('collision_count') or 0)
                         + (r.get('penalty_count') or 0)
                         + (r.get('rewind_count') or 0))
            compromised = (laps and incidents / laps >= max_rate
                           and r['best_lap_time'] > med * 1.01)
            if not compromised:
                kept.append(r)
        timed = kept
    return timed


def trend(records):
    """
    Direction of travel across the most recent comparable sessions —
    answers "am I actually getting better?".

    records — session_db-shaped dicts for ONE game/car class/track/
    session type combo (session_db.combo_history()). The newest
    trend_sessions with a best clean lap form the window; each session's
    gap to the personal best across the given history is compared
    between the window's older and newer halves. Rows unfit to measure
    pace are dropped first (_pace_trend_rows): implausible best laps
    (corrupt index rows — a "+94s" gap must never appear) and
    incident-compromised sessions whose slow best measured the crashes,
    not the driver.

    Returns None with fewer than 3 such sessions, else:
      direction 'improving' | 'stable' | 'declining'
      arrow     '↗' | '→' | '↘'
      gaps      [(date, gap_seconds), ...] oldest → newest, the window
    """
    cfg = config()
    timed = _pace_trend_rows(records, cfg)
    if len(timed) < 3:
        return None
    pb     = min(r['best_lap_time'] for r in timed)
    window = timed[-cfg['trend_sessions']:]
    gaps   = [r['best_lap_time'] - pb for r in window]

    half   = len(gaps) // 2
    older  = gaps[:half]
    newer  = gaps[len(gaps) - half:]
    shift  = (sum(newer) / half) - (sum(older) / half)
    if shift <= -cfg['trend_threshold']:
        direction, arrow = 'improving', '↗'
    elif shift >= cfg['trend_threshold']:
        direction, arrow = 'declining', '↘'
    else:
        direction, arrow = 'stable', '→'

    return {'direction': direction, 'arrow': arrow,
            'gaps': [(r.get('date'), g) for r, g in zip(window, gaps)]}


def driver_profile(records):
    """
    Repeatable performance at one combo — "who the driver is today",
    not their once-in-a-lifetime lap. A PB of 1:31.6 with every other
    session at 1:34 is not the driver's pace; the typical range is.

    records — session_db.combo_history() rows for one combo.
    Returns None only when no session carries a best clean lap. Always
    present: pb, avg_best, sessions. Fields needing more history are
    None below their minimums (show what the data supports, hide the
    rest):
      typical      (lo, hi) interquartile range of session bests — the
                   band the driver's best laps normally land in; needs
                   3+ sessions
      avg_std      mean clean-lap std dev across sessions | None
      stars        1–5 consistency rating from avg_std (thresholds in
                   repeatability_stars config); needs 3+ sessions with
                   std data
      on_pace_pct  fast-lap repeatability: % of consistency-eligible
                   laps within 1% of their session's best — how often
                   the driver actually hits their pace, the coach's
                   straggler-vs-solid signal; needs 10+ such laps
      baseline     {'from', 'to', 'shift', 'direction', 'arrow'} —
                   movement of the typical pace itself: average session
                   best over the older vs newer half of the last
                   trend_sessions bests, guarded like trend()
                   (_pace_trend_rows — corrupt or incident-compromised
                   bests don't move the baseline). PBs rarely move; the
                   baseline should. None below 3 sessions.
      confidence   {'stars', 'sessions', 'clean_laps'} — how stable the
                   profile is: the weaker of the session-count and
                   clean-lap-count ratings (profile_confidence config).
                   A 4-session profile is useful; a 50-session one is
                   representative. Always present.
    """
    timed = [r for r in records if r.get('best_lap_time') is not None]
    if not timed:
        return None
    bests = sorted(r['best_lap_time'] for r in timed)

    typical = None
    if len(bests) >= 3:
        q1, _, q3 = quantiles(bests, n=4, method='inclusive')
        typical = (q1, q3)

    stds = [r['clean_std_dev'] for r in timed
            if r.get('clean_std_dev') is not None]
    avg_std = sum(stds) / len(stds) if stds else None
    stars = None
    if avg_std is not None and len(stds) >= 3:
        stars = 1
        for threshold, s in config()['repeatability_stars']:
            if avg_std <= threshold:
                stars = int(s)
                break

    cons_total = sum(r.get('cons_lap_count') or 0 for r in timed)
    band_total = sum(r.get('cons_band_count') or 0 for r in timed)
    on_pace = (100.0 * band_total / cons_total
               if cons_total >= 10 else None)

    # Baseline movement: older vs newer half of the recent session bests.
    # Same row guards as trend(): a corrupt or incident-compromised best
    # must not move the typical-pace baseline either.
    baseline = None
    cfg = config()
    window = [r['best_lap_time'] for r in _pace_trend_rows(timed, cfg)]
    window = window[-cfg['trend_sessions']:]
    if len(window) >= 3:
        half  = len(window) // 2
        older = sum(window[:half]) / half
        newer = sum(window[-half:]) / half
        shift = newer - older
        if shift <= -cfg['trend_threshold']:
            direction, arrow = 'improving', '↗'
        elif shift >= cfg['trend_threshold']:
            direction, arrow = 'declining', '↘'
        else:
            direction, arrow = 'stable', '→'
        baseline = {'from': older, 'to': newer, 'shift': shift,
                    'direction': direction, 'arrow': arrow}

    # Confidence — the weaker of the two sample-size ratings.
    def _conf_stars(anchors, count):
        for max_count, s in anchors:
            if count <= max_count:
                return int(s)
        return 5

    clean_total = sum(r.get('clean_lap_count') or 0 for r in timed)
    conf_cfg = cfg['profile_confidence']
    confidence = {
        'stars': min(_conf_stars(conf_cfg['sessions'], len(timed)),
                     _conf_stars(conf_cfg['clean_laps'], clean_total)),
        'sessions': len(timed),
        'clean_laps': clean_total,
    }

    return {'pb': bests[0], 'avg_best': sum(bests) / len(bests),
            'sessions': len(timed), 'typical': typical,
            'avg_std': avg_std, 'stars': stars, 'on_pace_pct': on_pace,
            'baseline': baseline, 'confidence': confidence}


def stars_text(stars):
    """3 → '★★★☆☆'; '' for None."""
    if not stars:
        return ''
    return '★' * stars + '☆' * (5 - stars)


def milestones(record, prior_records):
    """
    Personal milestones this session set against everything before it
    at the same combo — progress rewards that aren't just outright
    speed. record / prior_records — session_db-shaped rows (the priors
    from combo_history(), minus the session itself).

    Returns [{'icon', 'title', 'detail'}, ...]; empty when nothing was
    beaten or there is no history to beat (a first session sets no
    milestones — there's nothing to improve on).
    """
    out = []
    if not prior_records:
        return out

    best = record.get('best_lap_time')
    prior_bests = [r['best_lap_time'] for r in prior_records
                   if r.get('best_lap_time') is not None]
    new_pb = bool(best is not None and prior_bests and best < min(prior_bests))
    if new_pb:
        out.append({'icon': '🏆', 'title': 'New personal best',
                    'detail': (f"{format_lap_time(best)} — improved by "
                               f"{min(prior_bests) - best:.3f}s")})
    else:
        # Sector records only when the PB didn't fall — a PB lap sets
        # sector records trivially and would drown its own headline.
        for key, name in (('best_s1', 'S1'), ('best_s2', 'S2'),
                          ('best_s3', 'S3')):
            v = record.get(key)
            prior = [r[key] for r in prior_records if r.get(key) is not None]
            if v is not None and prior and v < min(prior):
                out.append({'icon': '⭐', 'title': f'Best {name} on record',
                            'detail': format_sector_time(v)})

    streak = record.get('clean_streak')
    if (streak and streak >= 3
            and streak > max((r.get('clean_streak') or 0
                              for r in prior_records), default=0)):
        out.append({'icon': '🔥', 'title': 'Longest clean streak',
                    'detail': f"{streak} clean laps in a row"})

    def _invalid_frac(r):
        lc, vc = r.get('lap_count'), r.get('valid_lap_count')
        return (lc - vc) / lc if lc and vc is not None else None

    frac = _invalid_frac(record)
    if frac is not None and frac < 0.10 and (record.get('lap_count') or 0) >= 5:
        prior_fracs = [f for f in map(_invalid_frac, prior_records)
                       if f is not None]
        if prior_fracs and all(f >= 0.10 for f in prior_fracs):
            out.append({'icon': '🎯',
                        'title': 'First session with under 10% invalid laps',
                        'detail': (f"{record['valid_lap_count']} of "
                                   f"{record['lap_count']} laps valid")})

    # First A-grade execution. Graded without a prior-PB baseline so
    # every session is measured the same way (the PB-comparison pillar
    # simply drops out and the weights renormalise).
    def _execution(r):
        g = grade(r)
        return g.get('execution') if g else None

    ex = _execution(record)
    if ex and ex['letter'].startswith('A'):
        prior_ex = (e for e in map(_execution, prior_records) if e)
        if not any(e['letter'].startswith('A') for e in prior_ex):
            # No score/letter in the detail: this comparison is graded
            # without the PB pillar, so quoting its number would clash
            # with the session's displayed grade.
            out.append({'icon': '🏅', 'title': 'First A-range execution',
                        'detail': 'execution grade A- or better'})
    return out


def latest_milestone(records):
    """
    The most recent session (across every combo) that set a milestone —
    for the connect screen's "latest milestone" line.
    records — session_db.all_sessions().
    Returns (record, milestones) or None.
    """
    groups = {}
    for r in records:
        key = (r.get('game'), r.get('car_class'), r.get('track'),
               r.get('session_type'))
        if all(key):
            groups.setdefault(key, []).append(r)

    newest = None
    for recs in groups.values():
        recs = sorted(recs, key=_chrono_key)
        for i, r in enumerate(recs):
            ms = milestones(r, recs[:i])
            if ms and (newest is None
                       or _chrono_key(r) > _chrono_key(newest[0])):
                newest = (r, ms)
    return newest


def letter(score):
    """Score 0–100 → 'A+' … 'F'. Thirds within each ten-point band."""
    if score < 60:
        return 'F'
    for floor, base in ((90, 'A'), (80, 'B'), (70, 'C'), (60, 'D')):
        if score >= floor:
            third = (score - floor) / (10.0 / 3)
            return base + ('-' if third < 1 else '' if third < 2 else '+')
    return 'F'


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _interp(curve, x):
    """Piecewise-linear lookup, clamped to the curve's end scores."""
    if x <= curve[0][0]:
        return float(curve[0][1])
    for (x0, y0), (x1, y1) in zip(curve, curve[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return float(curve[-1][1])


def _chrono_key(record):
    date = record.get('date')
    return (date.isoformat() if date is not None else '',
            record.get('filename') or '')


def _overall_cap(caps, invalid_frac):
    """First [max_invalid_frac, max_score] row the session fits under."""
    for threshold, cap in caps:
        if invalid_frac <= threshold:
            return cap
    return caps[-1][1]


def _explanation(raw, execution, cleanliness, lap_count, valid_count, std,
                 gap, pb_delta, rewinds, low_confidence=False,
                 is_race=False, pace_kind=None, collisions=0, penalties=0):
    """Coaching-style summary, still evidence-only: a headline mirroring
    the grade split ("Strong execution, but poor lap completion."), then
    an evidence sentence — positives first, negatives after a "yet" —
    built from what the data shows. Race sessions swap the lap-
    completion story for race discipline (incidents), and the pace
    reference follows pace_kind (theoretical vs prior best race lap)."""
    pace_s  = raw['pace'][0] if 'pace' in raw else None
    cons_s  = raw['consistency'][0] if 'consistency' in raw else None
    exec_s  = execution['score'] if execution else None
    clean_s = cleanliness['score'] if cleanliness else None

    # Pillars that are weak on solid evidence — a low-confidence
    # consistency sample doesn't count against the headline.
    confident_weak = [k for k, (s, _) in raw.items()
                      if s < 75 and not (k == 'consistency' and low_confidence)]

    parts = []
    if pb_delta is not None and pb_delta < 0:
        parts.append("New best race lap." if is_race
                     else "New personal best.")

    # Headline — mirrors Execution vs the secondary grade. Below the
    # "reasonable" band, name the pillars that held it back instead of
    # comparing to a "usual level" the data doesn't establish.
    right = None
    if clean_s is not None:
        if is_race:
            if clean_s >= 90:   right = "clean race discipline"
            elif clean_s >= 75: right = "a few incidents"
            elif clean_s >= 60: right = "poor race discipline"
            else:               right = "very poor race discipline"
        else:
            if clean_s >= 90:   right = "clean lap completion"
            elif clean_s >= 75: right = "a few invalid laps"
            elif clean_s >= 60: right = "poor lap completion"
            else:               right = "very poor lap completion"
    if exec_s is not None and exec_s < 70 and confident_weak:
        weak_names = {'pace': 'pace execution', 'consistency': 'consistency',
                      'improvement': 'PB comparison', 'mistakes': 'rewinds'}
        weak = [weak_names[k]
                for k, _ in sorted(raw.items(), key=lambda kv: kv[1][0])
                if k in confident_weak][:2]
        if clean_s is not None and clean_s < 75:
            weak = weak[:1] + (['race discipline'] if is_race
                               else ['lap completion'])
        parts.append("Execution was limited primarily by "
                     + " and ".join(weak) + ".")
    else:
        left = left_good = None
        if exec_s is not None and exec_s >= 93:
            left, left_good = "Excellent execution", True
        elif exec_s is not None and exec_s >= 85:
            left, left_good = "Strong execution", True
        elif (pace_s is not None and pace_s >= 85 and not confident_weak):
            # Execution dragged down only by thin/low-confidence data —
            # say what the numbers actually support: the pace was there.
            left, left_good = "Strong pace", True
        elif exec_s is not None:
            left, left_good = "Reasonable execution", False
        if left and right:
            # ", but" only when the two sides genuinely contrast.
            contrast = left_good != (clean_s >= 90)
            parts.append(f"{left}{', but ' if contrast else ' with '}{right}.")
        elif left or right:
            parts.append((left or right.capitalize()) + ".")

    # Evidence: positives, "yet", negatives.
    positives = []
    negatives = []
    pace_ref = ("your best race lap here" if pace_kind == 'race'
                else "your theoretical best")
    if gap is not None:
        if gap < 0.005:
            positives.append(f"level with {pace_ref}")
        elif gap <= 0.35:
            positives.append(f"within {gap:.3f}s of {pace_ref}")
        else:
            negatives.append(f"your fastest clean lap was +{gap:.3f}s off "
                             f"{pace_ref}")
    if not is_race and pb_delta is not None and pb_delta > 0:
        if pb_delta <= 0.35:
            positives.append(f"within {pb_delta:.3f}s of your personal best")
        else:
            negatives.append(f"+{pb_delta:.3f}s off your personal best")
    if cons_s is not None and cons_s < 85 and std is not None:
        negatives.append(f"clean-lap times varied by {std:.2f}s")
    if rewinds:
        negatives.append(f"{_num_word(rewinds)} rewind"
                         f"{'s were' if rewinds != 1 else ' was'} used")
    if is_race:
        # Races: incidents are the completion story, not invalid laps.
        incident_bits = []
        if collisions:
            incident_bits.append(f"{_num_word(collisions)} contact"
                                 f"{'s' if collisions != 1 else ''}")
        if penalties:
            incident_bits.append(f"{_num_word(penalties)} penalt"
                                 f"{'ies' if penalties != 1 else 'y'}")
        if incident_bits:
            negatives.append(" and ".join(incident_bits)
                             + (" were recorded" if collisions + penalties > 1
                                else " was recorded"))
    else:
        n_invalid = (lap_count - valid_count) if valid_count is not None else 0
        if n_invalid:
            frac = n_invalid / lap_count
            amount = ("more than half of your laps" if frac > 0.5
                      else f"{n_invalid} of {lap_count} laps")
            clause = f"{amount} were invalidated"
            if pace_s is not None and pace_s >= 85 and frac >= 0.25:
                clause += (" before that speed could be converted into "
                           "consistent clean laps")
            negatives.append(clause)

    if positives and negatives:
        # When the speed was there but execution/completion let it down,
        # lead with the pace so the sentence mirrors the coaching story.
        strong_pace = (pace_s is not None and pace_s >= 85
                       and ((exec_s is not None and exec_s < 85)
                            or (clean_s is not None and clean_s < 75)))
        lead = ("Your pace remained strong, finishing " if strong_pace
                else "You finished ")
        parts.append(f"{lead}{' and '.join(positives)}, "
                     f"yet {' and '.join(negatives[:2])}.")
    elif negatives:
        sentence = " and ".join(negatives[:2])
        parts.append(sentence[0].upper() + sentence[1:] + ".")
    elif positives:
        parts.append(f"You finished {' and '.join(positives)}. "
                     "No significant deductions.")
    else:
        parts.append("No significant deductions — a well-executed session.")

    return " ".join(parts)


def _focus(raw, cleanliness, invalid_frac, valid_count, std, theo, rewinds,
           is_race=False, incident_rate=None, pace_kind=None,
           prior_best=None):
    """One achievable objective for the next session — a fixed priority
    ladder so the app always names the single biggest opportunity:
    completion first (incident rate for races, invalid laps otherwise),
    then pace conversion, then consistency, then rewinds. Deliberately
    never "find more lap time"."""
    def _streak_target():
        return max(3, min((valid_count or 0) + 2, 10))

    if is_race:
        if incident_rate is not None and incident_rate > 0.30:
            return ("Bring contacts and flashbacks down — aim for a "
                    "zero-incident race.")
    elif invalid_frac is not None and invalid_frac > 0.40:
        return (f"Complete {_num_word(_streak_target())} consecutive "
                "clean laps.")
    if 'pace' in raw and raw['pace'][0] < 90:
        if pace_kind == 'race' and prior_best is not None:
            return ("Close the gap to your best race lap here — "
                    f"{format_lap_time(prior_best)}.")
        if pace_kind == 'theoretical' and theo is not None:
            return ("Combine your best sectors in one lap — "
                    f"{format_lap_time(theo)} is already in your data.")
    if 'consistency' in raw and raw['consistency'][0] < 85 and std:
        spread = max(0.3, round(std * 0.75, 1))
        return f"Bring your clean-lap spread under {spread:.1f}s."
    if rewinds and rewinds >= 3:
        return "Finish every lap without using a rewind."
    if cleanliness is not None and cleanliness['score'] < 90:
        if is_race:
            return "Keep it clean — aim for a zero-incident race."
        return (f"Complete {_num_word(_streak_target())} consecutive "
                "clean laps.")
    return "Repeat this level of execution over a longer run."


_NUM_WORDS = ('zero', 'one', 'two', 'three', 'four', 'five', 'six',
              'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve')


def _num_word(n):
    return _NUM_WORDS[n] if 0 <= n < len(_NUM_WORDS) else str(n)
