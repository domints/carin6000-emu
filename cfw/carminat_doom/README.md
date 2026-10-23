# Carminat Doom

Doom (doomgeneric, GPL-2) na nawigacji CARiN / Renault Carminat: 68EC030 @ 16 MHz, OS-9, ekran SCC66470 384×240 w kolorach RRRGGGBB. Startuje z płyty, flash zostaje nietknięty. WAD to Freedoom: Phase 1 (licencja BSD) okrojony do jednej mapy.

Stan: gra działa w emulatorze (E1M1, sterowanie panelem, kolory, pasek statusu) w tempie ok. 2–3 klatek/s (taktowanie emulatora; prawdziwy sprzęt pokaże benchmark z `../poc`).

## Budowanie

```bash
make -C cfw/carminat_doom chd      # cd/carminat_doom.img + .cue + .chd
tools/carin.py gui --state doom --seed --cd cd/carminat_doom.cue   # pusty flash: od razu z płyty
```

Wymaga `m68k-elf-gcc` z `m68k-elf-newlib`, `chdman` i `cd/carin_nav_sw.img`. Zip z Freedoom pobiera się sam do `build/dl/`. Binarki (`build/`, obraz, WAD) są poza gitem.

Do wypalenia jak PoC: `cd cd && cdrdao write --device /dev/sr0 carminat_doom.cue`. Płyta działa na obu wariantach sprzętu (0109 i 0209).

## Jak to działa

1. **Płyta** (`tools/cdfile.py` + `../poc/tools/mkdisc.py`): kopia NAV_SW, w której:
   - `ui_handler` (UI instalatora) to program ładujący Dooma (`loader/`);
   - `il` (instalator) to zaślepka z PoC, która tylko śpi;
   - obraz Dooma i WAD są dopisane na koniec płyty jako nowe sektory, a wpisy katalogu `language_cd/d_f.csf` i `e_f.csf` wskazują na nie (LBN i rozmiar, plus rozmiar woluminu w etykiecie). System plików CD-i zostaje bez przebudowy.
2. **Program ładujący** (`loader/loader.c`, moduł OS-9 bez zmiennych globalnych, jak PoC):
   - najpierw bierze blok na obraz, bss, stertę malloc (64 KB) i stos (32 KB), potem resztę wolnej pamięci na strefę Dooma, w maks. 8 blokach: Extension RAM (2 MB, jeśli jest), Development RAM VSC (0x680000, 512 KB), resztki RAM-u systemowego i obszaru USW. Zostawia 48 KB dla systemu. Bloki z RAM-u wideo i pamięci wspólnej slave'a, które lista wolnej pamięci też pokazuje, są trzymane do końca alokacji i oddawane, nigdy używane. Szybki RAM systemowy idzie na początek strefy, więc dane poziomu trafiają tam, a nie do wolniejszej pamięci VSC;
   - prawdziwe urządzenie 0209 nie ma Extension RAM (pierwsza wersja padała z `no RAM for the zone, error 0ED`, czyli E$NoRAM). Wolne było: 952K RAM-u systemowego, 512K Development RAM, 64K USW. W emulatorze odtwarza to `tools/carin.py ... --no-ext-ram`;
   - przy strefie z kilku bloków albo przy błędzie wypisuje mapę wolnej pamięci sprzed swoich alokacji (`F$GBlkMp`; w trakcie nie można, bo przy całkowicie zajętym obszarze pamięci to wywołanie wisi). Strefa mniejsza niż 512 KB to błąd;
   - wczytuje `/cd/language_cd/d_f.csf`, nakłada relokacje R_68K_32, zeruje bss i skacze do Dooma na nowym stosie.
3. **Obraz Dooma** (`tools/mkflat.py`): ELF zlinkowany od adresu 0 (`doom.ld`, `--emit-relocs`), przerobiony na płaski obraz z tabelą relokacji. Doom to zwykłe C ze zmiennymi globalnymi i newlib.
4. **Wywołania systemowe** (`src/syscalls.c`, `src/os9.S`): pliki to ścieżki OS-9 (tylko odczyt, I$Seek/SS_Size), konsola to UART A, `sbrk` daje stertę od programu ładującego.
5. **Backend** (`src/dg_carminat.c`):
   - `DG_ScreenBuffer` to sam bufor ekranu (384×240), więc ramka 320×200 trafia na ekran jednym kopiowaniem;
   - kolory: tabela PLAYPAL → RGB332 jest wkładana do `COLORMAP` przy każdej zmianie palety (błyski działają), a rysowanie łatek (pasek, menu, HUD), automapa i ramka idą przez tę samą tabelę.
