# navdb — mapy CARiN / Carminat

Narzędzia do map nawigacji Philips CARiN / Renault Carminat (Mk2):

- **dekoder**: oryginalna baza map (`carindb` z płyty `NAV_DB`) → GeoPackage do obejrzenia w QGIS;
- **enkoder**: OpenStreetMap → własna baza map i obraz płyty dla urządzenia (i emulatora).

Format bazy jest rozpracowany statycznie, z pliku i z kodu modułów OS-9, które go czytają. Opis formatu: [docs/format.md](docs/format.md).

Wymagany jest tylko Python 3. Do enkodera dodatkowo `ogr2ogr` (pakiet GDAL).

## Co chcesz zrobić?

### A. Obejrzeć oryginalną mapę w QGIS

```bash
python3 navdb/tools/extract_navdb.py          # raz: obraz płyty cd/carin_maps_pl_2012_2013.img -> temp/navdb/carindb
python3 navdb/decoder.py --info               # co jest w bazie
python3 navdb/decoder.py --area warszawa      # Warszawa -> temp/navdb/warszawa.gpkg (kilka sekund)
python3 navdb/decoder.py                      # cała baza -> temp/navdb/carindb.gpkg (~20 min, 2,8 GB)
```

Otwórz plik `.gpkg` w QGIS. Style wczytują się same.

### B. Zrobić własną płytę z mapą z OpenStreetMap

```bash
python3 navdb/encoder.py warszawa       # Warszawa (~40 s) -> cd/carin_warszawa.img + .cue
python3 navdb/encoder.py polska         # cała Polska
python3 navdb/encoder.py serbia         # cała Serbia
python3 navdb/encoder.py beograd        # Belgrad (szybki test Serbii)
```

Jedna płyta = jeden kraj. Enkoder sam pobiera dane z Geofabrik, konwertuje je przez `ogr2ogr` i składa obraz płyty `cd/carin_REGION.img` + `.cue`.

Nowsza płyta (DVD, `DB/DB_0` + `DB/DB_1`): wystarczy dowiązanie `temp/navdb -> <płyta>/DB`, `DB_1` dołącza się sam; wynik trafia wtedy do `temp/` (katalog płyty jest tylko do odczytu). Różnice formatu: [../docs/newer_disc_format.md](../docs/newer_disc_format.md).

Przy `--area`/`--bbox` dekoder czyta tylko jednostki spod prostokąta, znalezione przez indeks przestrzenny (jak urządzenie podczas jazdy), a nie całe tablice.

Obszary: `krakow`, `warszawa`, `malopolskie`, `mazowieckie`, `polska`; bez `--area`/`--bbox` dekodowana jest cała baza. Warstwy: `roads`, `background`, `poi`, `cities`. Przy wyborze części warstw pozostałe w istniejącym pliku zostają bez zmian. Wymagany jest tylko Python 3 (bez GDAL i innych bibliotek).

Sprawdzenie wyniku:

```bash
python3 navdb/tests/check_db.py temp/navdb/warszawa/carindb
python3 navdb/tests/check_search.py temp/navdb/warszawa/carindb
```

Test w emulatorze:

```bash
tools/carin.py gui --state installed --cd carin_warszawa
```

Wypalanie na prawdziwą płytę: `cd cd && cdrdao write --device /dev/sr0 carin_warszawa.cue` (szczegóły w głównym README, „Wypalanie na prawdziwą płytę”).

### C. Sprawdzić, co zrobił enkoder

```bash
python3 navdb/decoder.py temp/navdb/warszawa/carindb -o temp/navdb/warszawa/check.gpkg   # do QGIS
python3 navdb/decoder.py temp/navdb/warszawa/carindb --info                              # kiedy i gdzie zrobiona
python3 navdb/tests/compare_osm.py temp/navdb/warszawa/check.gpkg 20.85,52.10,21.27,52.37   # długości dróg vs OSM
```

## Dekoder

