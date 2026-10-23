#!/usr/bin/env python3
"""Strips a Doom IWAD down to one map, so the engine's tables and cache fit the CARiN's RAM.

usage: wadstrip.py IN.wad OUT.wad [--map E1M1] [--info .../info.c --items .../d_items.c]

Kept: the map's lumps; the textures its sidedefs use (TEXTURE1/PNAMES rewritten, only their
patches kept), its flats; the sprites of everything the map can show (computed from the engine's
own state tables: map things, their states, the missiles they fire, what they drop, the player's
weapons); animation ranges the map touches; the sky; status bar, menu, HUD font and intermission
graphics; PLAYPAL, COLORMAP and the identity lumps. Dropped: other maps, sounds, music, demos.

--lite (the default; --full turns it off) cuts what the game draws down to what fits the RAM of a
CARiN without Extension RAM (about 280 KB of zone cache), so that nothing is read from the CD
during play:
- map things: only zombiemen and imps (other monsters become one of them), the shotgun, clips,
  shells, stimpacks, medikits and keys; no decorations, barrels, armor, bonuses or heavy weapons;
- sprites: one view (rotation 0, the front) instead of eight, only the frames the kept states
  use, without the gib deaths (the engine is patched to always play the normal death) and without
  the player's own sprite (never seen in single player);
- wall textures: the most used ones that fit --tex-budget bytes; every other texture becomes the
  kept one of the same height closest in average colour (TEXTURE1 and SIDEDEFS rewritten);
- flats: the same with --flats (a count), no animations;
- sky: an 8 pixel wide vertical gradient made from the sky's rows instead of the 256 wide picture.
"""
import argparse
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOOM_SRC = ROOT / "third_party/doomgeneric/doomgeneric"

MAP_LUMPS = ("THINGS", "LINEDEFS", "SIDEDEFS", "VERTEXES", "SEGS", "SSECTORS", "NODES", "SECTORS",
             "REJECT", "BLOCKMAP")
# Whole lumps by exact name or prefix (graphics drawn directly, engine tables).
KEEP_NAMES = {"PLAYPAL", "COLORMAP", "ENDOOM", "FREEDOOM", "TITLEPIC", "HELP1", "HELP2", "CREDIT",
              "INTERPIC", "VICTORY2", "ENDPIC"}
KEEP_PREFIXES = ("ST", "M_", "WI", "AMMNUM", "BRDR_")
# Texture/flat animations (p_spec.c animdefs): if the map uses any member, the whole range stays.
TEXTURE_ANIMS = [("BLODGR1", "BLODGR4"), ("SLADRIP1", "SLADRIP3"), ("BLODRIP1", "BLODRIP4"),
                 ("FIREWALA", "FIREWALL"), ("GSTFONT1", "GSTFONT3"), ("FIRELAVA", "FIRELAV3"),
                 ("FIREMAG1", "FIREMAG3"), ("FIREBLU1", "FIREBLU2"), ("ROCKRED1", "ROCKRED3"),
                 ("BFALL1", "BFALL4"), ("SFALL1", "SFALL4"), ("WFALL1", "WFALL4"), ("DBRAIN1", "DBRAIN4")]
FLAT_ANIMS = [("NUKAGE1", "NUKAGE3"), ("FWATER1", "FWATER4"), ("SWATER1", "SWATER4"),
              ("LAVA1", "LAVA4"), ("BLOOD1", "BLOOD3"), ("RROCK05", "RROCK08"), ("SLIME01", "SLIME04"),
              ("SLIME05", "SLIME08"), ("SLIME09", "SLIME12")]
