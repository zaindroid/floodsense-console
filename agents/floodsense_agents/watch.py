"""Europe live watch: which gauges and model points a question is about.

Two live sources, kept apart because they mean different things:

  {schema}.gauge_levels  PEGELONLINE water levels (WSV), banded against the
                         station's own MHW: an official characteristic value.
  {schema}.eu_watch      Open-Meteo GloFAS discharge at 11 river points outside
                         Germany, banded against the series itself (7-day
                         forecast max vs 2x the exact past-30-day median): a model band,
                         not an official warning.

watch_target() reads place and river words from the question (or the user's
selection) and returns the stations and points it names. A city wins over a
river: "the Elbe in Dresden" is the DRESDEN gauge, "the Danube" is every
Danube gauge and point. The Rhine and Mosel stay on the EMSR517 live gauge
path (investigator._rhine_live); is_watch_only() says when a target needs this
path instead.

STATIONS mirrors ingestion/feeds/pegel_poll.py STATIONS (a test keeps them
equal). The point ids are migration 064's.
"""

from __future__ import annotations

import re

# (shortname, water) as PEGELONLINE returns them, in pegel_poll.py order.
STATIONS: tuple[tuple[str, str], ...] = (
    ("MAXAU", "RHEIN"),
    ("MAINZ", "RHEIN"),
    ("KAUB", "RHEIN"),
    ("KOBLENZ", "RHEIN"),
    ("ANDERNACH", "RHEIN"),
    ("BONN", "RHEIN"),
    ("KÖLN", "RHEIN"),
    ("DÜSSELDORF", "RHEIN"),
    ("EMMERICH", "RHEIN"),
    ("Trier UP", "MOSEL"),
    ("Cochem", "MOSEL"),
    ("Fremersdorf", "SAAR"),
    ("FRANKFURT OSTHAFEN", "MAIN"),
    ("WÜRZBURG", "MAIN"),
    ("Heidelberg UP", "NECKAR"),
    ("Lauffen", "NECKAR"),
    ("DRESDEN", "ELBE"),
    ("MAGDEBURG-STROMBRÜCKE", "ELBE"),
    ("WITTENBERGE", "ELBE"),
    ("REGENSBURG EISERNE BRÜCKE", "DONAU"),
    ("PASSAU DONAU", "DONAU"),
    ("FRANKFURT1 (ODER)", "ODER"),
    ("HOHENSAATEN-FINOW", "ODER"),
    ("HANN.MUENDEN", "WESER"),
    ("PORTA", "WESER"),
    ("RHEINE UNTERSCHLEUSE", "EMS"),
)
# Waters the EMSR517 live gauge path already answers.
RHINE_WATERS: tuple[str, ...] = ("RHEIN", "MOSEL")

# (point_id, city, country, river, lat, lon) as in migrations 063-065. Seville was dropped:
# its best GloFAS cell carries ~17 m3/s against ~160 m3/s long-term at the city.
EU_POINTS: tuple[tuple[str, str, str, str, float, float], ...] = (
    ("EU01", "Paris", "FR", "Seine", 48.925, 2.275),
    ("EU02", "Lyon", "FR", "Rhone", 45.775, 4.825),
    ("EU03", "Orleans", "FR", "Loire", 47.875, 1.875),
    ("EU04", "Piacenza", "IT", "Po", 45.075, 9.625),
    ("EU05", "Zaragoza", "ES", "Ebro", 41.625, -0.825),
    ("EU06", "Warsaw", "PL", "Vistula", 52.275, 20.975),
    ("EU07", "Vienna", "AT", "Danube", 48.175, 16.475),
    ("EU08", "Budapest", "HU", "Danube", 47.475, 19.025),
    ("EU09", "Szeged", "HU", "Tisza", 46.275, 20.125),
    ("EU10", "Liege", "BE", "Meuse", 50.675, 5.625),
    ("EU11", "Prague", "CZ", "Vltava", 50.125, 14.375),
)
EU_POINT_IDS: tuple[str, ...] = tuple(p[0] for p in EU_POINTS)

