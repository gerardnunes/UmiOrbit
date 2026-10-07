"""Regras de acesso: diretor só visualiza; trabalhador (e admin) edita."""
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied


def eh_diretor(user) -> bool:
    if not user.is_authenticated or user.is_superuser:
        return False
    perfil = getattr(user, "perfil", None)
    return bool(perfil and perfil.papel == "DIRETOR")


def pode_editar(user) -> bool:
    return user.is_authenticated and not eh_diretor(user)


class TrabalhadorRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Bloqueia diretores em qualquer tela que altere dados."""

    def test_func(self):
        return pode_editar(self.request.user)

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            raise PermissionDenied
        return super().handle_no_permission()
