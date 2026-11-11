"""
Leitura de telemetria do L42:
- Guinchos (TCP 7 e 8) → JSON puro
- Posição, propulsor, GPS e radares (ZMQ 5054) → protobuf
"""
import json
import math
import socket
import struct
import time

import zmq

from .models import (
    LeituraGuincho, LeituraPosicao, LeituraPropulsor, OrigemGPS, 
    RadarDetectado, Sistema,
)


# =========================================================
# GUINCHOS (TCP, JSON)
# =========================================================
def ler_guincho(host: str, porta: int, timeout: float = 3.0) -> dict | None:
    try:
        with socket.create_connection((host, porta), timeout=timeout) as s:
            s.settimeout(timeout)
            buf = b""
            while True:
                try:
                    data = s.recv(4096)
                except socket.timeout:
                    break
                if not data:
                    break
                buf += data
                inicio = buf.find(b"{")
                if inicio >= 0:
                    depth = 0
                    for i in range(inicio, len(buf)):
                        b = buf[i:i + 1]
                        if b == b"{":
                            depth += 1
                        elif b == b"}":
                            depth -= 1
                            if depth == 0:
                                texto = buf[inicio:i + 1].decode("utf-8", errors="replace")
                                try:
                                    return json.loads(texto)
                                except json.JSONDecodeError:
                                    continue
                if len(buf) > 100_000:
                    break
            return None
    except (socket.timeout, socket.error) as e:
        print(f"[guincho {porta}] erro: {e}")
        return None


def _f(v):
    if v is None: return None
    try: return float(v)
    except (TypeError, ValueError): return None


def _i(v):
    if v is None: return None
    try: return int(v)
    except (TypeError, ValueError): return None


def salvar_guincho(sistema: Sistema, tipo: str, dados: dict):
    campos = {"sistema": sistema, "tipo": tipo, "raw_json": dados}
    if tipo == LeituraGuincho.Tipo.SVP:
        campos.update({
            "current_temp": _f(dados.get("current_temp")),
            "current_vol": _f(dados.get("current_vol")),
            "current_ele": _f(dados.get("current_ele")),
            "current_pull": _f(dados.get("current_pull")),
            "rope_speed": _f(dados.get("rope_speed")),
            "pull_rope_len": _f(dados.get("pull_rope_len")),
            "winch_rate": _f(dados.get("winch_rate")),
            "current_work_status": _i(dados.get("current_work_status")),
            "warn": (dados.get("warn") or "")[:200],
            "sys_time": (dados.get("sys_time") or "")[:40],
        })
    else:
        campos.update({
            "max_rope_len": _f(dados.get("max_rope_len")),
            "remain_min_rope_len": _f(dados.get("remain_min_rope_len")),
            "sensor_once_rope_len": _f(dados.get("sensor_once_rope_len")),
            "winch_acc_speed_ratio": _f(dados.get("winch_acc_speed_ratio")),
            "winch_turn_rate_value": _f(dados.get("winch_turn_rate_value")),
        })
    return LeituraGuincho.objects.create(**campos)


# =========================================================
# PROTOBUF — helpers
# =========================================================
def _read_varint(data, pos):
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


def _zigzag_decode(v):
    return (v >> 1) ^ -(v & 1)


# =========================================================
# POSIÇÃO
# =========================================================
def decodificar_posicao(payload: bytes) -> dict | None:
    try:
        pos = 0
        candidatos = []
        while pos < len(payload):
            tag, pos = _read_varint(payload, pos)
            fn = tag >> 3
            wt = tag & 7
            if wt == 2:
                ln, pos = _read_varint(payload, pos)
                if pos + ln > len(payload): break
                sub = payload[pos:pos + ln]
                pos += ln
                nome, valores = _parse_transformada(sub)
                if nome and valores.get("x") is not None:
                    candidatos.append((nome, valores))
            elif wt == 1: pos += 8
            elif wt == 5: pos += 4
            elif wt == 0: _, pos = _read_varint(payload, pos)
            else: break

        if not candidatos: return None

        prioridade = ["usv_xy_3d_id", "usv_enu_3d_id", "usv_xy_2d_id"]
        for pref in prioridade:
            for nome, vals in candidatos:
                if nome == pref:
                    return {
                        "x": vals.get("x"), "y": vals.get("y"),
                        "z": vals.get("z", 0.0), "qw": vals.get("qw", 1.0),
                        "timestamp": vals.get("ts"), "nome": nome,
                    }
        return None
    except Exception as e:
        print(f"[posicao] erro: {e}")
        return None


