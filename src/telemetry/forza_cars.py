"""Shared Forza car ordinal lookup.

Loaded lazily on first call so the CSV is never read when a non-Forza
game is selected.  Both fh6.py and fm.py call load_forza_cars() in their
connect() method.

The CSV lives alongside this file: telemetry/forza_cars.csv
Columns: ordinal, slug, make, model, year
  - ordinal : CarOrdinal from telemetry (FH5/FH6/FM8 ordinals)
  - slug    : dashboard car_class name (e.g. "delorean"); empty = no custom dash
  - make/model/year : human-readable identity; used for car_name in TelemetryData
"""
import csv
import os
from typing import NamedTuple

_PATH = os.path.join(os.path.dirname(__file__), 'forza_cars.csv')


class ForzaCar(NamedTuple):
    slug: str   # empty string if no custom dashboard
    name: str   # "Year Make Model" display string


def load_forza_cars() -> dict[int, ForzaCar]:
    """Return ordinal → ForzaCar for every row in the CSV."""
    result: dict[int, ForzaCar] = {}
    with open(_PATH, newline='') as f:
        for row in csv.DictReader(f):
            ordinal = int(row['ordinal'])
            name = f"{row['year']} {row['make']} {row['model']}"
            result[ordinal] = ForzaCar(slug=row['slug'], name=name)
    return result
