"""Search tables for the encoder (docs/format.md section 7): countries (b, block 4) and their name
trie (c, block 3), city name trie (e), cities (d), street tries per city (10), streets with house
number ranges (f). The POI tables (7, 11, 12) come from libs/osmpoi.py; here the cities and the
countries get their POI category lists (d slot 3, block 4 slot 3). A disc can hold several
countries; each has its own city trie, the tables are shared.

Cities are the gminas (municipality = powiat) and the settlements (municipality = gmina), as in
the original; a gmina's streets have one entry for the whole gmina plus one per settlement, a
settlement's streets one entry each. Every name also gets its word rotations ("ulica adama
mickiewicza" -> "adama mickiewicza ulica", "mickiewicza ulica adama"; flags 0x1012 instead of
0x12), so a street can be found by any word.
"""
import struct
from dataclasses import dataclass, field

from .carindb import BLOCK

ROTATED = 0x1000
LEAF_MAX = 150           # a trie node becomes a leaf at this many entries (original leaves: up to ~160)
UNIT_MAX = 8 * BLOCK


def rotations(name, country, street=True):
    """The name and its word rotations, with the country's language byte: for streets of a country
    whose streets start with a street word ("ulica") that word goes where the rotation cuts; no
    rotation starts with a number."""
    words = name.split()
    lang = country.lang
    out = [(name, lang)]
    street = street and country.street_prefix
    if street and len(words) >= 2:
        head, rest = words[0], words[1:]
        for i in range(len(rest)):
            if not rest[i].isdigit():
                out.append((" ".join(rest[i:] + [head] + rest[:i]), lang | ROTATED))
    elif not street and len(words) >= 2:
        for i in range(1, len(words)):
            if not words[i].isdigit():
                out.append((" ".join(words[i:] + words[:i]), lang | ROTATED))
    return out


@dataclass(eq=False, slots=True)
class Item:
    """A run of consecutive segments of one street in one parcel (table f slot 2)."""
    pos: tuple                     # position of the settlement / town (GPS units)
    parcel: object
    seg_index: int                 # index in the parcel's segment order
    count: int
    numbers: tuple                 # even from, even to, odd from, odd to


@dataclass(eq=False)
class City:
    name: str
    muni: str
    country: object                # libs/countries.Country
    pos: tuple
    seg: tuple                     # (parcel, segment index) of the city's destination segment
    entries: list = field(default_factory=list)   # [(name, flags, settlement or None, [Item])]
    roots: object = None           # trie node list (set by the builder)
    poi: list = field(default_factory=list)       # [(category, list key)] (libs/osmpoi.py)


def _numbers(pieces):
    even, odd = [], []
    for pc in pieces:
        hn = getattr(pc, "hn", None)
        if hn:
            for v in hn[:4]:
                if v != 32767:
                    (even if v % 2 == 0 else odd).append(v)
    e = (min(even), max(even)) if even else (32767, 32767)
    o = (min(odd), max(odd)) if odd else (32767, 32767)
    return (*e, *o)


def collect(parcels, sorted_pieces, settlement_pos, countries):
    """Cities with their street entries from the level 0 parcels, per country (road.country, an
    ISO code of countries). settlement_pos(iso, name, city) -> position of a settlement or town."""
    streets = {}                   # (country, city, muni, settlement, name) -> [Item]
    for pc in parcels:
        pieces = sorted_pieces(pc)
        i = 0
        while i < len(pieces):
            rd = pieces[i].road
            j = i
            while j + 1 < len(pieces) and pieces[j + 1].road.name == rd.name and \
                    pieces[j + 1].road.settlement == rd.settlement and pieces[j + 1].road.city == rd.city \
                    and pieces[j + 1].road.country == rd.country:
                j += 1
            if rd.name:
                key = (rd.country, rd.city, rd.muni, rd.settlement, rd.name)
                pos = settlement_pos(rd.country, rd.settlement or rd.city, rd.city)
                streets.setdefault(key, []).append(Item(pos, pc, i, j - i + 1, _numbers(pieces[i:j + 1])))
            i = j + 1
    cities = {}

    def city(iso, name, muni):
        if (iso, name, muni) not in cities:
            cities[(iso, name, muni)] = City(name, muni, countries[iso],
                                             settlement_pos(iso, name, None if name == muni else muni), None)
        return cities[(iso, name, muni)]

    by_gmina = {}
    for (iso, c, m, s, n), items in streets.items():
        by_gmina.setdefault((iso, c, m, n), []).append((s, items))
        if s:
            city(iso, s, c).entries.append((n, None, None, items))
    for (iso, c, m, n), parts in by_gmina.items():
        g = city(iso, c, m)
        g.entries.append((n, None, None, [it for _, its in parts for it in its]))
        for s, its in parts:
            if s:
                g.entries.append((n, None, s, its))
    for c in cities.values():
        rows = []
        for n, _, s, items in c.entries:
            for text, flags in rotations(n, c.country):
                rows.append((text, flags, s, items))
        c.entries = sorted(rows, key=lambda r: (r[0], r[2] or ""))
    return list(cities.values())


