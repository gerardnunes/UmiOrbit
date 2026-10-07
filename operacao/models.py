from django.conf import settings
from django.db import models
from django.db.models import Case, F, IntegerField, When
from django.urls import reverse
from django.utils import timezone


class Perfil(models.Model):
    class Papel(models.TextChoices):
        TRABALHADOR = "TRABALHADOR", "Trabalhador"
        DIRETOR = "DIRETOR", "Diretor"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="perfil")
    papel = models.CharField(max_length=12, choices=Papel.choices, default=Papel.TRABALHADOR)
    cargo = models.CharField("cargo / função", max_length=80, blank=True)
    telefone = models.CharField(max_length=30, blank=True)

    class Meta:
        verbose_name = "perfil"
        verbose_name_plural = "perfis"

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.get_papel_display()})"


class Sistema(models.Model):
    """Partes do barco: casco, propulsão, energia, navegação autônoma..."""

    nome = models.CharField(max_length=80, unique=True)
    descricao = models.CharField("descrição", max_length=200, blank=True)
    ordem = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["ordem", "nome"]
        verbose_name = "sistema do barco"
        verbose_name_plural = "sistemas do barco"

    def __str__(self):
        return self.nome


class Status(models.TextChoices):
    PENDENTE = "PENDENTE", "Pendente"
    ANDAMENTO = "ANDAMENTO", "Em andamento"
    BLOQUEADA = "BLOQUEADA", "Bloqueada"
    CONCLUIDA = "CONCLUIDA", "Concluída"
    CANCELADA = "CANCELADA", "Cancelada"


STATUS_ABERTOS = (Status.PENDENTE, Status.ANDAMENTO, Status.BLOQUEADA)


class Prioridade(models.TextChoices):
    CRITICA = "CRITICA", "Crítica"
    ALTA = "ALTA", "Alta"
    MEDIA = "MEDIA", "Média"
    BAIXA = "BAIXA", "Baixa"


class Tipo(models.TextChoices):
    FALTANTE = "FALTANTE", "Item faltante"
    MANUTENCAO = "MANUTENCAO", "Manutenção"
    DEFEITO = "DEFEITO", "Defeito"
    INSPECAO = "INSPECAO", "Inspeção / teste"
    MELHORIA = "MELHORIA", "Melhoria"

class Classe(models.TextChoices):
    BATERIA = 'BATERIA', "Problema no compartimento ou nas baterias"
    MECANICO ='MECANICO', "Problema mecanico."
    ELETRICO = 'ELETRICO', "Problema Eletrico"
    LUZES = 'LUZES', "Problemas nas luzes"


class DemandaQuerySet(models.QuerySet):
    def abertas(self):
        return self.filter(status__in=STATUS_ABERTOS)

    def ordenadas(self):
        """Mais urgentes primeiro: prioridade, depois prazo mais próximo, depois mais novas."""
        peso = Case(
            When(prioridade=Prioridade.CRITICA, then=0),
            When(prioridade=Prioridade.ALTA, then=1),
            When(prioridade=Prioridade.MEDIA, then=2),
            default=3,
            output_field=IntegerField(),
        )
        return self.annotate(_peso=peso).order_by("_peso", F("prazo").asc(nulls_last=True), "-criado_em")


class Demanda(models.Model):
    titulo = models.CharField("título", max_length=160)
    descricao = models.TextField("descrição", blank=True)
    sistema = models.ForeignKey(Sistema, on_delete=models.PROTECT, related_name="demandas")
    tipo = models.CharField(max_length=12, choices=Tipo.choices, default=Tipo.MANUTENCAO)
    prioridade = models.CharField(max_length=8, choices=Prioridade.choices, default=Prioridade.MEDIA)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDENTE, db_index=True)

    item_faltante = models.CharField("item faltante", max_length=160, blank=True,
                                     help_text="O que está faltando (peça, material, ferramenta, licença...).")
    quantidade = models.PositiveIntegerField("quantidade", null=True, blank=True)
    bloqueia_operacao = models.BooleanField(
        "impede o barco de operar", default=False,
        help_text="Marque se o L42 não pode sair enquanto isto não for resolvido.")

    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                                   related_name="demandas_criadas")
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="demandas", verbose_name="responsável")
    prazo = models.DateField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    concluida_em = models.DateTimeField(null=True, blank=True)
    classe = models.CharField(max_length=8, choices=Classe.choices, default="")
    objects = DemandaQuerySet.as_manager()

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "demanda"
        verbose_name_plural = "demandas"
        indexes = [models.Index(fields=["status", "prioridade"])]

    def __str__(self):
        return f"{self.codigo} · {self.titulo}"

    def get_absolute_url(self):
        return reverse("demanda_detalhe", args=[self.pk])

    @property
    def codigo(self):
        return f"L42-{self.pk:04d}" if self.pk else "L42-novo"

    @property
    def aberta(self):
        return self.status in STATUS_ABERTOS

    @property
    def atrasada(self):
        return bool(self.aberta and self.prazo and self.prazo < timezone.localdate())

    def save(self, *args, **kwargs):
        if self.status == Status.CONCLUIDA and not self.concluida_em:
            self.concluida_em = timezone.now()
        elif self.status != Status.CONCLUIDA:
            self.concluida_em = None
        super().save(*args, **kwargs)


