"""Countries and regions the encoder knows. A map holds one country.

The country number (table b +40, block 2's per-country settings) indexes the firmware's country
table (number - 1 = record index; 6-byte records: index byte, car registration code shown in
the menus): an alphabetical English list of 240 countries (bg 33 BG, hr 53 HR, pl 171 PL, sk 190
SK, 188 WAL = Sierra Leone ...). Serbia has no code of its own there: 237 YU (Yugoslavia). The
country name comes from the disc; the per-country settings are copied from a similar country
(template).

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
    "rs": Country("srbija", "rs", 237, 0x1A, "hr", ((7, 8), 6, 9, 8),
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
