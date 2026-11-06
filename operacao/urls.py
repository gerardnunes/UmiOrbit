from django.contrib.auth import views as auth_views
from django.http import JsonResponse
from django.urls import path

from . import views


def saude(request):
    return JsonResponse({"status": "ok"}, status=200)
urlpatterns = [
    path("saude/", saude, name="saude"),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("sair/", auth_views.LogoutView.as_view(), name="logout"),
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("demandas/", views.DemandaListView.as_view(), name="demanda_lista"),
    path("demandas/nova/", views.DemandaCreateView.as_view(), name="demanda_nova"),
    path("demandas/<int:pk>/", views.DemandaDetailView.as_view(), name="demanda_detalhe"),
    path("demandas/<int:pk>/editar/", views.DemandaUpdateView.as_view(), name="demanda_editar"),
    path("demandas/<int:pk>/assumir/", views.AssumirDemandaView.as_view(), name="demanda_assumir"),
    path("demandas/<int:pk>/atualizar/", views.AtualizarDemandaView.as_view(), name="demanda_atualizar"),
    path("equipe/", views.EquipeView.as_view(), name="equipe"),
    path("perfil/", views.MeuPerfilView.as_view(), name="meu_perfil"),
    path("manutencao/", views.ManutencaoView.as_view(), name="manutencao"),
    path("missoes/", views.MissaoListView.as_view(), name="missoes"),
    path("missoes/nova/", views.MissaoCreateView.as_view(), name="missao_nova"),
    path("checklists/", views.ChecklistListView.as_view(), name="checklist_lista"),
    path("checklists/novo/", views.ChecklistCreateView.as_view(), name="checklist_novo"),
    path("checklists/modelo.xlsx", views.ChecklistModeloView.as_view(), name="checklist_modelo"),
    path("checklists/<int:pk>/", views.ChecklistDetailView.as_view(), name="checklist_detalhe"),
    path("checklists/<int:pk>/editar/", views.ChecklistUpdateView.as_view(), name="checklist_editar"),
    path("checklists/<int:pk>/importar/", views.ChecklistImportView.as_view(), name="checklist_importar"),
    path("checklists/item/<int:pk>/toggle/", views.ChecklistItemToggleView.as_view(), name="checklist_item_toggle"),
    path("auditoria/<uuid:token>/", views.AuditoriaChecklistView.as_view(), name="auditoria_checklist"),
    path("auditoria/<uuid:token>/item/<int:item_id>/toggle/", views.AuditoriaToggleItemView.as_view(), name="auditoria_toggle"),
    path("auditoria/<uuid:token>/item/<int:item_id>/foto/", views.AuditoriaUploadFotoView.as_view(), name="auditoria_foto"),
    path("missoes/<int:pk>/", views.MissaoDetailView.as_view(), name="missao_detalhe"),
    path("auditoria/<uuid:token>/foto/<int:foto_id>/remover/", views.AuditoriaRemoverFotoView.as_view(), name="auditoria_foto_remover"),
    # ---------------- INCIDENTES ----------------
    path("incidentes/", views.IncidenteListView.as_view(), name="incidente_lista"),
    path("incidentes/novo/", views.IncidenteCreateView.as_view(), name="incidente_novo"),
    path("incidentes/<int:pk>/", views.IncidenteDetailView.as_view(), name="incidente_detalhe"),
    path("incidentes/<int:pk>/editar/", views.IncidenteUpdateView.as_view(), name="incidente_editar"),
    path("incidentes/<int:pk>/apagar/", views.IncidenteDeleteView.as_view(), name="incidente_apagar"),
    path("incidentes/<int:pk>/status/", views.IncidenteMudarStatusView.as_view(), name="incidente_status"),
    path("incidentes/<int:pk>/comentar/", views.IncidenteComentarView.as_view(), name="incidente_comentar"),
    path("incidentes/<int:pk>/anexar/", views.IncidenteAnexoView.as_view(), name="incidente_anexar"),

    path("incidentes/<int:pk>/anexo/<int:anexo_id>/remover/", views.IncidenteRemoverAnexoView.as_view(), name="incidente_anexo_remover"),
    path("cadastro/", views.CadastroView.as_view(), name="cadastro"),
    path("aguardando-aprovacao/", views.AguardandoAprovacaoView.as_view(), name="aguardando_aprovacao"),
    path("selecionar-sistemas/", views.SelecionarSistemasView.as_view(), name="selecionar_sistemas"),
    path("aprovacoes/", views.AprovacaoListView.as_view(), name="aprovacoes_lista"),
    path("aprovacoes/<int:pk>/aprovar/", views.AprovarUsuarioView.as_view(), name="aprovacoes_aprovar"),
    path("aprovacoes/<int:pk>/rejeitar/", views.RejeitarUsuarioView.as_view(), name="aprovacoes_rejeitar"),
    path("telemetria/", views.TelemetriaView.as_view(), name="telemetria"),
    path("api/telemetria/", views.api_telemetria, name="api_telemetria"),
]


path(
    "checklists/modelo.xlsx",
    views.ChecklistModeloView.as_view(),
    name="checklist_modelo",
),