"""Countries and packages (discs) the encoder knows. A package is one disc with one or more
countries; each country is a separate entry of the Country menu.

The country number (table b +40, block 2's per-country settings) indexes the firmware's country
table (number - 1 = record index; 6-byte records: index byte, car registration code shown in
the menus): an alphabetical English list of 240 countries (docs/country_table.md). Every country
gets a number of its own, as the firmware may pick a country by number alone (e.g. one kept in
NV): its real one where the table has it, Serbia 237 YU (Yugoslavia), Montenegro and Kosovo
unused numbers without a code (235 Western Sahara, 236 Yemen). Block 2 holds the settings once
per number. The country name comes from the disc; the per-country settings are copied from a
similar country (template; hr and si have the same settings).

A country's area is its OSM admin_level 2 boundary (ISO3166-1 code, from its own Geofabrik
extract, libs/osmsrc.py); what lies outside every country of the package is left out.

levels = OSM admin_level of (city, municipality, settlement, district); city: the first level
found at a point; municipality None = the city. Like Poland's gmina / powiat / sołectwo / city
district (docs/format.md section 8, cities):
  pl  gmina 7, powiat 6, sołectwo 8, district 9
  si  občina 8, upravna enota 7, naselje 10, krajevna / četrtna skupnost 9
  hr  grad / općina 7, županija 4, naselje 8, gradska četvrt / mjesni odbor 9
  ba  grad 6 else općina 7, kanton 5, naselje 9, općina of a grad 7 (Sarajevo's Centar ...)
  me  opština 6, -, naselje 8, 9
  rs  grad 7 else opština 8, okrug 6, naselje 9, gradska opština 8 (Belgrade's Vračar ...)
  xk  komuna 6, rajoni 5, village 8, neighbourhood 10
  mk  grad 6 else opština 7, -, village 8, opština of Skopje 7
  al  bashkia 7, qark 6, village 8, njësia bashkiake 9
Bilingual names ("Koper / Capodistria", "Komuna e Kamenicës / Opština Kamenica") keep their first
part; genitive endings undo the "Komuna e Prishtinës" form (-> "prishtine").
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Country:
    name: str                  # shown in the Country menu (lower case ASCII, local name)
    iso: str                   # ISO3166-1 code of the OSM boundary, written lower case at b +46
    number: int
    lang: int                  # language byte of the name flags
    template: str              # original country whose record and settings are copied
    extract: str               # Geofabrik extract (libs/osmsrc.py)
    levels: tuple
    city_prefixes: tuple = ()  # stripped from admin area names
    street_prefix: bool = False    # Polish style "ulica " before plain street names
    genitive: tuple = ()       # (ending, replacement) of the last word after a stripped prefix


SQ_GENITIVE = (("ajt", "aj"), ("es", "e"), ("se", ""), ("it", ""), ("ut", ""))    # Albanian
# firmware country table numbers (record index + 1), docs/country_table.md
AL, BIH, HR, MK, PL, SLO, ME, XK, YU = 2, 27, 53, 126, 171, 191, 235, 236, 237

COUNTRIES = {
    "pl": Country("polska", "pl", PL, 0x12, "pl", "polska", ((7,), 6, 8, 9), ("gmina ",), True),
    "si": Country("slovenija", "si", SLO, 0x17, "si", "slovenia", ((8,), 7, 10, 9),
                  ("mestna obcina ", "obcina ", "upravna enota ", "cetrtna skupnost ", "krajevna skupnost ")),
    "hr": Country("hrvatska", "hr", HR, 0x1A, "hr", "croatia", ((7,), 4, 8, 9),
                  ("opcina ", "grad ", "gradska cetvrt ", "gradski kotar ", "mjesni odbor ")),
    "ba": Country("bosna i hercegovina", "ba", BIH, 0x1A, "hr", "bosnia-herzegovina", ((6, 7), 5, 9, 7),
                  ("grad ", "opcina ", "opstina ", "mz ")),
    "me": Country("crna gora", "me", ME, 0x1A, "hr", "montenegro", ((6,), None, 8, 9),
                  ("opstina ", "glavni grad ", "prijestolnica ")),
    "rs": Country("srbija", "rs", YU, 0x1A, "hr", "serbia", ((7, 8), 6, 9, 8),
                  ("gradska opstina ", "opstina ", "grad ")),
    "xk": Country("kosovo", "xk", XK, 0xFF, "hr", "kosovo", ((6,), 5, 8, 10),
                  ("komuna e ", "rajoni i "), genitive=SQ_GENITIVE),
    "mk": Country("makedonija", "mk", MK, 0xFF, "hr", "macedonia", ((6, 7), None, 8, 7),
                  ("opstina ", "grad ")),
    "al": Country("shqiperia", "al", AL, 0xFF, "hr", "albania", ((7,), 6, 8, 9),
                  ("bashkia ", "qarku i ", "njesia bashkiake ", "njesia administrative "), genitive=SQ_GENITIVE),
}

# package (disc) -> its countries; encoder.py PACKAGE -> cd/carin_PACKAGE.img
PACKAGES = {
    "poland": ("pl",),
    "exyugoslavia": ("si", "hr", "ba", "me", "rs", "xk", "mk", "al"),
}

for _isos in PACKAGES.values():         # addresses and POI streets are read with one street rule
    assert len({COUNTRIES[i].street_prefix for i in _isos}) == 1, _isos
    assert len({COUNTRIES[i].number for i in _isos}) == len(_isos), _isos