# Mobjs spawned by code rather than by state fields: action function -> spawned types.
ACTION_SPAWNS = {
    "A_TroopAttack": ["MT_TROOPSHOT"], "A_HeadAttack": ["MT_HEADSHOT"], "A_BruisAttack": ["MT_BRUISERSHOT"],
    "A_CyberAttack": ["MT_ROCKET"], "A_FatAttack1": ["MT_FATSHOT"], "A_FatAttack2": ["MT_FATSHOT"],
    "A_FatAttack3": ["MT_FATSHOT"], "A_SkelMissile": ["MT_TRACER"], "A_Tracer": ["MT_SMOKE"],
    "A_BspiAttack": ["MT_ARACHPLAZ"], "A_VileTarget": ["MT_FIRE"], "A_PainAttack": ["MT_SKULL"],
    "A_PainDie": ["MT_SKULL"], "A_FireMissile": ["MT_ROCKET"], "A_FirePlasma": ["MT_PLASMA"],
    "A_FireBFG": ["MT_BFG"], "A_BFGSpray": ["MT_EXTRABFG"], "A_BrainSpit": ["MT_SPAWNSHOT"],
    "A_SpawnFly": ["MT_SPAWNFIRE"], "A_BrainScream": ["MT_ROCKET"], "A_BrainExplode": ["MT_ROCKET"],
}
DROPS = {"MT_WOLFSS": "MT_CLIP", "MT_POSSESSED": "MT_CLIP", "MT_SHOTGUY": "MT_SHOTGUN", "MT_CHAINGUY": "MT_CHAINGUN"}
# Always there: the player, hitscan puffs and blood, fogs.
ALWAYS = ["MT_PLAYER", "MT_PUFF", "MT_BLOOD", "MT_TFOG", "MT_IFOG"]
# Weapon pickups -> weapon index in weaponinfo (fist and pistol are always available).
PICKUP_WEAPON = {"MT_SHOTGUN": 2, "MT_CHAINGUN": 3, "MT_MISC27": 4, "MT_MISC28": 5, "MT_MISC25": 6,
                 "MT_MISC26": 7, "MT_SUPERSHOTGUN": 8}
WEAPON_SPAWNS = {4: ["MT_ROCKET"], 5: ["MT_PLASMA"], 6: ["MT_BFG", "MT_EXTRABFG"]}
# --lite: map thing types kept (None: dropped, a number: replaced by that type). Player starts
# (1-4, 11) and teleport destinations (14) have no sprite and stay.
LITE_KEEP = {1, 2, 3, 4, 11, 14,
             3004, 3001,                  # zombieman, imp
             2001,                        # shotgun
             2007, 2008,                  # clip, shells
             2011, 2012,                  # stimpack, medikit
             5, 6, 13, 38, 39, 40,        # keys
             2025}                        # radiation suit (slime levels)
LITE_REPLACE = {9: 3004, 65: 3004, 84: 3004,                     # shotgun guy, chaingunner, SS -> zombieman
                3002: 3001, 58: 3001, 3006: 3001, 3005: 3001,    # demon, spectre, lost soul, caco -> imp
                3003: 3001, 69: 3001, 68: 3001, 71: 3001, 66: 3001, 67: 3001, 64: 3001, 16: 3001, 7: 3001,
                2048: 2007, 2049: 2008, 2013: 2012}              # boxes -> single ammo, soulsphere -> medikit
LITE_SKIP_SPRITES = {"PLAY"}
STATE_FIELDS = ("spawnstate", "seestate", "painstate", "meleestate", "missilestate", "deathstate",
                "xdeathstate", "raisestate")


def read_wad(path):
    data = path.read_bytes()
    ident, count, offset = struct.unpack_from("<4sii", data, 0)
    lumps = []
    for i in range(count):
        pos, size, name = struct.unpack_from("<ii8s", data, offset + 16 * i)
        lumps.append((name.rstrip(b"\0").decode("latin1").upper(), data[pos:pos + size]))
    return ident, lumps


def write_wad(path, ident, lumps):
    body = bytearray(b"\0" * 12)
    directory = bytearray()
    for name, data in lumps:
        directory += struct.pack("<ii8s", len(body), len(data), name.encode("latin1"))
        body += data
    struct.pack_into("<4sii", body, 0, ident, len(lumps), len(body))
    path.write_bytes(bytes(body + directory))


def parse_states(info_c):
    """states[]: name -> (sprite, frame, action, next)."""
    states = {}
    for m in re.finditer(r"\{SPR_(\w+),\s*(\d+),\s*[^,]+,\s*\{(\w+)\},\s*(\w+),[^}]*\},\s*//\s*(\w+)", info_c):
        sprite, frame, action, nxt, name = m.groups()
        states[name] = (sprite, int(frame) & 0x7fff, action, nxt)
    return states


def parse_mobjs(info_c):
    """mobjinfo[]: MT name -> {field: value}."""
    mobjs = {}
    for m in re.finditer(r"\{\s*//\s*(MT_\w+)(.*?)\n\s*\}", info_c, re.S):
        fields = {}
        for v, f in re.findall(r"\n\s*([^\n]*?),?\s*//\s*(\w+)", m.group(2)):
            fields[f] = v.strip().rstrip(",")
        mobjs[m.group(1)] = fields
    return mobjs