def _parse_transformada(data: bytes):
    try:
        pos = 0; nome = None; valores = {}
        while pos < len(data):
            tag, pos = _read_varint(data, pos)
            fn = tag >> 3; wt = tag & 7
            if wt == 2:
                ln, pos = _read_varint(data, pos)
                sub = data[pos:pos + ln]; pos += ln
                if fn == 2: nome = sub.decode("utf-8", errors="replace")
                elif fn == 4: valores.update(_parse_xyzw(sub))
            elif wt == 0: _, pos = _read_varint(data, pos)
            elif wt == 1:
                if fn == 1 and pos + 8 <= len(data):
                    valores["ts"] = struct.unpack("<d", data[pos:pos + 8])[0]
                pos += 8
            elif wt == 5: pos += 4
            else: break
        return nome, valores
    except Exception as e:
        print(f"[transformada] erro: {e}")
        return None, {}


def _parse_xyzw(data: bytes) -> dict:
    out = {}; pos = 0
    while pos < len(data):
        tag, pos = _read_varint(data, pos)
        fn = tag >> 3; wt = tag & 7
        if wt == 5 and pos + 4 <= len(data):
            val = struct.unpack("<f", data[pos:pos + 4])[0]
            if fn == 1: out["x"] = val
            elif fn == 2: out["y"] = val
            elif fn == 3: out["z"] = val
            elif fn == 4: out["qw"] = val
            pos += 4
        elif wt == 0: _, pos = _read_varint(data, pos)
        elif wt == 2:
            ln, pos = _read_varint(data, pos); pos += ln
        else: break
    return out


# =========================================================
# PROPULSOR
# =========================================================
def decodificar_propulsor(payload: bytes) -> dict | None:
    try:
        pos = 0; steer = None; modo = None; ts_msg = None; atuadores = []
        while pos < len(payload):
            tag, pos = _read_varint(payload, pos)
            fn = tag >> 3; wt = tag & 7
            if wt == 0:
                v, pos = _read_varint(payload, pos)
                if fn == 1: ts_msg = v / 1000.0
            elif wt == 2:
                ln, pos = _read_varint(payload, pos)
                sub = payload[pos:pos + ln]; pos += ln
                if fn == 4:
                    s, m, at = _parse_prop_inner(sub)
                    if s is not None: steer = s
                    if m is not None: modo = m
                    if at: atuadores = at
            elif wt == 5: pos += 4
            elif wt == 1: pos += 8
            else: break
        return {"steer": steer, "modo": modo, "timestamp": ts_msg, "atuadores": atuadores}
    except Exception as e:
        print(f"[propulsor] erro: {e}")
        return None


def _parse_prop_inner(data: bytes):
    steer = None; modo = None; atuadores = []; pos = 0
    while pos < len(data):
        tag, pos = _read_varint(data, pos)
        fn = tag >> 3; wt = tag & 7
        if wt == 2:
            ln, pos = _read_varint(data, pos)
            sub = data[pos:pos + ln]; pos += ln
            if fn == 3:
                s, m = _parse_prop_cmd(sub)
                if s is not None: steer = s
                if m is not None: modo = m
            elif fn == 7:
                at = _parse_prop_timestamps(sub)
                if at: atuadores = at
        elif wt == 0: _, pos = _read_varint(data, pos)
        elif wt == 5: pos += 4
        elif wt == 1: pos += 8
        else: break
    return steer, modo, atuadores