```
python3 navdb/decoder.py [carindb] [-o plik.gpkg] [--area NAZWA | --bbox LON0,LAT0,LON1,LAT1]
                         [--layers roads,background,poi,cities] [--info] [-q]
```

- Obszary: `warszawa`, `mazowieckie`, `polska`. Bez `--area` i `--bbox` dekodowana jest cała baza.
- `--layers` podmienia w istniejącym pliku tylko wybrane warstwy, a pozostałe zostają.
- `--info` pokazuje dane, kraje, datę i miejsce konwersji oraz tablice.

Warstwy w GeoPackage:

| Warstwa | Zawartość |
|---|---|
| `roads` | odcinki dróg na 4 poziomach routingu (`level` 0 = wszystkie drogi): kształt, nazwa, dzielnica, miasto, kraj, klasa, kierunkowość, długość, rodzaj drogi (`fow`: autostrada, łącznica, prom…), rondo/plac (`figure`), dostęp, zakazy skrętu, czas promu, numery domów po lewej i prawej stronie |
| `parcels` | prostokąty parceli (podział mapy) |
| `areas` | tło na 6 poziomach: woda, lasy i parki, zabudowa, cmentarze, ląd |
| `overview_roads` | linie tła: rzeki, kolej, drogi główne, krajowe i wojewódzkie (`type`) |
| `poi` | punkty: nazwa, marka, kategoria, ulica, numer, dzielnica, miasto, kod pocztowy, telefon |
| `cities` | miejscowości: nazwa, gmina, inne pisownie |

**Adres w QGIS.** Na warstwie `roads` użyj „Zaznacz obiekty za pomocą wyrażenia”, np. dla Nowego Światu 29:

```
"level" = 0 AND "name" LIKE '%nowy swiat%' AND "city" = 'warszawa' AND (
  (29 BETWEEN min("hn_left_from","hn_left_to") AND max("hn_left_from","hn_left_to") AND 29 % 2 = "hn_left_from" % 2)
  OR (29 BETWEEN min("hn_right_from","hn_right_to") AND max("hn_right_from","hn_right_to") AND 29 % 2 = "hn_right_from" % 2))
```

Nazwy są zapisane małymi literami, bez polskich znaków i z „ulica”/„aleja” w nazwie, stąd `LIKE '%…%'`.

## Enkoder

```
python3 navdb/encoder.py REGION [-t TEMP] [-o PLYTA.img] [--no-compress] [--detail normal|full]
```

| Region | Co |
|---|---|
| `polska` | cała Polska |
| `dolnoslaskie` … `zachodniopomorskie` | jedno z 16 województw |
| `warszawa`, `piaseczno` | wycinki Mazowsza do testów |
| `serbia` | cała Serbia (bez Kosowa, osobny plik Geofabrik) |
| `beograd` | wycinek Serbii do testów |

- `-t TEMP` (domyślnie `temp`): folder roboczy. Pobrane dane OSM są w `TEMP/osm` (cache), a baza i pliki pośrednie w `TEMP/navdb/REGION/`.
- **Cache OSM**: plik starszy niż 7 dni — enkoder pyta, czy pobrać świeży (bez terminala używa starego). Starszy niż 30 dni — pobiera nowy bez pytania.
- `-o` (domyślnie `cd/carin_REGION.img`): obraz płyty, `.cue` obok.
- `--no-compress`: parcele dróg bez kompresji (większa płyta, przydaje się do debugowania).
- `--detail normal` (domyślnie) pomija drogi polne i nienazwane drogi serwisowe. To ok. połowa dróg w OSM, a Navteq też ich prawie nie miał. `--detail full` bierze wszystko.

Co trafia do bazy (wszystko z OSM i tylko dla wybranego obszaru):

