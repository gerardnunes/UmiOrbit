from django.shortcuts import redirect
from django.urls import reverse


class PrimeiroLoginMiddleware:
    """
    - Se logado e Perfil NÃO aprovado: manda para 'aguardando_aprovacao'
      (exceto quando já está lá, ou em login/logout/cadastro/admin).
    - Se logado, aprovado mas NÃO escolheu sistemas: manda para
      'selecionar_sistemas' (exceto quando já está lá, etc).
    """

    # URLs que NUNCA devem ser bloqueadas
    ROTAS_LIVRES = {
        "login", "logout", "cadastro", "aguardando_aprovacao",
        "selecionar_sistemas", "admin:index", "admin:login", "admin:logout",
    }

    # Prefixos de path que NUNCA devem ser bloqueados
    PREFIXOS_LIVRES = ("/admin/", "/static/", "/media/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Se não está logado, não faz nada
        if not request.user.is_authenticated:
            return self.get_response(request)

        path = request.path or ""

        # Não intercepta admin/static/media
        if any(path.startswith(p) for p in self.PREFIXOS_LIVRES):
            return self.get_response(request)

        # O nome da rota ainda não está resolvido neste ponto do middleware
        # (o resolver_match é preenchido DEPOIS). Por isso usamos o path.
        urls_livres_path = {
            reverse("login"),
            reverse("logout"),
            reverse("cadastro"),
            reverse("aguardando_aprovacao"),
            reverse("selecionar_sistemas"),
        }

        # Se a URL é uma das livres, deixa passar
        if path in urls_livres_path:
            return self.get_response(request)

        # Tenta o Perfil
        perfil = getattr(request.user, "perfil", None)

        # Sem Perfil = não bloqueia (admin, superuser antigo, etc.)
        if perfil is None:
            return self.get_response(request)

        if not perfil.aprovado:
            return redirect("aguardando_aprovacao")

        if not perfil.escolheu_sistemas:
            return redirect("selecionar_sistemas")

        return self.get_response(request)