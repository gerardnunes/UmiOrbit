import zmq, time, struct

ctx = zmq.Context()
sock = ctx.socket(zmq.SUB)
sock.setsockopt(zmq.SUBSCRIBE, b'')
sock.setsockopt(zmq.RCVTIMEO, 1000)
sock.connect('tcp://10.20.42.4:5054')

print('Capturando 40101_142004...')
inicio = time.time()
payload = None
while time.time() - inicio < 20:
    try:
        topico = sock.recv()
        p = sock.recv()
    except:
        continue
    if topico == b'40101_142004':
        payload = p
        break
sock.close()
ctx.term()

if not payload:
    print('Nao capturou.')
    exit()

# Como o pacote mudou de tamanho (2273 bytes), vamos achar o SOC de novo
offsets_soc = [i for i in range(len(payload)) if payload[i] == 75]
print(f'Offsets com valor 75: {offsets_soc[:5]}')

for offset in offsets_soc[:2]: # Pega os 2 primeiros (Bateria 1 e 2)
    print(f'\n--- Analisando SOC no Offset {offset} ---')
    
    # Pega 60 bytes antes e 60 depois
    inicio_c = max(0, offset-60)
    fim_c = min(len(payload), offset+60)
    trecho = payload[inicio_c:fim_c]
    
    # Testa Int32 (Little Endian)
    for i in range(0, len(trecho)-3, 4):
        off_global = inicio_c + i
        v32 = struct.unpack('<i', trecho[i:i+4])[0]
        
        # Se for 5200 ou 520 ou 52 (Tensao)
        if 5100 <= v32 <= 5300 or 510 <= v32 <= 530 or 51 <= v32 <= 53:
            print(f'  [INT 32] Offset {off_global}: {v32} <- POSSIVEL TENSAO')
        # Se for 490, 49 ou 4900 (Corrente)
        elif 480 <= v32 <= 500 or 4800 <= v32 <= 5000 or 4 <= v32 <= 5:
            print(f'  [INT 32] Offset {off_global}: {v32} <- POSSIVEL CORRENTE')

    # Testa Int16 (Little Endian)
    for i in range(0, len(trecho)-1, 2):
        off_global = inicio_c + i
        v16 = struct.unpack('<h', trecho[i:i+2])[0]
        
        if 5100 <= v16 <= 5300 or 510 <= v16 <= 530:
            print(f'  [INT 16] Offset {off_global}: {v16} <- POSSIVEL TENSAO')
        elif 480 <= v16 <= 500 or 4800 <= v16 <= 5000:
            print(f'  [INT 16] Offset {off_global}: {v16} <- POSSIVEL CORRENTE')

print('\nFim.')
