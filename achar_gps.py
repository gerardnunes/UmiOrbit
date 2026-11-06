#!/usr/bin/env python3
"""
achar_gps.py - escuta TODOS os topicos do ZMQ e procura latitude/longitude.
Uso: python achar_gps.py [segundos] [endereco]
"""
import math
import re
import struct
import sys
import time
from collections import defaultdict

ENDERECO = "tcp://10.20.42.4:5054"
SEGUNDOS = 120

LAT_MIN, LAT_MAX = -34.0, 6.0
LON_MIN, LON_MAX = -74.0, -34.0

ESCALAS = (1e5, 1e6, 1e7, 1e8)
RE_NMEA = re.compile(r"\$G[NPLBA][A-Z]{3},")
RE_CHAVE = re.compile(r'gps|gnss|nmea|latitude|longitude|"lat"|"lon"|"lng"|经度|纬度|定位', re.I)
RE_TOPICO = re.compile(rb"^[A-Za-z0-9_]+_\d+$")
RE_RUIDO = re.compile(r"^radar_\d+$")


def ler_varint(d, i):
    r, s = 0, 0
    while True:
        if i >= len(d) or s > 63:
            raise ValueError
        b = d[i]
        i += 1
        r |= (b & 0x7F) << s
        if not b & 0x80:
            return r, i
        s += 7


def parse(d):
    i, out = 0, []
    try:
        while i < len(d):
            tag, i = ler_varint(d, i)
            fn, wt = tag >> 3, tag & 7
            if fn == 0 or fn > 5000:
                return None
            if wt == 0:
                v, i = ler_varint(d, i)
            elif wt == 1:
                if i + 8 > len(d):
                    return None
                v, i = d[i:i + 8], i + 8
            elif wt == 2:
                n, i = ler_varint(d, i)
                if i + n > len(d):
                    return None
                v, i = d[i:i + n], i + n
            elif wt == 5:
                if i + 4 > len(d):
                    return None
                v, i = d[i:i + 4], i + 4
            else:
                return None
            out.append((fn, wt, v))
    except ValueError:
        return None
    return out or None


def classifica(v):
    if not math.isfinite(v) or abs(v) < 1.0 or abs(v - round(v)) < 1e-6:
        return None
    if LAT_MIN <= v <= LAT_MAX:
        return "LAT"
    if LON_MIN <= v <= LON_MAX:
        return "LON"
    return None


def candidatos(wt, v):
    if wt == 1:
        yield "double", struct.unpack("<d", v)[0]
        i = struct.unpack("<q", v)[0]
        for e in ESCALAS:
            yield "int64/%g" % e, i / e
    elif wt == 5:
        yield "float", struct.unpack("<f", v)[0]
        i = struct.unpack("<i", v)[0]
        for e in ESCALAS:
            yield "int32/%g" % e, i / e
    elif wt == 0:
        s64 = v - (1 << 64) if v >= 1 << 63 else v
        zz = (v >> 1) ^ -(v & 1)
        for e in ESCALAS:
            yield "varint/%g" % e, s64 / e
            yield "zigzag/%g" % e, zz / e


class Estado:
    def __init__(self):
        self.achados = {}
        self.textos = defaultdict(set)
        self.nmea = defaultdict(set)
        self.strings = defaultdict(set)
        self.contagem = defaultdict(int)


def eh_texto(s):
    return len(s) >= 3 and all(c.isprintable() or c in "\r\n\t" for c in s)


def registra_texto(st, topico, s):
    if RE_NMEA.search(s):
        st.nmea[topico].add(s[:160])
    if RE_CHAVE.search(s):
        st.textos[topico].add(s[:160].replace("\n", " ").replace("\t", ""))
    if len(s) <= 40 and not RE_RUIDO.match(s):
        st.strings[topico].add(s)


def registra(st, topico, path, kind, x):
    cls = classifica(x)
    if not cls:
        return
    k = (topico, path, kind)
    r = st.achados.get(k)
    if r is None:
        st.achados[k] = {"cls": cls, "min": x, "max": x, "n": 1}
    else:
        r["min"], r["max"], r["n"] = min(r["min"], x), max(r["max"], x), r["n"] + 1


