from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.urls import reverse
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView
from .models import (
    STATUS_ABERTOS,
    Atualizacao,
    Demanda,
    Perfil,
    Prioridade,
    Sistema,
    Status,
    Tipo,
    Missao,
    StatusMissao,[
    
    ]
)
from .permissions import TrabalhadorRequiredMixin
from .forms import (
    AtualizacaoForm,
    DemandaForm,
    FiltroDemandaForm,
    PerfilForm,
    UsuarioForm,
    MissaoForm,
)
User = get_user_model()

GRAVES = (Prioridade.CRITICA, Prioridade.ALTA)

ESTADOS = {
    "NAO_APTO": ("Não apto para operar", "Há pendências que impedem o L42 de sair."),
    "ATENCAO": ("Apto com restrições", "Nada impede a saída, mas há pendências graves em aberto."),
    "APTO": ("Apto para operar", "Nenhuma pendência grave em aberto."),
}

# =========================================================
# MAPA: Sistema.nome (banco) -> local no barco (JS)
# Ajuste os nomes à esquerda conforme os Sistema.nome reais.
# Para conferir os nomes: Sistema.objects.values_list("nome", flat=True)
# =========================================================
MAPA_SISTEMA_LOCAL = {
    "Motor":       "motor",
    "Propulsão":   "helice",
    "Bateria":     "bateria",
    "Baterias":    "bateria",
    "Starlink":    "starlink",
    "Comunicação": "antena",
    "Casco":       "casco",
    "Estrutura":   "casco",
    "Mastro":      "mastro",
    "Leme":        "leme",
    "Cabine":      "cabine",
}

# Se o sistema não estiver mapeado, joga o alerta no centro do barco
LOCAL_FALLBACK = "cabine"


def _nivel(bloqueantes, graves):
    return "NAO_APTO" if bloqueantes else "ATENCAO" if graves else "APTO"


def _registrar(demanda, autor, texto="", anterior="", novo=""):
    return Atualizacao.objects.create(demanda=demanda, autor=autor, texto=texto,
                                      status_anterior=anterior, status_novo=novo)


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ativas = Demanda.objects.exclude(status=Status.CANCELADA)
        abertas = ativas.filter(status__in=STATUS_ABERTOS)

        total = ativas.count()
        concluidas = ativas.filter(status=Status.CONCLUIDA).count()
        bloqueantes = abertas.filter(bloqueia_operacao=True).count()
        graves = abertas.filter(prioridade__in=GRAVES).count()
        nivel = _nivel(bloqueantes, graves)

        sistemas = Sistema.objects.annotate(
            total=Count("demandas", filter=~Q(demandas__status=Status.CANCELADA)),
            feitas=Count("demandas", filter=Q(demandas__status=Status.CONCLUIDA)),
            abertas=Count("demandas", filter=Q(demandas__status__in=STATUS_ABERTOS)),
            bloqueantes=Count("demandas", filter=Q(demandas__status__in=STATUS_ABERTOS, demandas__bloqueia_operacao=True)),
            graves=Count("demandas", filter=Q(demandas__status__in=STATUS_ABERTOS, demandas__prioridade__in=GRAVES)),
        )
        for s in sistemas:
            s.pct = s.feitas * 100 // s.total if s.total else 100
            s.nivel = _nivel(s.bloqueantes, s.graves)
            s.nivel_label = ESTADOS[s.nivel][0]

        base = abertas.select_related("sistema", "responsavel")

        # =========================================================
        # 🔴 ALERTAS NO BARCO
        # Pega demandas abertas BLOQUEANTES ou GRAVES e traduz o
        # sistema de cada uma para um local físico do barco.
        # O resultado é consumido pelo JS no dashboard.html
        # =========================================================
        alertas_qs = (
            base
            .filter(Q(bloqueia_operacao=True) | Q(prioridade__in=GRAVES))
            .select_related("sistema")
            .order_by("-bloqueia_operacao", "prioridade", "prazo")
        )

        problemas_barco = []
        locais_usados = set()  # evita empilhar dois pontos no mesmo local

        for d in alertas_qs:
            nome_sistema = d.sistema.nome if d.sistema else ""
            local = MAPA_SISTEMA_LOCAL.get(nome_sistema, LOCAL_FALLBACK)

            if local in locais_usados:
                continue
            locais_usados.add(local)

            problemas_barco.append({
                "local": local,
                "titulo": d.titulo,
                "codigo": d.codigo,
                "prioridade": d.get_prioridade_display(),
                "bloqueante": bool(d.bloqueia_operacao),
            })

        ctx.update(
            estado=nivel,
            estado_titulo=ESTADOS[nivel][0],
            estado_texto=ESTADOS[nivel][1],
            prontidao=concluidas * 100 // total if total else 100,
            total=total,
            concluidas=concluidas,
            n_abertas=abertas.count(),
            n_andamento=abertas.filter(status=Status.ANDAMENTO).count(),
            n_pendentes=abertas.filter(status=Status.PENDENTE).count(),
            n_bloqueadas=abertas.filter(status=Status.BLOQUEADA).count(),
            n_faltantes=abertas.filter(tipo=Tipo.FALTANTE).count(),
            n_bloqueantes=bloqueantes,
            n_atrasadas=abertas.filter(prazo__lt=timezone.localdate()).count(),
            sistemas=sistemas,
            em_andamento=base.filter(status=Status.ANDAMENTO).ordenadas()[:10],
            criticas=base.filter(Q(bloqueia_operacao=True) | Q(prioridade=Prioridade.CRITICA)).ordenadas()[:10],
            faltantes=base.filter(tipo=Tipo.FALTANTE).ordenadas()[:10],
            recentes=Atualizacao.objects.select_related("demanda", "autor")[:8],
            minhas=base.filter(responsavel=self.request.user).ordenadas()[:8],

            # 🔴 nova chave consumida pelo dashboard.html
            problemas_barco=problemas_barco,
        )
        return ctx