6. **WAD** (`tools/wadstrip.py`): zostaje jedna mapa (`MAP=E1M1`). Do tego tekstury z jej sidedefów (TEXTURE1 i TEXTURE2 połączone, PNAMES przebudowane), jej flaty i sprite'y wszystkiego, co może się na niej pojawić: lista liczona z tablic stanów silnika (`info.c`, `d_items.c`), z pociskami, upuszczanymi przedmiotami i broniami gracza. Do tego grafika paska, menu i przerywnika. Bez dźwięku, muzyki i dem.
   Domyślnie (`--lite`; `--full` wyłącza) grafika gry jest cięta tak, żeby cała zmieściła się w RAM-ie urządzenia bez Extension RAM i żeby w trakcie gry nic nie było czytane z CD (każdy odczyt to seek, a pierwsza wersja na sprzęcie tak właśnie zwalniała do kilku sekund na klatkę):
   - **tekstury ścian:** zostają najczęściej używane, które mieszczą się w budżecie 64 KB (`--tex-budget`); każda inna staje się zachowaną teksturą tej samej wysokości o najbliższym średnim kolorze;
   - **płaskie tekstury:** zostaje 6 najczęściej używanych (`--flats`), bez animacji. Zachowana klatka animacji dostaje nową nazwę (np. CFLAT), bo silnik wymaga wtedy także ostatniej klatki;
   - **niebo:** pionowy gradient szerokości 8 pikseli, zbudowany ze średnich kolorów wierszy oryginalnego nieba;
   - **rzeczy na mapie:** zombie i impy (pozostałe potwory zamienione na nie), shotgun, amunicja, apteczki i klucze. Bez dekoracji, beczek, pancerzy, bonusów i ciężkiej broni;
   - **sprite'y:** tylko widok z przodu zamiast 8 obrotów i tylko klatki używane przez stany. Bez śmierci z rozerwaniem (łatka w `P_KillMobj`) i bez sprite'a gracza.

   Wynik dla E1M1: ok. 219 KB grafiki zamiast ok. 2 MB. Linia `memory` w logu pokazuje także liczbę odczytów z CD od poprzedniej linii; w trakcie gry powinno być 0.

Łatki w silniku (`third_party/doomgeneric`) są oznaczone `CARMINAT`:
- strefa z bloków od programu ładującego (`Z_Init` łączy je w jedną listę; między regionami stoi zajęty blok-płot, żeby zwalnianie nie sklejało bloków, które się nie stykają);
- bufor ekranu 320×200 w bss zamiast w strefie (strefa z małych bloków może nie mieć 64 KB w jednym kawałku);
- kolory w `R_InitColormaps`, `I_SetPalette`, `V_DrawPatch*`, automapie i `R_FillBackScreen`;
- brakujące tekstury przełączników są pomijane;
- bez śmierci z rozerwaniem (WAD lite nie ma tych klatek);
- licznik odczytów lumpów z płyty (`W_ReadLump`);
- `.csf` liczy się jako WAD;
- bez muzyki;
- bez efektu przejścia (melt);
- czekanie na przycisk przed startem gry (`D_DoomLoop`);
- `FixedMul`/`FixedDiv` przez `muls.l`/`divs.l` 68030, inline;
- `R_DrawColumnLow` w asemblerze (`src/r_draw68k.S`);
- szybki `memcpy` (`src/fastmem.S`).

Kompilacja z `-msoft-float`, bo 68EC030 nie ma FPU. Makefile odrzuca obraz z instrukcjami FPU.

## Start i log na ekranie

Cały start widać na ekranie, bez kabla do UART-a (`src/scrlog.c`: font 5×7, 64 kolumny, 28 linii, przewijanie z własnej kopii tekstu):
- program ładujący wypisuje każdy krok: bufor ekranu, strefa, otwarcie obrazu, adres, relokacje, `/nav_bus`. Błąd jest czerwony i program staje na nim;
- Doom przekierowuje na ekran wszystko, co pisze na konsolę (`W_Init`, `R_Init`…), a `stderr` (np. `I_Error`) zawsze, także w trakcie gry.

Przy READY i co 30 s gry na UART A idzie linia `memory ...`: strefa (stałe dane, cache, wolne), zużycie sterty i najgłębsze użycie stosu (program ładujący wypełnia stos wzorcem). Przy E1M1: stałe ok. 455K, sterta 50K.

Po wczytaniu poziomu pojawia się zielone **READY – PRESS ANY BUTTON**. Gra (zegar, ekran) rusza dopiero po dowolnym przycisku albo obrocie pokrętła. Jeśli coś utknie, ostatnia linia na ekranie pokazuje, gdzie. Wszystko idzie równolegle na UART A.

## Sterowanie

Panel wysyła tylko wciśnięcia (bez puszczenia), więc ruch działa na zatrzask.

| Przycisk | W grze | W menu |
|---|---|---|
| VOL+ | naprzód: wciśnij idzie, wciśnij stoi | góra |
| VOL− | wstecz, zatrzask jak wyżej | dół |
| Pokrętło ←/→ | obrót, ok. 4° na krok (ze strafe: krok w bok) | góra/dół |
| Wciśnięcie pokrętła | strzał | Enter |
| Last message | użyj (drzwi, przełączniki, odrodzenie) | |
| Address book | następna broń | |
| Mute nav | strafe: zatrzask | |
| Stand by | menu (Esc) | |

Domyślnie: niskie detale, widok `screenblocks 8`, zawsze bieg. Wszystko można zmienić w menu.

## Wydajność (emulator)

| Etap | ms na klatkę |
|---|---|
| C, pełny ekran | ~1100 |
| niskie detale, mniejszy widok | ~505 |
| `FixedMul`/`FixedDiv` 68030, `memcpy` | ~390–450 |
| `R_DrawColumnLow` w asm | ~350–400 |

Profil: skrypt Lua próbkuje PC co klatkę emulacji, próbki mapowane na symbole z `build/doom.elf`. Dalej w kolejce:
- `R_RenderSegLoop` (11%);
- kopiowanie do RAM-u wideo (6%): kopiować tylko widok, pasek tylko po zmianie;
- `V_DrawPatch` (5%);
- `R_DrawSpanLow` w asm;
- 14 gotowych colormap zamiast przeliczania przy błysku.

## Licencje

- doomgeneric: GPL-2 (`third_party/doomgeneric/LICENSE`).
- Freedoom: BSD (`build/dl/COPYING.txt`).
- Płyty się nie publikuje, bo zawiera OS-9 i oprogramowanie Philipsa/Renault. Wydaje się źródła; użytkownik buduje płytę z własnego obrazu NAV_SW.
