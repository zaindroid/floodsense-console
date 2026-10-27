"""The two reference events, keyed by Copernicus EMS activation id.

Fixes the replay window the Watchers query and the point ids involved.

Point ids are the warehouse ids, not town slugs. Valencia is VAL01–VAL08
(ingestion/prep/valencia_points.csv and the discharge views in migrations
004 and 012). Chiva is VAL07. Paiporta, on the Barranco del Poyo, is VAL01.
Turís is not on that list, so it is not a filter. The Ahr ids are the
ingestion/feeds/feeds.py tuple: AHR01 Altenahr, AHR02 Ahrweiler.
floodsense_seed hazard and discharge views hold Valencia and, since migrations
051/052, a real Open-Meteo Ahr extract (AHR01-AHR04, ERA5 rain 13-16 Jul 2021,
GloFAS discharge 10-20 Jul 2021). The live floodsense views are Valencia only.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

# Order is ingestion/prep/valencia_points.csv and migration 003.
VALENCIA_POINT_IDS: tuple[str, ...] = tuple(f"VAL0{n}" for n in range(1, 9))
# ingestion/feeds/feeds.py. Seed hazard views do not store these rows.
AHR_POINT_IDS: tuple[str, ...] = ("AHR01", "AHR02", "AHR03", "AHR04")

# Place names for claim text. Municipality from valencia_points.csv, and the
# town name from feeds.py. AHR02 is Bad Neuenahr-Ahrweiler; the scope gate also takes "Ahrweiler".
POINT_NAMES: dict[str, str] = {
    "VAL01": "Paiporta",
    "VAL02": "Catarroja",
    "VAL03": "Sedaví",
    "VAL04": "Alfafar",
    "VAL05": "Benetússer",
    "VAL06": "Algemesí",
    "VAL07": "Chiva",
    "VAL08": "Utiel",
    "AHR01": "Altenahr",
    "AHR02": "Bad Neuenahr-Ahrweiler",
    "AHR03": "Schuld",
    "AHR04": "Dernau",
}


def point_label(point_id: str) -> str:
    """Chiva (VAL07). An unknown id stays the id, so a new point is still named."""
    name = POINT_NAMES.get(point_id)
    if not name:
        return point_id
    return f"{name} ({point_id})"


# PEGELONLINE shortname and water. The Ahr joins the Rhine between Koblenz and Bonn.
# feeds.py and the seed rows use this tuple. Do not keep a second copy of the names.
RHINE_GAUGES: tuple[tuple[str, str], ...] = (
    ("BONN", "RHEIN"),
    ("KÖLN", "RHEIN"),
    ("KOBLENZ", "RHEIN"),
)

# Words that put a question in Germany. They join the EMSR517 vocabulary (the
# scope gate) and route a default-event question there (route_event). In live
# mode EMSR517 is "the Rhine right now": gauge_levels, not the 2021 window.
GERMAN_PLACES: tuple[str, ...] = (
    "Rhine",
    "Rhein",
    "Köln",
    "Koeln",
    "Cologne",
    "Bonn",
    "Koblenz",
    "Mosel",
    "Moselle",
    "Ahrtal",
    "Germany",
    "Deutschland",
    "NRW",
    "Nordrhein-Westfalen",
    "Rheinland-Pfalz",
    "Rhineland-Palatinate",
)
# "Ahr" in any case (AHR too) and the AHR point ids route to EMSR517.
_GERMAN_RE = re.compile(
    r"\b(?:"
    + "|".join(re.escape(w) for w in (*GERMAN_PLACES, "Ahr", "Altenahr", "Ahrweiler"))
    + r"|AHR\d{2})\b",
    re.IGNORECASE | re.UNICODE,
)
# Every Valencia town in POINT_NAMES (Catarroja, Sedaví, ...) keeps a question in Valencia.
_VALENCIA_RE = re.compile(
    r"\b(?:"
    + "|".join(re.escape(name) for pid, name in POINT_NAMES.items() if pid.startswith("VAL"))
    + r"|valencia|val[eè]ncia|spain|españa|espana|poyo|dana|VAL\d{2})\b",
    re.IGNORECASE | re.UNICODE,
)
DEFAULT_EVENT = "EMSR773"
GERMAN_EVENT = "EMSR517"


def names_germany(question: str) -> str | None:
    """The first German place word of a question, or None."""
    m = _GERMAN_RE.search(question or "")
    return m.group(0) if m else None


@dataclass(frozen=True)
class EventSpec:
    event_id: str
    name: str
    window_from_utc: str
    window_to_utc: str
    region: str
    river: str
    catchment: str
    river_points: tuple[
        str, ...
    ]  # point_ids in hazard_timeline / discharge_daily that carry discharge
    rain_points: tuple[str, ...]  # point_ids that carry rain
    # (lat_min, lat_max, lon_min, lon_max). exposure_join has no event column,
    # so this is what keeps one event's footprint off another's portfolio.
    bbox: tuple[float, float, float, float]
    # When Copernicus first published the mapping. A replay before this cannot
    # use the footprint, because nobody had it yet. Proposed: confirm against
    # the activation record.
    footprint_published_utc: str
    # Moments worth replaying the run at, so a reviewer can see what was
    # knowable when. Proposed from the seed; Saleeta and Urvashi confirm.
    moments: tuple[tuple[str, str], ...]
    # PEGELONLINE stations this event may cite, as (shortname, water).
    # Empty means the watchers do not query gauge_levels. A live pull is the
    # last 30 days, so it does not overlap these frozen windows.
    # EMSR773 is empty: Valencia does not read gauge_levels. hazard_now is
    # not on this path; Watchers read hazard_timeline.
    gauges: tuple[tuple[str, str], ...]
    # Names a question may use. Not point ids, and not SQL filters.
    place_names: tuple[str, ...] = ()
    # Schema whose hazard_timeline / discharge_daily hold this event's replay
    # rows, whatever FF_LIVE_DATA says. None: the configured schema. The live
    # floodsense.* hazard views hold Valencia only; the real Ahr extract
    # (migrations 051/052) is in floodsense_seed, so an EMSR517 replay must
    # read it there or it reads Valencia's views and finds nothing.
    hazard_schema: str | None = None
    # Every warehouse point id of the event (hazard_timeline / discharge_daily).
    point_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return asdict(self)


EVENTS: dict[str, EventSpec] = {
    "EMSR773": EventSpec(
        "EMSR773",
        "Valencia DANA, 29 Oct 2024",
        "2024-10-28T00:00:00Z",
        "2024-10-30T23:59:59Z",
        "Valencia province",
        "Barranco del Poyo",
        "Poyo ravine catchment",
        ("VAL01",),  # Paiporta, Barranco del Poyo
        ("VAL07",),  # Chiva
        (38.90, 39.70, -1.10, -0.20),
        "2024-10-30T00:00:00Z",
        (
            ("2024-10-29T09:00:00Z", "Rain begins, red warning at Chiva"),
            ("2024-10-29T13:00:00Z", "Rain over the catchment for four hours"),
            ("2024-10-29T15:00:00Z", "Discharge reaches 310 m3/s"),
            ("2024-10-29T17:00:00Z", "Peak reading, 2,282 m3/s"),
            ("2024-10-29T18:00:00Z", "The gauge stops reporting"),
            ("2024-10-29T19:11:00Z", "ES-Alert reaches phones"),
            ("2024-10-30T06:00:00Z", "Copernicus publishes the footprint"),
        ),
        (),
        ("Chiva", "Paiporta"),
        point_ids=VALENCIA_POINT_IDS,
    ),
    "EMSR517": EventSpec(
        "EMSR517",
        "Ahr valley flood, 14-15 Jul 2021",
        "2021-07-12T00:00:00Z",
        "2021-07-16T23:59:59Z",
        "Ahr valley, Rhineland-Palatinate",
        "Ahr",
        "Ahr catchment (Eifel)",
        ("AHR01",),  # Altenahr
        ("AHR02",),  # Bad Neuenahr-Ahrweiler
        (50.20, 50.70, 6.60, 7.40),
        "2021-07-15T00:00:00Z",
        (
            ("2021-07-14T14:00:00Z", "Rain over the Eifel"),
            ("2021-07-14T19:00:00Z", "Altenahr at 1,000 m3/s"),
            ("2021-07-14T20:00:00Z", "The gauge stops reporting"),
            ("2021-07-15T06:00:00Z", "Copernicus publishes the footprint"),
        ),
        RHINE_GAUGES,
        ("Altenahr", "Ahrweiler", "Bad Neuenahr-Ahrweiler", *GERMAN_PLACES),
        "floodsense_seed",
        point_ids=AHR_POINT_IDS,
    ),
}
# Views whose rows are per event point (hazard and discharge), so the replay
# schema applies to them. exposure_join, gauge_levels and provenance are not.
HAZARD_VIEWS: tuple[str, ...] = ("hazard_timeline", "discharge_daily")
ALIASES = {"valencia_2024": "EMSR773", "ahr_2021": "EMSR517"}


def spec(event_id: str) -> EventSpec:
    key = ALIASES.get(event_id, event_id)
    if key not in EVENTS:
        raise KeyError(
            f"unknown event_id {event_id!r}; known: {', '.join(EVENTS)} (aliases: "
            f"{', '.join(ALIASES)})"
        )
    return EVENTS[key]


def hazard_schema(event: dict | None, default: str) -> str:
    """The schema an event-mode replay reads hazard_timeline / discharge_daily from.

    Falls back to the registry by event_id, so state resumed from an older
    checkpoint (no hazard_schema key) still reads the right views.
    """
    ev = event or {}
    if ev.get("hazard_schema"):
        return str(ev["hazard_schema"])
    known = EVENTS.get(ALIASES.get(str(ev.get("event_id")), str(ev.get("event_id"))))
    return (known.hazard_schema if known else None) or default


def _context_event(context: dict | None) -> tuple[str, str] | None:
    """The event the user's selection points at: event_id, then point, station, place."""
    ctx = context or {}
    if ctx.get("event_id"):
        try:
            return spec(str(ctx["event_id"])).event_id, f"context event_id {ctx['event_id']}"
        except KeyError:
            pass
    pid = ctx.get("point_id")
    if pid in POINT_NAMES:
        ev = GERMAN_EVENT if str(pid).startswith("AHR") else DEFAULT_EVENT
        return ev, f"context point {pid}"
    if ctx.get("station"):
        # PEGELONLINE stations are German, whatever list gauge_levels grows to.
        return GERMAN_EVENT, f"context station {ctx['station']}"
    place = str(ctx.get("place") or "")
    if place and names_germany(place):
        return GERMAN_EVENT, f"context place {place}"
    if place and _VALENCIA_RE.search(place):
        return DEFAULT_EVENT, f"context place {place}"
    return None


def route_event(
    question: str, event_id: str | None, context: dict | None = None
) -> tuple[str, str]:
    """(event_id, reason). An explicit event_id always stands; only None is routed.

    Unset: the user's selection (context) wins, then a German question (Rhine,
    Köln, Ahr, AHR01 ...) goes to EMSR517, else EMSR773. A question that also
    names a Valencia town stays on EMSR773 (the scope gate decides).
    """
    if event_id:
        chosen = spec(event_id).event_id
        return chosen, f"event_id {chosen} requested"
    picked = _context_event(context)
    if picked:
        return picked
    word = names_germany(question)
    if word and not _VALENCIA_RE.search(question or ""):
        return GERMAN_EVENT, f"question names '{word}' (Germany), so the run uses {GERMAN_EVENT}"
    return DEFAULT_EVENT, f"no event_id; default {DEFAULT_EVENT}"