- **Drogi** na 4 poziomach routingu, czyli tak jak w oryginale: od wszystkich ulic po same autostrady. Każda ma kształt, klasę, rodzaj (autostrada, ekspresówka, łącznica, prom), kierunkowość, ronda i ograniczenia dostępu.
- **Topologia do routingu**: skrzyżowania, przejścia między parcelami, połączenia między poziomami, czasy dojazdu do szybkich dróg.
- **Numery domów** z adresów OSM, przypisane do odcinków po lewej i prawej stronie.
- **Wyszukiwanie adresów**: kraj → gminy, miejscowości i dzielnice → ulice (po dowolnym słowie nazwy, np. „mickiewicza”) → numer.
- **POI** (podstawowe): stacje paliw, dealerzy i serwisy samochodowe, wypożyczalnie aut, P&R, hotele, szpitale, policja, dworce kolejowe i autobusowe, lotniska, muzea. Są na mapie, w wyszukiwaniu POI w mieście (gmina) i — lotniska i muzea — w całym kraju. Każdy POI ma nazwę, markę, adres, telefon i odcinek dojazdu do nawigacji. Warszawa: ok. 1600 POI.
- **Tło** na 6 poziomach przybliżenia: woda, lasy, parki, zabudowa, cmentarze, rzeki, kolej i drogi przeglądowe (A, S, krajowe, wojewódzkie).
- **Metadane konwersji**: czas w ISO 8601 (UTC, z sekundami) i nazwa komputera. Są w bazie (blok 1, `decoder.py --info`) i w pliku ABSTRACT na płycie.

Czego jeszcze nie ma:
- **listy marek POI** (menu „marka” w wyszukiwaniu POI jest puste; marka jest przy samym POI);
- **zakazy skrętu**: wymagają relacji `restriction` z OSM;
- **drogowskazy** (kierunki na znakach).

TMC (komunikaty drogowe przez RDS) jest pusty celowo, bo nie jest używany.

Dane mapy pochodzą wyłącznie z OSM. Z oryginalnej płyty enkoder bierze tylko metadane: tablicę rozmiarów rekordów, układ bloków nagłówkowych z zakresami zoomu, stałe ustawienia kraju, a dla obrazu płyty strukturę ISO, BIBLIOGR (lista zgodnych wersji oprogramowania) i CARINET.

**Kraje.** Oryginalna płyta ma 11 krajów (bg, cz, ee, hr, hu, lt, lv, pl, ro, si, sk). Numer kraju to pozycja w alfabetycznej angielskiej liście krajów ISO sprzed 2006 r. (np. pl = 171, sk = 190). Serbii na płycie nie ma, więc numer **188** (za Senegalem) jest zgadnięty. Ustawienia kraju i język nazw (chorwacki) bierze z Chorwacji. Oprogramowanie nie ma własnej listy krajów, bo nazwy krajów są na płycie, więc numer powinien wystarczyć. Nazwy cyrylicą są transliterowane na łacinkę bez znaków diakrytycznych („Кнеза Милоша” → „kneza milosa”, đ → dj). Nowy kraj dodaje się w `libs/countries.py`: numer, język, poziomy administracyjne OSM i region Geofabrik w `libs/osmsrc.py`.

**Kompresja.** Parcele dróg (największa część bazy) są kompresowane tym samym kodem bitowym co w oryginale. Kompresor to dokładna odwrotność rozpakowywania z urządzenia; na oryginalnych parcelach daje identyczny wynik po rozpakowaniu i ok. 2× mniejsze dane. Pozostałe jednostki są zapisywane nieskompresowane, co format dopuszcza.

Rozmiary (z dietą i kompresją): Warszawa ok. 15 MB, Mazowsze ok. 70 MB. Cała Polska powinna zmieścić się na płycie CD-R 80 min (ok. 730 MB); enkoder ostrzega, jeśli obraz jest za duży. Na całą Polskę enkoder potrzebuje kilkunastu GB RAM.

Dane OSM są na licencji ODbL: © OpenStreetMap contributors. Płyta zawiera tę informację w COPYRIGH.

## Jak sprawdzana jest poprawność

Bez emulatora, w trzech warstwach:

