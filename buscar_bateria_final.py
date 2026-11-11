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

# 1. Procurar Tensao (52V)
print('\n--- Procurando TENSAO (52V) ---')
for i in range(0, len(payload)-3, 4):
    f = struct.unpack('<f', payload[i:i+4])[0]
    if 51.0 <= f <= 53.0:
        print(f'[FLOAT] Offset {i}: {f:.2f}V | Hex: {payload[i:i+4].hex()}')

# 2. Procurar Corrente (4.9A)
print('\n--- Procurando CORRENTE (4.9A) ---')
for i in range(0, len(payload)-3, 4):
    f = struct.unpack('<f', payload[i:i+4])[0]
    if 4.5 <= f <= 5.2:
        print(f'[FLOAT] Offset {i}: {f:.2f}A | Hex: {payload[i:i+4].hex()}')

# 3. Procurar Charge (75)
print('\n--- Procurando CHARGE (75%) ---')
for i in range(len(payload)):
    if payload[i] == 75:
        print(f'[INT 8] Offset {i}: 75% | Contexto: {payload[max(0,i-5):i+5].hex()}')

print('\nFim da busca.')
