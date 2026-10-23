# carin6000-emu

Emulator nawigacji Philips CARiN (Renault Carminat, Mk2) oparty na MAME. 68EC030 z OS-9, wideo i napęd CD z rodziny CD-i (MCD212, CDIC).

Stan: instalacja oprogramowania z CD do flasha przechodzi, start z flasha uruchamia całą aplikację MMI bez power down (zapłon i wyświetlacz na magistrali nav są emulowane na sztywno). Ekran wideo działa (plansza startowa z ostrzeżeniem i przyciskiem OK); brakuje jeszcze wejścia z pilota/auta (szczegóły w [docs/carin_testowanie.md](docs/carin_testowanie.md), sekcja „Gdzie jesteśmy”).

## Licencja

Wydano na licencji "DO WHAT THE FUCK YOU WANT TO".
Czyli róbta co chceta to tylko AI slop.

## Zawartość repo

| Katalog | Co jest w środku |
|---|---|
| `mame/` | Drzewo źródeł MAME przycięte do jednego sterownika: `src/mame/philips/carin.cpp` (+ `carin.h`, `carin_trace.h`) i urządzeń, których używa. Bazą jest upstream MAME, commit `b1f71f8f`. |
| `roms/carin/` | `bootrom_0209.bin` (bootrom 2.21, sprzęt 0209) i `nv.img` (seed pamięci NV). |
| `roms/carin0109/` | `bootrom_0109.bin` (bootrom 1.21 z płyty NAV_SW, `Mk2IC/0109`) i `nv.img` (seed NV z identyfikatorem `Mk2IC0109`). |
| `cd/` | Obrazy płyt, nie są w repo (`.gitignore`): oprogramowanie `carin_nav_sw` i mapy, np. `carin_maps_pl_2012_2013` (`.chd` albo `.cue` + `.img`). Opis w [cd/README.md](cd/README.md). |
| `tools/` | `carin.py` (budowanie i uruchamianie) oraz narzędzia analityczne. |
| `navdb/` | Mapy: dekoder oryginalnej bazy map do GeoPackage (QGIS) i enkoder OpenStreetMap → własna płyta z mapą. Opis w [navdb/README.md](navdb/README.md), format w [navdb/docs/format.md](navdb/docs/format.md). |
| `cfw/` | Własne oprogramowanie na płytę (custom firmware): [`cfw/poc`](cfw/poc/README.md) (hello world, przyciski, π, benchmark RAM/wideo na prawdziwy sprzęt) i [`cfw/carminat_doom`](cfw/carminat_doom/README.md) (port Dooma, w budowie). Binarki (`build/`, moduły, obrazy, WAD-y) są poza gitem. |
| `docs/` | Notatki z reverse engineeringu. |
| `state/` | Stany maszyny (NV + flash). Ignorowany przez gita. |
| `logs/` | Log builda i logi kolejnych uruchomień. Ignorowany przez gita. |
| `temp/` | Brudnopis: wyciągnięte pliki, projekty Ghidry itp. Ignorowany przez gita. |

## Wymagania

- kompilator C++ (GCC lub Clang), `make`, Python 3.9+
- biblioteki deweloperskie MAME dla Linuksa: SDL2, SDL2_ttf, fontconfig, ALSA/PulseAudio, Qt 6 (debugger) i X11
  - Arch: `pacman -S base-devel sdl2 sdl2_ttf fontconfig libpulse alsa-lib qt6-base libxinerama`
  - Debian/Ubuntu: `apt install build-essential libsdl2-dev libsdl2-ttf-dev libfontconfig-dev libpulse-dev libasound2-dev qt6-base-dev libxinerama-dev`
- `chdman` (pakiet `mame-tools` lub `mame`), żeby zrobić obraz CHD

## Szybki start

