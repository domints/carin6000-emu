# navdb

Dekoder bazy map CARiN / Carminat (`carindb` z płyty `NAV_DB`) do GeoPackage, czyli pierwszy krok do konwertera OSM → Carminat. Format jest rozpracowany statycznie: z pliku i z kodu modułów OS-9, które go czytają (`pbp`, `dbq`, `rpmod`), bez emulatora.

```
navdb/
  decoder.py     baza -> GeoPackage (to uruchamiasz)
  libs/          biblioteka formatu, wspólna dla dekodera i przyszłego enkodera
  tools/         narzędzia pomocnicze (wypakowanie płyty, zrzut nagłówka, adnotacje Ghidry)
  docs/format.md specyfikacja formatu
```

## Szybki start

```bash
python3 navdb/tools/extract_navdb.py          # obraz płyty -> temp/navdb/carindb (raz)
python3 navdb/decoder.py --info               # co jest w bazie
python3 navdb/decoder.py --area warszawa      # Warszawa -> temp/navdb/warszawa.gpkg (kilka sekund)
python3 navdb/decoder.py                      # cała baza -> temp/navdb/carindb.gpkg (~20 min, 2,8 GB)
```

Więcej opcji:

```bash
python3 navdb/decoder.py --area mazowieckie --layers roads,poi   # tylko wybrane warstwy
python3 navdb/decoder.py --bbox 20.98,52.22,21.04,52.25 -o /tmp/centrum.gpkg
python3 navdb/decoder.py --help
```

Nowsza płyta (DVD, `DB/DB_0` + `DB/DB_1`): wystarczy dowiązanie `temp/navdb -> <płyta>/DB`, `DB_1` dołącza się sam; wynik trafia wtedy do `temp/` (katalog płyty jest tylko do odczytu). Różnice formatu: [../docs/newer_disc_format.md](../docs/newer_disc_format.md).

Przy `--area`/`--bbox` dekoder czyta tylko jednostki spod prostokąta, znalezione przez indeks przestrzenny (jak urządzenie podczas jazdy), a nie całe tablice.

Obszary: `krakow`, `warszawa`, `malopolskie`, `mazowieckie`, `polska`; bez `--area`/`--bbox` dekodowana jest cała baza. Warstwy: `roads`, `background`, `poi`, `cities`. Przy wyborze części warstw pozostałe w istniejącym pliku zostają bez zmian. Wymagany jest tylko Python 3 (bez GDAL i innych bibliotek).

## Co jest w GeoPackage

| Warstwa | Zawartość |
|---|---|
| `roads` | odcinki dróg na 4 poziomach routingu (`level` 0 = pełna sieć): kształt, nazwa, dzielnica, miasto, kraj, klasa, kierunkowość, długość, form of way (autostrada, łącznica, prom…), rondo/plac, dostęp, zakazy skrętu, czas promu, numery domów po lewej i prawej stronie |
| `parcels` | prostokąty parceli (podział mapy) |
| `areas` | tło mapy na 6 poziomach: woda, lasy, zabudowa, cmentarze, ląd |
| `overview_roads` | uproszczone drogi z numerami (widok kraju i Europy) |
| `poi` | 698 tys. punktów: nazwa, marka, kategoria, ulica, numer, dzielnica, miasto, kod pocztowy, telefon |
| `cities` | 110 tys. miejscowości: nazwa, gmina, inne pisownie |

Kolumny i ich pochodzenie opisuje [libs/layers.py](libs/layers.py), a znaczenie pól [docs/format.md](docs/format.md).

## Oglądanie w QGIS

Otwórz plik `.gpkg`. Style wczytują się same z tabeli `layer_styles`:
- drogi są pokolorowane według klasy, a drobne klasy pojawiają się dopiero po przybliżeniu;
- nazwy ulic widać od skali 1:25 000;
- tło i drogi przeglądowe zmieniają poziom wraz ze skalą.

Adres (np. Nowy Świat 29) znajdziesz na warstwie `roads` przez „Zaznacz obiekty za pomocą wyrażenia”:

```
"level" = 0 AND "name" LIKE '%nowy swiat%' AND "city" = 'warszawa' AND (
  (29 BETWEEN min("hn_left_from","hn_left_to") AND max("hn_left_from","hn_left_to") AND 29 % 2 = "hn_left_from" % 2)
  OR (29 BETWEEN min("hn_right_from","hn_right_to") AND max("hn_right_from","hn_right_to") AND 29 % 2 = "hn_right_from" % 2))
```

Nazwy są zapisane małymi literami, bez polskich znaków i z „ulica”/„aleja” w nazwie.

## Enkoder (OSM → carindb, w budowie)

