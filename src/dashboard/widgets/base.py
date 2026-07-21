import pygame
from . import design_system as DS

# Legacy palette alias — keeps old widget code working unchanged.
PALETTE = {
    'bg':          DS.BG,
    'border':      DS.BORDER,
    'label':       DS.TEXT3,
    'value':       DS.TEXT,
    'dim':         DS.INSET,
    'active':      DS.GREEN,
    'green':       DS.GREEN,
    'yellow':      DS.AMBER,
    'red':         DS.RED,
    'throttle':    DS.GREEN,
    'brake':       DS.RED,
    'delta_fast':  DS.GREEN,
    'delta_slow':  DS.RED,
}


class Widget:
    """Abstract base class for all dashboard widgets."""

    PALETTE = PALETTE
    DS = DS

    def __init__(self, x: int, y: int, width: int, height: int):
        self.x = x
        self.y = y
        self.width = width
        self.height = height

    def update(self, telemetry) -> None:
        """Pull fresh values from a TelemetryData object."""

    def draw(self, surface: pygame.Surface) -> None:
        """Render the widget onto *surface*."""

    def handle_event(self, event) -> None:
        """Handle a pygame event (touch, keyboard, etc.)."""

    def set_session(self, session) -> None:
        """Receive the shared SessionHistory.  Override to opt in."""

    # ── Shared drawing helpers ────────────────────────────────────────────────

    def _draw_bg(self, surface: pygame.Surface, radius: int = 8) -> pygame.Rect:
        """Fill the widget area with the standard dark panel."""
        rect = pygame.Rect(self.x, self.y, self.width, self.height)
        DS.draw_panel(surface, rect, radius)
        return rect

    def _clip(self, surface: pygame.Surface) -> None:
        """Set clip rect to this widget's bounds."""
        surface.set_clip(pygame.Rect(self.x, self.y, self.width, self.height))