class DemandaListView(LoginRequiredMixin, ListView):
    template_name = "demanda_list.html"
    context_object_name = "demandas"
    paginate_by = 20

    def get_filtro(self):
        dados = self.request.GET.copy()
        if "status" not in dados:
            dados["status"] = "ABERTAS"  # por padrão, só o que ainda precisa de ação
        return FiltroDemandaForm(dados)

    def get_queryset(self):
        qs = Demanda.objects.select_related("sistema", "responsavel")
        f = self.get_filtro()
        if f.is_valid():
            d = f.cleaned_data
            if d["q"]:
                termo = d["q"].strip()
                cond = Q(titulo__icontains=termo) | Q(item_faltante__icontains=termo) | Q(descricao__icontains=termo)
                if termo.upper().startswith("L42-") and termo[4:].isdigit():
                    cond |= Q(pk=int(termo[4:]))
                qs = qs.filter(cond)
            if d["status"] == "ABERTAS":
                qs = qs.filter(status__in=STATUS_ABERTOS)
            elif d["status"]:
                qs = qs.filter(status=d["status"])
            for campo in ("prioridade", "tipo", "sistema", "responsavel"):
                if d[campo]:
                    qs = qs.filter(**{campo: d[campo]})
            if d["atrasadas"]:
                qs = qs.filter(status__in=STATUS_ABERTOS, prazo__lt=timezone.localdate())
        return qs.ordenadas()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filtro"] = self.get_filtro()
        return ctx


class DemandaDetailView(LoginRequiredMixin, DetailView):
    model = Demanda
    template_name = "demanda_detail.html"
    context_object_name = "demanda"

    def get_queryset(self):
        return Demanda.objects.select_related("sistema", "responsavel", "criado_por")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form"] = AtualizacaoForm()
        ctx["atualizacoes"] = self.object.atualizacoes.select_related("autor")
        return ctx


class DemandaCreateView(TrabalhadorRequiredMixin, CreateView):
    model = Demanda
    form_class = DemandaForm
    template_name = "demanda_form.html"

    def get_initial(self):
        initial = super().get_initial()
        if self.request.GET.get("tipo") in Tipo.values:
            initial["tipo"] = self.request.GET["tipo"]
        return initial

    def form_valid(self, form):
        form.instance.criado_por = self.request.user
        resp = super().form_valid(form)
        _registrar(self.object, self.request.user, "Demanda criada.")
        messages.success(self.request, f"{self.object.codigo} registrada.")
        return resp


class DemandaUpdateView(TrabalhadorRequiredMixin, UpdateView):
    model = Demanda
    form_class = DemandaForm
    template_name = "demanda_form.html"

    def form_valid(self, form):
        anterior = form.initial.get("status", "")
        mudou_status = "status" in form.changed_data
        resp = super().form_valid(form)
        if mudou_status:
            _registrar(self.object, self.request.user, anterior=anterior, novo=self.object.status)
        elif form.changed_data:
            _registrar(self.object, self.request.user, "Demanda editada.")
        messages.success(self.request, f"{self.object.codigo} atualizada.")
        return resp