```bash
ogr2ogr -f GPKG temp/osm/mazowieckie.gpkg temp/osm/mazowieckie-latest.osm.pbf lines points multipolygons   # raz, ~1 min
python3 navdb/encoder.py --area piaseczno           # -> temp/navdb/enc/carindb (kilka sekund)
python3 navdb/tests/check_db.py                     # reguły struktury (te same przechodzą na oryginale)
python3 navdb/tests/check_search.py                 # wyszukiwanie adresów jak w urządzeniu
python3 navdb/decoder.py temp/navdb/enc/carindb -o temp/navdb/enc/check.gpkg   # podgląd w QGIS
python3 navdb/tools/mkdisc.py --chd                 # płyta: cd/carin_osm.img/.cue/.chd
```

Plik PBF pobiera się z Geofabrik (`https://download.geofabrik.de/europe/poland/mazowieckie-latest.osm.pbf`).

Co enkoder robi teraz:
- **drogi z OSM** na 4 poziomach routingu: klasy, form of way, kierunkowość, ronda, dostęp, kształty, topologia, poziomy z powiązaniami węzłów i czasami dojazdu;
- **numery domów** z adresów OSM, per odcinek, lewa i prawa strona;
- **wyszukiwanie**: kraj Polska, gminy i miejscowości, ulice z rotacjami nazw;
- **tło i TMC** są na razie **skopiowane z oryginalnej płyty**, a POI puste.

Każdy writer jest sprawdzony testem w obie strony na oryginale (`tests/test_parcelfmt.py`, `tests/test_spindex.py`), a wynik walidatorami. Obraz płyty bierze oryginał jako szablon: deskryptory, BIBLIOGR (lista zgodnych wersji oprogramowania) i CARINET zostają, a ABSTRACT i COPYRIGH opisują dane OSM (ODbL).

## Stan

Struktura całego pliku jest znana (poza TMC, które jest niepotrzebne). Znane są też wszystkie pola, których używa router (`rpmod`): topologia, zakazy skrętu, kierunkowość, dostęp, model prędkości i powiązanie poziomów routingu. Otwarte drobiazgi, których router nie czyta, są wypisane w [docs/format.md](docs/format.md), sekcja 8, razem z planem enkodera.

## Biblioteka (`libs/`)

| Moduł | Co robi |
|---|---|
| `carindb.py` | podstawy pliku: bloki, jednostki, współrzędne, nagłówek, katalog tablic |
| `unpack.py` | rozpakowanie jednostek (port 1:1 z `pbp`: czytnik bitów, sloty, kod tekstu) |
| `spindex.py` | indeks przestrzenny tablic i katalog indeksów w bloku 2 |
| `layers.py` | dekodowanie warstw do GeoPackage |
| `gpkg.py` | minimalny zapis GeoPackage przez sqlite3 (z indeksem RTree) |
| `qgis_style.py` | domyślne style QGIS zapisywane w pliku |

## Narzędzia (`tools/`)

| Skrypt | Co robi |
|---|---|
| `extract_navdb.py [obraz] [katalog]` | wypakowuje pliki płyty NAV_DB (ISO9660 w sektorach MODE2/2352) do `temp/navdb/` |
| `carindb_header.py [carindb]` | zrzut nagłówka: tablica typów rekordów i katalog tablic |
| `annotate_dbq.py IN OUT INDEX --base ADR` | podpisuje eksport z Ghidry nazwami `RECSIZE_xx` i robi indeks, które funkcje używają których typów rekordów (baza tablicy: `dbq` 0x0ef8, `pbp` 0x0cf8, `rpmod` 0x168) |

Baza i wyniki leżą w `temp/navdb/` (ignorowane przez gita).

## Ghidra (dekompilacja modułów bazy)

```bash
/opt/ghidra/support/analyzeHeadless temp/navdb/ghidra navdb_db -import temp/navdb/mods/*.mod \
    -processor 68000:BE:32:MC68030 -postScript ExportOS9Modules.java $PWD/temp/navdb/ghidra_out \
    -scriptPath $PWD/tools/ghidra -overwrite
python3 tools/ghidra/resolve_a6.py temp/navdb/mods/064_dbq.mod temp/navdb/ghidra_out/064_dbq.mod_analysis.md \
    temp/navdb/ghidra_out/064_dbq.resolved.md
```

`ExportOS9Modules.java` (skrypt Ghidry w Javie):
- tworzy funkcje od prologów `link a5`;
- ustawia konwencję Microware C (argumenty w D0/D1, potem stos);
- eksportuje pseudo-C i assembler do Markdown.

`resolve_a6.py` zamienia wywołania przez tablicę skoków w danych procesu (`unaff_A6 + -N`) na nazwy funkcji, a zmienne globalne na `g_XXXX`. Fragmentów z emulacją FPU (`trap #15` + słowo funkcji) Ghidra nie dekoduje; te miejsca czyta się capstone’em.

Projekt Ghidry jest osobny (`temp/navdb/ghidra/`), żeby nie ruszać `temp/ghidra/`. Moduły: `dbpa`, `pbp`, `dbc`, `dbd`, `dbq`, `rpmod` (router), `gd_man` (prowadzenie).
