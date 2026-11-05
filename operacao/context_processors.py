from .permissions import eh_diretor, pode_editar

def aprovacoes_pendentes(request):
    if not request.user.is_authenticated:
        return {}
    perfil = getattr(request.user, "perfil", None)
    if request.user.is_superuser or (perfil and perfil.is_diretor):
        from .models import Perfil
        return {"aprovacoes_pendentes_count": Perfil.objects.filter(aprovado=False).count()}
    return {}
def contexto(request):
    user = request.user
    papel = ""
    if user.is_authenticated:
        papel = "Diretor" if eh_diretor(user) else "Trabalhador"
    return {"pode_editar": pode_editar(user), "eh_diretor": eh_diretor(user), "papel_label": papel}
