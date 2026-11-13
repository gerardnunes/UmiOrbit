import io
import json
import time as _time

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import AccessMixin, LoginRequiredMixin
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import (
    CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView,
)

from .forms import (
    AtualizacaoForm, CadastroForm, ChecklistForm, ChecklistImportForm,
    DemandaForm, FiltroDemandaForm, IncidenteAnexoForm, IncidenteEventoForm,
    IncidenteForm, MissionPlanForm, MissaoForm, PerfilForm,
    SelecionarSistemasForm, UsuarioForm,
)
from .mixins import SistemaScopedMixin
from .models import (
    STATUS_ABERTOS, Atualizacao, Checklist, ChecklistImportacao,
    ChecklistItem, ChecklistItemEvento, ChecklistItemFoto, Demanda,
    Incidente, IncidenteAnexo, IncidenteEvento, IncidenteSeveridade,
    IncidenteStatus, IncidenteTipo, LeituraGuincho, LeituraPosicao,
    LeituraPropulsor, Missao, MissionPlan, OrigemGPS, Perfil, Prioridade,
    RadarDetectado, Route, Sistema, Status, StatusMissao, Tipo, Waypoint,
)
from .permissions import TrabalhadorRequiredMixin
from .services import ler_excel, aplicar_import
from .services.route_planner import (
    analisar_area,
    gerar_rota_lawn_mower,
    gerar_rota_waypoints,
    otimizar_waypoints_nearest_neighbor,
)
from .services.marine_weather import fetch_marine_conditions, conditions_to_dict

User = get_user_model()


# =========================================================
# CONSTANTES
# =========================================================
GRAVES = (Prioridade.CRITICA, Prioridade.ALTA)

INCIDENTE_ABERTOS = (
    IncidenteStatus.ABERTO,
    IncidenteStatus.EM_ANALISE,
    IncidenteStatus.EM_REPARO,
    IncidenteStatus.AGUARDANDO_PECA,
)
_Q_INCIDENTE_ABERTOS = Q(status__in=INCIDENTE_ABERTOS)

ESTADOS = {
    "NAO_APTO": ("Não apto para operar", "Há pendências que impedem a operação."),
    "ATENCAO": ("Apto com restrições", "Nada impede a saída, mas há pendências graves."),
    "APTO": ("Apto para operar", "Nenhuma pendência grave em aberto."),
}

MAPA_SISTEMA_LOCAL = {
    "Motor": "motor", "Propulsão": "helice", "Bateria": "bateria",
    "Baterias": "bateria", "Starlink": "starlink", "Comunicação": "antena",
    "Casco": "casco", "Estrutura": "casco", "Mastro": "mastro",
    "Leme": "leme", "Cabine": "cabine", "Inversor": "inversor",
}
LOCAIS_BARCO_FALLBACK = ("cabine", "casco", "proa", "mastro", "motor", "bateria")


# =========================================================
# ESCOPO POR SISTEMA
# =========================================================
def _sistemas_do_usuario(user):
    if not user.is_authenticated:
        return Sistema.objects.none()
    perfil = getattr(user, "perfil", None)
    if user.is_superuser or (perfil and perfil.is_diretor):
        return Sistema.objects.filter(ativo=True)
    if perfil:
        return perfil.sistemas.filter(ativo=True)
    return Sistema.objects.none()


def _get_no_escopo(model, user, **lookup):
    qs = model.objects.all()
    if hasattr(qs, "do_usuario"):
        qs = qs.do_usuario(user)
    elif hasattr(model, "sistema"):
        qs = qs.filter(sistema__in=_sistemas_do_usuario(user))
    return get_object_or_404(qs, **lookup)


def _sistema_do_usuario(user):
    perfil = getattr(user, "perfil", None)
    if perfil and not perfil.is_diretor and not user.is_superuser:
        sistemas = perfil.sistemas.filter(ativo=True)
        if sistemas.count() == 1:
            return sistemas.first()
    return None


def _injetar_sistema_no_data(data, user):
    if not data:
        return data
    if data.get("sistema"):
        return data
    sistema = _sistema_do_usuario(user)
    if sistema is None:
        return data
    try:
        data = data.copy()
        data["sistema"] = str(sistema.pk)
    except AttributeError:
        pass
    return data


def _forcar_sistema_unico(user, form):
    if "sistema" in form.fields:
        sistema = _sistema_do_usuario(user)
        if sistema is not None:
            form.instance.sistema = sistema


# =========================================================
# HELPERS DE APRESENTAÇÃO
# =========================================================
def _nivel(bloqueantes, graves):
    return "NAO_APTO" if bloqueantes else "ATENCAO" if graves else "APTO"


def _label_status(chave):
    if not chave:
        return "—"
    try:
        return IncidenteStatus(chave).label
    except ValueError:
        return chave


def _icone_evento(tipo):
    return {
        "criado": "🆕", "comentario": "💬", "status": "🔄",
        "severidade": "⚠", "responsavel": "👤", "anexo": "📎",
    }.get(tipo, "•")


def _cor_evento(tipo):
    return {
        "criado": "ok", "comentario": "info", "status": "info",
        "severidade": "alto", "responsavel": "ok", "anexo": "info",
    }.get(tipo, "info")


def _is_ajax(request):
    return (
        request.headers.get("x-requested-with") == "XMLHttpRequest"
        or "application/json" in request.headers.get("accept", "")
    )


def _nome_autor(request):
    if not request.user.is_authenticated:
        return "anônimo"
    return request.user.get_full_name() or request.user.username


def _registrar(demanda, autor, texto="", anterior="", novo=""):
    return Atualizacao.objects.create(
        demanda=demanda, autor=autor, texto=texto,
        status_anterior=anterior, status_novo=novo,
    )


def _evento(item, tipo, autor=None, texto=""):
    return ChecklistItemEvento.objects.create(
        item=item, tipo=tipo, autor=autor, texto=texto,
    )


def _evento_incidente(incidente, tipo, autor=None, texto=""):
    return IncidenteEvento.objects.create(
        incidente=incidente, tipo=tipo, autor=autor, texto=texto,
    )


def _escolher_local_livre(usados, preferido=None):
    if preferido and preferido not in usados:
        return preferido
    for local in LOCAIS_BARCO_FALLBACK:
        if local not in usados:
            return local
    return "cabine"