class Atualizacao(models.Model):
    """Histórico da demanda: comentários e mudanças de status."""

    demanda = models.ForeignKey(Demanda, on_delete=models.CASCADE, related_name="atualizacoes")
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    texto = models.TextField(blank=True)
    status_anterior = models.CharField(max_length=10, choices=Status.choices, blank=True)
    status_novo = models.CharField(max_length=10, choices=Status.choices, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "atualização"
        verbose_name_plural = "atualizações"

    def __str__(self):
        return f"{self.demanda.codigo} · {self.criado_em:%d/%m %H:%M}"


class StatusMissao(models.TextChoices):
    PREPARACAO = "PREPARACAO", "Em preparação"
    EM_OPERACAO = "EM_OPERACAO", "Em operação"
    PAUSADA = "PAUSADA", "Pausada"
    FINALIZADA = "FINALIZADA", "Finalizada"
    CANCELADA = "CANCELADA", "Cancelada"


class Missao(models.Model):
    titulo = models.CharField("missão", max_length=160)
    objetivo = models.TextField("objetivo", blank=True)
    local = models.CharField("local de operação", max_length=160, blank=True)

    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="missoes_responsavel",
        verbose_name="responsável",
    )

    status = models.CharField(
        max_length=20,
        choices=StatusMissao.choices,
        default=StatusMissao.PREPARACAO,
        db_index=True,
    )

    inicio_previsto = models.DateTimeField(
        "início previsto",
        null=True,
        blank=True,
    )

    inicio = models.DateTimeField(
        "início da operação",
        null=True,
        blank=True,
    )

    fim = models.DateTimeField(
        "fim da operação",
        null=True,
        blank=True,
    )

    observacoes = models.TextField(
        "observações",
        blank=True,
    )

    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="missoes_criadas",
    )

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "missão"
        verbose_name_plural = "missões"

    def __str__(self):
        return f"MISSÃO #{self.pk or 'nova'} · {self.titulo}"

    @property
    def ativa(self):
        return self.status in {
            StatusMissao.PREPARACAO,
            StatusMissao.EM_OPERACAO,
            StatusMissao.PAUSADA,
        }

    @property
    def checklist_total(self):
        return self.checklist.count()

    @property
    def checklist_concluido(self):
        return self.checklist.filter(concluido=True).count()

    @property
    def checklist_percentual(self):
        total = self.checklist_total

        if total == 0:
            return 0

        return round((self.checklist_concluido / total) * 100)


from django.core.exceptions import ValidationError
from django.db import models
import os


def validar_pdf_ou_imagem(arquivo):
    extensoes_permitidas = [".pdf", ".jpg", ".jpeg", ".png", ".webp"]
    ext = os.path.splitext(arquivo.name)[1].lower()
    if ext not in extensoes_permitidas:
        raise ValidationError(
            "Envie um arquivo PDF ou uma imagem (JPG, JPEG, PNG ou WEBP)."
        )


class ChecklistMissao(models.Model):
    missao = models.ForeignKey(
        Missao,
        on_delete=models.CASCADE,
        related_name="checklist",
    )

    item = models.CharField("item", max_length=160)
    concluido = models.BooleanField("concluído", default=False)
    ordem = models.PositiveSmallIntegerField(default=0)
    observacao = models.CharField("observação", max_length=255, blank=True)

    arquivo = models.FileField(
        "arquivo (PDF ou imagem)",
        upload_to="checklist/arquivos/%Y/%m/",
        validators=[validar_pdf_ou_imagem],
        blank=True,
        null=True,
    )

    class Meta:
        ordering = ["ordem", "id"]
        verbose_name = "item do checklist"
        verbose_name_plural = "itens do checklist"

    def __str__(self):
        estado = "OK" if self.concluido else "PENDENTE"
        return f"{self.missao} · {self.item} · {estado}"