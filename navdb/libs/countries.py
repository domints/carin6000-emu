"""Countries and regions the encoder knows. A map holds one country.

The country number (table b +40, block 2's per-country settings) is the country's 1-based place
in an alphabetical English country list: the 11 countries of the original disc fit an ISO 3166
list from before 2006 (bg 33, hr 53, cz 56, ee 67, hu 97, lv 117, lt 123, pl 171, ro 176, sk 190,
si 191). Serbia is not on the original disc; 188 is its place in that order (after Senegal) and
is a guess. The firmware has no country table of its own (names come from the disc), so the
number should only key the per-country settings, copied from a similar country (template).

levels = OSM admin_level of (city, municipality, settlement, district); city: the first level
found at a point. Poland: gmina, powiat, sołectwo / town, city district (docs/format.md section
8, cities). Serbia: grad (else opština), okrug, naselje, gradska opština (Belgrade's Vračar,
Zemun ... like Warsaw's districts).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Country:
    name: str                  # shown in the Country menu (lower case ASCII, local name)
    iso: str
    number: int
    lang: int                  # language byte of the name flags
    template: str              # original country whose record and settings are copied
    levels: tuple
    city_prefixes: tuple = ()  # stripped from admin area names
    street_prefix: bool = False    # Polish style "ulica " before plain street names


COUNTRIES = {
    "pl": Country("polska", "pl", 171, 0x12, "pl", ((7,), 6, 8, 9), ("gmina ",), True),
    "rs": Country("srbija", "rs", 188, 0x1A, "hr", ((7, 8), 6, 9, 8),
                  ("gradska opstina ", "opstina ", "grad ")),
}

VOIVODESHIPS = ("dolnoslaskie", "kujawsko-pomorskie", "lodzkie", "lubelskie", "lubuskie", "malopolskie",
                "mazowieckie", "opolskie", "podkarpackie", "podlaskie", "pomorskie", "slaskie",
                "swietokrzyskie", "warminsko-mazurskie", "wielkopolskie", "zachodniopomorskie")

# region -> (country, Geofabrik extract (libs/osmsrc.py), box in degrees or None = the extract's)
REGIONS = {
    "polska": ("pl", "polska", None),
    **{v: ("pl", v, None) for v in VOIVODESHIPS},
    "warszawa": ("pl", "mazowieckie", (20.85, 52.10, 21.27, 52.37)),
    "piaseczno": ("pl", "mazowieckie", (20.95, 52.03, 21.12, 52.12)),
    "serbia": ("rs", "serbia", None),
    "beograd": ("rs", "serbia", (20.25, 44.68, 20.62, 44.92)),
}
