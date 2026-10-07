from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
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
]
