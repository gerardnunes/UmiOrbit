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

print('\n--- Procurando TENSAO (floats entre 48 e 55) ---')
for i in range(0, len(payload)-3, 4):
    f = struct.unpack('<f', payload[i:i+4])[0]
    if 48.0 <= f <= 55.0:
        print(f'[FLOAT] Offset {i}: {f:.2f}V | Hex: {payload[i:i+4].hex()}')

print('\n--- Procurando CORRENTE (floats entre 1 e 50) ---')
for i in range(0, len(payload)-3, 4):
    f = struct.unpack('<f', payload[i:i+4])[0]
    if 1.0 <= f <= 50.0 and not (4.0 <= f <= 5.0): # Exclui 4.00 que é o padrão
        print(f'[FLOAT] Offset {i}: {f:.2f}A | Hex: {payload[i:i+4].hex()}')
    elif 4.0 <= f <= 5.0:
        print(f'[FLOAT] Offset {i}: {f:.2f}A (pode ser 4.9) | Hex: {payload[i:i+4].hex()}')

print('\nFim.')
