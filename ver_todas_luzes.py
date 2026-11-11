import zmq, time

ctx = zmq.Context()
sock = ctx.socket(zmq.SUB)
sock.setsockopt(zmq.SUBSCRIBE, b'')
sock.setsockopt(zmq.RCVTIMEO, 1000)
sock.connect('tcp://10.20.42.4:5054')

print('Escutando a lista completa de luzes (10102_142004)...')
inicio = time.time()
payload = None
while time.time() - inicio < 20:
    try:
        topico = sock.recv()
        p = sock.recv()
    except:
        continue
    if topico == b'10102_142004' and len(p) > 500: # Filtra pelo pacote grande (lista completa)
        payload = p
        break
sock.close()
ctx.term()

if not payload:
    print('Nao capturou o pacote completo das luzes.')
    exit()

print(f'Capturado! Tamanho: {len(payload)} bytes\n')

# Dicionário de tradução
TRADUCAO = {
    "左外推进器电源": "Propulsor Esq. Externo",
    "右外推进器电源": "Propulsor Dir. Externo",
    "左内推进器电源": "Propulsor Esq. Interno",
    "右内推进器电源": "Propulsor Dir. Interno",
    "锚灯": "Luz de Âncora",
    "NUC ≥ light": "Luz NUC (Alta)",
    "NUC ≤ light": "Luz NUC (Baixa)",
    "Masthead light": "Luz do Mastro",
    "Anchor light": "Luz de Fundeio",
    "White stern light": "Luz de Popa",
    "Navigation light": "Luz de Navegação",
    "拖拽系统应用": "Sistema de Reboque",
    "SVP绞车应用": "Guincho SVP",
    "左片体舱底水": "Porão Esq.",
    "右片体舱底水": "Porão Dir.",
    "White": "Branca",
    "左撒放": "Soltar Esq.",
    "右撒放": "Soltar Dir.",
    "自动油平衡": "Balanceamento Automático",
}

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

luzes = []
pos = 0
while pos < len(payload):
    tag, pos = read_varint(payload, pos)
    fn = tag >> 3
    wt = tag & 7
    if wt == 2:
        ln, pos = read_varint(payload, pos)
        sub = payload[pos:pos + ln]
        pos += ln
        if fn == 5: # Lista de itens
            p = 0
            while p < len(sub):
                t2, p = read_varint(sub, p)
                f2 = t2 >> 3
                w2 = t2 & 7
                if w2 == 2:
                    l2, p = read_varint(sub, p)
                    item = sub[p:p + l2]
                    p += l2
                    # Extrai nome e status do item
                    nome = None
                    status = 0
                    ip = 0
                    while ip < len(item):
                        t3, ip = read_varint(item, ip)
                        f3 = t3 >> 3
                        w3 = t3 & 7
                        if w3 == 2:
                            l3, ip = read_varint(item, ip)
                            sub3 = item[ip:ip + l3]
                            ip += l3
                            if f3 == 3:
                                nome = sub3.decode("utf-8", errors="replace")
                        elif w3 == 0:
                            v3, ip = read_varint(item, ip)
                            if f3 == 5:
                                status = v3
                        elif w3 == 5: ip += 4
                        elif w3 == 1: ip += 8
                        else: break
                    if nome:
                        luzes.append({"nome": nome, "status": status})
                elif w2 == 0: _, p = read_varint(sub, p)
                elif w2 == 5: p += 4
                elif w2 == 1: p += 8
                else: break
    elif wt == 0: _, pos = read_varint(payload, pos)
    elif wt == 5: pos += 4
    elif wt == 1: pos += 8
    else: break

print(f'Encontradas {len(luzes)} luzes:\n')
for l in luzes:
    nome_pt = TRADUCAO.get(l["nome"], l["nome"])
    # 0x28 (40) = LIGADA, 0x0B (11) = DESLIGADA
    estado = "LIGADA" if l["status"] in (40, 0x28) else "DESLIGADA"
    print(f'  {nome_pt:30s} -> {estado} (Raw: {l["status"]})')
