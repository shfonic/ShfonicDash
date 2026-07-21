"""Declared driver-identity vocabulary — the canonical option lists.

Experience / discipline / goal are self-described profile fields that both
apps let the driver set and that sync between them (Pi ↔ companion). The
option *values* and their display *labels* must agree everywhere, so they
live here — the shared, pure-stdlib home — rather than being copied into each
app's editor. The companion's ``driver.py`` and the Pi's web-companion editor
both read these; the Pi's profile browser uses the label helpers so a stored
value like ``pace`` renders as "Outright pace", not a title-cased "Pace".

Each list is ``(value, label[, description])``; ``value`` is what persists.
Pure standard library only — part of the shared ``sessionlog`` package.
"""

EXPERIENCE_LEVELS = [
    ('beginner',     'Beginner',
     'New to sim racing, still learning the basics.'),
    ('intermediate', 'Intermediate',
     'Comfortable on track, working on consistency and pace.'),
    ('experienced',  'Experienced',
     'Confident across cars and tracks, hunting tenths.'),
    ('veteran',      'Veteran',
     'Years of sim racing; leagues, ranked or competitive.'),
]

DISCIPLINES = [
    ('formula',   'Formula'),
    ('gt',        'GT'),
    ('prototype', 'Prototype'),
    ('road',      'Road / Street'),
    ('mixed',     'A bit of everything'),
]

GOALS = [
    ('consistency', 'Consistency'),
    ('pace',        'Outright pace'),
    ('racecraft',   'Race craft'),
    ('fun',         'Just for fun'),
]


def _label(options, value):
    for opt in options:
        if opt[0] == value:
            return opt[1]
    return ''


def experience_label(value):
    return _label(EXPERIENCE_LEVELS, value)


def discipline_label(value):
    return _label(DISCIPLINES, value)


def goal_label(value):
    return _label(GOALS, value)


def options(field):
    """(value, label) pairs for a field name ('experience'/'discipline'/'goal'),
    or [] for an unknown field — a UI-friendly view that drops descriptions."""
    src = {'experience': EXPERIENCE_LEVELS,
           'discipline': DISCIPLINES, 'goal': GOALS}.get(field, [])
    return [(o[0], o[1]) for o in src]


def label(field, value):
    """The display label for a stored value in a given field, or '' if unknown."""
    return _label({'experience': EXPERIENCE_LEVELS,
                   'discipline': DISCIPLINES, 'goal': GOALS}.get(field, []), value)
