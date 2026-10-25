from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.db.models import Count, Q
from django.utils.html import format_html

from .models import (
    Atualizacao,
    Checklist,
    ChecklistItem,
    ChecklistMissao,
    Demanda,
    Missao,
    Perfil,
    Sistema,
    Status,
    StatusMissao,
)

User = get_user_model()


# ============================================================
# HELPERS DE COR
# ============================================================

CORES_STATUS_DEMANDA = {
    Status.PENDENTE:  "#94a3b8",   # cinza
    Status.ANDAMENTO: "#7f9dbf",   # azul acinzentado
    Status.BLOQUEADA: "#c47a7a",   # vermelho suave
    Status.CONCLUIDA: "#6fa86f",   # verde suave
    Status.CANCELADA: "#64748b",   # cinza escuro
}

CORES_STATUS_MISSAO = {
    StatusMissao.PREPARACAO:  "#d4a24c",   # âmbar
    StatusMissao.EM_OPERACAO: "#6fa86f",   # verde
    StatusMissao.PAUSADA:     "#94a3b8",   # cinza
    StatusMissao.FINALIZADA:  "#7f9dbf",   # azul
    StatusMissao.CANCELADA:   "#c47a7a",   # vermelho
}

CORES_PRIORIDADE = {
    "CRITICA": "#c47a7a",
    "ALTA":    "#d4a24c",
    "MEDIA":   "#94a3b8",
    "BAIXA":   "#64748b",
}


def badge(texto, cor):
    """Devolve um <span> estilizado como badge (HTML seguro)."""
    return format_html(
        '<span style="display:inline-block;padding:2px 8px;'
        'border-radius:10px;font-size:11px;font-weight:600;'
        'background:{}22;color:{};border:1px solid {}55;">{}</span>',
        cor, cor, cor, texto,
    )


def barra_progresso(pct, cor="#6fa86f"):
    """Barra de progresso em HTML puro (sem JS)."""
    pct = max(0, min(100, int(pct)))
    return format_html(
        '<div style="display:inline-block;min-width:120px;vertical-align:middle;">'
        '<div style="background:#2a3441;border-radius:4px;height:6px;overflow:hidden;'
        'margin-bottom:3px;"><div style="width:{}%;background:{};height:100%;"></div></div>'
        '<span style="font-size:11px;color:#94a3b8;">{}%</span>'
        '</div>',
        pct, cor, pct,
    )


# ============================================================
# USUÁRIOS + PERFIL
# ============================================================

class PerfilInline(admin.StackedInline):
    model = Perfil
    can_delete = False
    verbose_name_plural = "Perfil (trabalhador ou diretor)"


class UserAdminComPerfil(UserAdmin):
    inlines = [PerfilInline]

    list_display = (
        "username",
        "first_name",
        "last_name",
        "papel_badge",
        "is_active",
    )

    list_select_related = ("perfil",)

    actions = ["virar_diretor", "virar_trabalhador"]

    @admin.display(description="papel")
    def papel_badge(self, obj):
        try:
            papel = obj.perfil.papel
        except Perfil.DoesNotExist:
            return "—"
        if papel == Perfil.Papel.DIRETOR:
            return badge("Diretor", "#d4a24c")
        return badge("Trabalhador", "#7f9dbf")

    def get_inline_instances(self, request, obj=None):
        return super().get_inline_instances(request, obj) if obj else []

    @admin.action(description="Definir como DIRETOR (somente visualização)")
    def virar_diretor(self, request, qs):
        n = Perfil.objects.filter(user__in=qs).update(papel=Perfil.Papel.DIRETOR)
        self.message_user(request, f"{n} usuário(s) agora são diretores.", messages.SUCCESS)

    @admin.action(description="Definir como TRABALHADOR (pode editar)")
    def virar_trabalhador(self, request, qs):
        n = Perfil.objects.filter(user__in=qs).update(papel=Perfil.Papel.TRABALHADOR)
        self.message_user(request, f"{n} usuário(s) agora são trabalhadores.", messages.SUCCESS)


try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass

admin.site.register(User, UserAdminComPerfil)


# ============================================================
# SISTEMAS / EMBARCAÇÕES
# ============================================================

@admin.register(Sistema)
class SistemaAdmin(admin.ModelAdmin):
    list_display = ("nome", "descricao", "ordem", "ativo")
    list_editable = ("ordem", "ativo")
    search_fields = ("nome", "descricao")
    ordering = ("ordem", "nome")