def _parse_prop_cmd(data: bytes):
    steer = None; modo = None; pos = 0
    while pos < len(data):
        tag, pos = _read_varint(data, pos)
        fn = tag >> 3; wt = tag & 7
        if wt == 5 and pos + 4 <= len(data):
            val = struct.unpack("<f", data[pos:pos + 4])[0]
            if fn == 6: steer = val
            elif fn == 8: modo = val
            pos += 4
        elif wt == 0:
            v, pos = _read_varint(data, pos)
            if fn == 15: modo = v
        elif wt == 2:
            ln, pos = _read_varint(data, pos); pos += ln
        elif wt == 1: pos += 8
        else: break
    return steer, modo


def _parse_prop_timestamps(data: bytes):
    atuadores = []; pos = 0
    while pos < len(data):
        tag, pos = _read_varint(data, pos)
        fn = tag >> 3; wt = tag & 7
        if wt == 2:
            ln, pos = _read_varint(data, pos)
            sub = data[pos:pos + ln]; pos += ln
            p = 0
            while p < len(sub):
                t, p = _read_varint(sub, p)
                f2 = t >> 3; w2 = t & 7
                if w2 == 0:
                    v, p = _read_varint(sub, p)
                    if f2 == 1: atuadores.append(v)
                elif w2 == 2:
                    l2, p = _read_varint(sub, p); p += l2
                elif w2 == 5: p += 4
                elif w2 == 1: p += 8
                else: break
        elif wt == 0: _, pos = _read_varint(data, pos)
        elif wt == 5: pos += 4
        elif wt == 1: pos += 8
        else: break
    return atuadores


# =========================================================
# GPS
# =========================================================
def decodificar_gps(payload: bytes) -> dict | None:
    try:
        pos = 0; lat = None; lon = None; ts = None
        while pos < len(payload):
            tag, pos = _read_varint(payload, pos)
            fn = tag >> 3; wt = tag & 7
            if wt == 0:
                v, pos = _read_varint(payload, pos)
                if fn == 1: ts = v / 1000.0
            elif wt == 2:
                ln, pos = _read_varint(payload, pos)
                sub = payload[pos:pos + ln]; pos += ln
                if fn == 6:
                    la, lo = _parse_gps_field6(sub)
                    if la is not None: lat, lon = la, lo
            elif wt == 5: pos += 4
            elif wt == 1: pos += 8
            else: break

        if lat is None or lon is None: return None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180): return None
        return {"lat": lat, "lon": lon, "timestamp": ts}
    except Exception as e:
        print(f"[gps] erro: {e}")
        return None


def _parse_gps_field6(data: bytes):
    pos = 0
    while pos < len(data):
        tag, pos = _read_varint(data, pos)
        fn = tag >> 3; wt = tag & 7
        if wt == 2:
            ln, pos = _read_varint(data, pos)
            sub = data[pos:pos + ln]; pos += ln
            if fn == 1:
                lon_raw, lat_raw = _parse_gps_inner(sub)
                if lon_raw is not None and lat_raw is not None:
                    return (_zigzag_decode(lat_raw) / 1e7, _zigzag_decode(lon_raw) / 1e7)
        elif wt == 0: _, pos = _read_varint(data, pos)
        elif wt == 5: pos += 4
        elif wt == 1: pos += 8
        else: break
    return None, None


def _parse_gps_inner(data: bytes):
    lon_raw = None; lat_raw = None; pos = 0
    while pos < len(data):
        tag, pos = _read_varint(data, pos)
        fn = tag >> 3; wt = tag & 7
        if wt == 0:
            v, pos = _read_varint(data, pos)
            if fn == 1: lon_raw = v
            elif fn == 2: lat_raw = v
        elif wt == 2:
            ln, pos = _read_varint(data, pos); pos += ln
        elif wt == 5: pos += 4
        elif wt == 1: pos += 8
        else: break
    return lon_raw, lat_raw