# --- tries -------------------------------------------------------------------------------

@dataclass(eq=False)
class Node:
    char: int
    leaf: bool
    first: int                     # leaf: index of the first entry in the sorted list
    count: int
    children: list = None


def trie(names, depth=0, lo=0, hi=None, leaf_max=None, weights=None, max_weight=None):
    """Node list for names[lo:hi] (sorted) at this depth. A node becomes a leaf at leaf_max names
    and, with weights (bytes per name), max_weight bytes, unless its names cannot be split."""
    hi = len(names) if hi is None else hi
    leaf_max = leaf_max or LEAF_MAX
    nodes = []
    i = lo
    while i < hi:
        ch = names[i][depth] if depth < len(names[i]) else " "
        j = i
        while j < hi and (names[j][depth] if depth < len(names[j]) else " ") == ch:
            j += 1
        # a group can only be split while its names differ ("muzeum" and "muzeum narodowe" can)
        exhausted = names[i] == names[j - 1] if j - i > leaf_max else any(depth + 1 >= len(names[k]) for k in range(i, j))
        light = weights is None or sum(weights[i:j]) <= max_weight
        if (j - i <= leaf_max and light) or exhausted or depth > 30:
            nodes.append(Node(ord(ch), True, i, j - i))
        else:
            kids = trie(names, depth + 1, i, j, leaf_max, weights, max_weight)
            nodes.append(Node(ord(ch), False, i, len(kids), kids))
        i = j
    return nodes


def leaves(nodes):
    for nd in nodes:
        if nd.leaf:
            yield nd
        else:
            yield from leaves(nd.children)


def node_lists(nodes):
    """Every node list of a trie, parents first."""
    out = [nodes]
    for nd in nodes:
        if not nd.leaf:
            out += node_lists(nd.children)
    return out


# --- units -------------------------------------------------------------------------------

def _a4(n):
    return (n + 3) & ~3


class Texts:
    def __init__(self):
        self.order, self.size = [], 0

    def need(self, *texts):
        return sum(len(t) + 1 for t in set(texts) if t and t not in self.order)

    def add(self, t):
        if t and t not in self.order:
            self.order.append(t)
            self.size += len(t) + 1


class NameUnit:
    """One unit of table d or f: name entries (slot 0) with their records, then the texts."""

    def __init__(self, kind):
        self.kind, self.rows, self.texts = kind, [], Texts()
        self.n_runs = self.n_items = 0
        self.cities = {}                    # d: city -> its POI category records (in slot 3)

    def size_with(self, rows):
        e = len(self.rows) + len(rows)
        if self.kind == 0x0E:
            runs = self.n_runs + len(rows)
            items = self.n_items + sum(len(r[3]) for r in rows)
            body = _a4(0x30 + 8 * e) + _a4(6 * runs) + 24 * items
        else:
            new = {id(r[3]): r[3] for r in rows if id(r[3]) not in self.cities}
            cats = sum(len(c.poi) for c in self.cities.values()) + sum(len(c.poi) for c in new.values())
            body = _a4(0x30 + 8 * e) + 24 * e + 12 * cats
        texts = Texts()
        texts.order, texts.size = list(self.texts.order), self.texts.size
        for r in rows:
            for t in (r[0], r[2]):
                texts.add(t)
        return body + texts.size

    def add(self, rows):
        for r in rows:
            self.rows.append(r)
            self.texts.add(r[0])
            self.texts.add(r[2])
            self.n_runs += 1
            self.n_items += len(r[3]) if self.kind == 0x0E else 0
            if self.kind == 0x0C:
                self.cities.setdefault(id(r[3]), r[3])


