import struct

def read_varint(data, pos):
    result = 0; shift = 0
    while True:
        b = data[pos]; pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80): break
        shift += 7
    return result, pos

def parse_prop_cmd(data):
    steer = None; modo = None; pos = 0
    while pos < len(data):
        tag, pos = read_varint(data, pos)
        fn = tag >> 3; wt = tag & 7
        if wt == 5 and pos + 4 <= len(data):
            val = struct.unpack("<f", data[pos:pos+4])[0]
            if fn == 6: steer = val
            elif fn == 8: modo = val
            pos += 4
        elif wt == 0:
            v, pos = read_varint(data, pos)
            if fn == 15: modo = v
        elif wt == 2:
            ln, pos = read_varint(data, pos); pos += ln
        elif wt == 1: pos += 8
        else: break
    return steer, modo

def parse_prop_timestamps(data):
    ats = []; pos = 0
    while pos < len(data):
        tag, pos = read_varint(data, pos)
        fn = tag >> 3; wt = tag & 7
        if wt == 2:
            ln, pos = read_varint(data, pos)
            sub = data[pos:pos+ln]; pos += ln
            p = 0
            while p < len(sub):
                t, p = read_varint(sub, p)
                f2 = t >> 3; w2 = t & 7
                if w2 == 0:
                    v, p = read_varint(sub, p)
                    if f2 == 1: ats.append(v)
                elif w2 == 2:
                    l2, p = read_varint(sub, p); p += l2
                elif w2 == 5: p += 4
                elif w2 == 1: p += 8
                else: break
        elif wt == 0: _, pos = read_varint(data, pos)
        elif wt == 5: pos += 4
        elif wt == 1: pos += 8
        else: break
    return ats

def parse_prop_inner(data):
    steer = None; modo = None; ats = []; pos = 0
    while pos < len(data):
        tag, pos = read_varint(data, pos)
        fn = tag >> 3; wt = tag & 7
        if wt == 2:
            ln, pos = read_varint(data, pos)
            sub = data[pos:pos+ln]; pos += ln
            if fn == 3:
                s, m = parse_prop_cmd(sub)
                if s is not None: steer = s
                if m is not None: modo = m
            elif fn == 7:
                at = parse_prop_timestamps(sub)
                if at: ats = at
        elif wt == 0: _, pos = read_varint(data, pos)
        elif wt == 5: pos += 4
        elif wt == 1: pos += 8
        else: break
    return steer, modo, ats

def decodificar_propulsor(payload):
    pos = 0; steer = None; modo = None; ts = None; ats = []
    while pos < len(payload):
        tag, pos = read_varint(payload, pos)
        fn = tag >> 3; wt = tag & 7
        if wt == 0:
            v, pos = read_varint(payload, pos)
            if fn == 1: ts = v / 1000.0
        elif wt == 2:
            ln, pos = read_varint(payload, pos)
            sub = payload[pos:pos+ln]; pos += ln
            if fn == 4:
                s, m, at = parse_prop_inner(sub)
                if s is not None: steer = s
                if m is not None: modo = m
                if at: ats = at
        elif wt == 5: pos += 4
        elif wt == 1: pos += 8
        else: break
    return {"steer": steer, "modo": modo, "timestamp": ts, "atuadores": ats}

# Payload real do sniffer [3914]
hex_prop = "08aab6d8b2ee3010958a8802223b1a0a35508da73f45d9b81ebb2a070a05737465657232060a0470726f703a1c5a05088ba7ec025a050889a7ec025a05088ca7ec025a05088aa7ec02"
print("PROPULSOR:", decodificar_propulsor(bytes.fromhex(hex_prop)))