```bash
# 1. Budowanie (pierwszy raz kilka–kilkanaście minut, zależnie od liczby rdzeni)
tools/carin.py build

# 2. Płyta: wrzuć carin_nav_sw.chd do cd/, albo carin_nav_sw.cue + .img i zrób z nich CHD:
tools/carin.py chd                # dowolną inną: tools/carin.py chd NAZWA

# 3. Pierwsze uruchomienie: instalacja z CD do flasha (ok. 150 s czasu emulacji, przy
#    domyślnym -nothrottle kilka sekund; konsola pokaże "il: Release loaded correctly",
#    potem zamknij MAME)
tools/carin.py gui --seed --state installed

# 4. Kolejne uruchomienia: start z zainstalowanego oprogramowania
tools/carin.py gui --state installed
```

Instalację można też zrobić bez okna, w kilka sekund: `tools/carin.py run 200 --seed --state installed`.

Wszystkie opcje: `tools/carin.py --help` oraz `tools/carin.py run --help` / `gui --help`. Skrypt nie czyta zmiennych środowiskowych.

## Płyta w napędzie

Do instalacji i zmiany języka potrzebna jest płyta z oprogramowaniem, a do jazdy płyta z mapami. Płytę wybiera się przy każdym uruchomieniu (`run` i `gui`):

| Opcja | Działanie |
|---|---|
| (brak) | pusty napęd; z `--seed` płyta `cd/carin_nav_sw` (instalacja) |
| `--cd NAZWA` | `cd/NAZWA.chd` albo `cd/NAZWA.cue`, np. `--cd carin_maps_pl_2012_2013` |
| `--cd ŚCIEŻKA` | dowolny obraz (`.chd`, `.cue`, `.iso`…) |
| `--no-cd` | pusty napęd |

```bash
tools/carin.py gui --state installed --cd carin_maps_pl_2012_2013   # nawigacja z mapami
tools/carin.py gui --state installed --cd ~/obrazy/inna_plyta.cue
```

Jak w aucie: z zainstalowanym softem urządzenie startuje z flasha także z płytą w napędzie, a o starcie z płyty decyduje sam soft. Płytę z oprogramowaniem (NAV_SW, zmiana języka) rozpoznaje działający system: ustawia w NV flagę sw-load, a po zamknięciu planszy „Attention!” się wyłącza. Gdy master skończy i powtarza prośbę o wyłączenie (MCASIC C0000F bit 7), slave go restartuje (emulator robi wtedy reset strony mastera), a bootrom widzi flagę i ładuje instalator z płyty. Na koniec IL wysuwa płytę i prosi o OK, potem kolejny restart i start z flasha.

Uwaga: przy zainstalowanym flashu bootrom startuje dziś zawsze z flasha, nawet z płytą `NAV_SW` w napędzie. Na prawdziwym sprzęcie płyta ma pierwszeństwo, więc to jest do poprawienia.

### Wypalanie na prawdziwą płytę

Nagrywa się `cdrdao` z pliku `.cue` (obraz to jedna ścieżka MODE2/2352, więc zwykłe nagrywanie ISO nie zadziała), z katalogu `cd/`. `cdrdao` szuka `.img` z `.cue` względem bieżącego katalogu:

```bash
sudo pacman -S cdrdao
cd cd
cdrdao write --device /dev/sr0 NAZWA.cue
```

Obraz jest tylko jako CHD? Najpierw `chdman extractcd -i NAZWA.chd -o NAZWA.cue -ob NAZWA.img`. Płyta musi być czysta: nieudana próba zapisu psuje CD-R.

## Stan maszyny: seed albo własny seed