def walk(st, topico, d, path=""):
    campos = parse(d)
    if campos is None:
        return False
    for fn, wt, v in campos:
        p = "%s.%d" % (path, fn) if path else str(fn)
        if wt == 2:
            try:
                s = v.decode("utf-8")
            except UnicodeDecodeError:
                s = None
            if s is not None and eh_texto(s):
                registra_texto(st, topico, s)
            elif v:
                walk(st, topico, v, p)
        else:
            for kind, x in candidatos(wt, v):
                registra(st, topico, p, kind, x)
    return True


def processa(st, topico, payload):
    st.contagem[topico] += 1
    if not walk(st, topico, payload):
        try:
            s = payload.decode("utf-8")
            if eh_texto(s):
                registra_texto(st, topico, s)
        except UnicodeDecodeError:
            pass


def relatorio(st):
    print("\n" + "=" * 70)
    print("TOPICOS VISTOS (%d):" % len(st.contagem))
    for t, n in sorted(st.contagem.items()):
        print("  %-28s %5d msgs" % (t, n))

    grupos = defaultdict(lambda: defaultdict(list))
    for (t, p, kind), r in st.achados.items():
        pai = p.rsplit(".", 1)[0] if "." in p else ""
        grupos[(t, pai, kind)][r["cls"]].append((p, r))
    pares = [(k, g) for k, g in grupos.items() if "LAT" in g and "LON" in g]
    pares.sort(key=lambda kg: (0 if kg[0][2] in ("double", "float") else 1, kg[0]))

    print("\n" + "=" * 70)
    print("PARES LAT+LON PROVAVEIS (mesmo topico, mesmo nivel, mesma codificacao):")
    if not pares:
        print("  nenhum")
    for (t, pai, kind), g in pares[:30]:
        print("  [%s] nivel '%s' como %s" % (t, pai or "raiz", kind))
        for cls in ("LAT", "LON"):
            for p, r in g[cls]:
                print("     %s campo %-10s min=%.7f max=%.7f (%d amostras)" % (cls, p, r["min"], r["max"], r["n"]))

    print("\n" + "=" * 70)
    print("NMEA ENCONTRADO:")
    if not st.nmea:
        print("  nenhum")
    for t, ss in st.nmea.items():
        for s in sorted(ss)[:5]:
            print("  [%s] %s" % (t, s))

    print("\n" + "=" * 70)
    print("TEXTOS COM GPS/LAT/LON:")
    if not st.textos:
        print("  nenhum")
    for t, ss in st.textos.items():
        for s in sorted(ss)[:8]:
            print("  [%s] %s" % (t, s))

    print("\n" + "=" * 70)
    print("STRINGS CURTAS POR TOPICO:")
    for t, ss in sorted(st.strings.items()):
        amostra = sorted(ss)[:10]
        print("  [%s] %s%s" % (t, amostra, " ..." if len(ss) > 10 else ""))

    print("\nCandidatos soltos (sem par) =", sum(1 for g in grupos.values() if not ("LAT" in g and "LON" in g)))


def main():
    import zmq
    segundos = int(sys.argv[1]) if len(sys.argv) > 1 else SEGUNDOS
    endereco = sys.argv[2] if len(sys.argv) > 2 else ENDERECO
    ctx = zmq.Context()
    sock = ctx.socket(zmq.SUB)
    sock.setsockopt(zmq.SUBSCRIBE, b"")
    sock.setsockopt(zmq.RCVTIMEO, 1000)
    sock.connect(endereco)
    st = Estado()
    topico_atual = None
    inicio = ultimo = time.time()
    print("Escutando %s por %ds (Ctrl+C para parar)..." % (endereco, segundos))
    aviso_dado = False
    try:
        while time.time() - inicio < segundos:
            try:
                partes = sock.recv_multipart()
            except zmq.Again:
                if not aviso_dado and time.time() - inicio > 10 and sum(st.contagem.values()) == 0:
                    print("  10s sem receber nada — a porta %s está correta?" % endereco)
                    aviso_dado = True
                continue
            if len(partes) >= 2:
                topico, payload = partes[0], partes[-1]
            elif RE_TOPICO.match(partes[0]):
                topico_atual = partes[0]
                continue
            elif topico_atual is None:
                continue
            else:
                topico, payload = topico_atual, partes[0]
            processa(st, topico.decode("utf-8", "replace"), payload)
            if time.time() - ultimo > 15:
                ultimo = time.time()
                print("  %ds: %d topicos, %d candidatos" % (ultimo - inicio, len(st.contagem), len(st.achados)))
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
        ctx.term()
    relatorio(st)


if __name__ == "__main__":
    main()