# ============================================================
# DEMANDAS
# ============================================================

class AtualizacaoInline(admin.TabularInline):
    model = Atualizacao
    extra = 0
    readonly_fields = ("autor", "criado_em", "status_anterior", "status_novo")
    fields = ("criado_em", "autor", "status_anterior", "status_novo", "texto")
    ordering = ("-criado_em",)


@admin.register(Demanda)
class DemandaAdmin(admin.ModelAdmin):
    list_display = (
        "codigo",
        "titulo_curto",
        "missao_link",
        "sistema",
        "tipo",
        "prioridade_badge",
        "status_badge",
        "responsavel",
        "prazo_curto",
        "bloqueia_badge",
    )

    list_filter = (
        "status",
        "prioridade",
        "tipo",
        "sistema",
        "missao",
        "bloqueia_operacao",
    )

    search_fields = ("titulo", "item_faltante", "descricao")

    autocomplete_fields = ("sistema", "criado_por", "responsavel", "missao")

    inlines = [AtualizacaoInline]

    list_select_related = ("sistema", "responsavel", "missao")

    date_hierarchy = "criado_em"

    fieldsets = (
        (
            "Identificação",
            {
                "fields": (
                    "titulo",
                    "missao",
                    "sistema",
                    "tipo",
                    "classe",
                )
            },
        ),
        (
            "Classificação",
            {
                "fields": (
                    "prioridade",
                    "status",
                    "bloqueia_operacao",
                )
            },
        ),
        (
            "Execução",
            {
                "fields": (
                    "responsavel",
                    "prazo",
                )
            },
        ),
        (
            "Detalhes",
            {
                "fields": (
                    "descricao",
                    "item_faltante",
                    "quantidade",
                )
            },
        ),
        (
            "Metadados",
            {
                "fields": ("criado_por", "criado_em", "atualizado_em", "concluida_em"),
                "classes": ("collapse",),
            },
        ),
    )

    readonly_fields = ("criado_em", "atualizado_em", "concluida_em")

    @admin.display(description="Título")
    def titulo_curto(self, obj):
        return (obj.titulo[:60] + "…") if len(obj.titulo) > 60 else obj.titulo

    @admin.display(description="Missão")
    def missao_link(self, obj):
        if not obj.missao:
            return "—"
        url = f"/admin/operacao/missao/{obj.missao.pk}/change/"
        return format_html('<a href="{}">{}</a>', url, obj.missao.titulo[:40])

    @admin.display(description="Prioridade", ordering="prioridade")
    def prioridade_badge(self, obj):
        return badge(obj.get_prioridade_display(), CORES_PRIORIDADE.get(obj.prioridade, "#94a3b8"))

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        return badge(obj.get_status_display(), CORES_STATUS_DEMANDA.get(obj.status, "#94a3b8"))

    @admin.display(description="Prazo", ordering="prazo")
    def prazo_curto(self, obj):
        if not obj.prazo:
            return "—"
        if obj.atrasada:
            return format_html('<span style="color:#c47a7a;font-weight:600;">{}</span> ⚠', obj.prazo.strftime("%d/%m/%Y"))
        return obj.prazo.strftime("%d/%m/%Y")

    @admin.display(description="Bloqueia?", ordering="bloqueia_operacao", boolean=False)
    def bloqueia_badge(self, obj):
        if obj.bloqueia_operacao:
            return badge("BLOQUEIA", "#c47a7a")
        return ""


# ============================================================
# ATUALIZAÇÕES
# ============================================================

@admin.register(Atualizacao)
class AtualizacaoAdmin(admin.ModelAdmin):
    list_display = ("demanda", "autor", "status_anterior", "status_novo", "criado_em")
    list_filter = ("status_anterior", "status_novo")
    search_fields = ("demanda__titulo", "texto")
    autocomplete_fields = ("demanda", "autor")


# ============================================================
# CHECKLISTS (novo)
# ============================================================

class ChecklistItemInline(admin.TabularInline):
    model = ChecklistItem
    extra = 0
    fields = ("ordem", "titulo", "sistema", "prioridade", "concluido")
    ordering = ("ordem",)
    show_change_link = True


