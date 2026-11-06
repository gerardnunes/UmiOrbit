import struct

def read_varint(data, pos):
    result = 0; shift = 0
    while True:
        b = data[pos]; pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80): break
        shift += 7
    return result, pos

def dump(data, indent=0):
    pos = 0
    while pos < len(data):
        try: tag, pos = read_varint(data, pos)
        except IndexError: break
        fn = tag >> 3; wt = tag & 7
        prefix = "  " * indent
        if wt == 0:
            v, pos = read_varint(data, pos)
            print(f"{prefix}field {fn} (varint): {v} | s32: {struct.unpack('<i', struct.pack('<I', v & 0xFFFFFFFF))[0]} | s64: {struct.unpack('<q', struct.pack('<Q', v & 0xFFFFFFFFFFFFFFFF))[0]}")
        elif wt == 2:
            ln, pos = read_varint(data, pos)
            sub = data[pos:pos+ln]; pos += ln
            try:
                s = sub.decode("utf-8")
                if s.isprintable() and len(s) > 0 and all(ord(c) < 128 for c in s):
                    print(f"{prefix}field {fn} (string): {s!r}")
                    continue
            except: pass
            print(f"{prefix}field {fn} (msg {len(sub)}b):")
            dump(sub, indent + 1)
        elif wt == 5:
            if pos + 4 <= len(data):
                f = struct.unpack("<f", data[pos:pos+4])[0]
                i = struct.unpack("<i", data[pos:pos+4])[0]
                print(f"{prefix}field {fn} (float32): {f} | int32: {i}")
                pos += 4
            else: break
        elif wt == 1:
            if pos + 8 <= len(data):
                d = struct.unpack("<d", data[pos:pos+8])[0]
                print(f"{prefix}field {fn} (double): {d}")
                pos += 8
            else: break
        else: break

# Carrega o 25101 e procura por "bs_63"
with open("25101-142004.bin", "rb") as f:
    data = f.read()

# Acha o offset de "bs_63"
idx = data.find(b"bs_63")
if idx >= 0:
    print(f"Encontrado 'bs_63' no offset {idx}")
    # Pega 100 bytes antes pra decodificar a sub-mensagem inteira
    inicio = max(0, idx - 20)
    print(f"Contexto (hex): {data[inicio:idx+150].hex()}")
    print()
    print("Decodificando a sub-mensagem do bs_63:")
    # O field 4 começa antes do nome. Vamos decodificar a msg toda
    dump(data[inicio:idx+150])
