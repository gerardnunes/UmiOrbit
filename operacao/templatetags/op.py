from django import template

register = template.Library()


@register.filter
def nome(user):
    """Nome completo ou, na falta dele, o login."""
    if not user:
        return "—"
    return user.get_full_name() or user.username


@register.simple_tag(takes_context=True)
def pagina(context, numero):
    """Querystring atual trocando só o número da página (mantém os filtros)."""
    q = context["request"].GET.copy()
    q["page"] = numero
    return q.urlencode()