# City words -> station shortnames or EU point ids. Case-insensitive, full words.
_CITY: dict[str, tuple[str, ...]] = {
    "Maxau": ("MAXAU",),
    "Karlsruhe": ("MAXAU",),
    "Mainz": ("MAINZ",),
    "Kaub": ("KAUB",),
    "Koblenz": ("KOBLENZ",),
    "Andernach": ("ANDERNACH",),
    "Bonn": ("BONN",),
    "Köln": ("KÖLN",),
    "Koeln": ("KÖLN",),
    "Cologne": ("KÖLN",),
    "Düsseldorf": ("DÜSSELDORF",),
    "Duesseldorf": ("DÜSSELDORF",),
    "Dusseldorf": ("DÜSSELDORF",),
    "Emmerich": ("EMMERICH",),
    "Trier": ("Trier UP",),
    "Cochem": ("Cochem",),
    "Fremersdorf": ("Fremersdorf",),
    "Würzburg": ("WÜRZBURG",),
    "Wuerzburg": ("WÜRZBURG",),
    "Wurzburg": ("WÜRZBURG",),
    "Heidelberg": ("Heidelberg UP",),
    "Lauffen": ("Lauffen",),
    "Dresden": ("DRESDEN",),
    "Magdeburg": ("MAGDEBURG-STROMBRÜCKE",),
    "Wittenberge": ("WITTENBERGE",),
    "Regensburg": ("REGENSBURG EISERNE BRÜCKE",),
    "Passau": ("PASSAU DONAU",),
    "Hohensaaten": ("HOHENSAATEN-FINOW",),
    "Hann. Münden": ("HANN.MUENDEN",),
    "Hann. Muenden": ("HANN.MUENDEN",),
    "Hannoversch Münden": ("HANN.MUENDEN",),
    "Porta Westfalica": ("PORTA",),
    "Rheine": ("RHEINE UNTERSCHLEUSE",),
    # Frankfurt alone is Frankfurt am Main; the Oder town is named with the river.
    "Frankfurt (Oder)": ("FRANKFURT1 (ODER)",),
    "Frankfurt an der Oder": ("FRANKFURT1 (ODER)",),
    "Frankfurt/Oder": ("FRANKFURT1 (ODER)",),
    "Frankfurt": ("FRANKFURT OSTHAFEN",),
    "Paris": ("EU01",),
    "Lyon": ("EU02",),
    "Orléans": ("EU03",),
    "Orleans": ("EU03",),
    "Piacenza": ("EU04",),
    "Zaragoza": ("EU05",),
    "Saragossa": ("EU05",),
    "Warsaw": ("EU06",),
    "Warszawa": ("EU06",),
    "Warschau": ("EU06",),
    "Vienna": ("EU07",),
    "Wien": ("EU07",),
    "Budapest": ("EU08",),
    "Szeged": ("EU09",),
    "Liège": ("EU10",),
    "Liege": ("EU10",),
    "Lüttich": ("EU10",),
    "Prague": ("EU11",),
    "Praha": ("EU11",),
    "Prag": ("EU11",),
}
# River words -> (PEGELONLINE waters, EU rivers). Ambiguous words ("Main",
# "Ems", "Oder" = German "or", "Po") only count capitalised.
_RIVER: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "Rhine": (("RHEIN",), ()),
    "Rhein": (("RHEIN",), ()),
    "Mosel": (("MOSEL",), ()),
    "Moselle": (("MOSEL",), ()),
    "Saar": (("SAAR",), ()),
    "Neckar": (("NECKAR",), ()),
    "Elbe": (("ELBE",), ()),
    "Danube": (("DONAU",), ("Danube",)),
    "Donau": (("DONAU",), ("Danube",)),
    "Duna": ((), ("Danube",)),
    "Weser": (("WESER",), ()),
    "Seine": ((), ("Seine",)),
    "Rhône": ((), ("Rhone",)),
    "Rhone": ((), ("Rhone",)),
    "Loire": ((), ("Loire",)),
    "Ebro": ((), ("Ebro",)),
    "Vistula": ((), ("Vistula",)),
    "Wisła": ((), ("Vistula",)),
    "Weichsel": ((), ("Vistula",)),
    "Tisza": ((), ("Tisza",)),
    "Theiss": ((), ("Tisza",)),
    "Meuse": ((), ("Meuse",)),
    "Maas": ((), ("Meuse",)),
    "Vltava": ((), ("Vltava",)),
    "Moldau": ((), ("Vltava",)),
}
_RIVER_CASED: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "Main": (("MAIN",), ()),
    "Ems": (("EMS",), ()),
    "Oder": (("ODER",), ()),
    "Po": ((), ("Po",)),
}


def _alt(words) -> re.Pattern[str]:
    alts = sorted(words, key=len, reverse=True)
    return re.compile(r"(?<!\w)(?:" + "|".join(re.escape(w) for w in alts) + r")(?!\w)")


_CITY_RE = re.compile(_alt(_CITY).pattern, re.IGNORECASE | re.UNICODE)
_RIVER_RE = re.compile(_alt(_RIVER).pattern, re.IGNORECASE | re.UNICODE)
# "Main", "Oder", "Ems", "Po" are also ordinary words ("Main roads", "Oder doch",
# "Ems?"). They count only beside a river word: "river Main", "am Main",
# "an der Oder", "Main at Frankfurt", "Oder river".
_CASED = "|".join(_RIVER_CASED)
_RIVER_CASED_RE = re.compile(
    rf"(?:(?i:\b(?:river|fluss|am|an der)\s+)(?P<a>{_CASED})\b)"
    rf"|(?:\b(?P<b>{_CASED})(?i:\s+(?:river|fluss|at)\b))"
)
_CITY_KEYS = {k.lower(): v for k, v in _CITY.items()}
_RIVER_KEYS = {k.lower(): v for k, v in _RIVER.items()}
_STATION_WATER = dict(STATIONS)
_STATION_KEYS = {s.upper(): s for s, _ in STATIONS}