1. **Writer kontra oryginał.** Każdy zapis formatu jest sprawdzony testem w obie strony. Oryginalna jednostka jest czytana do modelu i zapisywana ponownie, a wynik ma być identyczny bajt w bajt:

   | Test | Zakres |
   |---|---|
   | `tests/test_parcelfmt.py` | parcele |
   | `tests/test_bgfmt.py` | 6356 jednostek tła |
   | `tests/test_spindex.py` | 11 indeksów przestrzennych |
   | `tests/test_pack.py` | kompresja parceli: oryginalny obraz → nasza kompresja → rozpakowanie jak w urządzeniu |

2. **Reguły struktury.** `tests/check_db.py` sprawdza reguły odkryte na oryginale:
   - pierścienie węzłów i punkty brzegowe;
   - indeks klas;
   - poziomy routingu i siatki dzieci;
   - numery domów;
   - indeksy, tło.

   `tests/check_search.py` przechodzi wyszukiwanie adresu tak jak urządzenie. Oba przechodzą także na oryginale, więc same reguły też są sprawdzone.
3. **Treść.** `tests/compare_osm.py` porównuje łączne długości dróg (per klasa, rodzaj, kierunek i nazwa) z OSM.

## Struktura katalogu

```
navdb/
  decoder.py           baza -> GeoPackage
  encoder.py           OSM -> baza
  libs/                biblioteka formatu (wspólna)
  tests/               testy w obie strony i walidatory
  tools/               wypakowanie płyty, obraz płyty, zrzut nagłówka, adnotacje Ghidry
  docs/format.md       opis formatu
```

| Moduł `libs/` | Co robi |
|---|---|
| `carindb.py` | podstawy pliku: bloki, jednostki, współrzędne, nagłówek, katalog tablic |
| `unpack.py` | rozpakowanie jednostek (port 1:1 z `pbp`) |
| `parcelfmt.py`, `bgfmt.py` | układ bajtów parceli i jednostek tła (czytanie i zapis) |
| `spindex.py` | indeksy przestrzenne (czytanie i zapis) |
| `layers.py`, `gpkg.py`, `qgis_style.py` | dekoder: warstwy, zapis GeoPackage, style QGIS |
| `osmsrc.py` | enkoder: pobieranie i konwersja regionów Geofabrik, odczyt z wielu plików |
| `countries.py` | enkoder: kraje (numer, język, poziomy administracyjne OSM) i regiony |
| `osmnet.py`, `osmplaces.py`, `osmaddr.py`, `osmbg.py`, `osmpoi.py` | enkoder: drogi, miejscowości, adresy, tło i POI z OSM |
| `pack.py` | kompresja parceli (odwrotność `pbp`) |
| `parcelbuild.py`, `levels.py`, `search.py`, `dbwrite.py` | enkoder: parcele, poziomy routingu, wyszukiwanie, składanie pliku |

| Narzędzie `tools/` | Co robi |
|---|---|
| `extract_navdb.py [obraz] [katalog]` | wypakowuje pliki płyty NAV_DB do `temp/navdb/` |
| `mkdisc.py [carindb] [-o obraz] [--chd]` | obraz płyty z naszą bazą (szablon: oryginalna płyta) |
| `carindb_header.py [carindb]` | zrzut nagłówka bazy |
| `annotate_dbq.py IN OUT INDEX --base ADR` | podpisuje eksport z Ghidry nazwami typów rekordów |

Dane, wyniki i pliki OSM leżą w `temp/` (ignorowane przez gita), obrazy płyt w `cd/`.

## Reverse engineering

Format odczytano z kodu modułów OS-9 z flasha urządzenia, dekompilowanych w Ghidrze w trybie headless:
- `pbp`: rozpakowywanie;
- `dbq`: wyszukiwanie;
- `rpmod`: routing.

Jak to powtórzyć i które funkcje są kluczowe, opisuje [docs/format.md](docs/format.md), sekcja 12.
