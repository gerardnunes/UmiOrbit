from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Perfil


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def criar_perfil(sender, instance, created, **kwargs):
    """Todo usuário novo nasce como trabalhador; o admin pode promovê-lo a diretor."""
    if created:
        Perfil.objects.get_or_create(user=instance)
