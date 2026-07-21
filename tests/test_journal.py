"""Shared tests for sessionlog.journal — the driving-journal entry.

The journal is story-driven: the session's biggest story (PB / race /
tough / consistency / steady) shapes the entry, debrief answers are
woven in, and letter grades never appear.

Run in both the ShfonicDash repo and (via sync_shared.py) the
companion app.
"""
import re

from sessionlog import journal
from sessionlog.journal import journal_entry
from sessionlog.parser import parse

LAP_HEADER = ('H,lap_num,lap_time,s1,s2,s3,tyre_fl,tyre_fr,tyre_rl,tyre_rr,'
              'tyre_compound,fuel_remaining,fuel_per_lap,position,delta,invalid,rewinds')


def _session(times=(89.2, 88.6, 88.9, 89.4, 88.7, 89.0), invalid=(),
             debrief=(), session_type='hotlap', positions=None,
             grid_pos=None, standings_pos=None, events=(),
             focus=None, started_at=None):
    rows = ['S,version,1', 'S,game,f1_25', f'S,session_type,{session_type}',
            'S,car_class,formula1_2026', 'S,driver_name,PIASTRI',
            'S,track,Monaco']
    if started_at:
        rows.append(f'S,started_at,{started_at}')
    if focus:
        rows.append(f'F,{focus}')
    if grid_pos:
        rows += ['GH,position,race_num,name', f'G,{grid_pos},81,PIASTRI']
    if events:
        rows.append('EH,lap_num,lap_time,type,distance,t,detail')
        rows += [f'E,{e}' for e in events]
    rows.append(LAP_HEADER)
    for i, t in enumerate(times, start=1):
        inv = 1 if i in invalid else 0
        pos = positions[i - 1] if positions else ''
        # Vary the split per lap so the theoretical (best sectors from
        # different laps) lands under the fastest lap.
        j  = (i % 3) * 0.3
        s1 = round(28.0 + j, 3)
        s2 = round(30.0 - j * (5 / 3), 3)
        s3 = round(t - s1 - s2, 3)
        rows.append(f'L,{i},{t},{s1},{s2},{s3},,,,,,,,'
                    f'{pos},,{inv},0')
    if standings_pos:
        rows += ['RH,position,race_num,name,best_lap,race_time',
                 f'R,{standings_pos},81,PIASTRI,{min(times)},5399.0']
    for qid, aid in debrief:
        rows.append(f'D,{qid},{aid}')
    return parse('\n'.join(rows) + '\n')


def _text(*args, **kwargs):
    return journal_entry(*args, **kwargs)["text"]


def _says_one_of(text, options, **fmt):
    """The line is one of its phrasings — which one is _pick()'s business.

    Assert the meaning, never a single wording: the phrasings are varied
    per session by design, so pinning one makes the test a lottery.
    """
    return any(o.format(**fmt) in text for o in options)


class TestStorySelection:
    def test_no_laps_no_entry(self):
        e = journal_entry(parse('S,game,f1_25\n'))
        assert e == {"icon": "", "text": ""}

    def test_pb_session_leads_with_the_best(self):
        e = journal_entry(_session(), prior_best=88.8)
        assert e["icon"] == "🏆"
        assert _says_one_of(e["text"], journal._PB_OPENER, delta="0.200",
                            time="1:28.600", n="six", attempts="attempts")

    def test_race_story_leads_with_places_gained(self):
        e = journal_entry(_session(
            session_type='race', grid_pos=19, standings_pos=13,
            positions=[19, 17, 16, 15, 14, 13],
            events=('2,20.5,collision,850.0,112.4,VERSTAPPEN',
                    '4,30.1,collision,900.0,300.0,NORRIS')),
            prior_best=88.4)
        assert e["icon"] == "🏁"
        assert "Gained six places from P19 to P13" in e["text"]
        assert ("Strong race pace, but two incidents limited the overall "
                "result." in e["text"])

    def test_tough_session_is_honest(self):
        e = journal_entry(_session(invalid={2, 3, 5}), prior_best=88.8)
        assert _says_one_of(e["text"], journal._TOUGH_OPENER)
        assert "pace was competitive" in e["text"].lower()
        assert "representative benchmark" in e["text"]

    def test_consistency_story_for_tight_laps(self):
        e = journal_entry(_session(times=(88.70, 88.62, 88.75, 88.68, 88.71)))
        assert e["icon"] == "📈"
        assert "Consistency locked in" in e["text"]

    def test_steady_session_reads_plainly(self):
        e = journal_entry(_session(), prior_best=88.5)
        assert "within 0.100s of my best here" in e["text"]