def salvar_origem_gps(sistema, dados):
    OrigemGPS.objects.update_or_create(
        sistema=sistema, defaults={"lat": dados["lat"], "lon": dados["lon"]},
    )


# =========================================================
# RADARES
# =========================================================
def decodificar_radares(payload: bytes) -> list[dict]:
    try:
        pos = 0; radares = []
        while pos < len(payload):
            tag, pos = _read_varint(payload, pos)
            fn = tag >> 3; wt = tag & 7
            if wt == 2:
                ln, pos = _read_varint(payload, pos)
                sub = payload[pos:pos + ln]; pos += ln
                if fn == 5:
                    p = 0
                    while p < len(sub):
                        t2, p = _read_varint(sub, p)
                        f2 = t2 >> 3; w2 = t2 & 7
                        if w2 == 2:
                            l2, p = _read_varint(sub, p)
                            radar_data = sub[p:p + l2]; p += l2
                            if f2 == 1:
                                radar = _parse_radar(radar_data)
                                if radar: radares.append(radar)
                        elif w2 == 0: _, p = _read_varint(sub, p)
                        elif w2 == 5: p += 4
                        elif w2 == 1: p += 8
                        else: break
            elif wt == 0: _, pos = _read_varint(payload, pos)
            elif wt == 5: pos += 4
            elif wt == 1: pos += 8
            else: break
        return radares
    except Exception as e:
        print(f"[radares] erro: {e}")
        return []


def _parse_radar(data: bytes) -> dict | None:
    """Extrai os dados de um radar. Usa distância (4.11) + ângulo (4.7)."""
    nome = None
    x = 0.0
    y = 0.0
    z = 0.0
    ts = 0.0
    qualidade = 0.0
    distancia = 0.0
    azimute_raw = None

    pos = 0
    while pos < len(data):
        tag, pos = _read_varint(data, pos)
        fn = tag >> 3
        wt = tag & 7
        if wt == 2:
            ln, pos = _read_varint(data, pos)
            sub = data[pos:pos + ln]
            pos += ln
            if fn == 2:  # Nome
                nome = sub.decode("utf-8", errors="replace")
            elif fn == 4:  # Dados do radar
                p = 0
                while p < len(sub):
                    t2, p = _read_varint(sub, p)
                    f2 = t2 >> 3
                    w2 = t2 & 7
                    if w2 == 0:
                        v2, p = _read_varint(sub, p)
                        if f2 == 6:
                            ts = v2 / 1000.0
                        elif f2 == 7:
                            azimute_raw = v2      # ← AZIMUTE (vamos descobrir a fórmula)
                        elif f2 == 10:
                            x = float(v2)          # X (só alguns têm)
                        elif f2 == 11:
                            distancia = float(v2)  # DISTÂNCIA
                            y = float(v2)
                        elif f2 == 12:
                            z = float(v2)
                    elif w2 == 5:
                        p += 4
                    elif w2 == 1:
                        p += 8
                    elif w2 == 2:
                        l2, p = _read_varint(sub, p)
                        p += l2
                    else:
                        break
            elif fn == 6:  # Meta
                p = 0
                while p < len(sub):
                    t2, p = _read_varint(sub, p)
                    f2 = t2 >> 3
                    w2 = t2 & 7
                    if w2 == 5 and p + 4 <= len(sub):
                        val = struct.unpack("<f", sub[p:p + 4])[0]
                        if f2 == 3:
                            qualidade = val
                        p += 4
                    elif w2 == 0:
                        _, p = _read_varint(sub, p)
                    else:
                        break
        elif wt == 0:
            _, pos = _read_varint(data, pos)
        elif wt == 5:
            pos += 4
        elif wt == 1:
            pos += 8
        else:
            break

    if nome and distancia > 0:
        # ⚠️ Se o radar tem X e Y (4.10 e 4.11), usa direto (radar_5439 tem)
        # Senão, calcula X e Y a partir de distância + azimute
        
        if x != 0:  # radar_5439 tem X
            # Usa x/y direto (não precisa de azimute)
            pass
        elif azimute_raw is not None:
            # Calcula x/y a partir de distância + azimute
            # ⚠️ TENTATIVA: o azimute_raw parece ser em mili-radianos ou algo assim
            # 406569411 / 1e6 = 406.57 → - 360 = 46.57°
            azimute_deg = (azimute_raw / 1e6) % 360
            rad = math.radians(azimute_deg)
            x = distancia * math.cos(rad)
            y = distancia * math.sin(rad)
        else:
            # Sem azimute, plotar no eixo Y (o que está acontecendo agora)
            x = 0
            y = distancia
        
        return {
            "nome": nome,
            "x": x,
            "y": y,
            "distancia": distancia,
            "azimute": math.degrees(math.atan2(y, x)) if (x != 0 or y != 0) else 0,
            "timestamp": ts,
            "qualidade": qualidade,
        }
    return None