class AssumirDemandaView(TrabalhadorRequiredMixin, View):
    def post(self, request, pk):
        demanda = get_object_or_404(Demanda, pk=pk)
        anterior = demanda.status
        demanda.responsavel = request.user
        if demanda.status == Status.PENDENTE:
            demanda.status = Status.ANDAMENTO
        demanda.save()
        novo = demanda.status if demanda.status != anterior else ""
        _registrar(demanda, request.user, "Assumiu a demanda.", anterior if novo else "", novo)
        messages.success(request, f"Você assumiu {demanda.codigo}.")
        return redirect(demanda)


class AtualizarDemandaView(TrabalhadorRequiredMixin, View):
    def post(self, request, pk):
        demanda = get_object_or_404(Demanda, pk=pk)
        form = AtualizacaoForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Escreva um comentário ou escolha um novo status.")
            return redirect(demanda)
        novo = form.cleaned_data["status"]
        texto = form.cleaned_data["texto"].strip()
        anterior = demanda.status
        if novo and novo != anterior:
            demanda.status = novo
            if novo == Status.ANDAMENTO and not demanda.responsavel:
                demanda.responsavel = request.user
            demanda.save()
        else:
            novo = ""
        _registrar(demanda, request.user, texto, anterior if novo else "", novo)
        messages.success(request, "Atualização registrada.")
        return redirect(demanda)


class EquipeView(LoginRequiredMixin, TemplateView):
    template_name = "equipe.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        usuarios = (User.objects.filter(is_active=True).select_related("perfil")
                    .annotate(n_abertas=Count("demandas", filter=Q(demandas__status__in=STATUS_ABERTOS)),
                              n_feitas=Count("demandas", filter=Q(demandas__status=Status.CONCLUIDA)))
                    .order_by("first_name", "username"))
        ctx["diretores"] = [u for u in usuarios if u.perfil.papel == Perfil.Papel.DIRETOR]
        ctx["trabalhadores"] = [u for u in usuarios if u.perfil.papel != Perfil.Papel.DIRETOR]
        return ctx


class MeuPerfilView(LoginRequiredMixin, View):
    template_name = "perfil.html"

    def _render(self, request, uform, pform):
        minhas = (Demanda.objects.filter(responsavel=request.user, status__in=STATUS_ABERTOS)
                  .select_related("sistema").ordenadas())
        return render(request, self.template_name, {"uform": uform, "pform": pform, "minhas": minhas})

    def get(self, request):
        return self._render(request, UsuarioForm(instance=request.user), PerfilForm(instance=request.user.perfil))

    def post(self, request):
        uform = UsuarioForm(request.POST, instance=request.user)
        pform = PerfilForm(request.POST, instance=request.user.perfil)
        if uform.is_valid() and pform.is_valid():
            uform.save()
            pform.save()
            messages.success(request, "Perfil atualizado.")
            return redirect("meu_perfil")
        return self._render(request, uform, pform)


class ManutencaoView(LoginRequiredMixin, ListView):
    model = Demanda
    template_name = "manutencao.html"
    context_object_name = "manutencoes"

    def get_queryset(self):
        return (
            Demanda.objects
            .filter(tipo=Tipo.MANUTENCAO)
            .select_related("sistema", "responsavel")
            .ordenadas()
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = self.get_queryset()

        ctx["total"] = qs.count()
        ctx["abertas"] = qs.filter(status__in=STATUS_ABERTOS).count()
        ctx["bloqueantes"] = qs.filter(
            status__in=STATUS_ABERTOS,
            bloqueia_operacao=True
        ).count()
        ctx["concluidas"] = qs.filter(status=Status.CONCLUIDA).count()

        return ctx


class MissaoListView(LoginRequiredMixin, ListView):
    model = Missao
    template_name = "missao_list.html"
    context_object_name = "missoes"

    def get_queryset(self):
        return (
            Missao.objects
            .select_related("responsavel")
            .prefetch_related("checklist")
            .order_by("-criado_em")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["missao_atual"] = (
            Missao.objects
            .filter(
                status__in=[
                    StatusMissao.PREPARACAO,
                    StatusMissao.EM_OPERACAO,
                    StatusMissao.PAUSADA,
                ]
            )
            .select_related("responsavel")
            .prefetch_related("checklist")
            .order_by("-criado_em")
            .first()
        )

        context["status_missao"] = StatusMissao

        return context


class MissaoCreateView(LoginRequiredMixin, CreateView):
    model = Missao
    form_class = MissaoForm
    template_name = "missao_form.html"

    def form_valid(self, form):
        form.instance.criado_por = self.request.user
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("missoes")



class MissaoCreateView(LoginRequiredMixin, CreateView):
    model = Missao
    form_class = MissaoForm
    template_name = "missao_form.html"

    def form_valid(self, form):
        form.instance.criado_por = self.request.user
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("missoes")