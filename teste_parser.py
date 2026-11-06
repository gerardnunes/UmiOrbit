import struct


def read_varint(data, pos):
    result = 0
    shift = 0
    while True:
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return result, pos


def parse_xyzw(data):
    vals = {}
    pos = 0
    while pos < len(data):
        try:
            tag, pos = read_varint(data, pos)
        except IndexError:
            break
        fn = tag >> 3
        wt = tag & 7
        if wt == 5 and pos + 4 <= len(data):
            v = struct.unpack("<f", data[pos:pos + 4])[0]
            vals[fn] = v
            pos += 4
        elif wt == 0:
            _, pos = read_varint(data, pos)
        elif wt == 2:
            ln, pos = read_varint(data, pos)
            pos += ln
        else:
            break
    return vals


def parse_transformada(data):
    nome = None
    vals = {}
    pos = 0
    while pos < len(data):
        try:
            tag, pos = read_varint(data, pos)
        except IndexError:
            break
        fn = tag >> 3
        wt = tag & 7
        if wt == 2:
            ln, pos = read_varint(data, pos)
            if pos + ln > len(data):
                break
            sub = data[pos:pos + ln]
            pos += ln
            if fn == 2:
                nome = sub.decode("utf-8", errors="replace")
            elif fn == 4:
                vals = parse_xyzw(sub)
        elif wt == 1 and pos + 8 <= len(data):
            pos += 8
        elif wt == 5:
            pos += 4
        elif wt == 0:
            _, pos = read_varint(data, pos)
        else:
            break
    return nome, vals


def decodificar_posicao(payload):
    pos = 0
    candidatos = []
    while pos < len(payload):
        try:
            tag, pos = read_varint(payload, pos)
        except IndexError:
            break
        fn = tag >> 3
        wt = tag & 7
        if wt == 2:
            ln, pos = read_varint(payload, pos)
            if pos + ln > len(payload):
                break
            sub = payload[pos:pos + ln]
            pos += ln
            nome, vals = parse_transformada(sub)
            if nome and vals.get(1) is not None:
                candidatos.append((nome, vals))
        elif wt == 1:
            pos += 8
        elif wt == 5:
            pos += 4
        elif wt == 0:
            _, pos = read_varint(payload, pos)
        else:
            break

    for pref in ("usv_xy_3d_id", "usv_enu_3d_id", "usv_xy_2d_id"):
        for c in candidatos:
            if c[0] == pref:
                v = c[1]
                return {"nome": c[0], "x": v.get(1), "y": v.get(2), "z": v.get(3), "qw": v.get(4)}
    return None


def parse_prop_cmd(data):
    steer = None
    modo = None
    pos = 0
    while pos < len(data):
        try:
            tag, pos = read_varint(data, pos)
        except IndexError:
            break
        fn = tag >> 3
        wt = tag & 7
        if wt == 0:
            v, pos = read_varint(data, pos)
            if fn == 15:
                modo = v
        elif wt == 5 and pos + 4 <= len(data):
            if fn == 2:
                steer = struct.unpack("<f", data[pos:pos + 4])[0]
            pos += 4
        elif wt == 2:
            ln, pos = read_varint(data, pos)
            pos += ln
        elif wt == 1:
            pos += 8
        else:
            break
    return steer, modo


def parse_prop_timestamps(data):
    ats = []
    pos = 0
    while pos < len(data):
        try:
            tag, pos = read_varint(data, pos)
        except IndexError:
            break
        fn = tag >> 3
        wt = tag & 7
        if wt == 2:
            ln, pos = read_varint(data, pos)
            sub = data[pos:pos + ln]
            pos += ln
            p = 0
            while p < len(sub):
                try:
                    t, p = read_varint(sub, p)
                except IndexError:
                    break
                f2 = t >> 3
                w2 = t & 7
                if w2 == 0:
                    v, p = read_varint(sub, p)
                    if f2 == 1:
                        ats.append(v)
                elif w2 == 2:
                    l2, p = read_varint(sub, p)
                    p += l2
                elif w2 == 5:
                    p += 4
                elif w2 == 1:
                    p += 8
                else:
                    break
        elif wt == 0:
            _, pos = read_varint(data, pos)
        elif wt == 5:
            pos += 4
        elif wt == 1:
            pos += 8
        else:
            break
    return ats


def parse_prop_inner(data):
    steer = None
    modo = None
    atuadores = []
    pos = 0
    while pos < len(data):
        try:
            tag, pos = read_varint(data, pos)
        except IndexError:
            break
        fn = tag >> 3
        wt = tag & 7
        if wt == 2:
            ln, pos = read_varint(data, pos)
            sub = data[pos:pos + ln]
            pos += ln
            if fn == 3:
                steer, modo = parse_prop_cmd(sub)
            elif fn == 7:
                atuadores = parse_prop_timestamps(sub)
        elif wt == 0:
            _, pos = read_varint(data, pos)
        elif wt == 5:
            pos += 4
        elif wt == 1:
            pos += 8
        else:
            break
    return steer, modo, atuadores


def decodificar_propulsor(payload):
    pos = 0
    steer = None
    modo = None
    ts_msg = None
    atuadores = []
    while pos < len(payload):
        try:
            tag, pos = read_varint(payload, pos)
        except IndexError:
            break
        fn = tag >> 3
        wt = tag & 7
        if wt == 0:
            v, pos = read_varint(payload, pos)
            if fn == 1:
                ts_msg = v / 1000.0
        elif wt == 2:
            ln, pos = read_varint(payload, pos)
            sub = payload[pos:pos + ln]
            pos += ln
            if fn == 4:
                s, m, at = parse_prop_inner(sub)
                if s is not None:
                    steer = s
                if m is not None:
                    modo = m
                if at:
                    atuadores = at
        elif wt == 5:
            pos += 4
        elif wt == 1:
            pos += 8
        else:
            break
    return {"steer": steer, "modo": modo, "timestamp": ts_msg, "atuadores": atuadores}


if __name__ == "__main__":
    hex_pos = "0a330a0909c57b6f4b7c04d941120c7573765f78795f32645f69641a0a7573765f6e65645f6964220a1d0dcd4659bf256b60073f2a000a3d0a0909c57b6f4b7c04d941120c7573765f78795f33645f69641a0a7573765f6e65645f696422140d923784bc15f7c4863c1df63b59bf25f550073f2a000a3e0a0909c57b6f4b7c04d941120d7573765f656e755f33645f69641a0a7573765f6e65645f696422140df550073f15f63b593f1df7c4863c25923784bc2a000a2e0a0909c57b6f4b7c04d941120a7573765f6e65645f6964"
    print("POSICAO:", decodificar_posicao(bytes.fromhex(hex_pos)))
    hex_prop = "08d2dbdeaeee3010958a880222381a07150000008078052a070a05737465657232060a0470726f703a1c5a05088ba7ec025a050889a7ec025a05088ca7ec025a05088aa7ec02"
    print("PROPULSOR:", decodificar_propulsor(bytes.fromhex(hex_prop)))