Stan to pliki w `state/<nazwa>/`: `nv` (8 KB NV), `flash0..3` (główny flash), `bootflash` i `bootflash2` (dwa układy flasha rozruchowego po 1 MB: bootrom, dane głosowe/językowe, flash slave'a) i `mk48t08`. Stany zainstalowane przed dodaniem `bootflash2` mają niepełne dane językowe: trzeba je zainstalować od nowa (`--seed` albo płyta NAV_SW). Domyślna nazwa to `default`. Zamiast nazwy można podać ścieżkę. MAME pracuje bezpośrednio na tym katalogu, więc każde uruchomienie kontynuuje poprzednie.

**Z seeda** (`--seed`): flash jest pusty, NV pochodzi z `roms/carin/nv.img`. Bootrom nie znajdzie oprogramowania we flashu, więc załaduje instalator z CD i zaprogramuje flash (ok. 150 s czasu emulacji, a bez okna to kilka sekund).

```bash
tools/carin.py run 200 --seed                    # instalacja do state/default
tools/carin.py run 200 --seed --state installed  # instalacja do state/installed
```

**Z własnego seeda** (`--load KATALOG`): stan jest zastępowany kopią plików z podanego katalogu, np. zachowanego snapshotu. Oryginał zostaje nienaruszony.

```bash
tools/carin.py run 60 --save-to ~/carin_snapshots/po_instalacji --state installed   # zrób snapshot
tools/carin.py gui --load ~/carin_snapshots/po_instalacji --state proba             # start z niego
```

**Bez flag** stan jest kontynuowany, a jeśli katalog jest pusty, maszyna startuje jak z seeda.

**Wariant sprzętu** (`--hw 0209` albo `--hw 0109`, domyślnie 0209). Płyta NAV_SW ma oprogramowanie dla dwóch wariantów: `Mk2IC/0209` i `Mk2IC/0109`, z osobnymi `loader.ini` (instalator) i `slave.apl`, a aplikacja jest wspólna. Wariant wynika z fabrycznego identyfikatora w NV (blok `phil_id`: `Mk2IC0209` albo `Mk2IC0109`): bootrom i IL budują z niego ścieżkę na płycie. Dla 0109 emulator uruchamia system MAME `carin0109` z bootromem 1.21 i seedem NV z `roms/carin0109/`. Stan zapamiętuje swój wariant w `state/<nazwa>/hw`, więc `--hw` podaje się tylko przy pierwszym uruchomieniu:

```bash
tools/carin.py run 300 --seed --hw 0109 --state hw0109   # instalacja na sprzęcie 0109
tools/carin.py gui --state hw0109 --cd carin_maps_pl_2012_2013
```

| Opcja | Działanie |
|---|---|
| `--state NAZWA\|ŚCIEŻKA` | który stan (domyślnie `state/default`) |
| `--seed` | wyczyść stan: pusty flash, NV z `nv.img` |
| `--load KATALOG` | wczytaj stan z katalogu (własny seed) |
| `--save-to KATALOG` | po zakończeniu skopiuj stan do katalogu |
| `--no-ext-ram` | bez 2 MB Extension RAM pod 0xA00000 (`-ram 2m`), jak prawdziwe urządzenie 0209; mapy z płyty go potrzebują |

## Bez okna (headless)

```bash
tools/carin.py run            # 30 s emulacji
tools/carin.py run 90         # 90 s
tools/carin.py run 90 -b      # najpierw przebuduj
```

Emulacja idzie najszybciej, jak się da (`--realtime` zwalnia do czasu rzeczywistego), bez obrazu i dźwięku. Na końcu skrypt drukuje raport (~80 linii): zdarzenia, liczniki, gdzie stoi CPU, końcówkę konsoli OS-9 i kanałów śledzenia.

## Z oknem (GUI)

```bash
tools/carin.py gui --state installed
tools/carin.py gui --state installed --debug     # z debuggerem MAME
tools/carin.py gui --state installed --realtime  # w tempie prawdziwego urządzenia
tools/carin.py gui -- -resolution 1320x1248      # dodatkowe opcje MAME po "--"
```

Otwiera się jedno okno (layout `mame/src/mame/layout/carin.lay`): u góry ekran nawigacji, obok panel z przyciskami do klikania myszką (PANEL: przyciski i pokrętło `<` PUSH `>`; SERVICE: autotest i nieużywane kody; CAR: miejsce na emulator auta), pod spodem konsola OS-9 (UART A). UART B ląduje tylko w `uart_b.txt`. Inne widoki (sama nawigacja, nawigacja z panelem, sama konsola) są w menu MAME (Tab → Video Options).

Zapłon: przycisk IGNITION w sekcji CAR panelu albo klawisz **I** (przełącznik). Po wyłączeniu system po ok. 25 s zapisuje ustawienia do NV i się wyłącza, a slave odcina zasilanie (czarny ekran). Ponowne włączenie zapłonu uruchamia urządzenie. Tak wymusza się zapis ustawień przed zamknięciem MAME.

Klawiatura: 1 Mute nav, 2 Last message, 3 VOL+, 4 VOL−, 5 wciśnięcie pokrętła, 7 Stand by, 8 Address book, ←/→ pokrętło; 6 i 9 uruchamiają autotest diagnostyczny; Q/W/E/R to kody nieobsługiwane przez soft. Nazwy i klawisze można zmienić w MAME (Tab → Input). Emulacja domyślnie idzie najszybciej, jak się da (`-nothrottle`); `--realtime` zwalnia ją do prędkości prawdziwego urządzenia. Menu MAME (Tab) działa zawsze, `gui` uruchamia MAME z `-ui_active`. Płytę wkłada się w trakcie przez Tab → File Manager → cdrom (wyjęcie: „[empty slot]”).

## Własne płyty (cfw)

W `cfw/` są dwie osobne płyty z własnym oprogramowaniem (custom firmware). Każda to kopia płyty NAV_SW, na której `sysgo` zamiast UI instalatora (`ui_handler`) uruchamia nasz program, a instalator `il` jest zastąpiony zaślepką, która tylko śpi. Flash zostaje nietknięty, a ta sama płyta działa na obu wariantach sprzętu (0109 i 0209).

| Płyta | Projekt | Co robi |
|---|---|---|
| `cd/carin_poc` | [`cfw/poc`](cfw/poc/README.md) | HELLO WORLD, licznik z przycisków, cyfry π. W pasku tytułu benchmark na prawdziwy sprzęt: wolny RAM, kopiowanie ramki do pamięci wideo, rysowanie kolumn. |
| `cd/carminat_doom` | [`cfw/carminat_doom`](cfw/carminat_doom/README.md) | Doom (doomgeneric) z Freedoom E1M1, sterowanie panelem z zatrzaskiem. |

**Wymagania:** `m68k-elf-gcc`, `m68k-elf-newlib` i `m68k-elf-binutils` (Arch: AUR), `python3`, `chdman` (pakiet `mame-tools`), `curl` i `unzip` (Doom pobiera Freedoom sam) oraz obraz `cd/carin_nav_sw.img` + `.cue`.

**Budowanie:**

```bash
make -C cfw            # obie płyty
make -C cfw poc        # tylko cd/carin_poc.{img,cue,chd}
make -C cfw doom       # tylko cd/carminat_doom.{img,cue,chd}
make -C cfw clean
```

**Test w emulatorze.** Z pustym flashem (`--seed`) bootrom od razu startuje z płyty. Z zainstalowanym stanem płyta działa jak aktualizacja: zamknij planszę „Attention!”, urządzenie się zrestartuje i wystartuje z płyty.

```bash
tools/carin.py gui --state poc  --seed --cd cd/carin_poc.cue
tools/carin.py gui --state doom --seed --cd cd/carminat_doom.cue
tools/carin.py gui --state poc0109 --load state/hw0109 --cd cd/carin_poc.cue   # jak aktualizacja, sprzęt 0109
```

**Nagrywanie** na CD-R, z katalogu `cd/` (szczegóły w sekcji „Wypalanie na prawdziwą płytę”):

```bash
cd cd && cdrdao write --device /dev/sr0 carin_poc.cue
cd cd && cdrdao write --device /dev/sr0 carminat_doom.cue
```

Na prawdziwym sprzęcie warto najpierw wypalić PoC i odczytać benchmark z paska tytułu. Obrazów płyt nie publikuje się, bo zawierają OS-9 i oprogramowanie Philipsa/Renault. Każdy buduje je z własnego obrazu NAV_SW.

## Mapy z OpenStreetMap (navdb)

Własną płytę z mapą (jeden kraj) robi się z danych OSM. Enkoder sam je pobiera z Geofabrik:

```bash
python3 navdb/encoder.py warszawa             # drogi, routing, adresy, POI, tło -> cd/carin_warszawa.img/.cue
python3 navdb/encoder.py polska               # cała Polska (także: serbia, województwa)
tools/carin.py gui --state installed --cd carin_warszawa
```

Regiony, opcje, ograniczenia (na razie bez zakazów skrętu) i weryfikacja: [navdb/README.md](navdb/README.md).

## Logi

Każde uruchomienie dostaje własny katalog `logs/<data>_<czas>_<run|gui>_<stan>/`, a `logs/latest` wskazuje na ostatni:

- `uart_a.txt`, `uart_b.txt`: konsole OS-9 (DUART kanał A/B)
- `report.txt`: raport jak po `run`
- `mame.log`: wyjście MAME
- `trace/`: `events.log` (czytaj pierwszy), `summary.txt` i kanały `ipc`, `mailbox`, `mcasic`, `arcnet`, `duart`, `nv`, `irq`, `cdrom`, `video`

Opcje: `--trace off`, `--trace ipc,nv` (tylko wybrane kanały), `--trace-cap BAJTY`. Raport dla starego katalogu: `tools/carin.py report logs/<katalog>`. Log builda: `logs/build.log`.

Katalog logów z sesji GUI nadaje się do wysłania jako feedback.

## Sonda (zrzut stanu, podgląd magistrali)

```bash
tools/carin.py run 13 --state installed --probe-at 12.3 --probe-mem 9F8800:64 --probe-wtap 9F8800-9F88FF
```

Wynik trafia do `trace/probe.log` w katalogu logów. Pozostałe opcje to `--probe-rtap` (odczyty), `--probe-bp "adres:wyrażenia;..."`, `--probe-exit`, `--probe-regs` i `--probe-stack`.

## Narzędzia

| Skrypt | Do czego |
|---|---|
| `tools/carin.py` | build, run, gui, chd [NAZWA], report |
| `tools/extract_cd.py [obraz] [katalog]` | wyciąga pliki z płyty (domyślnie do `temp/extracted_cd/`); raport używa stamtąd `loader.ini` do nazywania modułów |
| `tools/carin_flash_modules.py state/installed [katalog]` | lista modułów OS-9 we flashu, opcjonalnie wyciąga je do katalogu |
| `tools/unpack_os9.py plik katalog` | wyciąga moduły OS-9 z dowolnego pliku (np. `loader.ini`) |
| `tools/ghidra/export_os9_modules.py [moduły] [wyjście]` | analiza modułów w headless Ghidrze i eksport do Markdown |
| `tools/carin_probe.lua` | skrypt Lua sondy, uruchamiany przez `carin.py run --probe-*` |

## Praca na sterowniku

Kod sterownika jest w `mame/src/mame/philips/carin.cpp`. Po zmianach wystarczy `tools/carin.py build` albo `run -b`. Drzewo MAME zawiera tylko pliki potrzebne do zbudowania tego sterownika, więc dodanie urządzenia spoza obecnego zestawu wymaga dogrania jego źródeł z upstreamu (ten sam commit `b1f71f8f`).

## Uwagi prawne

Bootrom, obraz NV i oprogramowanie z płyty pochodzą z urządzenia z lat 90., którego producent od dawna go nie wspiera. Traktujemy je jako abandonware o znaczeniu wyłącznie hobbystycznym. MAME jest na licencji GPL-2.0+ (pliki w `mame/` zachowują swoje nagłówki licencyjne, patrz `mame/COPYING`).
