"""Popula o sistema com sistemas do barco, usuários de exemplo e demandas de demonstração.

    python manage.py seed
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from operacao.models import Atualizacao, Demanda, Perfil, Sistema

User = get_user_model()

SISTEMAS = [
    ("Casco e estrutura", "Casco, convés, vedação, ânodos"),
    ("Propulsão", "Motores, hélices, controladores"),
    ("Energia e baterias", "Baterias, carregadores, painéis"),
    ("Elétrica geral", "Chicotes, conectores, quadros"),
    ("Navegação e autonomia", "LIDAR, GPS, câmeras, software de bordo"),
    ("Comunicação e telemetria", "Rádio, 4G/satélite, antenas"),
    ("Segurança e emergência", "Parada de emergência, sentina, luzes de navegação"),
]

USUARIOS = [
    # login, nome, sobrenome, papel, cargo
    ("ana", "Ana", "Souza", Perfil.Papel.TRABALHADOR, "Engenheira de automação"),
    ("carlos", "Carlos", "Lima", Perfil.Papel.TRABALHADOR, "Técnico naval"),
    ("diretor", "Marcos", "Andrade", Perfil.Papel.DIRETOR, "Diretor de operações"),
]

# título, sistema, tipo, prioridade, status, bloqueia, item, qtd, resp, dias_prazo, descricao
DEMANDAS = [
    ("Bateria reserva de 48 V não chegou", "Energia e baterias", "FALTANTE", "CRITICA", "PENDENTE", True, "Bateria LiFePO4 48 V", 1, None, 5, "Sem a reserva o barco não cumpre a autonomia mínima de missão."),
    ("Teste de parada de emergência remota", "Segurança e emergência", "INSPECAO", "CRITICA", "BLOQUEADA", True, "", None, "ana", 3, "Bloqueado até chegar o módulo de rádio reserva."),
    ("Calibrar LIDAR frontal", "Navegação e autonomia", "MANUTENCAO", "ALTA", "ANDAMENTO", False, "", None, "ana", 2, "Desvio de 2° observado no último teste."),
    ("Conector estanque IP68 de 12 pinos", "Elétrica geral", "FALTANTE", "ALTA", "PENDENTE", False, "Conector IP68 12 pinos", 4, None, 7, ""),
    ("Suporte da antena 4G quebrado", "Comunicação e telemetria", "DEFEITO", "MEDIA", "ANDAMENTO", False, "", None, "carlos", -1, "Trincou na solda. Refazer com reforço."),
    ("Sensor de sentina com falha intermitente", "Segurança e emergência", "DEFEITO", "ALTA", "PENDENTE", False, "", None, None, 4, ""),
    ("Trocar ânodos de sacrifício", "Casco e estrutura", "MANUTENCAO", "MEDIA", "PENDENTE", False, "Ânodo de zinco", 6, "carlos", 14, ""),
    ("Atualizar firmware do controlador de propulsão", "Propulsão", "MELHORIA", "BAIXA", "CONCLUIDA", False, "", None, "ana", None, ""),
    ("Inspeção visual do casco", "Casco e estrutura", "INSPECAO", "MEDIA", "CONCLUIDA", False, "", None, "carlos", None, "Sem trincas ou osmose."),
]


class Command(BaseCommand):
    help = "Cria dados de demonstração (idempotente)."

    def handle(self, *args, **opts):
        sistemas = {}
        for i, (nome, desc) in enumerate(SISTEMAS):
            sistemas[nome], _ = Sistema.objects.get_or_create(nome=nome, defaults={"descricao": desc, "ordem": i})

        users = {}
        for login, nome, sobrenome, papel, cargo in USUARIOS:
            u, criado = User.objects.get_or_create(username=login, defaults={"first_name": nome, "last_name": sobrenome})
            if criado:
                u.set_password(f"{login}12345")
                u.save()
            Perfil.objects.filter(user=u).update(papel=papel, cargo=cargo)
            users[login] = u

        if Demanda.objects.exists():
            self.stdout.write("Já existem demandas; nada criado além de sistemas e usuários.")
        else:
            hoje = timezone.localdate()
            for t, sis, tipo, prio, st, bloq, item, qtd, resp, dias, desc in DEMANDAS:
                d = Demanda.objects.create(
                    titulo=t, sistema=sistemas[sis], tipo=tipo, prioridade=prio, status=st,
                    bloqueia_operacao=bloq, item_faltante=item, quantidade=qtd, descricao=desc,
                    responsavel=users.get(resp), criado_por=users["ana"],
                    prazo=hoje + timedelta(days=dias) if dias is not None else None)
                Atualizacao.objects.create(demanda=d, autor=users["ana"], texto="Demanda criada.")
            self.stdout.write(self.style.SUCCESS(f"{len(DEMANDAS)} demandas de exemplo criadas."))

        self.stdout.write("Usuários de exemplo (troque as senhas!):")
        for login, *_ in USUARIOS:
            self.stdout.write(f"  {login} / {login}12345")