def parse_weapons(items_c):
    body = items_c[items_c.index("weaponinfo[NUMWEAPONS]"):]
    weapons = []
    for block in re.findall(r"\{\s*//[^\n]*\n(.*?)\}", body, re.S)[:9]:
        weapons.append([s for s in re.findall(r"\b(S_\w+)", block)])
    return weapons


def sprites_for_map(things, info_c, items_c, lite=False):
    """The sprites the map can show: name -> the highest frame used (frames 0..n must exist)."""
    states = parse_states(info_c)
    fields = [f for f in STATE_FIELDS if not (lite and f in ("xdeathstate", "raisestate"))]
    mobjs = parse_mobjs(info_c)
    weapons = parse_weapons(items_c)
    by_ednum = {}
    for name, f in mobjs.items():
        try:
            by_ednum[int(f.get("doomednum", "-1"))] = name
        except ValueError:
            pass
    types = set(ALWAYS if not lite else ["MT_PLAYER", "MT_PUFF", "MT_BLOOD"])
    for t in things:
        if t in by_ednum:
            types.add(by_ednum[t])
    weapon_ids = {0, 1}
    sprites, seen_states, todo = {}, set(), list(types)
    done_types = set()

    def walk(state):
        while state and state != "S_NULL" and state not in seen_states and state in states:
            seen_states.add(state)
            sprite, frame, action, nxt = states[state]
            sprites[sprite] = max(sprites.get(sprite, 0), frame)
            for spawned in ACTION_SPAWNS.get(action, []):
                todo.append(spawned)
            state = nxt

    while todo:
        t = todo.pop()
        if t in done_types or t not in mobjs:
            continue
        done_types.add(t)
        if t in DROPS:
            todo.append(DROPS[t])
        if t in PICKUP_WEAPON:
            weapon_ids.add(PICKUP_WEAPON[t])
        for field in fields:
            walk(mobjs[t].get(field))
    walk("S_GIBS")   # p_map.c: a corpse crushed by a door or a ceiling
    for w in sorted(weapon_ids):
        if w < len(weapons):
            for s in weapons[w]:
                walk(s)
        for spawned in WEAPON_SPAWNS.get(w, []):
            todo.append(spawned)
    while todo:   # missiles of the weapons
        t = todo.pop()
        if t in done_types or t not in mobjs:
            continue
        done_types.add(t)
        for field in fields:
            walk(mobjs[t].get(field))
    return sprites


def textures_by_name(texture1):
    count = struct.unpack_from("<i", texture1, 0)[0]
    offsets = struct.unpack_from(f"<{count}i", texture1, 4)
    result = []
    for off in offsets:
        name = texture1[off:off + 8].rstrip(b"\0").decode("latin1").upper()
        patchcount = struct.unpack_from("<h", texture1, off + 20)[0]
        result.append((name, texture1[off:off + 22 + 10 * patchcount]))
    return result


def anim_range(names, start, end):
    if start in names and end in names:
        a, b = names.index(start), names.index(end)
        return names[min(a, b):max(a, b) + 1]
    return []


def patch_columns(data):
    """A patch (picture) lump: width, height and per column the list of (top, bytes) posts."""
    width, height = struct.unpack_from("<hh", data, 0)
    cols = []
    for x in range(width):
        pos = struct.unpack_from("<i", data, 8 + 4 * x)[0]
        posts = []
        while data[pos] != 0xff:
            top, length = data[pos], data[pos + 1]
            posts.append((top, data[pos + 3:pos + 3 + length]))
            pos += length + 4
        cols.append(posts)
    return width, height, cols


def make_patch(cols, height):
    """A patch from columns of full-height pixel bytes (one post each)."""
    width = len(cols)
    head = struct.pack("<hhhh", width, height, 0, 0)
    body, offs = bytearray(), []
    base = 8 + 4 * width
    for c in cols:
        offs.append(base + len(body))
        body += bytes([0, height, 0]) + bytes(c) + bytes([0, 0xff])
    return head + struct.pack(f"<{width}i", *offs) + bytes(body)


def average_rgb(pixels, palette):
    if not pixels:
        return (0, 0, 0)
    n = len(pixels)
    return tuple(sum(palette[3 * p + k] for p in pixels) / n for k in range(3))


def nearest_index(rgb, palette):
    return min(range(256), key=lambda i: sum((palette[3 * i + k] - rgb[k]) ** 2 for k in range(3)))


