"""
rodar.py — Sobe Django + coletor ZMQ + abre navegador.

Uso:
    python manage.py rodar
    python manage.py rodar --porta 8000
    python manage.py rodar --sem-coletor   (só Django)
    python manage.py rodar --sem-browser   (não abre navegador)
"""
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Sobe Django + coletor ZMQ + abre navegador automaticamente"

    def add_arguments(self, parser):
        parser.add_argument("--porta", type=int, default=8000)
        parser.add_argument("--sistema", default="L42")
        parser.add_argument("--sem-coletor", action="store_true",
                            help="Não inicia o coletor ZMQ")
        parser.add_argument("--sem-browser", action="store_true",
                            help="Não abre o navegador")

    def handle(self, *args, **opts):
        porta = opts["porta"]
        sistema = opts["sistema"]
        base = Path(__file__).resolve().parent.parent.parent.parent
        manage_py = base / "manage.py"
        python = sys.executable

        if not manage_py.exists():
            self.stderr.write(f"[ERRO] manage.py não encontrado em {manage_py}")
            return

        processos = []

        try:
            # ============ 1. COLETOR ============
            if not opts["sem_coletor"]:
                self.stdout.write(self.style.HTTP_INFO("[1/3] Iniciando coletor ZMQ..."))
                coletor = subprocess.Popen(
                    [python, str(manage_py), "puxar_telemetria",
                     "--sistema", sistema, "--loop"],
                    cwd=str(base),
                )
                processos.append(("Coletor", coletor))
                time.sleep(2)  # dá tempo do ZMQ conectar
                self.stdout.write(self.style.SUCCESS(f"  OK — PID {coletor.pid}"))
            else:
                self.stdout.write(self.style.WARNING("[1/3] Coletor desligado (--sem-coletor)"))

            # ============ 2. DJANGO ============
            self.stdout.write(self.style.HTTP_INFO(f"[2/3] Iniciando Django na porta {porta}..."))
            django = subprocess.Popen(
                [python, str(manage_py), "runserver", f"0.0.0.0:{porta}",
                 "--noreload"],  # --noreload pra Ctrl+C matar direitinho
                cwd=str(base),
            )
            processos.append(("Django", django))
            time.sleep(3)
            self.stdout.write(self.style.SUCCESS(f"  OK — PID {django.pid}"))

            # ============ 3. NAVEGADOR ============
            if not opts["sem_browser"]:
                self.stdout.write(self.style.HTTP_INFO("[3/3] Abrindo navegador..."))
                time.sleep(1)
                try:
                    webbrowser.open(f"http://127.0.0.1:{porta}/telemetria/")
                    self.stdout.write(self.style.SUCCESS("  OK"))
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"  Aviso: {e}"))

            # ============ STATUS ============
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("=" * 60))
            self.stdout.write(self.style.SUCCESS("  SISTEMA RODANDO"))
            self.stdout.write(self.style.SUCCESS("=" * 60))
            self.stdout.write(f"  Dashboard: http://127.0.0.1:{porta}/telemetria/")
            self.stdout.write(f"  Admin:     http://127.0.0.1:{porta}/admin/")
            self.stdout.write("")
            self.stdout.write(self.style.HTTP_INFO("  Logs em tempo real abaixo:"))
            self.stdout.write(self.style.HTTP_INFO("  (Ctrl+C para parar tudo)"))
            self.stdout.write("")

            # ============ LOOP DE MONITORAMENTO ============
            # Fica monitorando os 2 processos. Se um cair, mata o outro.
            while True:
                time.sleep(1)
                for nome, p in processos:
                    if p.poll() is not None:
                        self.stderr.write(self.style.ERROR(
                            f"[AVISO] {nome} parou (exit {p.returncode}). Parando tudo..."
                        ))
                        raise KeyboardInterrupt

        except KeyboardInterrupt:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Parando sistema..."))

        finally:
            for nome, p in processos:
                if p.poll() is None:
                    try:
                        p.terminate()
                        p.wait(timeout=5)
                        self.stdout.write(f"  {nome} parado")
                    except subprocess.TimeoutExpired:
                        p.kill()
                        self.stdout.write(f"  {nome} forçado a parar")
                    except Exception as e:
                        self.stderr.write(f"  Erro ao parar {nome}: {e}")

            self.stdout.write(self.style.SUCCESS("Sistema encerrado."))