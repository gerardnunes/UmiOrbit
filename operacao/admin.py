from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

from .models import (
    Atualizacao,
    ChecklistMissao,
    Demanda,
    Missao,
    Perfil,
    Sistema,
)

User = get_user_model()


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
        "papel",
        "is_active",
    )

    list_select_related = ("perfil",)

    actions = [
        "virar_diretor",
        "virar_trabalhador",
    ]

    @admin.display(description="papel")
    def papel(self, obj):
        return obj.perfil.get_papel_display()

    def get_inline_instances(self, request, obj=None):
        # No cadastro o perfil é criado automaticamente.
        # Depois o administrador pode editar/promover.
        return super().get_inline_instances(request, obj) if obj else []

    @admin.action(description="Definir como DIRETOR (somente visualização)")
    def virar_diretor(self, request, qs):
        n = Perfil.objects.filter(
            user__in=qs
        ).update(
            papel=Perfil.Papel.DIRETOR
        )

        self.message_user(
            request,
            f"{n} usuário(s) agora são diretores.",
            messages.SUCCESS,
        )

    @admin.action(description="Definir como TRABALHADOR (pode editar)")
    def virar_trabalhador(self, request, qs):
        n = Perfil.objects.filter(
            user__in=qs
        ).update(
            papel=Perfil.Papel.TRABALHADOR
        )

        self.message_user(
            request,
            f"{n} usuário(s) agora são trabalhadores.",
            messages.SUCCESS,
        )


# Evita conflito com o UserAdmin padrão do Django.
try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass

admin.site.register(User, UserAdminComPerfil)


# ============================================================
# SISTEMAS
# ============================================================

@admin.register(Sistema)
class SistemaAdmin(admin.ModelAdmin):
    list_display = (
        "nome",
        "descricao",
        "ordem",
    )

    list_editable = (
        "ordem",
    )

    search_fields = (
        "nome",
        "descricao",
    )

    ordering = (
        "ordem",
        "nome",
    )


# ============================================================
# DEMANDAS / MANUTENÇÃO
# ============================================================

class AtualizacaoInline(admin.TabularInline):
    model = Atualizacao
    extra = 0
    readonly_fields = (
        "autor",
        "criado_em",
    )


@admin.register(Demanda)
class DemandaAdmin(admin.ModelAdmin):
    list_display = (
        "codigo",
        "titulo",
        "sistema",
        "tipo",
        "prioridade",
        "status",
        "responsavel",
        "prazo",
        "bloqueia_operacao",
        "classe"
    )

    list_filter = (
        "status",
        "prioridade",
        "tipo",
        "sistema",
        "bloqueia_operacao",
    )

    search_fields = (
        "titulo",
        "item_faltante",
        "descricao",
    )

    autocomplete_fields = (
        "sistema",
        "criado_por",
        "responsavel",
    )

    inlines = [
        AtualizacaoInline,
    ]


# ============================================================
# ATUALIZAÇÕES
# ============================================================

@admin.register(Atualizacao)
class AtualizacaoAdmin(admin.ModelAdmin):
    list_display = (
        "demanda",
        "autor",
        "status_anterior",
        "status_novo",
        "criado_em",
    )

    list_filter = (
        "status_anterior",
        "status_novo",
    )

    search_fields = (
        "demanda__titulo",
        "texto",
    )

    autocomplete_fields = (
        "demanda",
        "autor",
    )


# ============================================================
# MISSÕES
# ============================================================

class ChecklistMissaoInline(admin.TabularInline):
    model = ChecklistMissao

    extra = 1

    fields = (
        "ordem",
        "item",
        "concluido",
        "observacao",
    )


@admin.register(Missao)
class MissaoAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "titulo",
        "local",
        "responsavel",
        "status",
        "inicio_previsto",
        "inicio",
        "fim",
        "checklist_status",
    )

    list_filter = (
        "status",
        "local",
    )

    search_fields = (
        "titulo",
        "objetivo",
        "local",
        "observacoes",
    )

    autocomplete_fields = (
        "responsavel",
        "criado_por",
    )

    readonly_fields = (
        "criado_em",
        "atualizado_em",
    )

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
                "fields": (
                    "criado_por",
                    "criado_em",
                    "atualizado_em",
                )
            },
        ),
    )

    inlines = [
        ChecklistMissaoInline,
    ]

    @admin.display(description="Checklist")
    def checklist_status(self, obj):
        total = obj.checklist_total
        concluido = obj.checklist_concluido

        if total == 0:
            return "Sem checklist"

        return f"{concluido}/{total} ({obj.checklist_percentual}%)"


# ============================================================
# CHECKLIST DE MISSÃO
# ============================================================

@admin.register(ChecklistMissao)
class ChecklistMissaoAdmin(admin.ModelAdmin):

    list_display = (
        "missao",
        "ordem",
        "item",
        "concluido",
        "observacao",
    )

    list_filter = (
        "concluido",
    )

    search_fields = (
        "item",
        "observacao",
        "missao__titulo",
    )

    autocomplete_fields = (
        "missao",
    )

    ordering = (
        "missao",
        "ordem",
    )