def color_distance(a, b):
    return sum((a[k] - b[k]) ** 2 for k in range(3))


def lite_textures(textures, pnames, lump, used_tex, use_count, palette, budget):
    """Picks the textures to keep and maps every used texture to one of them."""
    info = {}
    for name, raw in textures:
        if name not in used_tex or name == "SKY1":
            continue
        width, height, count = (*struct.unpack_from("<hh", raw, 12), struct.unpack_from("<h", raw, 20)[0])
        patches = {pnames[struct.unpack_from("<h", raw, 22 + 10 * k + 4)[0]] for k in range(count)}
        cost = sum(len(lump.get(p, b"")) for p in patches)
        if count > 1:
            cost += width * height   # the composite the engine builds
        pixels = []
        for pname in patches:
            if pname in lump:
                for col in patch_columns(lump[pname])[2]:
                    for _, px in col:
                        pixels += px
        info[name] = (height, cost, average_rgb(pixels, palette))
    kept, total = [], 0
    for name in sorted(info, key=lambda n: -use_count.get(n, 0)):
        if total + info[name][1] <= budget:
            kept.append(name)
            total += info[name][1]
    tall = [k for k in kept if info[k][0] == 128] or kept
    mapping = {}
    for name in info:
        if name in kept:
            mapping[name] = name
            continue
        same = [k for k in kept if info[k][0] == info[name][0]] or tall
        mapping[name] = min(same, key=lambda k: color_distance(info[k][2], info[name][2]))
    return kept, mapping, total


def lite_flats(flat_lumps, used_flats, use_count, palette, count):
    data = {n: d for n, d in flat_lumps if len(d) == 4096 and n in used_flats and n != "F_SKY1"}
    rgb = {n: average_rgb(d, palette) for n, d in data.items()}
    kept = sorted(data, key=lambda n: -use_count.get(n, 0))[:count]
    mapping = {n: n if n in kept else min(kept, key=lambda k: color_distance(rgb[k], rgb[n])) for n in data}
    return kept, mapping


def lite_sky(sky_patch, palette):
    """An 8 pixel wide patch: each row is the sky's average colour on that row."""
    width, height, cols = patch_columns(sky_patch)
    rows = [[] for _ in range(height)]
    for col in cols:
        for top, px in col:
            for i, p in enumerate(px):
                if top + i < height:
                    rows[top + i].append(p)
    column = [nearest_index(average_rgb(r, palette), palette) for r in rows]
    return make_patch([column] * 8, height)


def rewrite_names(data, record, fields, mapping):
    """Renames 8-byte texture/flat names in fixed-size map records."""
    out = bytearray(data)
    for i in range(0, len(out), record):
        for k in fields:
            name = out[i + k:i + k + 8].rstrip(b"\0").decode("latin1").upper()
            if name in mapping:
                out[i + k:i + k + 8] = mapping[name].encode("latin1").ljust(8, b"\0")
    return bytes(out)


def lite_things(things):
    out = bytearray()
    for i in range(0, len(things), 10):
        rec = bytearray(things[i:i + 10])
        t = struct.unpack_from("<h", rec, 6)[0]
        t = LITE_REPLACE.get(t, t)
        if t in LITE_KEEP:
            struct.pack_into("<h", rec, 6, t)
            out += rec
    return bytes(out)