@admin.register(Checklist)
class ChecklistAdmin(admin.ModelAdmin):
    list_display = (
        "titulo",
        "missao_link",
        "status_badge",
        "progresso_badge",
        "exige_login_badge",
        "criado_em",
    )

    list_filter = ("status", "missao", "exige_login_auditoria")

    search_fields = ("titulo", "descricao")

    autocomplete_fields = ("missao", "criado_por")

    inlines = [ChecklistItemInline]

    list_select_related = ("missao",)

    readonly_fields = ("token_auditoria", "criado_em", "atualizado_em")

    @admin.display(description="Missão")
    def missao_link(self, obj):
        if not obj.missao:
            return "—"
        url = f"/admin/operacao/missao/{obj.missao.pk}/change/"
        return format_html('<a href="{}">{}</a>', url, obj.missao.titulo[:40])

    @admin.display(description="Status")
    def status_badge(self, obj):
        cores = {
            Checklist.Status.RASCUNHO:  "#94a3b8",
            Checklist.Status.ATIVO:     "#6fa86f",
            Checklist.Status.CONCLUIDO: "#7f9dbf",
            Checklist.Status.ARQUIVADO: "#64748b",
        }
        return badge(obj.get_status_display(), cores.get(obj.status, "#94a3b8"))

    @admin.display(description="Progresso")
    def progresso_badge(self, obj):
        return barra_progresso(obj.pct)

    @admin.display(description="Auditoria")
    def exige_login_badge(self, obj):
        if obj.exige_login_auditoria:
            return badge("🔒 login", "#d4a24c")
        return badge("🌐 livre", "#6fa86f")


# ============================================================
# MISSÕES
# ============================================================

class ChecklistMissaoInline(admin.TabularInline):
    model = ChecklistMissao
    extra = 1
    fields = ("ordem", "item", "concluido", "observacao")


class DemandaInlineMissao(admin.TabularInline):
    """Mostra, dentro da missão, as demandas vinculadas."""
    model = Demanda
    fk_name = "missao"
    extra = 0
    fields = ("codigo", "titulo", "tipo", "prioridade", "status", "responsavel")
    readonly_fields = ("codigo",)
    show_change_link = True
    ordering = ("-criado_em",)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Missao)
class MissaoAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "titulo",
        "local",
        "responsavel",
        "status_badge",
        "inicio_previsto",
        "fim",
        "checklists_badge",
        "demandas_badge",
    )

    list_filter = ("status", "local")

    search_fields = ("titulo", "objetivo", "local", "observacoes")

    autocomplete_fields = ("responsavel", "criado_por")

    readonly_fields = ("criado_em", "atualizado_em")

    list_select_related = ("responsavel",)

    fieldsets = (
        (
            "Missão",
            {
                "fields": (
                    "titulo",
                    "objetivo",
                    "local",
                    "responsavel",
                    "status",
                )
            },
        ),
        (
            "Operação",
            {
                "fields": (
                    "inicio_previsto",
                    "inicio",
                    "fim",
                    "observacoes",
                )
            },
        ),
        (
            "Sistema",
            {
                "fields": ("criado_por", "criado_em", "atualizado_em"),
                "classes": ("collapse",),
            },
        ),
    )

    inlines = [DemandaInlineMissao, ChecklistMissaoInline]

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        return badge(obj.get_status_display(), CORES_STATUS_MISSAO.get(obj.status, "#94a3b8"))

    @admin.display(description="Checklists")
    def checklists_badge(self, obj):
        total = obj.checklists.count()
        if total == 0:
            return "—"
        concluidos = obj.checklists.filter(status=Checklist.Status.CONCLUIDO).count()
        pct = concluidos * 100 // total
        return barra_progresso(pct)

    @admin.display(description="Demandas")
    def demandas_badge(self, obj):
        total = obj.demandas.count()
        if total == 0:
            return "—"
        abertas = obj.demandas.filter(status__in=[Status.PENDENTE, Status.ANDAMENTO, Status.BLOQUEADA]).count()
        if abertas:
            return badge(f"{abertas} aberta{'s' if abertas != 1 else ''}", "#d4a24c")
        return badge(f"{total}", "#6fa86f")


# ============================================================
# CHECKLIST DE MISSÃO (antigo, mantido)
# ============================================================

@admin.register(ChecklistMissao)
class ChecklistMissaoAdmin(admin.ModelAdmin):
    list_display = ("missao", "ordem", "item", "concluido", "observacao")
    list_filter = ("concluido",)
    search_fields = ("item", "observacao", "missao__titulo")
    autocomplete_fields = ("missao",)
    ordering = ("missao", "ordem")