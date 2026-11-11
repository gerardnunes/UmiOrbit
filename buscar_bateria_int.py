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

print(f'Capturado! {len(payload)} bytes')

for nome, offset in [('BATERIA 1', 2064), ('BATERIA 2', 2162)]:
    print(f'\n--- {nome} (SOC = 75 no Offset {offset}) ---')
    
    # Pega 30 bytes antes e 30 depois
    inicio_c = max(0, offset-30)
    fim_c = min(len(payload), offset+30)
    trecho = payload[inicio_c:fim_c]
    
    print(f'Hex: {trecho.hex()}')
    
    # Tenta ler como int32 escalado (ex: 5200 / 100 = 52.0)
    for i in range(0, len(trecho)-3, 4):
        off_global = inicio_c + i
        # Little endian signed int
        v32 = struct.unpack('<i', trecho[i:i+4])[0]
        
        # Testa Tensao (52V): se for 5200, 520, ou 52
        if 5100 <= v32 <= 5300 or 510 <= v32 <= 530:
            print(f'  Offset {off_global}: {v32} <- POSSIVEL TENSAO (dividir por 100 ou 10)')
            
        # Testa Corrente (4.9A): se for 490, 49
        elif 480 <= v32 <= 500 or 48 <= v32 <= 50:
            print(f'  Offset {off_global}: {v32} <- POSSIVEL CORRENTE (dividir por 100 ou 10)')

print('\nFim.')
