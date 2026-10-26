"""The two reference events, keyed by Copernicus EMS activation id.

Fixes the replay window the Watchers query and the point ids involved.

Point ids are the warehouse ids, not town slugs. Valencia is VAL01–VAL08
(ingestion/prep/valencia_points.csv and the discharge views in migrations
004 and 012). Chiva is VAL07. Paiporta, on the Barranco del Poyo, is VAL01.
Turís is not on that list, so it is not a filter. The Ahr ids are the
ingestion/feeds/feeds.py tuple: AHR01 Altenahr, AHR02 Ahrweiler.
floodsense_seed hazard and discharge views hold the Valencia series only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

# Order is ingestion/prep/valencia_points.csv and migration 003.
VALENCIA_POINT_IDS: tuple[str, ...] = tuple(f"VAL0{n}" for n in range(1, 9))
# ingestion/feeds/feeds.py. Seed hazard views do not store these rows.
AHR_POINT_IDS: tuple[str, ...] = ("AHR01", "AHR02", "AHR03", "AHR04")

# Place names for claim text. Municipality from valencia_points.csv, and the
# town name from feeds.py. AHR02 is Ahrweiler, the short name the scope gate uses.
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
    "AHR02": "Ahrweiler",
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
        ("Altenahr", "Ahrweiler"),
    ),
}
ALIASES = {"valencia_2024": "EMSR773", "ahr_2021": "EMSR517"}


def spec(event_id: str) -> EventSpec:
    key = ALIASES.get(event_id, event_id)
    if key not in EVENTS:
        raise KeyError(
            f"unknown event_id {event_id!r}; known: {', '.join(EVENTS)} (aliases: "
            f"{', '.join(ALIASES)})"
        )
    return EVENTS[key]