# =========================================================
# SALVAR NO BANCO (CORRIGIDO)
# =========================================================
def salvar_posicao(sistema, dados):
    return LeituraPosicao.objects.create(
        sistema=sistema, x=dados["x"] or 0.0, y=dados["y"] or 0.0,
        z=dados.get("z") or 0.0, qw=dados.get("qw") or 1.0,
        timestamp_msg=dados.get("timestamp") or 0.0,
    )


def salvar_propulsor(sistema, dados):
    ats = (dados.get("atuadores") or []) + [None] * 4
    return LeituraPropulsor.objects.create(
        sistema=sistema, steer=dados.get("steer"), modo=dados.get("modo"),
        timestamp_msg=dados.get("timestamp") or 0.0,
        ts_atuador_1=ats[0], ts_atuador_2=ats[1], ts_atuador_3=ats[2], ts_atuador_4=ats[3],
    )


def salvar_radares(sistema, radares):
    """Apaga os antigos e insere os novos."""
    RadarDetectado.objects.filter(sistema=sistema).delete()
    for r in radares:
        RadarDetectado.objects.create(
            sistema=sistema, nome=r["nome"], x=r["x"], y=r["y"],
            distancia=r["distancia"], azimute=r["azimute"],
            timestamp=r["timestamp"], qualidade=r["qualidade"],
        )


# =========================================================
# PROCESSAR MENSAGEM ZMQ (CORRIGIDO)
# =========================================================
def processar_zmq(sock, sistema, duracao=2.0):
    n_pos = n_prop = n_gps = n_radar = 0
    deadline = time.time() + duracao
    
    while time.time() < deadline:
        try:
            topico = sock.recv()
            payload = sock.recv()
        except zmq.Again:
            break

        if topico == b"avos_tf_tree_142004":
            dados = decodificar_posicao(payload)
            if dados and dados.get("x") is not None:
                salvar_posicao(sistema, dados)
                n_pos += 1

        elif topico == b"50101_142004":
            dados = decodificar_propulsor(payload)
            if dados and dados.get("steer") is not None:
                salvar_propulsor(sistema, dados)
                n_prop += 1

        elif topico == b"20501_142004":
            dados = decodificar_gps(payload)
            if dados and dados.get("lat") is not None:
                salvar_origem_gps(sistema, dados)
                n_gps += 1

        elif topico == b"25101_142004":
            radares = decodificar_radares(payload)
            if radares:
                salvar_radares(sistema, radares)
                n_radar = len(radares)

        elif topico == b"20401_142004":
            dados = decodificar_bateria(payload)
            if dados:
                salvar_bateria(sistema, dados)

        elif topico == b"10102_142004":
            luzes = decodificar_luzes(payload)
            if luzes:
                salvar_luzes(sistema, luzes)

    return n_pos, n_prop, n_gps, n_radar