def lite_sprite_lumps(sprite_lumps, sprites):
    """Rotation 0 only: the front view (rotation 1) renamed to rotation 0; frames past the last
    one a kept state uses are dropped."""
    out, have = [], set()
    for n, d in sprite_lumps:
        prefix = n[:4]
        if prefix not in sprites or len(n) < 6:
            continue
        frame = ord(n[4]) - ord("A")
        if frame > sprites[prefix] or n[5] not in "01":
            continue
        name = n[:5] + "0"
        if name not in have:
            have.add(name)
            out.append((name, d))
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("inp", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("--map", default="E1M1")
    p.add_argument("--info", type=Path, default=DOOM_SRC / "info.c")
    p.add_argument("--items", type=Path, default=DOOM_SRC / "d_items.c")
    p.add_argument("--full", dest="lite", action="store_false", help="keep every texture, flat and sprite rotation")
    p.add_argument("--tex-budget", type=int, default=64 * 1024, help="--lite: bytes of wall textures kept")
    p.add_argument("--flats", type=int, default=6, help="--lite: number of flats kept")
    a = p.parse_args()

    ident, lumps = read_wad(a.inp)
    names = [n for n, _ in lumps]
    lump = {n: d for n, d in reversed(lumps)}   # first occurrence wins
    mi = names.index(a.map.upper())
    map_lumps = [(a.map.upper(), b"")] + lumps[mi + 1:mi + 1 + len(MAP_LUMPS)]
    md = {n: d for n, d in map_lumps}

    # Textures and flats the map uses, and how often.
    def scan():
        tex, flats = {}, {}
        sd = md["SIDEDEFS"]
        for i in range(0, len(sd), 30):
            for k in (4, 12, 20):
                n = sd[i + k:i + k + 8].rstrip(b"\0").decode("latin1").upper()
                tex[n] = tex.get(n, 0) + 1
        sec = md["SECTORS"]
        for i in range(0, len(sec), 26):
            for k in (4, 12):
                n = sec[i + k:i + k + 8].rstrip(b"\0").decode("latin1").upper()
                flats[n] = flats.get(n, 0) + 1
        tex.pop("-", None)
        return tex, flats

    tex_count, flat_count = scan()
    used_tex, used_flats = set(tex_count) | {"SKY1"}, set(flat_count) | {"F_SKY1", "FLOOR7_2"}  # FLOOR7_2: view border

    textures = textures_by_name(lump["TEXTURE1"])
    if "TEXTURE2" in lump:   # Freedoom (like registered Doom) has a second list; merged into one
        textures += textures_by_name(lump["TEXTURE2"])
    tex_names = [n for n, _ in textures]
    flat_lumps = lumps[names.index("F_START") + 1:names.index("F_END")]
    flat_names = [n for n, d in flat_lumps if len(d) == 4096]
    pn = lump["PNAMES"]
    pcount = struct.unpack_from("<i", pn, 0)[0]
    pnames = [pn[4 + 8 * i:12 + 8 * i].rstrip(b"\0").decode("latin1").upper() for i in range(pcount)]
    lite_note = ""
    if a.lite:
        palette = lump["PLAYPAL"][:768]
        kept_tex, tex_map, tex_bytes = lite_textures(textures, pnames, lump, used_tex, tex_count, palette,
                                                     a.tex_budget)
        kept_flats, flat_map = lite_flats(flat_lumps, used_flats, flat_count, palette, a.flats)
        # A kept member of an animation gets a name of its own: the engine animates a range only if
        # its first and last names exist, and errors when only the first one does.
        anim_tex = {n for s_, e_ in TEXTURE_ANIMS for n in anim_range(tex_names, s_, e_)}
        anim_flats = {n for s_, e_ in FLAT_ANIMS for n in anim_range(flat_names, s_, e_)}
        renamed = {}
        for i, n in enumerate(kept_tex):
            if n in anim_tex:
                renamed[n] = f"CTEX{i}"
        for i, n in enumerate(kept_flats):
            if n in anim_flats:
                renamed[n] = f"CFLAT{i}"
        tex_map = {k: renamed.get(v, v) for k, v in tex_map.items()}
        flat_map = {k: renamed.get(v, v) for k, v in flat_map.items()}
        textures = [(renamed.get(n, n), r[:0] + renamed[n].encode("latin1").ljust(8, b"\0") + r[8:]
                     if n in renamed else r) for n, r in textures]
        tex_names = [n for n, _ in textures]
        flat_lumps = [(renamed.get(n, n), d) for n, d in flat_lumps]
        flat_names = [n for n, d in flat_lumps if len(d) == 4096]
        md["SIDEDEFS"] = rewrite_names(md["SIDEDEFS"], 30, (4, 12, 20), tex_map)
        md["SECTORS"] = rewrite_names(md["SECTORS"], 26, (4, 12), flat_map)
        md["THINGS"] = lite_things(md["THINGS"])
        map_lumps = [(n, md.get(n, d)) for n, d in map_lumps]
        tex_count, flat_count = scan()
        used_tex, used_flats = set(tex_count) | {"SKY1"}, set(flat_count) | {"F_SKY1", "FLOOR7_2"}
        # The sky: one 8 pixel wide patch, SKY1 rebuilt as that patch alone.
        sky_raw = dict(textures)["SKY1"]
        sky_patch = pnames[struct.unpack_from("<h", sky_raw, 22 + 4)[0]]
        lump = dict(lump)
        lump["CSKY"] = lite_sky(lump[sky_patch], palette)
        pnames = pnames + ["CSKY"]
        sky = bytearray(sky_raw[:22 + 10])
        struct.pack_into("<h", sky, 12, 8)                       # width
        struct.pack_into("<hhh", sky, 22, 0, 0, len(pnames) - 1)  # the one patch at 0,0
        struct.pack_into("<h", sky, 20, 1)
        textures = [(n, bytes(sky) if n == "SKY1" else r) for n, r in textures]
        lite_note = (f" lite: {len(kept_tex)} wall textures ({tex_bytes // 1024} KB), "
                     f"{len(kept_flats)} flats, sky gradient, renamed {' '.join(sorted(renamed)) or 'none'}")
    else:
        for s, e in TEXTURE_ANIMS:
            r = anim_range(tex_names, s, e)
            if used_tex & set(r):
                used_tex |= set(r)
        for s, e in FLAT_ANIMS:
            r = anim_range(flat_names, s, e)
            if used_flats & set(r):
                used_flats |= set(r)

    # TEXTURE1/PNAMES with only the kept textures (index 0 stays: it means "no texture").
    kept = [t for i, t in enumerate(textures) if i == 0 or t[0] in used_tex]
    new_pnames, remap = [], {}
    rebuilt = []
    for name, raw in kept:
        raw = bytearray(raw)
        for k in range(struct.unpack_from("<h", raw, 20)[0]):
            old = struct.unpack_from("<h", raw, 22 + 10 * k + 4)[0]
            if old not in remap:
                remap[old] = len(new_pnames)
                new_pnames.append(pnames[old])
            struct.pack_into("<h", raw, 22 + 10 * k + 4, remap[old])
        rebuilt.append(bytes(raw))
    head = 4 + 4 * len(rebuilt)
    offs, pos = [], head
    for r in rebuilt:
        offs.append(pos)
        pos += len(r)
    texture1 = struct.pack(f"<i{len(rebuilt)}i", len(rebuilt), *offs) + b"".join(rebuilt)
    pnames_lump = struct.pack("<i", len(new_pnames)) + b"".join(n.encode().ljust(8, b"\0") for n in new_pnames)

    things = md["THINGS"]
    thing_types = {struct.unpack_from("<h", things, i + 6)[0] for i in range(0, len(things), 10)}
    sprites = sprites_for_map(thing_types, (a.info).read_text(), (a.items).read_text(), a.lite)
    if a.lite:
        for name in LITE_SKIP_SPRITES:
            sprites.pop(name, None)

    out = []
    for n, d in lumps:
        if n in KEEP_NAMES or n.startswith(KEEP_PREFIXES):
            if n not in ("STEP1", "STEP2", "STARTAN1"):   # ST* also matches some flats/textures
                out.append((n, d))
    out.append(("TEXTURE1", texture1))
    out.append(("PNAMES", pnames_lump))
    out += map_lumps
    out.append(("P_START", b""))
    seen = set()
    for n in new_pnames:
        if n not in seen and lump.get(n):
            out.append((n, lump[n]))
            seen.add(n)
    missing = set(new_pnames) - seen
    out.append(("P_END", b""))
    out.append(("F_START", b""))
    out += [(n, d) for n, d in flat_lumps if n in used_flats]
    out.append(("F_END", b""))
    out.append(("S_START", b""))
    sprite_lumps = lumps[names.index("S_START") + 1:names.index("S_END")]
    if a.lite:
        kept_sprites = lite_sprite_lumps(sprite_lumps, sprites)
    else:
        kept_sprites = [(n, d) for n, d in sprite_lumps if n[:4] in sprites]
    out += kept_sprites
    out.append(("S_END", b""))
    write_wad(a.out, ident, out)

    size = a.out.stat().st_size
    print(f"{a.out}: {len(out)} lumps, {size // 1024} KB ({a.map}: {len(kept)} textures, "
          f"{len(new_pnames)} patches, {len(used_flats & set(flat_names))} flats, {len(sprites)} sprites)" + lite_note)
    in_game = (sum(len(lump[n]) for n in seen) + 4096 * len(used_flats & set(flat_names))
               + sum(len(d) for _, d in kept_sprites))
    print(f"graphics the game can draw (patches, flats, sprites): {in_game // 1024} KB")
    if missing:
        print("warning: patches not found:", " ".join(sorted(missing)))
    print("sprites:", " ".join(sorted(sprites)))


if __name__ == "__main__":
    main()
