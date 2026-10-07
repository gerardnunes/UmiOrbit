from django.apps import AppConfig


class OperacaoConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "operacao"
    verbose_name = "Operação do L42"

    def ready(self):
        from . import signals  # noqa: F401
