import zmq, time

ctx = zmq.Context()
sock = ctx.socket(zmq.SUB)
sock.setsockopt(zmq.SUBSCRIBE, b"")
sock.setsockopt(zmq.RCVTIMEO, 2000)
sock.connect("tcp://10.20.42.4:5054")

alvos = {b"10102_142004", b"20101_142004", b"20202_142004", b"20602_142004", b"20103_142004"}
salvos = set()
inicio = time.time()

print("Capturando 30s...")
while time.time() - inicio < 60 and len(salvos) < len(alvos):
    try:
        topico = sock.recv()
        payload = sock.recv()
        if topico in alvos and topico not in salvos:
            salvos.add(topico)
            nome = topico.decode().replace("_", "-") + ".bin"
            with open(nome, "wb") as f:
                f.write(payload)
            print(f"✅ {topico.decode()}: {len(payload)} bytes → {nome}")
            print(f"   hex: {payload.hex()}")
            print()
    except zmq.Again:
        pass

print(f"Capturados: {len(salvos)}/{len(alvos)}")
sock.close()
ctx.term()