def _target(stations: list[str], points: list[str], word: str) -> dict:
    return {
        "stations": list(dict.fromkeys(stations)),
        "points": list(dict.fromkeys(points)),
        "word": word,
    }


def watch_target(question: str, context: dict | None = None) -> dict | None:
    """{"stations": [...], "points": [...], "word": ...} the question names, else None.

    Cities first (every city named), then rivers. With neither, the user's
    selection: context watch_point (an EU id) or station (a PEGELONLINE name).
    """
    text = question or ""
    stations: list[str] = []
    points: list[str] = []
    words: list[str] = []
    for m in _CITY_RE.finditer(text):
        for ident in _CITY_KEYS[m.group(0).lower()]:
            (points if ident in EU_POINT_IDS else stations).append(ident)
        words.append(m.group(0))
    # Longest alternative first, so "Frankfurt (Oder)" never also reads as "Frankfurt".
    if stations or points:
        return _target(stations, points, ", ".join(words))
    hits = [(m.group(0), _RIVER_KEYS[m.group(0).lower()]) for m in _RIVER_RE.finditer(text)]
    for m in _RIVER_CASED_RE.finditer(text):
        word = m.group("a") or m.group("b")
        hits.append((word, _RIVER_CASED[word]))
    for word, (waters, rivers) in hits:
        stations += [s for s, w in STATIONS if w in waters]
        points += [p[0] for p in EU_POINTS if p[3] in rivers]
        words.append(word)
    if stations or points:
        return _target(stations, points, ", ".join(words))
    ctx = context or {}
    if ctx.get("watch_point") in EU_POINT_IDS:
        return _target([], [ctx["watch_point"]], f"selected {ctx['watch_point']}")
    picked = _STATION_KEYS.get(str(ctx.get("station") or "").upper())
    if picked and _STATION_WATER[picked] not in RHINE_WATERS:
        return _target([picked], [], f"selected {picked}")
    return None


def is_watch_only(target: dict | None) -> bool:
    """True when the target needs the watch path: an EU point, or a gauge off the Rhine/Mosel."""
    if not target:
        return False
    if target["points"]:
        return True
    return any(_STATION_WATER.get(s) not in RHINE_WATERS for s in target["stations"])


# A watch question must ask about the present. Live cue: always live. A level or
# discharge word: live unless the question also points at the past.
_LIVE_CUE = re.compile(
    r"\b(?:right now|now|currently|current|today|tonight|tomorrow|at the moment|rising|"
    r"next (?:few )?\d* ?(?:h|hours?|days?)|coming (?:hours?|days?)|"
    r"heute|jetzt|aktuell|derzeit|ahora|hoy|actualmente)\b",
    re.IGNORECASE | re.UNICODE,
)
_LEVEL_WORD = re.compile(
    r"\b(?:levels?|water levels?|discharge|flow|gauges?|risk|pegel|wasserstand|abfluss|"
    r"caudal|nivel)\b",
    re.IGNORECASE | re.UNICODE,
)
_PAST_CUE = re.compile(
    r"\b(?:was|did|were|happened|affected|flood of|floods of|hit|last (?:year|month|week)|"
    r"(?:19|20)\d{2}|january|february|march|april|may|june|july|august|september|october|"
    r"november|december|januar|februar|märz|juni|juli|oktober|dezember|enero|julio|octubre|"
    r"war|waren|wurde|fue|emsr\d*)\b",
    re.IGNORECASE | re.UNICODE,
)


def has_watch_cue(question: str) -> bool:
    """A live cue, or a level/discharge word with no past cue."""
    q = question or ""
    if _LIVE_CUE.search(q):
        return True
    return bool(_LEVEL_WORD.search(q)) and not _PAST_CUE.search(q)


def all_sources() -> dict:
    """Every model point and every gauge off the Rhine/Mosel: a watch run that names nothing."""
    return _target(
        [s for s, w in STATIONS if w not in RHINE_WATERS], list(EU_POINT_IDS), "all watch sources"
    )


def place_words() -> tuple[str, ...]:
    """Every city and river word the watch reads, for the LIVE-EU scope vocabulary."""
    return (*_CITY, *_RIVER, *_RIVER_CASED)


def sql_list(values) -> str:
    return ", ".join("'" + str(v).replace("'", "''") + "'" for v in values)
