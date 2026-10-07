from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Atualizacao, Demanda, Perfil, Sistema, Status, Tipo

User = get_user_model()


class BaseTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.sis = Sistema.objects.create(nome="Propulsão")
        cls.trab = User.objects.create_user("trab", password="x")
        cls.dir = User.objects.create_user("dir", password="x")
        Perfil.objects.filter(user=cls.dir).update(papel=Perfil.Papel.DIRETOR)

    def nova(self, **kw):
        base = dict(titulo="Teste", sistema=self.sis, criado_por=self.trab)
        base.update(kw)
        return Demanda.objects.create(**base)


class PermissoesTest(BaseTest):
    def test_anonimo_vai_para_login(self):
        r = self.client.get(reverse("dashboard"))
        self.assertRedirects(r, f"{reverse('login')}?next=/")

    def test_diretor_ve_painel_e_lista(self):
        d = self.nova()
        self.client.force_login(self.dir)
        for url in (reverse("dashboard"), reverse("demanda_lista"), d.get_absolute_url(), reverse("equipe")):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_diretor_nao_edita(self):
        d = self.nova()
        self.client.force_login(self.dir)
        self.assertEqual(self.client.get(reverse("demanda_nova")).status_code, 403)
        self.assertEqual(self.client.post(reverse("demanda_assumir", args=[d.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("demanda_atualizar", args=[d.pk]), {"texto": "oi"}).status_code, 403)
        self.assertEqual(self.client.get(reverse("demanda_editar", args=[d.pk])).status_code, 403)

    def test_diretor_nao_ve_botoes_de_edicao(self):
        d = self.nova()
        self.client.force_login(self.dir)
        html = self.client.get(d.get_absolute_url()).content.decode()
        self.assertNotIn("Assumir", html)
        self.assertNotIn("Registrar andamento", html)


class FluxoTrabalhadorTest(BaseTest):
    def setUp(self):
        self.client.force_login(self.trab)

    def test_criar_faltante_exige_item(self):
        r = self.client.post(reverse("demanda_nova"), {"titulo": "Falta", "tipo": Tipo.FALTANTE, "sistema": self.sis.pk,
                                                       "prioridade": "ALTA"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Demanda.objects.exists())

    def test_criar_demanda(self):
        r = self.client.post(reverse("demanda_nova"), {"titulo": "Falta cabo", "tipo": Tipo.FALTANTE, "sistema": self.sis.pk,
                                                       "prioridade": "ALTA", "item_faltante": "Cabo 10mm", "quantidade": 3})
        d = Demanda.objects.get()
        self.assertRedirects(r, d.get_absolute_url())
        self.assertEqual(d.criado_por, self.trab)
        self.assertEqual(d.status, Status.PENDENTE)
        self.assertTrue(d.atualizacoes.exists())

    def test_assumir_muda_status(self):
        d = self.nova()
        self.client.post(reverse("demanda_assumir", args=[d.pk]))
        d.refresh_from_db()
        self.assertEqual(d.responsavel, self.trab)
        self.assertEqual(d.status, Status.ANDAMENTO)

    def test_concluir_registra_data_e_historico(self):
        d = self.nova()
        self.client.post(reverse("demanda_atualizar", args=[d.pk]), {"status": Status.CONCLUIDA, "texto": "Pronto"})
        d.refresh_from_db()
        self.assertEqual(d.status, Status.CONCLUIDA)
        self.assertIsNotNone(d.concluida_em)
        a = Atualizacao.objects.filter(demanda=d).latest("criado_em")
        self.assertEqual((a.status_anterior, a.status_novo), (Status.PENDENTE, Status.CONCLUIDA))

    def test_atualizacao_vazia_e_rejeitada(self):
        d = self.nova()
        self.client.post(reverse("demanda_atualizar", args=[d.pk]), {})
        self.assertEqual(d.atualizacoes.count(), 0)


class EstadoDoBarcoTest(BaseTest):
    def estado(self):
        self.client.force_login(self.dir)
        return self.client.get(reverse("dashboard")).context["estado"]

    def test_apto_sem_pendencias(self):
        self.assertEqual(self.estado(), "APTO")

    def test_atencao_com_demanda_grave(self):
        self.nova(prioridade="ALTA")
        self.assertEqual(self.estado(), "ATENCAO")

    def test_nao_apto_com_bloqueante_aberta(self):
        d = self.nova(bloqueia_operacao=True)
        self.assertEqual(self.estado(), "NAO_APTO")
        d.status = Status.CONCLUIDA
        d.save()
        self.assertEqual(self.estado(), "APTO")


class FiltrosTest(BaseTest):
    def test_lista_padrao_so_abertas_e_filtro_por_tipo(self):
        self.nova(titulo="Aberta")
        self.nova(titulo="Feita", status=Status.CONCLUIDA)
        self.nova(titulo="Falta", tipo=Tipo.FALTANTE, item_faltante="x")
        self.client.force_login(self.dir)
        r = self.client.get(reverse("demanda_lista"))
        self.assertEqual({d.titulo for d in r.context["demandas"]}, {"Aberta", "Falta"})
        r = self.client.get(reverse("demanda_lista"), {"tipo": "FALTANTE"})
        self.assertEqual([d.titulo for d in r.context["demandas"]], ["Falta"])
        r = self.client.get(reverse("demanda_lista"), {"status": ""})
        self.assertEqual(len(r.context["demandas"]), 3)
