import zmq, time

ctx = zmq.Context()
sock = ctx.socket(zmq.SUB)
sock.setsockopt(zmq.SUBSCRIBE, b"")
sock.setsockopt(zmq.RCVTIMEO, 2000)
sock.connect("tcp://10.20.42.4:5054")

alvos = {
    b"1202_142004", b"50002_142004", b"25101_142004",
    b"20401_142004", b"51103_142004", b"20301_142004",
    b"50101_142004", b"50102_142004", b"50103_142004",
    b"50201_142004", b"50202_142004", b"20103_142004",
}
salvos = {}
inicio = time.time()

print(f"Capturando {len(alvos)} tópicos por 60s...")
while time.time() - inicio < 60:
    try:
        topico = sock.recv()
        payload = sock.recv()
        if topico in alvos and topico not in salvos:
            salvos[topico] = payload
            nome = topico.decode().replace("_", "-") + ".bin"
            with open(nome, "wb") as f:
                f.write(payload)
            print(f"✅ {topico.decode()}: {len(payload)}b")
            print(f"   {payload.hex()}")
            if len(salvos) == len(alvos):
                break
    except zmq.Again:
        pass

print(f"\nCapturados: {len(salvos)}/{len(alvos)}")
sock.close()
ctx.term()