def pack(groups, kind):
    """Units for consecutive row groups (a trie leaf's rows stay in one unit). Returns the units
    and, per group, (unit index, first row index)."""
    units, where = [], []
    for rows in groups:
        if not units or units[-1].size_with(rows) > UNIT_MAX:
            units.append(NameUnit(kind))
        u = units[-1]
        if u.size_with(rows) > UNIT_MAX:
            raise ValueError(f"{len(rows)} names do not fit one unit")
        where.append((len(units) - 1, len(u.rows)))
        u.add(rows)
    return units


def name_unit_bytes(u, own, nxt, prv, parcel_ptr, record, poi_list=None):
    """Bytes of a d / f unit. record(payload, category slot offset, count) -> the 24-byte city
    record (the f run and items are handled here); poi_list(key) -> (table 12 unit, offset, count)
    of a POI list."""
    off = {}
    n = len(u.rows)
    o_runs = _a4(0x30 + 8 * n)
    cat_at = {}
    if u.kind == 0x0E:
        o_items = _a4(o_runs + 6 * n)
        o_text = o_items + 24 * sum(len(r[3]) for r in u.rows)
    else:
        o_items = None
        o_cats = o_runs + 24 * n
        pos = o_cats
        for key, c in u.cities.items():
            cat_at[key] = pos
            pos += 12 * len(c.poi)
        o_text = pos                        # slot 5 (brand lists) stays empty, here
    pos = o_text
    for t in u.texts.order:
        off[t] = pos
        pos += len(t) + 1
    d = bytearray(-(-pos // BLOCK) * BLOCK)
    if u.kind == 0x0E:
        struct.pack_into(">IHHHHHHHH", d, 0, own, u.kind, 0, 0x30, n, o_runs, n, o_items,
                         sum(len(r[3]) for r in u.rows))
    else:
        struct.pack_into(">IHHHHHHHHHHHHHH", d, 0, own, u.kind, 0, 0x30, n, o_runs, n, 0, 0,
                         o_cats, sum(len(c.poi) for c in u.cities.values()), 0, 0, o_text, 0)
        for key, c in u.cities.items():
            for k, (cat, lst) in enumerate(c.poi):
                struct.pack_into(">IHHHH", d, cat_at[key] + 12 * k, *poi_list(lst), cat, o_text)
    struct.pack_into(">II", d, 0x28, nxt, prv)
    item_pos = o_items
    for i, r in enumerate(u.rows):
        name, flags, second, payload = r
        rec = o_runs + (6 if u.kind == 0x0E else 24) * i
        struct.pack_into(">HHHH", d, 0x30 + 8 * i, off[name], flags, off.get(second, 0), rec)
        if u.kind == 0x0E:
            struct.pack_into(">HBBH", d, rec, item_pos, min(len(payload), 255), 1, 0)
            for it in payload[:255]:
                struct.pack_into(">II4HIHH", d, item_pos, it.pos[0], it.pos[1], *it.numbers,
                                 parcel_ptr(it.parcel), it.parcel.seg_base + 32 * it.seg_index, it.count)
                item_pos += 24
        else:
            d[rec:rec + 24] = record(payload, cat_at[id(payload)], len(payload.poi))
    for t, o in off.items():
        d[o:o + len(t)] = t.encode("latin1")
    return bytes(d)


def pack_lists(roots):
    """Node lists of many tries spread over units of at most UNIT_MAX: a trie starts a new unit
    when it does not fit the current one, a list never spans units (children may sit in another
    unit: an inner node holds their unit pointer). Returns ([[list]] per unit, {id(list): (unit,
    offset)})."""
    units, where, size = [[]], {}, 0x0C
    for root in roots:
        lists = node_lists(root)
        if units[-1] and size + 12 * sum(len(lst) for lst in lists) > UNIT_MAX:
            units.append([])
            size = 0x0C
        for lst in lists:
            if size + 12 * len(lst) > UNIT_MAX:
                units.append([])
                size = 0x0C
            where[id(lst)] = (len(units) - 1, size)
            units[-1].append(lst)
            size += 12 * len(lst)
    return units, where


def trie_unit_bytes(own, kind, lists, place, child=None):
    """Bytes of a table 10 / e / c / 12 unit holding node lists; place(node) -> (ptr, off, count)
    for a leaf; child(list) -> (ptr, off) of an inner node's children (default: in this unit)."""
    start, pos = {}, 0x0C
    for lst in lists:
        start[id(lst)] = pos
        pos += 12 * len(lst)
    child = child or (lambda lst: (own, start[id(lst)]))
    d = bytearray(-(-pos // BLOCK) * BLOCK)
    struct.pack_into(">IHHHH", d, 0, own, kind, 0, 0x0C, (pos - 0x0C) // 12)
    for lst in lists:
        o = start[id(lst)]
        for nd in lst:
            if nd.leaf:
                ptr, off, cnt = place(nd)
                struct.pack_into(">IBBHHH", d, o, ptr, nd.char, 1, off, cnt, 0)
            else:
                ptr, off = child(nd.children)
                struct.pack_into(">IBBHHH", d, o, ptr, nd.char, 0, off, len(nd.children), 0)
            o += 12
    return bytes(d), start


def trie_table(units, where, prefix, kind, place, Unit):
    """The units of a trie table from pack_lists(); unit keys (prefix, n)."""
    def build(resolve, n):
        child = lambda lst: (resolve((prefix, where[id(lst)][0])), where[id(lst)][1])
        return trie_unit_bytes(resolve((prefix, n)), kind, units[n], place, child)[0]
    return [Unit((prefix, n), lambda resolve, n=n: build(resolve, n)) for n in range(len(units))]


def add_tables(db, cities, countries, Unit, Table, parcel_ptr, poi_list=None):
    """Registers tables e, d, 10, f and blocks 3 / 4 in a dbwrite.Database. countries = [(Country,
    template record, country-wide POI lists)]: the 56-byte country record of the original (fields
    not known are kept) and [(category, key)]; parcel_ptr(parcel) gives a level 0 parcel's unit
    pointer; poi_list(key) -> (table 12 unit, offset, count) of a POI list named in City.poi or a
    country's lists."""
    cities = sorted(cities, key=lambda c: (c.name, c.muni))
    # f: street entries per city, leaves kept in one unit
    f_groups, f_leaf = [], {}
    for c in cities:
        names = [r[0] for r in c.entries]
        weights = [8 + 6 + 24 * min(len(r[3]), 255) + len(r[0]) + 1 for r in c.entries]
        c.trie = trie(names, weights=weights, max_weight=UNIT_MAX * 3 // 4)
        for leaf in leaves(c.trie):
            f_leaf[id(leaf)] = len(f_groups)
            f_groups.append(c.entries[leaf.first:leaf.first + leaf.count])
    f_units = pack(f_groups, 0x0E)
    placement, ui, used = [], 0, 0          # (unit index, first row) per group, as pack() placed them
    unit_rows = [len(u.rows) for u in f_units]
    for rows in f_groups:
        if used + len(rows) > unit_rows[ui]:
            ui, used = ui + 1, 0
        placement.append((ui, used))
        used += len(rows)
    f_keys = [("f", i) for i in range(len(f_units))]

    def f_place(leaf):
        ui_, row = placement[f_leaf[id(leaf)]]
        return db.resolve(f_keys[ui_]), 0x30 + 8 * row, leaf.count

    # 10: the street tries of many cities share units
    t10_lists, t10_where = pack_lists([c.trie for c in cities])
    t10_units = trie_table(t10_lists, t10_where, "t10", 0x0F, f_place, Unit)

    def roots_of(c):
        u, off = t10_where[id(c.trie)]
        return db.resolve(("t10", u)), off, len(c.trie)

    # d: city name rows (with rotations), one city record per row; a city trie per country
    d_groups, d_leaf, d_tries = [], {}, {}
    for country, _, _ in countries:
        rows = []
        for c in cities:
            if c.country is country:
                for text, flags in rotations(c.name, country, street=False):
                    rows.append((text, flags, c.muni, c))
        rows.sort(key=lambda r: (r[0], r[2] or ""))
        d_tries[country.iso] = d_trie = trie([r[0] for r in rows])
        for leaf in leaves(d_trie):
            d_leaf[id(leaf)] = len(d_groups)
            d_groups.append(rows[leaf.first:leaf.first + leaf.count])
    d_units = pack(d_groups, 0x0C)
    d_place, ui, used = [], 0, 0
    for g in d_groups:
        if used + len(g) > len(d_units[ui].rows):
            ui, used = ui + 1, 0
        d_place.append((ui, used))
        used += len(g)
    d_keys = [("d", i) for i in range(len(d_units))]

    def d_place_of(leaf):
        ui_, row = d_place[d_leaf[id(leaf)]]
        return db.resolve(d_keys[ui_]), 0x30 + 8 * row, leaf.count

    def city_record(c, slot3, count):
        root_ptr, root_off, root_n = roots_of(c)
        parcel, idx = c.seg
        return struct.pack(">IHHHHIH6x", root_ptr, root_off, root_n, slot3, count, parcel_ptr(parcel),
                           parcel.seg_base + 32 * idx)

    def name_units(units, keys, kind, record):
        out = []
        for i, u in enumerate(units):
            def build(resolve, i=i, u=u):
                nxt = resolve(keys[i + 1]) if i + 1 < len(units) else 0
                prv = resolve(keys[i - 1]) if i else 0
                return name_unit_bytes(u, resolve(keys[i]), nxt, prv, parcel_ptr, record, poi_list)
            out.append(Unit(keys[i], build))
        return out

    db.add(Table(0x0F, name_units(f_units, f_keys, 0x0E, None)))
    db.add(Table(0x10, t10_units))
    db.add(Table(0x0D, name_units(d_units, d_keys, 0x0C, city_record)))
    e_lists, e_where = pack_lists(list(d_tries.values()))
    db.add(Table(0x0E, trie_table(e_lists, e_where, "e", 0x0D, d_place_of, Unit)))

    # blocks 3 (country trie) and 4 (countries): name rows (slot 0) and records (slot 1) sorted by
    # name, the countries' POI category records (slot 3), the names
    countries = sorted(countries, key=lambda c: c[0].name)
    n = len(countries)
    rec = 0x30 + 8 * n
    cats = rec + 56 * n
    txt = cats + 12 * sum(len(lists) for _, _, lists in countries)

    def block4(resolve):
        d = bytearray(BLOCK)
        struct.pack_into(">IHHHHHHHHHHHH", d, 0, 4 << 8 | 1, 0x0A, 0, 0x30, n, rec, n, 0, 0, cats,
                         (txt - cats) // 12, 0, 0)
        cat, name_at = cats, txt
        for k, (country, template, lists) in enumerate(countries):
            r_off = rec + 56 * k
            struct.pack_into(">HHHH", d, 0x30 + 8 * k, name_at, country.lang, 0, r_off)
            r = bytearray(template)
            trie_root = d_tries[country.iso]
            u, off = e_where[id(trie_root)]
            struct.pack_into(">IHH", r, 0, resolve(("e", u)) if trie_root else 0, off, len(trie_root))
            struct.pack_into(">HH", r, 24, cat, len(lists))
            struct.pack_into(">H", r, 40, country.number)
            r[46:48] = country.iso.encode()
            d[r_off:r_off + 56] = r
            for c_, lst in lists:
                struct.pack_into(">IHHHH", d, cat, *poi_list(lst), c_, txt)
                cat += 12
            d[name_at:name_at + len(country.name)] = country.name.encode("latin1")
            name_at += len(country.name) + 1
        if name_at > BLOCK:
            raise ValueError(f"block 4: {n} countries do not fit")
        return bytes(d)

    firsts = []                             # country trie: one leaf per first letter
    for k, (country, _, _) in enumerate(countries):
        if firsts and firsts[-1][0] == country.name[0]:
            firsts[-1][2] += 1
        else:
            firsts.append([country.name[0], 0x30 + 8 * k, 1])

    def block3(resolve):
        d = bytearray(BLOCK)
        struct.pack_into(">IHHHH", d, 0, 3 << 8 | 1, 0x0B, 0, 0x0C, len(firsts))
        for k, (ch, off, cnt) in enumerate(firsts):
            struct.pack_into(">IBBHHH", d, 0x0C + 12 * k, 4 << 8 | 1, ord(ch), 1, off, cnt, 0)
        return bytes(d)

    db.blocks[3], db.blocks[4] = block3, block4
    db.country_roots = len(firsts)          # block 0 names the country trie root (block 3, 0x0c, count)
    db.country_numbers = {}                 # block 2: settings of our countries (numbers may repeat)
    for country, template, _ in countries:
        db.country_numbers.setdefault(country.number, struct.unpack_from(">H", template, 40)[0])
