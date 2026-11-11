import zmq
import time
import struct

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

# Busca por qualquer valor que possa ser 75
for i in range(len(payload)):
    if payload[i] == 75:
        inicio_c = max(0, i-5)
        fim_c = min(len(payload), i+5)
        contexto = payload[inicio_c:fim_c].hex()
        print(f'[INT 8] Offset {i}: 75 (0x4b) | Contexto: {contexto}')

# Busca por int16 (2 bytes) = 75
for i in range(0, len(payload)-1, 2):
    v = struct.unpack('<H', payload[i:i+2])[0]
    if v == 75:
        print(f'[INT 16] Offset {i}: 75 | Hex: {payload[i:i+2].hex()}')

# Busca por int32 (4 bytes) = 75
for i in range(0, len(payload)-3, 4):
    v = struct.unpack('<I', payload[i:i+4])[0]
    if v == 75:
        print(f'[INT 32] Offset {i}: 75 | Hex: {payload[i:i+4].hex()}')

# Busca por float 75.0 (4 bytes)
for i in range(0, len(payload)-3, 4):
    f = struct.unpack('<f', payload[i:i+4])[0]
    if 74.0 <= f <= 76.0:
        print(f'[FLOAT] Offset {i}: {f:.2f} | Hex: {payload[i:i+4].hex()}')

# Busca por double 75.0 (8 bytes)
for i in range(0, len(payload)-7, 8):
    d = struct.unpack('<d', payload[i:i+8])[0]
    if 74.0 <= d <= 76.0:
        print(f'[DOUBLE] Offset {i}: {d:.2f} | Hex: {payload[i:i+8].hex()}')

# Busca por '75' como string
for i in range(len(payload)-1):
    if payload[i:i+2] == b'75':
        try:
            texto = payload[max(0,i-10):i+10].decode('utf-8')
        except:
            texto = '???'
        print(f'[STRING] Offset {i}: 75 | Contexto: {texto}')

print('Fim da busca.')
