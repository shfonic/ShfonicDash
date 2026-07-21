"""
Config-driven dashboard.

Reads a JSON file that lists which widgets to show and where, then
delegates update/render to those widgets.  No Python code needs to change
to create a new dashboard layout — just write a new JSON file.

JSON schema
-----------
.. code-block:: json

    {
        "name": "My Dashboard",
        "background": [14, 18, 16],
        "widgets": [
            {
                "type":   "GearWidget",
                "x":      8,
                "y":      64,
                "width":  190,
                "height": 220
            },
            {
                "type":   "SpeedWidget",
                "x":      206,
                "y":      64,
                "width":  180,
                "height": 150,
                "unit":   "mph"
            }
        ]
    }

Reserved keys inside each widget object:
    ``type``, ``x``, ``y``, ``width``, ``height``

Any additional keys are forwarded as keyword arguments to the widget
constructor, so widget-specific options (e.g. ``unit``, ``count``) live
naturally in the config.
"""

import json
import os

from dashboard.base import Dashboard
from dashboard.widgets.registry import REGISTRY


def find_config(name: str) -> str:
    """
    Resolve a dashboard name/path to an absolute config file path.

    Resolution order:
    1. Absolute path — used as-is.
    2. Relative path (contains ``/`` or ends with ``.json``) — resolved
       relative to the current working directory.
    3. Bare name — looked up as ``<name>.json`` inside the bundled
       ``configs/`` directory next to this file.

    Raises ``FileNotFoundError`` if nothing matches.
    """
    if os.path.isabs(name):
        path = name
    elif '/' in name or name.endswith('.json'):
        path = os.path.abspath(name)
    else:
        configs_dir = os.path.join(os.path.dirname(__file__), 'configs')
        path = os.path.join(configs_dir, f'{name}.json')

    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"Dashboard config not found: {path!r}\n"
            f"  (resolved from {name!r})"
        )
    return path


class ConfigDashboard(Dashboard):
    """A dashboard whose layout is fully defined by a JSON config file."""

    def __init__(self, config_path: str, width: int, height: int):
        super().__init__(width, height)
        from dashboard.widgets.design_system import BG
        self._bg      = BG
        self._widgets = []
        self._load(config_path)

    def _load(self, path: str) -> None:
        with open(path) as f:
            cfg = json.load(f)

        bg = cfg.get('background')
        if bg:
            self._bg = tuple(int(c) for c in bg)

        for entry in cfg.get('widgets', []):
            entry  = dict(entry)                      # don't mutate the parsed dict
            wtype  = entry.pop('type')
            x      = int(entry.pop('x'))
            y      = int(entry.pop('y'))
            width  = int(entry.pop('width'))
            height = int(entry.pop('height'))

            cls = REGISTRY.get(wtype)
            if cls is None:
                raise ValueError(
                    f"{os.path.basename(path)}: unknown widget type {wtype!r}. "
                    f"Available: {sorted(REGISTRY)}"
                )

            # Remaining keys are widget-specific kwargs (e.g. unit, count)
            try:
                widget = cls(x, y, width, height, **entry)
            except TypeError as e:
                # Most likely a typo'd option key in the JSON — name the culprit
                # instead of surfacing a bare constructor TypeError.
                import inspect
                params  = set(inspect.signature(cls.__init__).parameters) - {'self'}
                unknown = sorted(k for k in entry if k not in params)
                options = sorted(params - {'x', 'y', 'width', 'height'})
                hint = (f" Unknown option(s) {unknown}; accepted options: {options}."
                        if unknown else "")
                raise ValueError(
                    f"{os.path.basename(path)}: {wtype}: {e}.{hint}") from e
            self._widgets.append(widget)

    # ------------------------------------------------------------------
    # Dashboard interface
    # ------------------------------------------------------------------

    def update(self, data) -> None:
        for w in self._widgets:
            w.update(data)

    def render(self, surface) -> None:
        surface.fill(self._bg)
        for w in self._widgets:
            w.draw(surface)

    def set_session(self, session) -> None:
        for w in self._widgets:
            w.set_session(session)

    def handle_event(self, event) -> None:
        pass