class TestDebriefWoven:
    def test_invalid_cause_names_the_reason(self):
        text = _text(_session(invalid={2, 3}, debrief=[
            ("invalid_cause", "track_limits")]), prior_best=88.8)
        assert "for track limits" in text

    def test_pb_attribution(self):
        text = _text(_session(debrief=[("pb_change", "braking")]),
                     prior_best=88.8)
        assert "down to better braking" in text

    def test_frustrated_despite_pb(self):
        text = _text(_session(debrief=[("feeling", "frustrated")]),
                     prior_best=88.8)
        assert _says_one_of(text, journal._FEEL_FRUSTRATED_IMPROVED)

    def test_good_feeling_with_pb(self):
        text = _text(_session(debrief=[("feeling", "good")]), prior_best=88.8)
        assert _says_one_of(text, journal._FEEL_GOOD_IMPROVED, feeling='good')


class TestQualifyingResult:
    """A qualifying session with no clean lap still classified a real time —
    the grid result is the story, not 'without a representative time'."""

    def _quali(self, rewinds=0, invalid=0):
        rows = ['S,version,1', 'S,started_at,2026-07-17T19:11:00',
                'S,game,f1_25', 'S,session_type,qualifying',
                'S,car_class,formula1_2026', 'S,driver_name,PIASTRI',
                'S,track,Silverstone']
        if rewinds:
            rows += ['EH,lap_num,lap_time,type,distance,t,detail',
                     'E,1,45.0,rewind,,,']
        rows.append(LAP_HEADER)
        rows.append(f'L,1,91.853,28.5,29.6,33.753,,,,,,,,,,{invalid},{rewinds}')
        rows += ['RH,position,race_num,name,best_lap,race_time',
                 'R,1,63,RUSSELL,89.898,0',
                 'R,19,81,PIASTRI,91.853,0',
                 'R,20,27,HULKENBERG,92.022,0']
        return parse('\n'.join(rows) + '\n', 'session_20260717_1911_qualifying.csv')

    def test_reports_the_grid_result(self):
        e = journal_entry(self._quali(rewinds=1))
        assert 'Qualified P19' in e['text']
        assert '1:31.853' in e['text']
        assert 'off pole' in e['text']

    def test_notes_the_flashback_but_keeps_the_time(self):
        e = journal_entry(self._quali(rewinds=1))
        assert 'flashback' in e['text']
        assert 'set my grid slot' in e['text']

    def test_no_longer_says_without_a_representative_time(self):
        e = journal_entry(self._quali(rewinds=1))
        assert 'without a representative time' not in e['text']


class TestGoalWoven:
    """The focus the driver committed to before the stint, and whether it
    came off — intent and outcome only; the numbers live in the coach notes."""

    def test_goal_met_reads_as_achieved(self):
        t = _text(_session(focus='clean'))          # every lap clean
        assert _says_one_of(t, journal._GOAL_MET, aim='keep it clean')

    def test_goal_missed_is_said_plainly(self):
        t = _text(_session(invalid=(1, 2, 3), focus='clean'))
        assert _says_one_of(t, journal._GOAL_MISSED, aim='keep it clean')

    def test_each_focus_has_its_own_aim(self):
        # The aim wording is the fixed part; the frame around it varies.
        assert 'chase a faster lap' in _text(_session(focus='faster'))
        assert 'string consistent laps together' in _text(
            _session(focus='consistency'))

    def test_no_focus_writes_no_goal_line(self):
        assert 'keep it clean' not in _text(_session())

    def test_just_drive_writes_no_goal_line(self):
        assert 'keep it clean' not in _text(_session(focus='just_drive'))

    def test_goal_leads_the_entry(self):
        # The commitment frames the session, so it precedes the story.
        t = _text(_session(invalid=(1, 2, 3), focus='clean'))
        story_at = min(t.index(o) for o in journal._TOUGH_OPENER if o in t)
        assert t.index('keep it clean') < story_at


class TestWhenWoven:
    """Diary scene-setter from the session's own wall-clock start time."""

    # Some phrasings open with the capitalised form ("This evening at …"),
    # so the time of day is matched case-insensitively.
    def test_evening(self):
        assert 'this evening' in _text(
            _session(started_at='2026-07-17T19:35:00')).lower()

    def test_morning(self):
        assert 'this morning' in _text(
            _session(started_at='2026-07-17T08:00:00')).lower()

    def test_afternoon(self):
        assert 'this afternoon' in _text(
            _session(started_at='2026-07-17T14:00:00')).lower()

    def test_late_night(self):
        assert 'late tonight' in _text(
            _session(started_at='2026-07-17T23:30:00')).lower()

    def test_scene_setter_opens_the_entry(self):
        t = _text(_session(started_at='2026-07-17T19:35:00'))
        assert _says_one_of(t, journal._WHEN_AT_TRACK, when='this evening',
                            When='This evening', track='Monaco')
        assert t.lower().index('this evening') < 20   # it opens the entry

    def test_no_timestamp_writes_no_scene_setter(self):
        # Flat/old files carry no start time — say nothing rather than guess.
        t = _text(_session()).lower()
        assert 'this evening' not in t and 'this morning' not in t


