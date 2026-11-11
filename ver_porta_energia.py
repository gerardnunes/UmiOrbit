import zmq, time

ctx = zmq.Context()

# Conecta na porta do A9_2 (energia) e na porta do tópico 20401
sock_5033 = ctx.socket(zmq.SUB)
sock_5033.setsockopt(zmq.SUBSCRIBE, b'')
sock_5033.setsockopt(zmq.RCVTIMEO, 500)
sock_5033.connect('tcp://10.20.42.4:5033')

sock_20401 = ctx.socket(zmq.SUB)
sock_20401.setsockopt(zmq.SUBSCRIBE, b'')
sock_20401.setsockopt(zmq.RCVTIMEO, 500)
sock_20401.connect('tcp://10.20.42.4:5054')

print('Escutando A9_2 (5033) e 20401...')
inicio = time.time()
vistos = set()

while time.time() - inicio < 15:
    for nome, sock in [('5033', sock_5033), ('20401', sock_20401)]:
        try:
            topico = sock.recv()
            payload = sock.recv()
            if nome == '5033' and not topico: continue # Ignora vazio
            
            chave = f'{nome}_{topico.hex()}_{len(payload)}'
            if chave in vistos: continue
            vistos.add(chave)

            print(f'[{nome}] Topico: {topico} | Tamanho: {len(payload)} bytes')
            print(f'   Hex: {payload.hex()[:120]}...') # Mostra os primeiros 120 chars do hex
        except zmq.Again:
            pass

sock_5033.close()
sock_20401.close()
ctx.term()
print('Fim.')
