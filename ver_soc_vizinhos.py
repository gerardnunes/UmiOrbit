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

# O offset do SOC (75) na última captura foi 2065
soc_offset = 2065
inicio_c = max(0, soc_offset - 40)
fim_c = min(len(payload), soc_offset + 40)
trecho = payload[inicio_c:fim_c]

print(f'Hex ao redor do SOC (offset {soc_offset}):')
print(trecho.hex())

# Vamos testar se os bytes vizinhos são floats (tensão/corrente)
print('\nTestando floats na vizinhança:')
for i in range(0, len(trecho)-3, 4):
    off_global = inicio_c + i
    f = struct.unpack('<f', trecho[i:i+4])[0]
    print(f'  Offset {off_global}: {f:.2f}')

print('\nFim.')