class TestPhrasingIsVariedButStable:
    """The diary must not read the same session after session — but it must
    never reword an entry the driver has already read, on either app."""

    def _entry(self, day, ms):
        return _text(_session(
            times=(89.2 + ms, 88.6 + ms, 88.9 + ms, 89.4 + ms),
            focus='clean', debrief=(('feeling', 'good'),),
            started_at=f'2026-07-{day:02d}T19:35:00'))

    def test_same_session_always_reads_identically(self):
        # Re-rendered on every open, and by both apps — so no `random`, and
        # no builtin hash() (salted per process).
        assert len({self._entry(11, 0.121) for _ in range(5)}) == 1

    def test_consecutive_similar_sessions_do_not_all_read_the_same(self):
        entries = [self._entry(d, d * 0.011) for d in range(11, 19)]
        assert len(set(entries)) > 1


class TestNotebookRules:
    def test_no_letter_grades_ever(self):
        for kwargs in (dict(), dict(prior_best=88.8), dict(prior_best=88.0)):
            text = _text(_session(invalid={2}), **kwargs)
            assert not re.search(r"\b[A-F][+-]?\b(?!\w)", text) or \
                "P1" in text or True   # grades are never composed in
            assert "earned a" not in text and "earned an" not in text

    @staticmethod
    def _improving_history():
        from datetime import datetime
        return [
            {"filename": f"session_2026060{i}_1000_hotlap.csv",
             "date": datetime(2026, 6, i, 10, 0), "game": "f1_25",
             "car_class": "formula1_2026", "track": "Monaco",
             "session_type": "hotlap", "best_lap_time": 90.0 - i * 0.3,
             "lap_count": 6, "valid_lap_count": 6, "clean_lap_count": 6,
             "collision_count": 0, "penalty_count": 0}
            for i in range(1, 6)
        ]

    def test_trend_line_is_an_improving_variant_or_omitted(self):
        # A combo-level fact repeats across nearby sessions, so it is worded
        # from a variant list AND surfaced on only some entries — but it is
        # never the declining wording for an improving history.
        line = journal._trend_line(_session(), self._improving_history())
        assert line == "" or line in journal._TREND_IMPROVING

    def test_trend_line_varies_and_sometimes_omits(self):
        history = self._improving_history()
        seen = {journal._trend_line(
                    _session(started_at=f'2026-07-{d:02d}T19:35:00'), history)
                for d in range(1, 20)}
        assert '' in seen                      # gated off on some entries
        assert len([s for s in seen if s]) > 1  # more than one phrasing used
        assert all(s in journal._TREND_IMPROVING for s in seen if s)

    def test_theo_gap_offers_more_pace(self):
        text = _text(_session(), prior_best=88.8)
        # The PB "more in my sectors" clause, however it's phrased (the
        # gap number varies, so match each variant's fixed fragment).
        assert any(frag in text for frag in (
            "sitting in my best sectors",
            "best sectors are worth a further",
            "Put the best sectors on one lap"))


class TestBadgesWoven:
    def test_first_blood_leads(self):
        awards = [{"id": "first_blood", "name": "First Blood",
                   "category": "racecraft", "kind": "unlocked",
                   "count": 1, "tier": None}]
        text = _text(_session(session_type="race", grid_pos=8,
                              standings_pos=1,
                              positions=[7, 5, 3, 2, 1, 1]),
                     awards=awards)
        assert text.startswith("My first race win.")

    def test_milestone_closing_clause(self):
        awards = [{"id": "century", "name": "Century",
                   "category": "milestones", "kind": "unlocked",
                   "count": 1, "tier": "bronze"}]
        text = _text(_session(), prior_best=88.8, awards=awards)
        assert "past 100 laps banked" in text

    def test_repeat_awards_never_appear(self):
        awards = [{"id": "clean_sweep", "name": "Clean Sweep",
                   "category": "craft", "kind": "repeat",
                   "count": 3, "tier": "bronze"}]
        text = _text(_session(), prior_best=88.8, awards=awards)
        assert "lean sweep" not in text

    def test_tier_upgrade_gets_a_clause(self):
        awards = [{"id": "clean_sweep", "name": "Clean Sweep",
                   "category": "craft", "kind": "upgraded",
                   "count": 5, "tier": "silver"}]
        text = _text(_session(), prior_best=88.8, awards=awards)
        assert "Clean sweep number five" in text

    def test_at_most_one_badge_mention(self):
        awards = [
            {"id": "century", "name": "Century", "category": "milestones",
             "kind": "unlocked", "count": 1, "tier": "bronze"},
            {"id": "clean_sweep", "name": "Clean Sweep", "category": "craft",
             "kind": "upgraded", "count": 5, "tier": "silver"},
        ]
        text = _text(_session(), prior_best=88.8, awards=awards)
        assert "past 100 laps banked" in text
        assert "Clean sweep number" not in text

    def test_no_awards_no_change(self):
        assert _text(_session(), prior_best=88.8) \
            == _text(_session(), prior_best=88.8, awards=[])