# =========================================================
# DASHBOARD
# =========================================================
class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        hoje = timezone.localdate()
        user = self.request.user
        sistemas = _sistemas_do_usuario(user)
        eh_admin = user.is_superuser or (
            getattr(user, "perfil", None) and user.perfil.is_diretor
        )

        demandas = Demanda.objects.filter(sistema__in=sistemas).select_related(
            "sistema", "responsavel", "missao"
        )
        abertas = demandas.filter(status__in=STATUS_ABERTOS)

        total_dem = demandas.count()
        concluidas = demandas.filter(status=Status.CONCLUIDA).count()

        ctx.update({
            "total": total_dem,
            "concluidas": concluidas,
            "prontidao": round(concluidas * 100 / total_dem) if total_dem else 0,
            "n_abertas": abertas.count(),
            "n_andamento": demandas.filter(status=Status.ANDAMENTO).count(),
            "n_pendentes": demandas.filter(status=Status.PENDENTE).count(),
            "n_bloqueadas": demandas.filter(status=Status.BLOQUEADA).count(),
            "n_criticas": abertas.filter(prioridade=Prioridade.CRITICA).count(),
            "n_atrasadas": abertas.filter(prazo__lt=hoje).count(),
            "n_bloqueantes_demanda": abertas.filter(bloqueia_operacao=True).count(),
            "demandas_recentes": list(abertas.order_by("-criado_em")[:8]),
            "problemas_barco": self._problemas_barco(abertas),
        })

        incidentes = Incidente.objects.filter(sistema__in=sistemas).select_related(
            "sistema", "responsavel"
        ).order_by("-ocorrido_em")
        abertos_inc = incidentes.filter(_Q_INCIDENTE_ABERTOS)

        resolvidos = incidentes.filter(status=IncidenteStatus.RESOLVIDO)
        mttr_vals = [r.mttr_horas for r in resolvidos if r.mttr_horas is not None]

        ctx.update({
            "incidentes_total": incidentes.count(),
            "incidentes_abertos": abertos_inc.count(),
            "n_incidentes_criticos": abertos_inc.filter(
                severidade=IncidenteSeveridade.CRITICO
            ).count(),
            "n_bloqueantes_incidente": abertos_inc.filter(
                bloqueia_operacao=True
            ).count(),
            "mttr_incidentes": (
                round(sum(mttr_vals) / len(mttr_vals), 1) if mttr_vals else None
            ),
            "incidentes_recentes": list(abertos_inc[:8]),
            "incidentes_mapa": self._incidentes_mapa(abertos_inc),
        })

        n_bloqueantes = ctx["n_bloqueantes_demanda"] + ctx["n_bloqueantes_incidente"]
        ctx["n_bloqueantes"] = n_bloqueantes

        if n_bloqueantes:
            estado, titulo = "inoperante", "Barco INOPERANTE"
            texto = (
                f"{n_bloqueantes} pendência"
                f"{'s' if n_bloqueantes != 1 else ''} bloqueante"
                f"{'s' if n_bloqueantes != 1 else ''} impedem a operação."
            )
        elif ctx["n_atrasadas"] or ctx["n_criticas"]:
            estado, titulo = "atencao", "Atenção"
            texto = "Há demandas atrasadas ou críticas, mas nenhuma bloqueante."
        elif ctx["n_abertas"] or ctx["incidentes_abertos"]:
            estado, titulo = "operacional", "Operacional"
            texto = "Há pendências em aberto, mas nada bloqueia a operação."
        else:
            estado, titulo = "pronto", "Pronto"
            texto = "Nenhuma pendência em aberto."

        ctx.update({"estado": estado, "estado_titulo": titulo, "estado_texto": texto})

        missoes = Missao.objects.filter(sistema__in=sistemas)
        ativas = (
            missoes.filter(status__in=[
                StatusMissao.PREPARACAO, StatusMissao.EM_OPERACAO, StatusMissao.PAUSADA,
            ]).select_related("responsavel", "sistema")
            .prefetch_related("checklists__itens")
        )
        missoes_ativas = []
        for m in ativas:
            cl = list(m.checklists.all())
            total_itens = sum(c.total for c in cl)
            feitos = sum(c.feitos for c in cl)
            pct = round(feitos * 100 / total_itens) if total_itens else 0
            missoes_ativas.append({
                "titulo": m.titulo, "status": m.status,
                "get_status_display": m.get_status_display(),
                "local": m.local, "responsavel": m.responsavel,
                "sistema": m.sistema, "progresso": pct,
                "n_checklists": len(cl),
                "n_checklists_concluidos": sum(
                    1 for c in cl if c.status == Checklist.Status.CONCLUIDO
                ),
            })

        ctx.update({
            "total_missoes": missoes.count(),
            "missoes_em_operacao": missoes.filter(
                status=StatusMissao.EM_OPERACAO
            ).count(),
            "missoes_ativas": missoes_ativas,
        })

        checklists = Checklist.objects.filter(sistema__in=sistemas)
        checklists_ativos = []
        for c in checklists.filter(status=Checklist.Status.ATIVO).select_related(
            "missao", "sistema"
        ).prefetch_related("itens"):
            checklists_ativos.append({
                "titulo": c.titulo, "get_absolute_url": c.get_absolute_url(),
                "missao": c.missao, "sistema": c.sistema,
                "pct_calc": c.pct, "itens_feitos": c.feitos, "total_itens": c.total,
            })

        ctx.update({
            "total_checklists": checklists.count(),
            "checklists_concluidos": checklists.filter(
                status=Checklist.Status.CONCLUIDO
            ).count(),
            "checklists_ativos": checklists_ativos,
        })

        fotos = ChecklistItemFoto.objects.filter(
            item__checklist__sistema__in=sistemas
        ).select_related("item", "item__checklist", "enviado_por")

        ctx.update({
            "total_fotos": fotos.count(),
            "fotos_recentes": list(fotos.order_by("-enviado_em")[:8]),
            "sistemas": [{"nome": s.nome, "pct": 100, "nivel": "ok"} for s in sistemas],
            "diario": self._diario(sistemas),
            "ambiente": {},
            "embarcacao": {"lat": "-22.9", "lon": "-43.2", "base": "BASE"},
            "bateria_pct": 78,
            "agora": timezone.now(),
            "sistema_atual": sistemas.first() if sistemas else None,
            "tem_sistemas": sistemas.exists(),
            "eh_admin": eh_admin,
        })
        return ctx

    def _problemas_barco(self, abertas):
        alertas = (
            abertas.filter(Q(bloqueia_operacao=True) | Q(prioridade__in=GRAVES))
            .select_related("sistema")
            .order_by("-bloqueia_operacao", "prioridade", "prazo")
        )
        problemas, usados = [], set()
        for d in alertas:
            preferido = MAPA_SISTEMA_LOCAL.get(d.sistema.nome) if d.sistema else None
            local = _escolher_local_livre(usados, preferido)
            usados.add(local)
            problemas.append({
                "local": local, "titulo": d.titulo, "codigo": d.codigo,
                "prioridade": d.get_prioridade_display(),
                "bloqueante": bool(d.bloqueia_operacao),
                "sistema": d.sistema.nome if d.sistema else "",
            })
        return problemas

    def _incidentes_mapa(self, qs):
        marcadores, usados = [], set()
        for i in qs:
            preferido = (i.local or "").strip().lower() or None
            if i.sistema:
                preferido = preferido or MAPA_SISTEMA_LOCAL.get(i.sistema.nome)
            local = _escolher_local_livre(usados, preferido)
            usados.add(local)
            marcadores.append({
                "codigo": i.codigo, "titulo": i.titulo,
                "severidade": i.severidade, "status": i.get_status_display(),
                "local": local, "bloqueante": i.bloqueia_operacao,
                "url": i.get_absolute_url(),
            })
        return marcadores

    def _diario(self, sistemas):
        diario = []
        for a in (
            Atualizacao.objects.filter(demanda__sistema__in=sistemas)
            .select_related("demanda", "autor").order_by("-criado_em")[:4]
        ):
            diario.append({
                "tipo": "demanda", "quando": a.criado_em,
                "titulo": a.demanda.titulo,
                "texto": a.get_status_novo_display() or (a.texto[:60] if a.texto else "—"),
                "autor": a.autor.get_full_name() if a.autor else "",
                "icone": "🔧", "cor": "demanda",
            })
        for ev in (
            ChecklistItemEvento.objects.filter(item__checklist__sistema__in=sistemas)
            .select_related("item", "item__checklist", "autor").order_by("-criado_em")[:4]
        ):
            diario.append({
                "tipo": "checklist", "quando": ev.criado_em,
                "titulo": f"{ev.item.checklist.titulo} → {ev.item.titulo}",
                "texto": ev.get_tipo_display(),
                "autor": ev.autor.get_full_name() if ev.autor else "",
                "icone": "☑", "cor": "checklist",
            })
        for ev in (
            IncidenteEvento.objects.filter(incidente__sistema__in=sistemas)
            .select_related("incidente", "autor").order_by("-criado_em")[:4]
        ):
            diario.append({
                "tipo": "incidente", "quando": ev.criado_em,
                "titulo": f"{ev.incidente.codigo} · {ev.incidente.titulo}",
                "texto": ev.texto or ev.get_tipo_display(),
                "autor": ev.autor.get_full_name() if ev.autor else "",
                "icone": "⚠", "cor": "incidente",
            })
        for m in (
            Missao.objects.filter(sistema__in=sistemas)
            .select_related("responsavel").order_by("-atualizado_em")[:3]
        ):
            diario.append({
                "tipo": "missao", "quando": m.atualizado_em,
                "titulo": m.titulo, "texto": m.get_status_display(),
                "autor": m.responsavel.get_full_name() if m.responsavel else "",
                "icone": "🎯", "cor": "missao",
            })
        diario.sort(key=lambda x: x["quando"], reverse=True)
        return diario[:12]


# =========================================================
# DEMANDAS
# =========================================================
class DemandaListView(SistemaScopedMixin, LoginRequiredMixin, ListView):
    model = Demanda
    template_name = "demanda_list.html"
    context_object_name = "demandas"
    paginate_by = 20

    def get_filtro(self):
        dados = self.request.GET.copy()
        if "status" not in dados:
            dados["status"] = "ABERTAS"
        return FiltroDemandaForm(dados, user=self.request.user)

    def get_queryset(self):
        qs = super().get_queryset().select_related("sistema", "responsavel")
        f = self.get_filtro()
        if f.is_valid():
            d = f.cleaned_data
            if d["q"]:
                termo = d["q"].strip()
                cond = (
                    Q(titulo__icontains=termo)
                    | Q(item_faltante__icontains=termo)
                    | Q(descricao__icontains=termo)
                )
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


