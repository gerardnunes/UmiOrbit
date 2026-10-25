from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

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
]
path(
    "checklists/modelo.xlsx",
    views.ChecklistModeloView.as_view(),
    name="checklist_modelo",
),