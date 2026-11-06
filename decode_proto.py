"""
Decodificador de protobuf SEM schema (.proto).
Uso:
    python decode_proto.py 0a350a09...
"""
import ast
import struct
import sys

MAX_DEPTH = 6


def read_varint(data, pos):
    result = 0
    shift = 0
    while True:
        if pos >= len(data):
            raise ValueError("EOF lendo varint")
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
        if shift > 63:
            raise ValueError("varint grande demais")
    return result, pos


def _tentar_string(payload):
    try:
        txt = payload.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if all((32 <= ord(c) < 127) or c in "\n\r\t" for c in txt):
        return txt
    return None


def decode_message(data, indent=0, max_depth=MAX_DEPTH):
    if indent // 2 > max_depth:
        print(" " * indent + "... (profundidade maxima)")
        return

    pos = 0
    while pos < len(data):
        prefix = " " * indent
        try:
            tag, pos = read_varint(data, pos)
        except ValueError as e:
            print(prefix + "<erro: " + str(e) + ">")
            return

        field_num = tag >> 3
        wire_type = tag & 0x07

        if wire_type == 0:
            try:
                val, pos = read_varint(data, pos)
            except ValueError as e:
                print(prefix + "<erro: " + str(e) + ">")
                return
            print(prefix + "field " + str(field_num) + " (varint): " + str(val))

        elif wire_type == 1:
            if pos + 8 > len(data):
                print(prefix + "<erro: 64-bit truncado>")
                return
            raw = data[pos:pos + 8]
            pos += 8
            u = struct.unpack("<Q", raw)[0]
            f = struct.unpack("<d", raw)[0]
            i = struct.unpack("<q", raw)[0]
            print(prefix + "field " + str(field_num) + " (64-bit): uint=" + str(u) + " double=" + str(f) + " int=" + str(i))

        elif wire_type == 2:
            try:
                length, pos = read_varint(data, pos)
            except ValueError as e:
                print(prefix + "<erro: " + str(e) + ">")
                return
            if pos + length > len(data):
                print(prefix + "<erro: length " + str(length) + " passa do fim>")
                return
            payload = data[pos:pos + length]
            pos += length

            txt = _tentar_string(payload)
            if txt is not None:
                print(prefix + "field " + str(field_num) + " (string[" + str(length) + "]): " + repr(txt))
                continue

            print(prefix + "field " + str(field_num) + " (bytes[" + str(length) + "]): " + payload[:40].hex() + "...")
            try:
                if length >= 2 and payload[0] in (0x08, 0x0A, 0x10, 0x12, 0x18, 0x1A, 0x20, 0x22, 0x28, 0x2A, 0x30, 0x32):
                    decode_message(payload, indent + 2, max_depth)
            except Exception:
                pass

        elif wire_type == 5:
            if pos + 4 > len(data):
                print(prefix + "<erro: 32-bit truncado>")
                return
            raw = data[pos:pos + 4]
            pos += 4
            u = struct.unpack("<I", raw)[0]
            f = struct.unpack("<f", raw)[0]
            i = struct.unpack("<i", raw)[0]
            print(prefix + "field " + str(field_num) + " (32-bit): uint=" + str(u) + " float=" + str(f) + " int=" + str(i))

        else:
            print(prefix + "field " + str(field_num) + " (wire type " + str(wire_type) + " desconhecido)")
            return


def _parse_arg(arg):
    s = arg.strip()
    if s.startswith("b'") or s.startswith('b"'):
        try:
            val = ast.literal_eval(s)
            if isinstance(val, bytes):
                return val
        except Exception:
            pass
    s_hex = s.replace(" ", "").replace("\n", "").replace("\r", "").replace("\t", "")
    if len(s_hex) % 2 == 0 and all(c in "0123456789abcdefABCDEF" for c in s_hex):
        return bytes.fromhex(s_hex)
    raise ValueError("Formato nao reconhecido. Use hex (0a35...) ou bytes Python (b'...').")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python decode_proto.py <hex_do_payload>")
        print("Exemplo: python decode_proto.py 0a350a09...")
        sys.exit(1)
    raw = sys.argv[1]
    try:
        data = _parse_arg(raw)
    except ValueError as e:
        print("Erro: " + str(e))
        sys.exit(1)
    print("=== " + str(len(data)) + " bytes ===")
    print("Hex: " + data.hex())
    print()
    decode_message(data)
