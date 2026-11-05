class SistemaScopedMixin:
    """
    Filtra qualquer ListView/DetailView por `request.user.perfil.sistemas`.
    Uso:
        class DemandaListView(SistemaScopedMixin, LoginRequiredMixin, ListView):
            model = Demanda
            # pronto, o queryset já vem filtrado
    """

    def get_queryset(self):
        qs = super().get_queryset()
        if hasattr(qs, "do_usuario"):
            return qs.do_usuario(self.request.user)
        user = self.request.user
        perfil = getattr(user, "perfil", None)
        if user.is_superuser or (perfil and perfil.is_diretor):
            return qs
        if not perfil:
            return qs.none()
        return qs.filter(sistema__in=perfil.sistemas.all())


class SistemaDoUsuarioMixin:
    """Deixa a lista de sistemas do usuário disponível no contexto."""
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        perfil = getattr(user, "perfil", None)
        if user.is_superuser or (perfil and perfil.is_diretor):
            ctx["sistemas_do_usuario"] = list(
                __import__("operacao.models", fromlist=["Sistema"]).Sistema.objects.filter(ativo=True)
            )
        elif perfil:
            ctx["sistemas_do_usuario"] = list(perfil.sistemas.filter(ativo=True))
        else:
            ctx["sistemas_do_usuario"] = []
        return ctx