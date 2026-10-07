from .permissions import eh_diretor, pode_editar


def contexto(request):
    user = request.user
    papel = ""
    if user.is_authenticated:
        papel = "Diretor" if eh_diretor(user) else "Trabalhador"
    return {"pode_editar": pode_editar(user), "eh_diretor": eh_diretor(user), "papel_label": papel}
