# Input: the intermediate module on `nav_bus` (RE status)

Reverse engineering notes, as of 2026-10-21. The buttons from the dashboard / steering wheel and the data from the radio are collected by an intermediate module (this is not the C166 slave). It sends them to the navigation unit over I2C, without the MRQ line.

## Physical layer (confirmed)

- The OS-9 device `/nav_bus` (driver `vbnavi2c`, manager `vbf`) on the I2C controller in the MCASIC (`vbi2csp2`, 0xC00020).
- The module's I2C address is 0x50 (write), 0x51 (read).
- The module's "attention" line is a level 4 IRQ (autovector 28), gated by bit 2 in 0xC0001C. When it is raised, `vbnavi2c` reads 1 status byte from 0x51.
- Status: one nibble per slot (slot 0 in the high nibble). Bit 0 = "I received the frame", bit 1 = "I have a frame for the navigation".
- Fetching a frame from slot 1: write `01 01` to 0x50, then read 0x50 bytes from 0x51 (confirmed by experiment: status 0x13 triggered exactly this).
- Slots from the `nav_bus` descriptor: slot 0 (flags 0, address 0x00), slot 1 (flags 0x02, address 0x50/0x01, 2-byte prefix), both 0x50 bytes.

## Frames navigation → module (seen on the bus)

| Frame | Meaning (hypothesis) |
|---|---|
| `01 08 00` | `vbnavi2c` initialisation |
| `00 1C 07 8F 04 03 01 00 89` | slot 0, ID 0x1C, length 7 (input state from `recv_ibus`) |
| `00 3B 06 3A 00 01 01 01` | slot 0, module address 0x3B, length 6, function 0x3A (NAOK) |

## Command dictionary (`send_ibus`)

The MMI processes send text commands (e.g. `GIKS\r`, `SAUD,0,0,0`, `NAOK,1,2,1`, `SDIS,1,%d`). `send_ibus` translates them into binary frames from a table: destination address + two function bytes.

| Command | Address | Function |
|---|---|---|
| CSIC, CCNF | 3B | F0 00 |
| SDST | 3B | 3A 23 |
| NAOK | 3B | 3A 00 |
| SAUD | 3B | 68 4E (4 data bytes) |
| SDIS, CDSP | 3B | F0 3F |
| CCTL, SMOS | 3B | F0 4F |
| STIM / SDAT | 3B | 80 40 (4) |
| GTIM / GDAT | 3B | 80 41 (4) |
| **GIKS** | 3B | **80 10**: query of the button state (hypothesis: "Get Input Keys State") |
| SGTS | 3B | 67 02 |
| SNAS | 7F | 67 02 |
| STVS | 3B | BB 4F |
| DACK, DACB, DACR, DACE, DACN | 3B | 3F A0, A1, A2, B0, FF |
| DREQ, DIRE, DRTM | 3B | 3F A0 |
| NACK…NRCP | 7F | 3F A0… (counterparts with address 0x7F) |

## Flow in OS-9

- `recv_ibus` receives frames from `/nav_bus` (`$7b0a`, up to 0x25 bytes), see "How they reach the navigation".
- State changes from the module go into the state variable table (`$a2e2`) and generate 2-byte events `[code][arg]` (0xB3–0xBD) to `/pipe/i2c_trigger`.
- `device_dialog` reads `i2c_trigger`, `bsi_nav_in` and `bsi_ctrl_c`, and answers with text commands through `uni_requests` → `send_ibus` → I2C.
- The IR remote (RC5) is a separate path: C166 slave → `/rc5` (h_ibus_dr) → `recv_ibus`.

## Message addressing (confirmed)

An internal message has the form `[source][destination][function][data]`. On the bus there is also a length byte: `[slot][source][length from itself to the end][destination][function][data]`.

- 0x3B is the navigation. `recv_ibus` treats the destinations 0xBF, 0xE7 and 0xFF like 0x3B.
- 0x80 is the car state server (the key). `GIKS` = `3B→80 fn 0x10` ("Get Ignition Key State"), answer `80→3B fn 0x11`, value 0/1/3/7 = key position. These are not buttons.
- 0x3A is the panel. `3A→3B fn 0x48` is a button, and `3A→3B fn 0x49` is the knob.
- 0xF0 is the substitute source for frames rewritten by `recv_ibus`.

Routing table in `recv_ibus` (data, offset 0x1096; `[source][destination][function] → handler`): 67 3B 01, 67 7F 01, 80 3B 11, F0 3B 11, 80 3B 23, 80 3B 24, 3A 3B 48/49/00/19/21/23/5B, F0 3B 43, 3F 3B 04/14/05/30/00/01/0E/0F/9F/9E, 3F 7F 04/14/05/30/00/01/0E/0F/0B/9F/9E/40.

## Buttons: `3A 3B 48 <byte>` (handler `recv_ibus+0x64C`)