class DemandaDetailView(SistemaScopedMixin, LoginRequiredMixin, DetailView):
    model = Demanda
    template_name = "demanda_detail.html"
    context_object_name = "demanda"

    def get_queryset(self):
        return super().get_queryset().select_related(
            "sistema", "responsavel", "criado_por"
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form"] = AtualizacaoForm()
        ctx["atualizacoes"] = self.object.atualizacoes.select_related("autor")
        return ctx


class DemandaCreateView(TrabalhadorRequiredMixin, CreateView):
    model = Demanda
    form_class = DemandaForm
    template_name = "demanda_form.html"

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw["user"] = self.request.user
        if kw.get("data"):
            kw["data"] = _injetar_sistema_no_data(kw["data"], self.request.user)
        return kw

    def get_initial(self):
        initial = super().get_initial()
        if self.request.GET.get("tipo") in Tipo.values:
            initial["tipo"] = self.request.GET["tipo"]
        sistema = _sistema_do_usuario(self.request.user)
        if sistema is not None:
            initial["sistema"] = sistema
        return initial

    def form_valid(self, form):
        _forcar_sistema_unico(self.request.user, form)
        form.instance.criado_por = self.request.user
        resp = super().form_valid(form)
        _registrar(self.object, self.request.user, "Demanda criada.")
        messages.success(self.request, f"{self.object.codigo} registrada.")
        return resp


class DemandaUpdateView(TrabalhadorRequiredMixin, UpdateView):
    model = Demanda
    form_class = DemandaForm
    template_name = "demanda_form.html"

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw["user"] = self.request.user
        if kw.get("data"):
            kw["data"] = _injetar_sistema_no_data(kw["data"], self.request.user)
        return kw

    def get_queryset(self):
        qs = Demanda.objects.all()
        if hasattr(qs, "do_usuario"):
            qs = qs.do_usuario(self.request.user)
        return qs

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
        demanda = _get_no_escopo(Demanda, request.user, pk=pk)
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
        demanda = _get_no_escopo(Demanda, request.user, pk=pk)
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


# =========================================================
# EQUIPE / PERFIL
# =========================================================
class EquipeView(LoginRequiredMixin, TemplateView):
    template_name = "equipe.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        sistemas = _sistemas_do_usuario(self.request.user)

        usuarios = (
            User.objects.filter(is_active=True)
            .select_related("perfil")
            .prefetch_related("perfil__sistemas")
            .annotate(
                n_abertas=Count(
                    "demandas",
                    filter=Q(demandas__status__in=STATUS_ABERTOS)
                    & Q(demandas__sistema__in=sistemas),
                ),
                n_feitas=Count(
                    "demandas",
                    filter=Q(demandas__status=Status.CONCLUIDA)
                    & Q(demandas__sistema__in=sistemas),
                ),
            )
            .order_by("first_name", "username")
        )
        ctx["diretores"] = [
            u for u in usuarios
            if getattr(u, "perfil", None) and u.perfil.papel == Perfil.Papel.DIRETOR
        ]
        ctx["trabalhadores"] = [
            u for u in usuarios
            if not getattr(u, "perfil", None)
            or u.perfil.papel != Perfil.Papel.DIRETOR
        ]
        return ctx


class MeuPerfilView(LoginRequiredMixin, View):
    template_name = "perfil.html"

    def _render(self, request, uform, pform):
        sistemas = _sistemas_do_usuario(request.user)
        minhas = (
            Demanda.objects
            .filter(responsavel=request.user, status__in=STATUS_ABERTOS,
                    sistema__in=sistemas)
            .select_related("sistema").ordenadas()
        )
        return render(request, self.template_name, {
            "uform": uform, "pform": pform, "minhas": minhas,
        })

    def get(self, request):
        return self._render(
            request,
            UsuarioForm(instance=request.user),
            PerfilForm(instance=request.user.perfil),
        )

    def post(self, request):
        uform = UsuarioForm(request.POST, instance=request.user)
        pform = PerfilForm(request.POST, instance=request.user.perfil)
        if uform.is_valid() and pform.is_valid():
            uform.save()
            pform.save()
            messages.success(request, "Perfil atualizado.")
            return redirect("meu_perfil")
        return self._render(request, uform, pform)


# =========================================================
# MANUTENÇÃO
# =========================================================
class ManutencaoView(SistemaScopedMixin, LoginRequiredMixin, ListView):
    model = Demanda
    template_name = "manutencao.html"
    context_object_name = "manutencoes"

    def get_queryset(self):
        return (
            super().get_queryset()
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
            status__in=STATUS_ABERTOS, bloqueia_operacao=True
        ).count()
        ctx["concluidas"] = qs.filter(status=Status.CONCLUIDA).count()
        return ctx


# =========================================================
# MISSÕES
# =========================================================
class MissaoListView(SistemaScopedMixin, LoginRequiredMixin, ListView):
    model = Missao
    template_name = "missao_list.html"
    context_object_name = "missoes"

    def get_queryset(self):
        return (
            super().get_queryset()
            .select_related("responsavel", "sistema")
            .prefetch_related("checklists")
            .order_by("-criado_em")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        sistemas = _sistemas_do_usuario(self.request.user)
        ctx["missao_atual"] = (
            Missao.objects
            .filter(
                status__in=[StatusMissao.PREPARACAO, StatusMissao.EM_OPERACAO,
                            StatusMissao.PAUSADA],
                sistema__in=sistemas,
            )
            .select_related("responsavel", "sistema")
            .prefetch_related("checklists")
            .order_by("-criado_em").first()
        )
        ctx["status_missao"] = StatusMissao
        return ctx


class MissaoCreateView(LoginRequiredMixin, CreateView):
    model = Missao
    form_class = MissaoForm
    template_name = "missao_form.html"

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw["user"] = self.request.user
        if kw.get("data"):
            kw["data"] = _injetar_sistema_no_data(kw["data"], self.request.user)
        return kw

    def get_initial(self):
        initial = super().get_initial()
        sistema = _sistema_do_usuario(self.request.user)
        if sistema is not None:
            initial["sistema"] = sistema
        return initial

    def form_valid(self, form):
        _forcar_sistema_unico(self.request.user, form)
        form.instance.criado_por = self.request.user
        messages.success(self.request, "Missão criada.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("missoes")


class MissaoDetailView(SistemaScopedMixin, LoginRequiredMixin, DetailView):
    model = Missao
    template_name = "missao_detail.html"
    context_object_name = "missao"

    def get_queryset(self):
        return (
            super().get_queryset()
            .select_related("responsavel", "criado_por", "sistema")
            .prefetch_related(
                "checklists__itens__responsavel",
                "checklists__itens__fotos",
                "checklists__itens__eventos",
            )
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        m = self.object
        cl = list(m.checklists.all())
        total_itens = sum(c.itens.count() for c in cl)
        itens_feitos = sum(c.itens.filter(concluido=True).count() for c in cl)
        m.total_itens = total_itens
        m.itens_feitos = itens_feitos
        m.progresso_geral = (itens_feitos * 100 // total_itens) if total_itens else 0

        ctx["demandas_recentes"] = (
            Demanda.objects.filter(status__in=STATUS_ABERTOS, sistema=m.sistema)
            .select_related("sistema", "responsavel")
            .ordenadas()[:6]
        )
        ctx["checklists"] = cl
        return ctx


# =========================================================
# CHECKLISTS
# =========================================================
class ChecklistListView(SistemaScopedMixin, LoginRequiredMixin, ListView):
    model = Checklist
    template_name = "checklist_list.html"
    context_object_name = "checklists"

    def get_queryset(self):
        qs = (
            super().get_queryset()
            .select_related("missao", "criado_por", "sistema")
            .prefetch_related("itens")
            .order_by("-criado_em")
        )
        status = self.request.GET.get("status")
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        checklists = list(ctx["checklists"])

        grupos = {}
        for c in checklists:
            key = c.missao_id
            if key not in grupos:
                grupos[key] = {"missao": c.missao, "checklists": []}
            grupos[key]["checklists"].append(c)

        com_missao = [g for g in grupos.values() if g["missao"] is not None]
        sem_missao = [g for g in grupos.values() if g["missao"] is None]
        com_missao.sort(
            key=lambda g: max(c.criado_em for c in g["checklists"]),
            reverse=True,
        )

        ctx["grupos"] = com_missao + sem_missao
        ctx["total_geral"] = len(checklists)
        return ctx


class ChecklistDetailView(SistemaScopedMixin, LoginRequiredMixin, DetailView):
    model = Checklist
    template_name = "checklist_detail.html"
    context_object_name = "checklist"

    def get_queryset(self):
        return (
            super().get_queryset()
            .select_related("missao", "sistema")
            .prefetch_related(
                Prefetch(
                    "itens",
                    queryset=ChecklistItem.objects
                    .select_related("responsavel", "concluido_por")
                    .prefetch_related("fotos__enviado_por", "eventos__autor"),
                ),
            )
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["itens"] = self.object.itens.select_related(
            "responsavel", "concluido_por"
        ).prefetch_related("fotos__enviado_por", "eventos__autor")
        ctx["import_form"] = ChecklistImportForm()
        ctx["importacoes"] = self.object.importacoes.all()[:5]

        url_auditoria = self.request.build_absolute_uri(
            reverse("auditoria_checklist", args=[self.object.token_auditoria])
        )
        ctx["mensagem_whatsapp"] = (
            f"*Auditoria do checklist:* {self.object.titulo}\n"
            f"{self.object.feitos}/{self.object.total} itens concluídos\n\n"
            f"Abra o link abaixo e audite:\n{url_auditoria}"
        )
        return ctx


class ChecklistCreateView(TrabalhadorRequiredMixin, CreateView):
    model = Checklist
    form_class = ChecklistForm
    template_name = "checklist_form.html"

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw["user"] = self.request.user
        if kw.get("data"):
            kw["data"] = _injetar_sistema_no_data(kw["data"], self.request.user)
        return kw

    def get_initial(self):
        initial = super().get_initial()
        sistema = _sistema_do_usuario(self.request.user)
        if sistema is not None:
            initial["sistema"] = sistema
        return initial

    def form_valid(self, form):
        _forcar_sistema_unico(self.request.user, form)
        form.instance.criado_por = self.request.user
        messages.success(self.request, "Checklist criado. Agora importe a planilha.")
        return super().form_valid(form)


class ChecklistUpdateView(TrabalhadorRequiredMixin, UpdateView):
    model = Checklist
    form_class = ChecklistForm
    template_name = "checklist_form.html"

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw["user"] = self.request.user
        if kw.get("data"):
            kw["data"] = _injetar_sistema_no_data(kw["data"], self.request.user)
        return kw

    def get_queryset(self):
        qs = Checklist.objects.all()
        if hasattr(qs, "do_usuario"):
            qs = qs.do_usuario(self.request.user)
        return qs

    def form_valid(self, form):
        messages.success(self.request, "Checklist atualizado.")
        return super().form_valid(form)


class ChecklistImportView(TrabalhadorRequiredMixin, View):
    def post(self, request, pk):
        checklist = _get_no_escopo(Checklist, request.user, pk=pk)
        form = ChecklistImportForm(request.POST, request.FILES)
        if not form.is_valid():
            for erro in form.errors.values():
                messages.error(request, erro.as_text())
            return redirect(checklist)

        importacao = ChecklistImportacao.objects.create(
            checklist=checklist,
            arquivo=form.cleaned_data["arquivo"],
            enviado_por=request.user,
        )

        try:
            with importacao.arquivo.open("rb") as f:
                resultado = ler_excel(io.BytesIO(f.read()))
        except Exception as exc:
            importacao.erros = f"Falha ao ler a planilha: {exc}"
            importacao.save(update_fields=["erros"])
            messages.error(request, f"Falha ao ler a planilha: {exc}")
            return redirect(checklist)

        if form.cleaned_data.get("substituir"):
            checklist.itens.all().delete()

        criados = aplicar_import(
            checklist, resultado,
            criar_faltantes=form.cleaned_data.get("criar_sistemas", False),
            autor=request.user,
        )

        importacao.linhas_lidas = len(resultado.linhas)
        importacao.linhas_criadas = criados
        importacao.erros = "\n".join(resultado.erros)
        importacao.save()

        messages.success(
            request,
            f"{criados} ite{'ns' if criados != 1 else 'm'} importado"
            f"{'s' if criados != 1 else ''} de {len(resultado.linhas)} linha(s).",
        )
        if resultado.erros:
            messages.warning(
                request,
                f"{len(resultado.erros)} linha(s) com aviso — veja o histórico.",
            )
        return redirect(checklist)


class ChecklistItemToggleView(TrabalhadorRequiredMixin, View):
    def post(self, request, pk):
        item = get_object_or_404(
            ChecklistItem.objects.filter(
                checklist__sistema__in=_sistemas_do_usuario(request.user)
            ),
            pk=pk,
        )
        anterior = item.concluido
        item.concluido = not item.concluido
        if item.concluido:
            item.concluido_em = timezone.now()
            item.concluido_por = request.user
        else:
            item.concluido_em = None
            item.concluido_por = None
        item.save(update_fields=["concluido", "concluido_em", "concluido_por"])

        if item.concluido and not anterior:
            _evento(item, ChecklistItemEvento.Tipo.CONCLUIDO, autor=request.user)
        elif not item.concluido and anterior:
            _evento(item, ChecklistItemEvento.Tipo.REABERTO, autor=request.user)

        messages.success(
            request,
            f"{'Concluído' if item.concluido else 'Reaberto'}: {item.titulo}",
        )
        return redirect(item.checklist)


# =========================================================
# MODELO DE EXCEL
# =========================================================
try:
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    OPENPYXL_OK = True
except ImportError:
    OPENPYXL_OK = False


class ChecklistModeloView(LoginRequiredMixin, View):
    def get(self, request):
        if not OPENPYXL_OK:
            messages.error(request, "Instale o pacote 'openpyxl'.")
            return redirect("checklist_lista")

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Checklist"

        cabecalhos = ["Ordem", "Título", "Descrição", "Sistema", "Prioridade", "Responsável"]
        ws.append(cabecalhos)
        for linha in [
            [1, "Checar casco", "Inspeção visual externa", "Casco", "Alta", "joao"],
            [2, "Testar motor", "Partida a frio + rpm", "Motor", "Crítica", "maria"],
            [3, "Conferir bateria", "Nível mínimo de 80%", "Bateria", "Média", ""],
        ]:
            ws.append(linha)

        header_fill = PatternFill("solid", fgColor="1F3A5F")
        header_font = Font(bold=True, color="FFFFFF")
        for i, _ in enumerate(cabecalhos, start=1):
            c = ws.cell(row=1, column=i)
            c.fill = header_fill
            c.font = header_font
            c.alignment = Alignment(horizontal="center", vertical="center")

        for i, w in enumerate([8, 28, 36, 14, 12, 16], start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = "A2"

        guia = wb.create_sheet("Instruções")
        for linha in [
            ["COMO PREENCHER ESTA PLANILHA"], [""],
            ["1. Não mude os nomes das colunas."],
            ["2. Só 'Título' é obrigatório."],
            ["3. 'Prioridade': Baixa, Média, Alta, Crítica."],
            ["4. 'Responsável' = username."],
            ["5. Salve como .xlsx."],
        ]:
            guia.append(linha)
        guia.column_dimensions["A"].width = 80
        guia["A1"].font = Font(bold=True, size=13)

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        resp = HttpResponse(
            buf.read(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        resp["Content-Disposition"] = 'attachment; filename="modelo_checklist_l42.xlsx"'
        return resp


# =========================================================
# AUDITORIA
# =========================================================
class AuditoriaAccessMixin(AccessMixin):
    def dispatch(self, request, *args, **kwargs):
        token = kwargs.get("token")
        checklist = get_object_or_404(Checklist, token_auditoria=token)
        if checklist.exige_login_auditoria and not request.user.is_authenticated:
            return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)


class AuditoriaChecklistView(AuditoriaAccessMixin, DetailView):
    model = Checklist
    template_name = "auditoria/checklist.html"
    context_object_name = "checklist"
    slug_field = "token_auditoria"
    slug_url_kwarg = "token"

    def get_object(self, queryset=None):
        return get_object_or_404(
            Checklist.objects.prefetch_related(
                "itens__fotos__enviado_por",
                "itens__concluido_por",
                "itens__eventos__autor",
            ),
            token_auditoria=self.kwargs["token"],
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["itens"] = (
            self.object.itens.select_related("responsavel", "concluido_por")
            .prefetch_related("fotos__enviado_por", "eventos__autor")
        )
        return ctx


class AuditoriaToggleItemView(AuditoriaAccessMixin, View):
    def post(self, request, token, item_id):
        checklist = get_object_or_404(Checklist, token_auditoria=token)
        item = get_object_or_404(ChecklistItem, pk=item_id, checklist=checklist)

        anterior = item.concluido
        item.concluido = not item.concluido

        if item.concluido:
            item.concluido_em = timezone.now()
            item.concluido_por = request.user if request.user.is_authenticated else None
        else:
            item.concluido_em = None
            item.concluido_por = None

        obs = request.POST.get("observacao", "").strip()
        if obs and obs != item.observacao:
            item.observacao = obs
            _evento(
                item, ChecklistItemEvento.Tipo.OBSERVACAO,
                autor=request.user if request.user.is_authenticated else None,
                texto=obs,
            )

        item.save(update_fields=["concluido", "concluido_em", "concluido_por", "observacao"])

        autor = request.user if request.user.is_authenticated else None
        if item.concluido and not anterior:
            _evento(item, ChecklistItemEvento.Tipo.CONCLUIDO, autor=autor)
        elif not item.concluido and anterior:
            _evento(item, ChecklistItemEvento.Tipo.REABERTO, autor=autor)

        mensagem = f"{'Concluído' if item.concluido else 'Reaberto'} por {_nome_autor(request)}."

        if _is_ajax(request):
            return JsonResponse({
                "ok": True,
                "concluido": item.concluido,
                "checklist_pct": checklist.pct,
                "checklist_feitos": checklist.feitos,
                "checklist_total": checklist.total,
                "mensagem": mensagem,
                "item_html": render_to_string(
                    "auditoria/_item.html",
                    {"item": item, "checklist": checklist},
                    request=request,
                ),
            })

        messages.success(request, mensagem)
        return redirect("auditoria_checklist", token=token)


class AuditoriaUploadFotoView(AuditoriaAccessMixin, View):
    def post(self, request, token, item_id):
        checklist = get_object_or_404(Checklist, token_auditoria=token)
        item = get_object_or_404(ChecklistItem, pk=item_id, checklist=checklist)

        imagem = request.FILES.get("imagem")
        if not imagem or not imagem.content_type.startswith("image/"):
            msg = "Selecione uma imagem válida."
            if _is_ajax(request):
                return JsonResponse({"ok": False, "erro": msg}, status=400)
            messages.error(request, msg)
            return redirect("auditoria_checklist", token=token)

        legenda = request.POST.get("legenda", "").strip()
        autor = request.user if request.user.is_authenticated else None

        foto = ChecklistItemFoto.objects.create(
            item=item, imagem=imagem, legenda=legenda, enviado_por=autor,
        )
        _evento(
            item, ChecklistItemEvento.Tipo.FOTO, autor=autor,
            texto=legenda or f"Foto enviada ({foto.imagem.name.split('/')[-1]})",
        )

        if request.POST.get("concluir") == "on" and not item.concluido:
            item.concluido = True
            item.concluido_em = timezone.now()
            item.concluido_por = autor
            item.save(update_fields=["concluido", "concluido_em", "concluido_por"])
            _evento(item, ChecklistItemEvento.Tipo.CONCLUIDO, autor=autor)

        mensagem = f"Foto anexada por {_nome_autor(request)}."
        if _is_ajax(request):
            return JsonResponse({
                "ok": True,
                "concluido": item.concluido,
                "checklist_pct": checklist.pct,
                "checklist_feitos": checklist.feitos,
                "checklist_total": checklist.total,
                "mensagem": mensagem,
                "foto_url": foto.imagem.url,
                "foto_pk": foto.pk,
                "foto_legenda": foto.legenda,
                "item_html": render_to_string(
                    "auditoria/_item.html",
                    {"item": item, "checklist": checklist},
                    request=request,
                ),
            })

        messages.success(request, mensagem)
        return redirect("auditoria_checklist", token=token)


class AuditoriaRemoverFotoView(AuditoriaAccessMixin, View):
    def post(self, request, token, foto_id):
        checklist = get_object_or_404(Checklist, token_auditoria=token)
        foto = get_object_or_404(ChecklistItemFoto, pk=foto_id, item__checklist=checklist)

        if (
            foto.enviado_por
            and foto.enviado_por != request.user
            and not request.user.is_superuser
        ):
            msg = "Você só pode remover fotos que você enviou."
            if _is_ajax(request):
                return JsonResponse({"ok": False, "erro": msg}, status=403)
            messages.error(request, msg)
            return redirect("auditoria_checklist", token=token)

        item = foto.item
        _evento(
            item, ChecklistItemEvento.Tipo.FOTO_REMOVIDA,
            autor=request.user if request.user.is_authenticated else None,
            texto=foto.legenda or "",
        )
        foto.imagem.delete(save=False)
        foto.delete()

        if _is_ajax(request):
            return JsonResponse({"ok": True, "mensagem": "Foto removida."})

        messages.success(request, "Foto removida.")
        return redirect("auditoria_checklist", token=token)


# =========================================================
# INCIDENTES
# =========================================================
class IncidenteListView(SistemaScopedMixin, LoginRequiredMixin, ListView):
    model = Incidente
    template_name = "incidente_list.html"
    context_object_name = "incidentes"
    paginate_by = 25

    def get_queryset(self):
        qs = super().get_queryset().select_related("responsavel", "sistema")

        status = self.request.GET.get("status")
        if status == "abertos":
            qs = qs.filter(_Q_INCIDENTE_ABERTOS)
        elif status and status in IncidenteStatus.values:
            qs = qs.filter(status=status)

        sev = self.request.GET.get("severidade")
        if sev and sev in IncidenteSeveridade.values:
            qs = qs.filter(severidade=sev)

        tipo = self.request.GET.get("tipo")
        if tipo and tipo in IncidenteTipo.values:
            qs = qs.filter(tipo=tipo)

        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(titulo__icontains=q) | Q(codigo__icontains=q)
                | Q(descricao__icontains=q) | Q(local__icontains=q)
                | Q(sistema__nome__icontains=q)
            )

        return qs.order_by("-ocorrido_em", "-id")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        sistemas = _sistemas_do_usuario(self.request.user)
        base = Incidente.objects.filter(sistema__in=sistemas)

        agg = base.aggregate(
            total=Count("id"),
            abertos=Count("id", filter=_Q_INCIDENTE_ABERTOS),
            criticos=Count(
                "id", filter=_Q_INCIDENTE_ABERTOS & Q(severidade=IncidenteSeveridade.CRITICO)
            ),
            em_analise=Count("id", filter=Q(status=IncidenteStatus.EM_ANALISE)),
            em_reparo=Count("id", filter=Q(status=IncidenteStatus.EM_REPARO)),
            aguardando=Count("id", filter=Q(status=IncidenteStatus.AGUARDANDO_PECA)),
        )
        ctx.update({
            "total_incidentes": agg["total"] or 0,
            "incidentes_abertos": agg["abertos"] or 0,
            "n_criticos": agg["criticos"] or 0,
            "n_em_analise": agg["em_analise"] or 0,
            "n_em_reparo": agg["em_reparo"] or 0,
            "n_aguardando_peca": agg["aguardando"] or 0,
        })

        trinta_dias = timezone.now() - timezone.timedelta(days=30)
        resolvidos = base.filter(resolvido_em__gte=trinta_dias, resolvido_em__isnull=False)
        mttr_vals = [r.mttr_horas for r in resolvidos if r.mttr_horas]
        ctx["mttr_horas"] = round(sum(mttr_vals) / len(mttr_vals), 1) if mttr_vals else None
        ctx["tmr_dias"] = round(sum(mttr_vals) / len(mttr_vals) / 24, 1) if mttr_vals else None
        ctx["n_resolvidos_hoje"] = base.filter(
            resolvido_em__date=timezone.localdate()
        ).count()

        total = agg["total"] or 1
        ctx["severidades"] = [
            {"chave": chave, "label": label,
             "qtd": base.filter(severidade=chave).count(),
             "pct": base.filter(severidade=chave).count() * 100 // total}
            for chave, label in IncidenteSeveridade.choices
        ]

        if ctx["n_criticos"]:
            ctx["estado_geral"] = "NAO_APTO"
        elif ctx["incidentes_abertos"]:
            ctx["estado_geral"] = "ATENCAO"
        else:
            ctx["estado_geral"] = "APTO"
        ctx["estado_geral_titulo"] = ESTADOS[ctx["estado_geral"]][0]

        ctx["sistemas_opcoes"] = [
            {"chave": s.nome.lower().replace(" ", "_"), "label": s.nome}
            for s in sistemas[:30]
        ]

        ctx["incidentes_mapa"] = self._marcadores(base)
        ctx["timeline"] = [
            {
                "icone": _icone_evento(ev.tipo), "cor": _cor_evento(ev.tipo),
                "titulo": f"{ev.incidente.codigo} · {ev.incidente.titulo}",
                "texto": ev.texto or ev.get_tipo_display(),
                "autor": ev.autor.get_full_name() if ev.autor else "",
                "quando": ev.criado_em,
            }
            for ev in IncidenteEvento.objects
                .filter(incidente__sistema__in=sistemas)
                .select_related("incidente", "autor")
                .order_by("-criado_em")[:12]
        ]
        ctx["filtro_status"] = self.request.GET.get("status", "todos")
        ctx["agora"] = timezone.now()
        return ctx

    def _marcadores(self, base):
        marcadores, usados = [], set()
        para_mapa = base.filter(_Q_INCIDENTE_ABERTOS).filter(
            Q(bloqueia_operacao=True)
            | Q(severidade__in=[IncidenteSeveridade.CRITICO, IncidenteSeveridade.ALTO])
        )
        for i in para_mapa:
            preferido = MAPA_SISTEMA_LOCAL.get(i.sistema.nome) if i.sistema else None
            local = _escolher_local_livre(usados, preferido)
            usados.add(local)
            marcadores.append({
                "local": local, "titulo": i.titulo, "codigo": i.codigo,
                "severidade": i.severidade, "status": i.get_status_display(),
                "bloqueante": bool(i.bloqueia_operacao),
            })
        return marcadores


class IncidenteDetailView(SistemaScopedMixin, LoginRequiredMixin, DetailView):
    model = Incidente
    template_name = "incidente_detail.html"
    context_object_name = "incidente"

    def get_queryset(self):
        return super().get_queryset().select_related(
            "responsavel", "criado_por", "sistema",
        ).prefetch_related("eventos__autor", "anexos__enviado_por")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["evento_form"] = IncidenteEventoForm()
        ctx["anexo_form"] = IncidenteAnexoForm()
        ctx["severidades"] = IncidenteSeveridade.choices
        ctx["status_opcoes"] = IncidenteStatus.choices
        return ctx


class IncidenteCreateView(TrabalhadorRequiredMixin, CreateView):
    model = Incidente
    form_class = IncidenteForm
    template_name = "incidente_form.html"

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw["user"] = self.request.user
        if kw.get("data"):
            kw["data"] = _injetar_sistema_no_data(kw["data"], self.request.user)
        return kw

    def get_initial(self):
        initial = super().get_initial()
        tipo = self.request.GET.get("tipo")
        if tipo and tipo in IncidenteTipo.values:
            initial["tipo"] = tipo
        sistema = _sistema_do_usuario(self.request.user)
        if sistema is not None:
            initial["sistema"] = sistema
        return initial

    def form_valid(self, form):
        _forcar_sistema_unico(self.request.user, form)
        form.instance.criado_por = self.request.user
        resp = super().form_valid(form)
        _evento_incidente(
            self.object, IncidenteEvento.Tipo.CRIADO,
            autor=self.request.user,
            texto=f"Incidente registrado: {self.object.titulo}",
        )
        messages.success(self.request, f"{self.object.codigo} registrado.")
        return resp


class IncidenteUpdateView(TrabalhadorRequiredMixin, UpdateView):
    model = Incidente
    form_class = IncidenteForm
    template_name = "incidente_form.html"

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw["user"] = self.request.user
        if kw.get("data"):
            kw["data"] = _injetar_sistema_no_data(kw["data"], self.request.user)
        return kw

    def get_queryset(self):
        qs = Incidente.objects.all()
        if hasattr(qs, "do_usuario"):
            qs = qs.do_usuario(self.request.user)
        return qs

    def form_valid(self, form):
        anterior = {
            "status": self.object.status,
            "severidade": self.object.severidade,
            "responsavel": self.object.responsavel,
        }
        resp = super().form_valid(form)

        if "status" in form.changed_data:
            _evento_incidente(
                self.object, IncidenteEvento.Tipo.STATUS,
                autor=self.request.user,
                texto=f"{_label_status(anterior['status'])} → {self.object.get_status_display()}",
            )
        if "severidade" in form.changed_data:
            _evento_incidente(
                self.object, IncidenteEvento.Tipo.SEVERIDADE,
                autor=self.request.user,
                texto=(
                    f"{IncidenteSeveridade(anterior['severidade']).label} → "
                    f"{self.object.get_severidade_display()}"
                ),
            )
        if "responsavel" in form.changed_data:
            resp = self.object.responsavel
            nome = resp.get_full_name() or resp.username if resp else "—"
            _evento_incidente(
                self.object, IncidenteEvento.Tipo.RESPONSAVEL,
                autor=self.request.user, texto=f"Responsável: {nome}",
            )

        messages.success(self.request, f"{self.object.codigo} atualizado.")
        return resp


class IncidenteDeleteView(TrabalhadorRequiredMixin, DeleteView):
    model = Incidente
    template_name = "incidente_confirm_delete.html"
    success_url = reverse_lazy("incidente_lista")

    def get_queryset(self):
        qs = Incidente.objects.all()
        if hasattr(qs, "do_usuario"):
            qs = qs.do_usuario(self.request.user)
        return qs

    def form_valid(self, form):
        codigo = self.object.codigo
        resp = super().form_valid(form)
        messages.success(self.request, f"{codigo} removido.")
        return resp


class IncidenteMudarStatusView(TrabalhadorRequiredMixin, View):
    def post(self, request, pk):
        incidente = _get_no_escopo(Incidente, request.user, pk=pk)
        novo = request.POST.get("status")

        if novo not in IncidenteStatus.values:
            messages.error(request, "Status inválido.")
            return redirect(incidente)

        anterior = incidente.status
        if anterior == novo:
            messages.info(request, "Status já estava definido.")
            return redirect(incidente)

        incidente.status = novo
        incidente.save(update_fields=["status", "resolvido_em", "atualizado_em"])
        _evento_incidente(
            incidente, IncidenteEvento.Tipo.STATUS,
            autor=request.user,
            texto=f"{_label_status(anterior)} → {_label_status(novo)}",
        )
        messages.success(request, f"{incidente.codigo} → {incidente.get_status_display()}.")
        return redirect(incidente)


class IncidenteComentarView(TrabalhadorRequiredMixin, View):
    def post(self, request, pk):
        incidente = _get_no_escopo(Incidente, request.user, pk=pk)
        form = IncidenteEventoForm(request.POST)

        if not form.is_valid():
            messages.error(request, "Comentário inválido.")
            return redirect(incidente)

        texto = (form.cleaned_data.get("texto") or "").strip()
        if not texto:
            messages.error(request, "Escreva um comentário.")
            return redirect(incidente)

        _evento_incidente(
            incidente, IncidenteEvento.Tipo.COMENTARIO,
            autor=request.user, texto=texto,
        )
        messages.success(request, "Comentário adicionado.")
        return redirect(incidente)


class IncidenteAnexoView(TrabalhadorRequiredMixin, View):
    def post(self, request, pk):
        incidente = _get_no_escopo(Incidente, request.user, pk=pk)
        form = IncidenteAnexoForm(request.POST, request.FILES)

        if not form.is_valid():
            messages.error(request, "Selecione uma imagem válida.")
            return redirect(incidente)

        anexo = form.save(commit=False)
        anexo.incidente = incidente
        anexo.enviado_por = request.user
        anexo.save()
        _evento_incidente(
            incidente, IncidenteEvento.Tipo.ANEXO,
            autor=request.user,
            texto=anexo.legenda or "Anexo adicionado",
        )
        messages.success(request, "Anexo adicionado.")
        return redirect(incidente)


class IncidenteRemoverAnexoView(TrabalhadorRequiredMixin, View):
    def post(self, request, pk, anexo_id):
        incidente = _get_no_escopo(Incidente, request.user, pk=pk)
        anexo = get_object_or_404(IncidenteAnexo, pk=anexo_id, incidente=incidente)

        if (
            anexo.enviado_por
            and anexo.enviado_por != request.user
            and not request.user.is_superuser
        ):
            messages.error(request, "Você só pode remover anexos que enviou.")
            return redirect(incidente)

        anexo.imagem.delete(save=False)
        anexo.delete()
        messages.success(request, "Anexo removido.")
        return redirect(incidente)


# =========================================================
# CADASTRO / APROVAÇÃO / SELEÇÃO DE SISTEMAS
# =========================================================
class CadastroView(View):
    template_name = "cadastro.html"

    def get(self, request):
        if request.user.is_authenticated:
            return redirect("dashboard")
        return render(request, self.template_name, {"form": CadastroForm()})

    def post(self, request):
        form = CadastroForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})
        user = form.save()
        auth_login(request, user)
        messages.success(
            request,
            "Conta criada. Aguarde a aprovação de um diretor para começar.",
        )
        return redirect("aguardando_aprovacao")


@method_decorator([login_required, never_cache], name="dispatch")
class AguardandoAprovacaoView(TemplateView):
    template_name = "aguardando_aprovacao.html"

    def dispatch(self, request, *args, **kwargs):
        perfil = getattr(request.user, "perfil", None)
        if perfil and perfil.aprovado:
            if not perfil.escolheu_sistemas:
                return redirect("selecionar_sistemas")
            return redirect("dashboard")
        return super().dispatch(request, *args, **kwargs)


@method_decorator([login_required, never_cache], name="dispatch")
class SelecionarSistemasView(View):
    template_name = "selecionar_sistemas.html"

    def _perfil(self, request):
        perfil, _ = Perfil.objects.get_or_create(user=request.user)
        return perfil

    def dispatch(self, request, *args, **kwargs):
        perfil = getattr(request.user, "perfil", None)
        if perfil and not perfil.aprovado:
            return redirect("aguardando_aprovacao")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        perfil = self._perfil(request)
        form = SelecionarSistemasForm(
            initial={"sistemas": perfil.sistemas.values_list("pk", flat=True)}
        )
        return render(request, self.template_name, {"form": form, "perfil": perfil})

    def post(self, request):
        perfil = self._perfil(request)
        form = SelecionarSistemasForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form, "perfil": perfil})

        perfil.sistemas.set(form.cleaned_data["sistemas"])
        perfil.escolheu_sistemas = True
        perfil.save(update_fields=["escolheu_sistemas", "aprovado_em"])
        messages.success(request, "Sistemas salvos. Bem-vindo a bordo!")
        return redirect("dashboard")


@method_decorator([login_required, never_cache], name="dispatch")
class AprovacaoListView(ListView):
    template_name = "aprovacoes/lista.html"
    context_object_name = "pendentes"
    paginate_by = 30

    def dispatch(self, request, *args, **kwargs):
        perfil = getattr(request.user, "perfil", None)
        if not (request.user.is_superuser or (perfil and perfil.is_diretor)):
            messages.error(request, "Acesso restrito a diretores.")
            return redirect("dashboard")
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return (
            Perfil.objects.filter(aprovado=False)
            .select_related("user")
            .order_by("-user__date_joined")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["aprovados_recentes"] = (
            Perfil.objects.filter(aprovado=True)
            .select_related("user", "aprovado_por")
            .order_by("-aprovado_em")[:20]
        )
        return ctx


@method_decorator([login_required], name="dispatch")
class AprovarUsuarioView(View):
    def post(self, request, pk):
        perfil = getattr(request.user, "perfil", None)
        if not (request.user.is_superuser or (perfil and perfil.is_diretor)):
            messages.error(request, "Acesso restrito a diretores.")
            return redirect("dashboard")

        alvo = get_object_or_404(Perfil, pk=pk, aprovado=False)
        alvo.aprovado = True
        alvo.aprovado_por = request.user
        alvo.aprovado_em = timezone.now()
        alvo.save(update_fields=["aprovado", "aprovado_por", "aprovado_em"])
        messages.success(request, f"{alvo.user.get_full_name() or alvo.user.username} aprovado.")
        return redirect("aprovacoes_lista")


@method_decorator([login_required], name="dispatch")
class RejeitarUsuarioView(View):
    def post(self, request, pk):
        perfil = getattr(request.user, "perfil", None)
        if not (request.user.is_superuser or (perfil and perfil.is_diretor)):
            messages.error(request, "Acesso restrito a diretores.")
            return redirect("dashboard")

        alvo = get_object_or_404(Perfil, pk=pk, aprovado=False)
        nome = alvo.user.get_full_name() or alvo.user.username
        alvo.user.is_active = False
        alvo.user.save(update_fields=["is_active"])
        messages.warning(request, f"{nome} rejeitado (conta desativada).")
        return redirect("aprovacoes_lista")


# =========================================================
# TELEMETRIA
# =========================================================
# =========================================================
# TELEMETRIA — dashboard + API
# =========================================================
from django.http import JsonResponse
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.utils import timezone

from .models import (
    LeituraGuincho, LeituraPosicao, LeituraPropulsor, 
    OrigemGPS, RadarDetectado, StatusBateria, StatusLuz,
)

# Dicionário para traduzir os nomes das luzes que vêm em chinês
TRADUCAO_LUZES = {
    "左外推进器电源": "Propulsor Esq. Externo",
    "右外推进器电源": "Propulsor Dir. Externo",
    "左内推进器电源": "Propulsor Esq. Interno",
    "右内推进器电源": "Propulsor Dir. Interno",
    "锚灯": "Luz de Âncora",
    "NUC ≥ light": "Luz NUC",
    "NUC ≤ light": "Luz NUC (Baixa)",
    "Masthead light": "Luz do Mastro",
    "Anchor light": "Luz de Fundeio",
    "White stern light": "Luz de Popa",
    "Navigation light": "Luz de Navegação",
    "拖拽系统应用": "Sistema de Reboque",
    "SVP绞车应用": "Guincho SVP",
    "左片体舱底水": "Porão Esq.",
    "右片体舱底水": "Porão Dir.",
    "White": "Branca",
    "左撒放": "Soltar Esq.",
    "右撒放": "Soltar Dir.",
    "自动油平衡": "Balanceamento Automático",
}


class TelemetriaView(LoginRequiredMixin, TemplateView):
    template_name = "telemetria.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        sistemas = _sistemas_do_usuario(self.request.user)
        ctx["sistemas"] = sistemas
        ctx["agora"] = timezone.now()
        
        # Dados iniciais (para carregar a página mais rápido antes do JS)
        ctx["svp"] = LeituraGuincho.objects.filter(sistema__in=sistemas, tipo="SVP").order_by("-criado_em").first()
        ctx["tracao"] = LeituraGuincho.objects.filter(sistema__in=sistemas, tipo="TRACAO").order_by("-criado_em").first()
        ctx["posicao"] = LeituraPosicao.objects.filter(sistema__in=sistemas).order_by("-criado_em").first()
        ctx["propulsor"] = LeituraPropulsor.objects.filter(sistema__in=sistemas).order_by("-criado_em").first()
        ctx["origem"] = OrigemGPS.objects.filter(sistema__in=sistemas).first()
        return ctx


@login_required
def api_telemetria(request):
    """JSON com os últimos dados (pra auto-refresh do dashboard)."""
    sistemas = _sistemas_do_usuario(request.user)

    def _guincho(qs):
        obj = qs.order_by("-criado_em").first()
        if not obj: return None
        return {
            "id": obj.id, "criado_em": obj.criado_em.isoformat(),
            "current_temp": obj.current_temp, "current_vol": obj.current_vol,
            "current_ele": obj.current_ele, "current_pull": obj.current_pull,
            "rope_speed": obj.rope_speed, "pull_rope_len": obj.pull_rope_len,
            "winch_rate": obj.winch_rate, "current_work_status": obj.current_work_status,
            "warn": obj.warn, "sys_time": obj.sys_time,
            "max_rope_len": obj.max_rope_len, "remain_min_rope_len": obj.remain_min_rope_len,
            "sensor_once_rope_len": obj.sensor_once_rope_len,
            "winch_acc_speed_ratio": obj.winch_acc_speed_ratio,
            "winch_turn_rate_value": obj.winch_turn_rate_value,
        }

    posicao = LeituraPosicao.objects.filter(sistema__in=sistemas).order_by("-criado_em").first()
    propulsor = LeituraPropulsor.objects.filter(sistema__in=sistemas).order_by("-criado_em").first()
    origem = OrigemGPS.objects.filter(sistema__in=sistemas).first()
    bateria = StatusBateria.objects.filter(sistema__in=sistemas).order_by("-criado_em").first()

    # === Radares ===
    radares = list(
        RadarDetectado.objects.filter(sistema__in=sistemas)
        .values("nome", "x", "y", "distancia", "azimute", "qualidade")
    )

    # === Luzes ===
    luzes_db = StatusLuz.objects.filter(sistema__in=sistemas)
    luzes = []
    for l in luzes_db:
        nome_traduzido = TRADUCAO_LUZES.get(l.nome, l.nome)
        luzes.append({
            "nome": nome_traduzido,
            "status": l.status,
        })
    # Ordena as luzes alfabeticamente em português
    luzes.sort(key=lambda x: x["nome"])

    # === Rastro ===
    rastro = list(
        LeituraPosicao.objects.filter(sistema__in=sistemas)
        .order_by("-criado_em").values("x", "y", "criado_em")[:200]
    )
    for r in rastro: r["criado_em"] = r["criado_em"].isoformat()
    rastro.reverse()

    return JsonResponse({
        "ok": True,
        "agora": timezone.now().isoformat(),
        "origem": {"lat": origem.lat, "lon": origem.lon} if origem else None,
        "guincho_svp": _guincho(LeituraGuincho.objects.filter(sistema__in=sistemas, tipo="SVP")),
        "guincho_tracao": _guincho(LeituraGuincho.objects.filter(sistema__in=sistemas, tipo="TRACAO")),
        "posicao": {
            "x": posicao.x, "y": posicao.y, "z": posicao.z, "qw": posicao.qw,
            "criado_em": posicao.criado_em.isoformat(),
        } if posicao else None,
        "propulsor": {
            "steer": propulsor.steer, "modo": propulsor.modo,
            "criado_em": propulsor.criado_em.isoformat(),
            "ts_atuadores": [propulsor.ts_atuador_1, propulsor.ts_atuador_2, propulsor.ts_atuador_3, propulsor.ts_atuador_4],
        } if propulsor else None,
        "bateria": {
            "temperatura": bateria.temperatura if bateria else None,
            "celulas": bateria.celulas if bateria else None,
            "contador": bateria.contador if bateria else None,
        } if bateria else None,
        "radares": radares,
        "luzes": luzes,
        "rastro": rastro,
    })
@csrf_exempt
def ingest_telemetria(request):
    """
    POST /api/telemetria/ingest/
    Recebe dados do script externo (serial, MQTT, TCP) e grava no banco.

    Body JSON:
    {
      "sistema_id": 1,
      "tipo": "SVP" | "TRACAO" | "POSICAO" | "PROPULSOR" | "ORIGEM" | "RADAR",
      "dados": { ... campos ... }
    }

    Autenticação: token no header X-Ingest-Token (settings.TELEMETRIA_INGEST_TOKEN).
    """
    from django.conf import settings as _settings

    token_esperado = getattr(_settings, "TELEMETRIA_INGEST_TOKEN", None)
    if token_esperado:
        recebido = request.headers.get("X-Ingest-Token", "")
        if recebido != token_esperado:
            return JsonResponse({"ok": False, "erro": "token inválido"}, status=403)

    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "use POST"}, status=405)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "erro": "JSON inválido"}, status=400)

    tipo = (payload.get("tipo") or "").upper()
    dados = payload.get("dados") or {}
    sistema_id = payload.get("sistema_id")

    if not sistema_id or tipo not in {"SVP", "TRACAO", "POSICAO", "PROPULSOR", "ORIGEM", "RADAR"}:
        return JsonResponse(
            {"ok": False, "erro": "sistema_id ou tipo inválido"}, status=400
        )

    try:
        if tipo in {"SVP", "TRACAO"}:
            campos = {
                k: dados.get(k) for k in (
                    "current_temp", "current_vol", "current_ele", "current_pull",
                    "rope_speed", "pull_rope_len", "winch_rate",
                    "current_work_status", "warn", "sys_time",
                    "max_rope_len", "remain_min_rope_len", "sensor_once_rope_len",
                    "winch_acc_speed_ratio", "winch_turn_rate_value",
                )
            }
            LeituraGuincho.objects.create(sistema_id=sistema_id, tipo=tipo, **campos)
        elif tipo == "POSICAO":
            LeituraPosicao.objects.create(
                sistema_id=sistema_id,
                x=float(dados.get("x", 0)),
                y=float(dados.get("y", 0)),
                z=float(dados.get("z", 0)),
                qw=float(dados.get("qw", 1.0)),
                timestamp_msg=float(dados.get("timestamp_msg", _time.time())),
            )
        elif tipo == "PROPULSOR":
            LeituraPropulsor.objects.create(
                sistema_id=sistema_id,
                steer=dados.get("steer"),
                modo=dados.get("modo"),
                timestamp_msg=float(dados.get("timestamp_msg", _time.time())),
                ts_atuador_1=dados.get("ts_atuador_1"),
                ts_atuador_2=dados.get("ts_atuador_2"),
                ts_atuador_3=dados.get("ts_atuador_3"),
                ts_atuador_4=dados.get("ts_atuador_4"),
            )
        elif tipo == "ORIGEM":
            OrigemGPS.objects.update_or_create(
                sistema_id=sistema_id,
                defaults={
                    "lat": float(dados["lat"]),
                    "lon": float(dados["lon"]),
                },
            )
        elif tipo == "RADAR":
            RadarDetectado.objects.create(
                sistema_id=sistema_id,
                nome=str(dados.get("nome", ""))[:50],
                x=float(dados.get("x", 0)),
                y=float(dados.get("y", 0)),
                distancia=float(dados.get("distancia", 0)),
                azimute=float(dados.get("azimute", 0)),
                timestamp=float(dados.get("timestamp", _time.time())),
                qualidade=float(dados.get("qualidade", 0)),
            )
    except (KeyError, TypeError, ValueError) as exc:
        return JsonResponse({"ok": False, "erro": str(exc)}, status=400)

    return JsonResponse({"ok": True})


# =========================================================
# MISSION PLANNER
# =========================================================
_marine_cache: dict[tuple[float, float], tuple[float, dict]] = {}
_MARINE_CACHE_TTL = 600


def _planos_do_usuario(user):
    if not user.is_authenticated:
        return MissionPlan.objects.none()
    perfil = getattr(user, "perfil", None)
    if user.is_superuser or (perfil and perfil.is_diretor):
        return MissionPlan.objects.all()
    return MissionPlan.objects.filter(sistema__in=_sistemas_do_usuario(user))


def _parse_payload(request):
    if request.content_type and "application/json" in request.content_type:
        try:
            return json.loads(request.body.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return {}
    return request.POST


def _centroide_simples(geojson):
    if not geojson:
        return None
    geo = geojson
    if isinstance(geo, dict) and geo.get("type") == "Feature":
        geo = geo.get("geometry") or {}
    if not isinstance(geo, dict) or geo.get("type") != "Polygon":
        return None
    coords = geo.get("coordinates") or []
    if not coords:
        return None
    anel = coords[0]
    if not anel:
        return None
    lons = [p[0] for p in anel]
    lats = [p[1] for p in anel]
    return (sum(lats) / len(lats), sum(lons) / len(lons))


def _waypoints_para_geojson(waypoints_latlon):
    return {
        "type": "LineString",
        "coordinates": [[lon, lat] for lat, lon in waypoints_latlon],
    }


def _salvar_waypoints(rota, waypoints_latlon):
    Waypoint.objects.filter(rota=rota).delete()
    objs, total = [], len(waypoints_latlon)
    for i, (lat, lon) in enumerate(waypoints_latlon):
        if i == 0:
            tipo = Waypoint.Tipo.PARTIDA
        elif i == total - 1:
            tipo = Waypoint.Tipo.CHEGADA
        else:
            tipo = Waypoint.Tipo.NAVEGACAO
        objs.append(Waypoint(rota=rota, ordem=i, lat=lat, lon=lon, tipo=tipo))
    if objs:
        Waypoint.objects.bulk_create(objs)


class _AreaGeoJSONMixin:
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        obj = getattr(self, "object", None)
        ctx["area_geojson_inicial"] = (
            json.dumps(obj.area_geojson) if obj and obj.area_geojson else "null"
        )
        return ctx


class MissionPlanListView(LoginRequiredMixin, ListView):
    model = MissionPlan
    template_name = "planner/plan_list.html"
    context_object_name = "planos"
    paginate_by = 20

    def get_queryset(self):
        return (
            _planos_do_usuario(self.request.user)
            .select_related("sistema", "missao", "criado_por")
            .order_by("-criado_em")
        )


class MissionPlanCreateView(_AreaGeoJSONMixin, LoginRequiredMixin, CreateView):
    model = MissionPlan
    form_class = MissionPlanForm
    template_name = "planner/plan_form.html"

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw["user"] = self.request.user
        return kw

    def form_valid(self, form):
        form.instance.criado_por = self.request.user
        messages.success(self.request, "Plano criado. Gere a rota.")
        return super().form_valid(form)


class MissionPlanUpdateView(_AreaGeoJSONMixin, LoginRequiredMixin, UpdateView):
    model = MissionPlan
    form_class = MissionPlanForm
    template_name = "planner/plan_form.html"

    def get_queryset(self):
        return _planos_do_usuario(self.request.user)

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw["user"] = self.request.user
        return kw

    def form_valid(self, form):
        messages.success(self.request, "Plano atualizado.")
        return super().form_valid(form)


class MissionPlanDetailView(LoginRequiredMixin, DetailView):
    model = MissionPlan
    template_name = "planner/plan_detail.html"
    context_object_name = "plano"

    def get_queryset(self):
        return _planos_do_usuario(self.request.user).select_related("sistema", "missao")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        plano = self.object
        rota = plano.rotas.order_by("-criado_em").first()

        ctx["rota"] = rota
        ctx["waypoints"] = list(rota.waypoints.order_by("ordem")) if rota else []

        # IMPORTANTE: manda dict/None, NÃO string JSON.
        # O json_script do template serializa. Se mandar string, dá double-encode.
        ctx["area_geojson_inicial"] = plano.area_geojson or None
        ctx["rota_geojson_inicial"] = (
            rota.geometria_geojson if rota and rota.geometria_geojson else None
        ) or None

        return ctx

class GerarRotaView(LoginRequiredMixin, View):
    def post(self, request, pk):
        plano = get_object_or_404(_planos_do_usuario(request.user), pk=pk)

        try:
            if plano.padrao_rota == MissionPlan.PadraoRota.LAWN_MOWER:
                if not plano.area_geojson:
                    return JsonResponse(
                        {"ok": False, "erro": "Desenhe a área antes de gerar a rota."},
                        status=400,
                    )
                resultado = gerar_rota_lawn_mower(
                    area_geojson=plano.area_geojson,
                    espacamento_m=plano.espacamento_linhas_m,
                    angulo_graus=plano.angulo_linhas_graus,
                    velocidade_nos=plano.velocidade_planejada_nos,
                )
            else:
                if not plano.area_geojson:
                    return JsonResponse(
                        {"ok": False, "erro": "Nenhum waypoint informado."},
                        status=400,
                    )
                pts = [
                    (c[1], c[0]) for c in
                    (plano.area_geojson.get("coordinates") or [[]])[0]
                ]
                resultado = gerar_rota_waypoints(
                    waypoints_latlon=pts,
                    velocidade_nos=plano.velocidade_planejada_nos,
                )
        except ValueError as exc:
            return JsonResponse({"ok": False, "erro": str(exc)}, status=400)

        rota = Route.objects.create(
            plano=plano,
            nome=f"Rota {plano.nome}",
            status=Route.Status.PLANNED,
            geometria_geojson=_waypoints_para_geojson(resultado.waypoints),
            distancia_total_m=resultado.distancia_total_m,
            tempo_estimado_min=resultado.tempo_estimado_min,
        )
        _salvar_waypoints(rota, resultado.waypoints)

        plano.distancia_total_m = resultado.distancia_total_m
        plano.tempo_estimado_min = resultado.tempo_estimado_min
        plano.area_cobertura_m2 = resultado.area_cobertura_m2
        plano.n_waypoints = len(resultado.waypoints)
        plano.save(update_fields=[
            "distancia_total_m", "tempo_estimado_min",
            "area_cobertura_m2", "n_waypoints", "atualizado_em",
        ])

        return JsonResponse({
            "ok": True,
            "rota_id": rota.pk,
            "geometria": rota.geometria_geojson,
            "distancia_m": resultado.distancia_total_m,
            "tempo_min": resultado.tempo_estimado_min,
            "area_m2": resultado.area_cobertura_m2,
            "n_waypoints": len(resultado.waypoints),
            "avisos": resultado.avisos,
            "url_detalhe": reverse("mission_plan_detail", args=[plano.pk]),
        })


class OtimizarWaypointsView(LoginRequiredMixin, View):
    def post(self, request, pk):
        plano = get_object_or_404(_planos_do_usuario(request.user), pk=pk)
        dados = _parse_payload(request)
        pontos = dados.get("pontos") or []
        if not isinstance(pontos, list) or len(pontos) < 2:
            return JsonResponse(
                {"ok": False, "erro": "Envie pelo menos 2 pontos."}, status=400
            )
        try:
            pts = [(float(p["lat"]), float(p["lon"])) for p in pontos]
        except (KeyError, TypeError, ValueError):
            return JsonResponse(
                {"ok": False, "erro": "Formato inválido dos pontos."}, status=400
            )

        otimizados = otimizar_waypoints_nearest_neighbor(pts)
        return JsonResponse({
            "ok": True,
            "pontos": [{"lat": lat, "lon": lon} for lat, lon in otimizados],
        })


class CondicoesAmbientaisView(LoginRequiredMixin, View):
    def get(self, request, pk):
        plano = get_object_or_404(_planos_do_usuario(request.user), pk=pk)

        centro = _centroide_simples(plano.area_geojson)
        if not centro:
            return JsonResponse(
                {"ok": False, "erro": "Plano sem área definida."}, status=400
            )
        lat, lon = centro

        chave = (round(lat, 3), round(lon, 3))
        agora = _time.time()
        if chave in _marine_cache:
            ts, dados = _marine_cache[chave]
            if agora - ts < _MARINE_CACHE_TTL:
                return JsonResponse(dados)

        cond = fetch_marine_conditions(lat, lon)
        dados = conditions_to_dict(cond)
        _marine_cache[chave] = (agora, dados)
        return JsonResponse(dados)


class CondicoesPontoView(LoginRequiredMixin, View):
    def get(self, request):
        try:
            lat = float(request.GET.get("lat", ""))
            lon = float(request.GET.get("lon", ""))
        except (TypeError, ValueError):
            return JsonResponse(
                {"ok": False, "erro": "Parâmetros lat/lon inválidos."}, status=400
            )

        chave = (round(lat, 3), round(lon, 3))
        agora = _time.time()
        if chave in _marine_cache:
            ts, dados = _marine_cache[chave]
            if agora - ts < _MARINE_CACHE_TTL:
                return JsonResponse(dados)

        cond = fetch_marine_conditions(lat, lon)
        dados = conditions_to_dict(cond)
        _marine_cache[chave] = (agora, dados)
        return JsonResponse(dados)


class AnalisarAreaView(LoginRequiredMixin, View):
    def post(self, request):
        dados = _parse_payload(request)
        area = dados.get("area_geojson")
        if not area:
            return JsonResponse(
                {"ok": False, "erro": "Área não enviada."}, status=400
            )
        try:
            info = analisar_area(area)
        except Exception as exc:
            return JsonResponse({"ok": False, "erro": str(exc)}, status=400)
        return JsonResponse({"ok": True, "info": info})