"""Prohibited turns for the encoder (docs/format.md section 3, slot 10) from OSM turn restrictions:
relations type=restriction with a from way, a via node and a to way. no_* forbids that turn,
only_* every other turn at the via node (U-turn included). Restrictions via ways, for other
vehicles only (restriction:hgv, except=motorcar) or that do not resolve to one piece per way at
the via node are left out.

The ogr2ogr GeoPackage has no relation members, so the relations are read from the .osm.pbf:
Geofabrik extracts are sorted (nodes, ways, relations), only the last blocks are decoded.
"""
import struct
import zlib


def _varint(b, p):
    v = shift = 0
    while True:
        c = b[p]
        p += 1
        v |= (c & 0x7F) << shift
        if c < 0x80:
            return v, p
        shift += 7


def _fields(b):
    """(field, wire type, value) of a protobuf message; length-delimited values as memoryview."""
    p, n = 0, len(b)
    while p < n:
        key, p = _varint(b, p)
        f, t = key >> 3, key & 7
        if t == 0:
            v, p = _varint(b, p)
        elif t == 2:
            ln, p = _varint(b, p)
            v = b[p:p + ln]
            p += ln
        elif t == 1:
            v = b[p:p + 8]
            p += 8
        elif t == 5:
            v = b[p:p + 4]
            p += 4
        else:
            raise ValueError(f"protobuf wire type {t}")
        yield f, t, v


def _packed(b, signed=False):
    out, p = [], 0
    while p < len(b):
        v, p = _varint(b, p)
        out.append((v >> 1) ^ -(v & 1) if signed else v)
    return out


def _blobs(path):
    """File offsets and sizes of the OSMData blobs."""
    out = []
    with open(path, "rb") as f:
        while True:
            head = f.read(4)
            if len(head) < 4:
                return out
            n, = struct.unpack(">I", head)
            kind, size = None, 0
            for fld, _, v in _fields(memoryview(f.read(n))):
                if fld == 1:
                    kind = bytes(v)
                elif fld == 3:
                    size = v
            if kind == b"OSMData":
                out.append((f.tell(), size))
            f.seek(size, 1)


def _block(f, off, size):
    f.seek(off)
    raw = zlib_data = None
    for fld, _, v in _fields(memoryview(f.read(size))):
        if fld == 1:
            raw = bytes(v)
        elif fld == 3:
            zlib_data = bytes(v)
    return memoryview(raw if raw is not None else zlib.decompress(zlib_data))


def restrictions(pbf):
    """[(kind 'no' / 'only', from way id, via node id, to way id)] of the extract."""
    out = []
    blobs = _blobs(pbf)
    with open(pbf, "rb") as f:
        for off, size in reversed(blobs):
            block = _block(f, off, size)
            strings, groups = [], []
            for fld, _, v in _fields(block):
                if fld == 1:
                    strings = [bytes(s).decode("utf-8", "replace") for g, _, s in _fields(v) if g == 1]
                elif fld == 2:
                    groups.append(v)
            found = False
            for g in groups:
                for fld, _, rel in _fields(g):
                    if fld != 4:
                        continue
                    found = True
                    r = _relation(rel, strings)
                    if r:
                        out.append(r)
            if not found:
                break                       # sorted file: the blocks before hold nodes and ways
    return out


def _relation(rel, strings):
    keys = vals = roles = ids = types = ()
    for fld, _, v in _fields(rel):
        if fld == 2:
            keys = _packed(v)
        elif fld == 3:
            vals = _packed(v)
        elif fld == 8:
            roles = _packed(v)
        elif fld == 9:
            ids = _packed(v, signed=True)
        elif fld == 10:
            types = _packed(v)
    tags = {strings[k]: strings[v] for k, v in zip(keys, vals)}
    if tags.get("type") != "restriction" or "motorcar" in tags.get("except", "").split(";"):
        return None
    value = tags.get("restriction") or tags.get("restriction:motorcar")
    if not value or "_" not in value:
        return None
    kind = value.split("_", 1)[0]
    if kind not in ("no", "only"):
        return None
    members, ref = {}, 0
    for role, delta, typ in zip(roles, ids, types):
        ref += delta
        members.setdefault((strings[role], typ), []).append(ref)
    frm, via, to = members.get(("from", 1)), members.get(("via", 0)), members.get(("to", 1))
    if not (frm and via and to) or len(frm) != 1 or len(via) != 1 or len(to) != 1 or ("via", 1) in members:
        return None
    return kind, frm[0], via[0], to[0]


def assign(parcels, sorted_pieces, rules):
    """Sets parcel.turns = {source segment index: [(target index, direction bit)]}; returns the
    number of restrictions placed. The via node is the point where a piece of the from way and a
    piece of the to way meet inside one parcel."""
    by_way = {}
    for pc in parcels:
        for i, piece in enumerate(sorted_pieces(pc)):
            by_way.setdefault(piece.road.osm_id, []).append((pc, i, piece))
    placed = 0
    for kind, frm, _, to in rules:
        cands = {}
        for pc, i, piece in by_way.get(str(frm), ()):
            for end in (piece.points[0], piece.points[-1]):
                cands.setdefault((id(pc), end), [pc, [], []])[1].append(i)
        for pc, i, piece in by_way.get(str(to), ()):
            for end in (piece.points[0], piece.points[-1]):
                if (id(pc), end) in cands:
                    cands[(id(pc), end)][2].append(i)
        hits = [(k, v) for k, v in cands.items() if v[2]]
        if len(hits) != 1:
            continue
        (_, via), (pc, sources, targets) = hits[0]
        if len(sources) != 1 or (len(targets) != 1 and not (frm == to and len(targets) == 2)):
            continue
        pieces = sorted_pieces(pc)
        src = sources[0]
        if pieces[src].points[0] == pieces[src].points[-1]:
            continue
        bit = 1 if pieces[src].points[-1] == via else 0
        if kind == "no":
            banned = [src] if frm == to else targets
        else:
            banned = [j for j, p in enumerate(pieces) if via in (p.points[0], p.points[-1]) and j not in targets]
        if pc.turns is None:
            pc.turns = {}
        lst = pc.turns.setdefault(src, [])
        for j in banned:
            if (j, bit) not in lst and sum(1 for _, b in lst if b == bit) < 8:     # the router keeps 8
                lst.append((j, bit))
        placed += 1
    return placed