Bits 0–5 are the code, bit 6 is a flag (for codes 2 and 3 the event is only sent with bit 6 clear, i.e. on press), bit 7 is a flag.

| Code | Event | Key (the "check KEY" test in diagnostics) |
|---|---|---|
| 0 | 0x9B → `i2c_trigger` | Mute NAV |
| 1 | 0x94 → `i2c_trigger` | Last message |
| 2 | 0xB3 (arg 1) → `i2c_trigger` | VOL+ |
| 3 | 0xB4 → `i2c_trigger` | VOL− |
| 4 | 0x83 → `i2c_trigger` | knob push (opens the menu) |
| 8 | 0x93 → MMI callback | Stand by (screen off) |
| 9 | 0xC0 → MMI callback | Address book |
| 7, 12 | 0xC1 → MMI callback | diagnostic self-test (red "auto test not ok" screen); no button on the panel, probably a service input |
| 5, 6, 10, 11 | not handled | — |

Panel: 6 buttons and a knob (A/B and push), 9 wires. The intermediate module has 11 inputs.

## Knob: `3A 3B 49 <byte>` (handler `recv_ibus+0x736`)

Bits 0–5 are the number of steps, bit 6 is the direction (negative). The result is event 0x80 with a signed value to `i2c_trigger`.

## RC5 remote: `/pack/rc5keys`

`recv_ibus` reads 1 byte at a time and turns the code into a ready message. There are three tables (selected by code 0x57 or 0x62, i.e. two remote types):

| RC5 | Message | RC5 | Message |
|---|---|---|---|
| 57 / 62 | `F0 3B 48 05` | 52 | `F0 3B 48 0D` |
| 55 / 60 | `F0 3B 49 21` | D5 / E0 | `F0 3B 49 23` |
| 56 / 61 | `F0 3B 49 A1` | D6 / E1 | `F0 3B 49 A3` |
| 50 / 5E | `F0 3B 49 E1` | D0 / DE | `F0 3B 49 E3` |
| 51 / 5F | `F0 3B 49 61` | D1 / DF | `F0 3B 49 63` |
| 1E | `F0 3B 48 0E` | 1C | `F0 3B 48 0F` |
| 10 / 66 | `F0 3B 48 1A` | 11 / 67 | `F0 3B 48 1B` |
| 3E / 77 | `F0 3B 48 1C` | 2E | `F0 3B 48 1D` |
| 47 | `F0 3B 48 1E` | 7E | `67 3B 00 01` |

The movement codes (fn 0x49) are four directions (bits 7/6) times 1 or 3 steps (bit 7 of the RC5 code = faster).

## How they reach the navigation (confirmed)

Through `/nav_bus`. `recv_ibus` opens it as path 8 and registers signal 0x2829 (SS_SSig). For SS_SSig `vbnavi2c` returns status 0x6000 (asynchronous), and `vbf` only sends the signal after a frame has been received. The reader `recv_ibus+$7b0a` reads up to 0x25 bytes and has three modes, selected by configuration:

- `(-$6d46)` = 1 (as on 0209): raw mode, the message is the frame bytes unchanged, so the source 0x3A stays;
- `(-$6d4a)` = 1: `F0 3B` + the bytes from the 3rd on (source replaced);
- default: `F0 3B` + the bytes from the 5th on; fn 0xA8 (RDS) goes separately, fn 0/1/3 are the handshake.

Sequence on I2C (emulated in `carin.cpp`, `car_frame`):

1. The module raises the attention line (IRQ4).
2. `vbnavi2c` reads the status from 0x51 (1 byte): 0x13 = slot 1 has a frame.
3. Write `01 01` to 0x50, then read 0x50 bytes from 0x51: the frame `[src][len][dst][fn][data]`, len counts itself and the bytes after it (for a button `3A 04 3B 48 code`).
4. `recv_ibus` gets `3A 3B 48 code` and passes it to the handler `+0x64C`.

Other sources in `recv_ibus` (signals 0x2821–0x2829 in order): 0x2821 `/pack/rc5keys`, 0x2822 `/rc5` (h_ibus_dr, mailbox channel 8; RC5 codes turned into `F0 3B 48/49`, which the routing table does not have, so the remote does not control the MMI in this configuration), 0x2824 the data module `rds_test_if_conf`, 0x2825 `rds_time`, 0x2826 `/c0/_129` (ARCNET, reader `$7a88`: `[src][len]` and len bytes), 0x2829 `/nav_bus`.

### Channel 8 (h_ibus_dr) in the emulator

Unsolicited notification: type 6, payload `01` (data available). Read: a type 2 request, a type 0 answer with the data. Every read consumes one notification. The interrupt for the answer must come with a delay (the driver sets the waiting flag `$74` only after sending the request). Function `car_rc5` in `carin.cpp`.

## To be found out

1. Why the self-test (codes 7/12) ends with "not ok": which test the emulator does not satisfy.
2. Whether codes 5, 6, 10, 11 mean anything in the "check KEY" test.
