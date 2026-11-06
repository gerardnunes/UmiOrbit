import time

import zmq
from django.core.management.base import BaseCommand

from operacao.models import LeituraGuincho, Sistema
from operacao.services_telemetria import (
    ler_guincho,
    processar_zmq,
    salvar_guincho,
)


class Command(BaseCommand):
    help = "Puxa telemetria do L42 (guinchos + ZMQ) e salva no banco."

    def add_arguments(self, parser):
        parser.add_argument("--sistema", default="L42")
        parser.add_argument("--intervalo", type=float, default=0.5,
                            help="Segundos entre ciclos (padrão: 0.5 = 500ms)")
        parser.add_argument("--loop", action="store_true")
        parser.add_argument("--host", default="10.20.42.4")
        parser.add_argument("--zmq", default="tcp://10.20.42.4:5054")

    def handle(self, *args, **opts):
        sistema = Sistema.objects.filter(nome__iexact=opts["sistema"]).first()
        if not sistema:
            self.stderr.write("Sistema nao encontrado: " + opts["sistema"])
            return

        host = opts["host"]
        intervalo = opts["intervalo"]

        ctx = zmq.Context()
        sock = ctx.socket(zmq.SUB)
        sock.setsockopt(zmq.SUBSCRIBE, b"")
        sock.setsockopt(zmq.RCVTIMEO, 500)
        sock.connect(opts["zmq"])
        self.stdout.write("ZMQ conectado: " + opts["zmq"])
        self.stdout.write(f"intervalo: {intervalo}s")

        try:
            while True:
                # ----- Guinchos -----
                for porta, tipo in [
                    (7, LeituraGuincho.Tipo.TRACAO),
                    (8, LeituraGuincho.Tipo.SVP),
                ]:
                    dados = ler_guincho(host, porta)
                    if dados:
                        salvar_guincho(sistema, tipo, dados)

                # ----- ZMQ: AGORA RETORNA 4 VALORES -----
                n_pos, n_prop, n_gps, n_radar = processar_zmq(
                    sock, sistema, duracao=intervalo
                )

                # Log resumido
                if int(time.time() * 2) % 10 == 0:
                    self.stdout.write(
                        f"posicao={n_pos} propulsor={n_prop} gps={n_gps} radares={n_radar}"
                    )

                if not opts["loop"]:
                    break

        except KeyboardInterrupt:
            self.stdout.write("Parando...")
        finally:
            sock.close()
            ctx.term()