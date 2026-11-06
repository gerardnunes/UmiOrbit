def read_varint(data, pos):
    result = 0; shift = 0
    while True:
        b = data[pos]; pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80): break
        shift += 7
    return result, pos

def varint_signed(v, bits=32):
    """Converte varint pra signed (2's complement)"""
    if v & (1 << (bits - 1)):
        return v - (1 << bits)
    return v

def dump(data, indent=0):
    pos = 0
    while pos < len(data):
        try:
            tag, pos = read_varint(data, pos)
        except IndexError:
            break
        fn = tag >> 3; wt = tag & 7
        prefix = "  " * indent
        if wt == 0:
            v, pos = read_varint(data, pos)
            # tenta float e signed
            print(f"{prefix}field {fn} (varint): {v} | signed32: {varint_signed(v, 32)} | signed64: {varint_signed(v, 64)} | /1e7: {v/1e7:.7f}")
        elif wt == 2:
            ln, pos = read_varint(data, pos)
            sub = data[pos:pos+ln]; pos += ln
            # tenta string
            try:
                s = sub.decode("utf-8")
                if s.isprintable() and len(s) > 1:
                    print(f"{prefix}field {fn} (string): {s!r}")
                    continue
            except:
                pass
            print(f"{prefix}field {fn} (msg {len(sub)}b):")
            dump(sub, indent + 1)
        elif wt == 5:
            import struct
            if pos + 4 <= len(data):
                f = struct.unpack("<f", data[pos:pos+4])[0]
                i = struct.unpack("<i", data[pos:pos+4])[0]
                print(f"{prefix}field {fn} (float32): {f} | int32: {i}")
                pos += 4
            else: break
        elif wt == 1:
            import struct
            if pos + 8 <= len(data):
                d = struct.unpack("<d", data[pos:pos+8])[0]
                i = struct.unpack("<q", data[pos:pos+8])[0]
                print(f"{prefix}field {fn} (double): {d} | int64: {i}")
                pos += 8
            else: break
        else:
            print(f"{prefix}field {fn}: wt={wt} inválido")
            break

import sys

for nome in ["20103-142004", "20602-142004", "20202-142004", "20101-142004"]:
    with open(nome + ".bin", "rb") as f:
        data = f.read()
    print(f"\n{'='*60}")
    print(f"{nome} ({len(data)} bytes)")
    print('='*60)
    dump(data)
