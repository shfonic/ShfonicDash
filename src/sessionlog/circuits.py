"""
Circuit reference data — the static facts about a track that the games
don't tell us.

Telemetry gives a bare short name ("Melbourne"), which is all the session
CSVs store. This module turns that into the circuit's real name and where
in the world it is, so both apps can render "Albert Park Circuit ·
Melbourne, Australia" from a name they already have.

Keyed by the exact strings the sources emit — for F1 that is _TRACK_ID_MAP
in telemetry/f1_2025.py, which is the authority for which names can appear
(it follows the official EA TrackId enum). A name missing from here just
falls back to the raw track name; nothing breaks.

F1 only for now, matching the track-length table this absorbed: PC2, Forza
and GT7 report no track name at all, and the ACC/AC importer's names are
the companion's to map when that lands. `game` is taken (and gated) so
those can be added as sibling tables without touching callers.

Lengths are the published current-layout figures, metre-level accuracy
being plenty for a chase statistic. Reverse layouts share their base
length; the *Short* variants are real alternate layouts whose lengths
aren't confirmed, so they carry `None` and are simply not counted, exactly
as before.
"""

# name -> (full_name, city, country, country_code, length_m)
_F1_CIRCUITS = {
    "Melbourne":     ("Albert Park Circuit", "Melbourne", "Australia", "AU", 5278),
    "Paul Ricard":   ("Circuit Paul Ricard", "Le Castellet", "France", "FR", 5842),
    "Shanghai":      ("Shanghai International Circuit", "Shanghai", "China", "CN", 5451),
    "Sakhir":        ("Bahrain International Circuit", "Sakhir", "Bahrain", "BH", 5412),
    "Catalunya":     ("Circuit de Barcelona-Catalunya", "Montmeló", "Spain", "ES", 4657),
    "Monaco":        ("Circuit de Monaco", "Monte Carlo", "Monaco", "MC", 3337),
    "Montreal":      ("Circuit Gilles Villeneuve", "Montreal", "Canada", "CA", 4361),
    "Silverstone":   ("Silverstone Circuit", "Silverstone", "United Kingdom", "GB", 5891),
    "Hockenheim":    ("Hockenheimring", "Hockenheim", "Germany", "DE", 4574),
    "Hungaroring":   ("Hungaroring", "Mogyoród", "Hungary", "HU", 4381),
    "Spa":           ("Circuit de Spa-Francorchamps", "Stavelot", "Belgium", "BE", 7004),
    "Monza":         ("Autodromo Nazionale Monza", "Monza", "Italy", "IT", 5793),
    "Singapore":     ("Marina Bay Street Circuit", "Singapore", "Singapore", "SG", 4940),
    "Suzuka":        ("Suzuka International Racing Course", "Suzuka", "Japan", "JP", 5807),
    "Abu Dhabi":     ("Yas Marina Circuit", "Abu Dhabi", "United Arab Emirates", "AE", 5281),
    "Austin":        ("Circuit of the Americas", "Austin", "United States", "US", 5513),
    "Interlagos":    ("Autódromo José Carlos Pace", "São Paulo", "Brazil", "BR", 4309),
    "Red Bull Ring": ("Red Bull Ring", "Spielberg", "Austria", "AT", 4318),
    "Sochi":         ("Sochi Autodrom", "Sochi", "Russia", "RU", 5848),
    "Mexico City":   ("Autódromo Hermanos Rodríguez", "Mexico City", "Mexico", "MX", 4304),
    "Baku":          ("Baku City Circuit", "Baku", "Azerbaijan", "AZ", 6003),
    "Zandvoort":     ("Circuit Zandvoort", "Zandvoort", "Netherlands", "NL", 4259),
    "Imola":         ("Autodromo Enzo e Dino Ferrari", "Imola", "Italy", "IT", 4909),
    "Jeddah":        ("Jeddah Corniche Circuit", "Jeddah", "Saudi Arabia", "SA", 6174),
    "Miami":         ("Miami International Autodrome", "Miami Gardens", "United States", "US", 5412),
    "Las Vegas":     ("Las Vegas Strip Circuit", "Las Vegas", "United States", "US", 6201),
    "Lusail":        ("Lusail International Circuit", "Lusail", "Qatar", "QA", 5419),
    "Madrid":        ("Madring", "Madrid", "Spain", "ES", 5474),

    # Alternate layouts. The game names them as separate tracks, so they are
    # separate entries; the full name carries the variant so it never reads
    # as the full circuit.
    "Sakhir Short":          ("Bahrain International Circuit (Short)", "Sakhir", "Bahrain", "BH", 3543),
    "Silverstone Short":     ("Silverstone Circuit (Short)", "Silverstone", "United Kingdom", "GB", None),
    "Austin Short":          ("Circuit of the Americas (Short)", "Austin", "United States", "US", None),
    "Suzuka Short":          ("Suzuka International Racing Course (East)", "Suzuka", "Japan", "JP", None),
    "Silverstone Reverse":   ("Silverstone Circuit (Reverse)", "Silverstone", "United Kingdom", "GB", 5891),
    "Red Bull Ring Reverse": ("Red Bull Ring (Reverse)", "Spielberg", "Austria", "AT", 4318),
    "Zandvoort Reverse":     ("Circuit Zandvoort (Reverse)", "Zandvoort", "Netherlands", "NL", 4259),
}

_FIELDS = ("full_name", "city", "country", "country_code", "length_m")

# game id -> its circuit table. Games absent from here have no track names.
_BY_GAME = {
    "f1_25": _F1_CIRCUITS,
}


def circuit(game, track):
    """The circuit's facts as a dict, or None when the game/track is unknown.

    Keys: full_name, city, country, country_code, length_m (length_m may be
    None on layouts whose length isn't confirmed).
    """
    row = _BY_GAME.get(game, {}).get(track) if game and track else None
    return dict(zip(_FIELDS, row)) if row else None


def display_name(game, track):
    """The circuit's real name ('Albert Park Circuit'), falling back to the
    raw telemetry name so this is always safe to render."""
    info = circuit(game, track)
    return info["full_name"] if info else (track or "")


def location(game, track):
    """'Melbourne, Australia' — where the circuit is, or None if unknown.

    The city is dropped when it just repeats the country (Singapore).
    """
    info = circuit(game, track)
    if not info:
        return None
    city, country = info["city"], info["country"]
    if not country:
        return city or None
    return country if city == country else "{}, {}".format(city, country)


def length_m(game, track):
    """Circuit length in metres, or None when unknown."""
    info = circuit(game, track)
    return info["length_m"] if info else None