# =========================================================
# BATERIA (20401_142004)
# =========================================================
def decodificar_bateria(payload: bytes) -> dict | None:
    try:
        pos = 0
        res = {"temperatura": None, "celulas": None, "contador": None}
        while pos < len(payload):
            tag, pos = _read_varint(payload, pos)
            fn = tag >> 3
            wt = tag & 7
            if wt == 2:
                ln, pos = _read_varint(payload, pos)
                sub = payload[pos:pos + ln]
                pos += ln
                if fn == 5:  # Sub-mensagem da bateria
                    p = 0
                    while p < len(sub):
                        t2, p = _read_varint(sub, p)
                        f2 = t2 >> 3
                        w2 = t2 & 7
                        if w2 == 0:
                            v2, p = _read_varint(sub, p)
                            # Interpreta como signed int32
                            s32 = struct.unpack("<i", struct.pack("<I", v2 & 0xFFFFFFFF))[0]
                            if f2 == 1: res["celulas"] = s32
                            elif f2 == 2: res["temperatura"] = float(s32)
                        elif w2 == 5 and p + 4 <= len(sub):
                            f = struct.unpack("<f", sub[p:p+4])[0]
                            if f2 == 4: res["contador"] = f
                            p += 4
                        elif w2 == 2:
                            l2, p = _read_varint(sub, p)
                            p += l2
                        elif w2 == 1:
                            p += 8
                        else:
                            break
            elif wt == 0: _, pos = _read_varint(payload, pos)
            elif wt == 5: pos += 4
            elif wt == 1: pos += 8
            else: break
        return res if res["temperatura"] is not None else None
    except Exception:
        return None

def salvar_bateria(sistema, dados):
    from .models import StatusBateria
    return StatusBateria.objects.create(
        sistema=sistema,
        temperatura=dados.get("temperatura"),
        celulas=dados.get("celulas"),
        contador=dados.get("contador")
    )

# =========================================================
# LUZES (10102_142004)
# =========================================================
def decodificar_luzes(payload: bytes) -> list[dict]:
    try:
        pos = 0
        luzes = []
        while pos < len(payload):
            tag, pos = _read_varint(payload, pos)
            fn = tag >> 3
            wt = tag & 7
            if wt == 2:
                ln, pos = _read_varint(payload, pos)
                sub = payload[pos:pos + ln]
                pos += ln
                if fn == 5:  # Lista de itens
                    p = 0
                    while p < len(sub):
                        t2, p = _read_varint(sub, p)
                        f2 = t2 >> 3
                        w2 = t2 & 7
                        if w2 == 2:
                            l2, p = _read_varint(sub, p)
                            item = sub[p:p + l2]
                            p += l2
                            nome, status = _parse_luz(item)
                            if nome:
                                luzes.append({"nome": nome, "status": status})
                        elif w2 == 0: _, p = _read_varint(sub, p)
                        elif w2 == 5: p += 4
                        elif w2 == 1: p += 8
                        else: break
            elif wt == 0: _, pos = _read_varint(payload, pos)
            elif wt == 5: pos += 4
            elif wt == 1: pos += 8
            else: break
        return luzes
    except Exception:
        return []

def _parse_luz(data: bytes):
    nome = None
    status = 0
    pos = 0
    while pos < len(data):
        tag, pos = _read_varint(data, pos)
        fn = tag >> 3
        wt = tag & 7
        if wt == 2:
            ln, pos = _read_varint(data, pos)
            sub = data[pos:pos + ln]
            pos += ln
            if fn == 2: # Nome em chinês
                nome = sub.decode("utf-8", errors="replace")
        elif wt == 0:
            v, pos = _read_varint(data, pos)
            if fn == 3: # Status (0x28=40 ON, 0x0B=11 OFF)
                status = v
        elif wt == 5: pos += 4
        elif wt == 1: pos += 8
        else: break
    return nome, status

def salvar_luzes(sistema, luzes):
    from .models import StatusLuz
    StatusLuz.objects.filter(sistema=sistema).delete()
    for l in luzes:
        StatusLuz.objects.create(
            sistema=sistema,
            nome=l["nome"],
            status=l["status"]
        )