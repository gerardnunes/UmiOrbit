import os
import uuid

import openpyxl  # noqa: F401
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Case, F, IntegerField, Q, When
from django.urls import reverse
from django.utils import timezone


# =========================================================
# PERFIL / USUÁRIO
# =========================================================
class Perfil(models.Model):
    class Papel(models.TextChoices):
        TRABALHADOR = "TRABALHADOR", "Trabalhador"
        DIRETOR = "DIRETOR", "Diretor"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="perfil"
    )
    papel = models.CharField(
        max_length=12, choices=Papel.choices, default=Papel.TRABALHADOR
    )
    cargo = models.CharField("cargo / função", max_length=80, blank=True)
    telefone = models.CharField(max_length=30, blank=True)

    aprovado = models.BooleanField(
        default=False,
        help_text="Liberado por um diretor/admin para usar o sistema.",
    )
    aprovado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="perfis_aprovados",
    )
    aprovado_em = models.DateTimeField(null=True, blank=True)

    sistemas = models.ManyToManyField(
        "Sistema",
        blank=True,
        related_name="perfis",
        verbose_name="sistemas que cobre",
    )
    escolheu_sistemas = models.BooleanField(default=False)

    class Meta:
        verbose_name = "perfil"
        verbose_name_plural = "perfis"

    def __str__(self):
        nome = self.user.get_full_name() or self.user.username
        return f"{nome} ({self.get_papel_display()})"

    @property
    def is_diretor(self):
        return self.papel == self.Papel.DIRETOR

    @property
    def sistemas_do_usuario(self):
        return self.sistemas.all()


# =========================================================
# SISTEMAS / EMBARCAÇÕES
# =========================================================
class Sistema(models.Model):
    nome = models.CharField(max_length=80, unique=True)
    descricao = models.CharField("descrição", max_length=200, blank=True)
    ordem = models.PositiveSmallIntegerField(default=0)
    ativo = models.BooleanField(default=True)

    imo = models.CharField("IMO", max_length=20, blank=True)
    mmsi = models.CharField("MMSI", max_length=20, blank=True)
    base = models.CharField("base", max_length=80, blank=True)

    class Meta:
        ordering = ["ordem", "nome"]
        verbose_name = "sistema / embarcação"
        verbose_name_plural = "sistemas / embarcações"

    def __str__(self):
        return self.nome


# =========================================================
# ENUMS DE DEMANDA
# =========================================================
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
    BATERIA = "BATERIA", "Problema no compartimento ou nas baterias"
    MECANICO = "MECANICO", "Problema mecânico."
    ELETRICO = "ELETRICO", "Problema elétrico"
    LUZES = "LUZES", "Problemas nas luzes"


# =========================================================
# DEMANDA
# =========================================================
class DemandaQuerySet(models.QuerySet):
    def abertas(self):
        return self.filter(status__in=STATUS_ABERTOS)

    def ordenadas(self):
        peso = Case(
            When(prioridade=Prioridade.CRITICA, then=0),
            When(prioridade=Prioridade.ALTA, then=1),
            When(prioridade=Prioridade.MEDIA, then=2),
            default=3,
            output_field=IntegerField(),
        )
        return self.annotate(_peso=peso).order_by(
            "_peso", F("prazo").asc(nulls_last=True), "-criado_em"
        )

    def do_usuario(self, user):
        if not user.is_authenticated:
            return self.none()
        perfil = getattr(user, "perfil", None)
        if user.is_superuser or (perfil and perfil.is_diretor):
            return self
        if not perfil:
            return self.none()
        return self.filter(sistema__in=perfil.sistemas.all())


class Demanda(models.Model):
    missao = models.ForeignKey(
        "Missao",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="demandas",
        verbose_name="missão",
        help_text="Opcional. Vincule se esta demanda pertence a uma missão em curso.",
    )
    titulo = models.CharField("título", max_length=160)
    descricao = models.TextField("descrição", blank=True)
    sistema = models.ForeignKey(
        Sistema, on_delete=models.PROTECT, related_name="demandas"
    )
    tipo = models.CharField(
        max_length=12, choices=Tipo.choices, default=Tipo.MANUTENCAO
    )
    prioridade = models.CharField(
        max_length=8, choices=Prioridade.choices, default=Prioridade.MEDIA
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDENTE,
        db_index=True,
    )

    item_faltante = models.CharField(
        "item faltante",
        max_length=160,
        blank=True,
        help_text="O que está faltando (peça, material, ferramenta, licença...).",
    )
    quantidade = models.PositiveIntegerField("quantidade", null=True, blank=True)
    bloqueia_operacao = models.BooleanField(
        "impede o barco de operar",
        default=False,
        help_text="Marque se o L42 não pode sair enquanto isto não for resolvido.",
    )

    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="demandas_criadas",
    )
    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="demandas",
        verbose_name="responsável",
    )
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
        indexes = [
            models.Index(fields=["status", "prioridade"]),
            models.Index(fields=["sistema", "status"]),
        ]

    def __str__(self):
        return f"{self.codigo} · {self.titulo}"

    def get_absolute_url(self):
        return reverse("demanda_detalhe", args=[self.pk])

    @property
    def codigo(self):
        if not self.pk:
            return "L42-novo"
        prefixo = (self.sistema.nome[:3].upper() if self.sistema else "L42")
        return f"{prefixo}-{self.pk:04d}"

    @property
    def aberta(self):
        return self.status in STATUS_ABERTOS

    @property
    def atrasada(self):
        return bool(
            self.aberta and self.prazo and self.prazo < timezone.localdate()
        )

    def save(self, *args, **kwargs):
        if self.status == Status.CONCLUIDA and not self.concluida_em:
            self.concluida_em = timezone.now()
        elif self.status != Status.CONCLUIDA:
            self.concluida_em = None
        super().save(*args, **kwargs)


class Atualizacao(models.Model):
    demanda = models.ForeignKey(
        Demanda, on_delete=models.CASCADE, related_name="atualizacoes"
    )
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
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


# =========================================================
# MISSÃO
# =========================================================
class StatusMissao(models.TextChoices):
    PREPARACAO = "PREPARACAO", "Em preparação"
    EM_OPERACAO = "EM_OPERACAO", "Em operação"
    PAUSADA = "PAUSADA", "Pausada"
    FINALIZADA = "FINALIZADA", "Finalizada"
    CANCELADA = "CANCELADA", "Cancelada"


class MissaoQuerySet(models.QuerySet):
    def do_usuario(self, user):
        if not user.is_authenticated:
            return self.none()
        perfil = getattr(user, "perfil", None)
        if user.is_superuser or (perfil and perfil.is_diretor):
            return self
        if not perfil:
            return self.none()
        return self.filter(sistema__in=perfil.sistemas.all())


class Missao(models.Model):
    sistema = models.ForeignKey(
        Sistema,
        on_delete=models.PROTECT,
        related_name="missoes",
        verbose_name="sistema / embarcação",
        help_text="Embarcação ou veículo desta missão.",
    )
    titulo = models.CharField("missão", max_length=160)
    objetivo = models.TextField("objetivo", blank=True)
    local = models.CharField("local de operação", max_length=160, blank=True)

    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
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

    inicio_previsto = models.DateTimeField("início previsto", null=True, blank=True)
    inicio = models.DateTimeField("início da operação", null=True, blank=True)
    fim = models.DateTimeField("fim da operação", null=True, blank=True)

    observacoes = models.TextField("observações", blank=True)

    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="missoes_criadas",
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    objects = MissaoQuerySet.as_manager()

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "missão"
        verbose_name_plural = "missões"
        indexes = [models.Index(fields=["sistema", "status"])]

    def __str__(self):
        return f"MISSÃO #{self.pk or 'nova'} · {self.titulo}"

    @property
    def ativa(self):
        return self.status in {
            StatusMissao.PREPARACAO,
            StatusMissao.EM_OPERACAO,
            StatusMissao.PAUSADA,
        }


# =========================================================
# CHECKLIST ANTIGO
# =========================================================
def validar_pdf_ou_imagem(arquivo):
    extensoes_permitidas = [".pdf", ".jpg", ".jpeg", ".png", ".webp"]
    ext = os.path.splitext(arquivo.name)[1].lower()
    if ext not in extensoes_permitidas:
        raise ValidationError(
            "Envie um arquivo PDF ou uma imagem (JPG, JPEG, PNG ou WEBP)."
        )


class ChecklistMissao(models.Model):
    missao = models.ForeignKey(
        Missao, on_delete=models.CASCADE, related_name="checklist"
    )
    item = models.CharField("item", max_length=160)
    concluido = models.BooleanField("concluído", default=False)
    ordem = models.PositiveSmallIntegerField(default=0)
    observacao = models.CharField("observação", max_length=255, blank=True)
    arquivo = models.FileField(
        "arquivo (PDF ou imagem)",
        upload_to="checklist/arquivos/%Y/%m/",
        validators=[validar_pdf_ou_imagem],
        blank=True, null=True,
    )

    class Meta:
        ordering = ["ordem", "id"]
        verbose_name = "item do checklist"
        verbose_name_plural = "itens do checklist"

    def __str__(self):
        return f"{self.missao} · {self.item}"


# =========================================================
# CHECKLIST NOVO
# =========================================================
class ChecklistQuerySet(models.QuerySet):
    def do_usuario(self, user):
        if not user.is_authenticated:
            return self.none()
        perfil = getattr(user, "perfil", None)
        if user.is_superuser or (perfil and perfil.is_diretor):
            return self
        if not perfil:
            return self.none()
        return self.filter(
            Q(sistema__in=perfil.sistemas.all())
            | Q(missao__sistema__in=perfil.sistemas.all())
        )


class Checklist(models.Model):
    class Status(models.TextChoices):
        RASCUNHO = "RASCUNHO", "Rascunho"
        ATIVO = "ATIVO", "Ativo"
        CONCLUIDO = "CONCLUIDO", "Concluído"
        ARQUIVADO = "ARQUIVADO", "Arquivado"

    titulo = models.CharField(max_length=200)
    descricao = models.TextField(blank=True)

    sistema = models.ForeignKey(
        Sistema,
        on_delete=models.PROTECT,
        related_name="checklists",
        verbose_name="sistema / embarcação",
        null=True, blank=True,
        help_text="Se não vincular a missão, escolha o sistema direto.",
    )
    missao = models.ForeignKey(
        Missao,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="checklists",
    )

    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.RASCUNHO
    )
    token_auditoria = models.UUIDField(
        default=uuid.uuid4, unique=True, editable=False, db_index=True,
    )
    exige_login_auditoria = models.BooleanField(
        default=True,
        help_text="Se desmarcado, o link de auditoria abre sem login.",
    )

    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="checklists_criados",
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    objects = ChecklistQuerySet.as_manager()

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "checklist"
        verbose_name_plural = "checklists"

    def __str__(self):
        return self.titulo

    def get_absolute_url(self):
        return reverse("checklist_detalhe", args=[self.pk])

    def save(self, *args, **kwargs):
        if not self.sistema_id and self.missao_id:
            self.sistema = self.missao.sistema
        super().save(*args, **kwargs)

    @property
    def total(self):
        return self.itens.count()

    @property
    def feitos(self):
        return self.itens.filter(concluido=True).count()

    @property
    def pct(self):
        return self.feitos * 100 // self.total if self.total else 0


class ChecklistItem(models.Model):
    class Prioridade(models.TextChoices):
        BAIXA = "BAIXA", "Baixa"
        MEDIA = "MEDIA", "Média"
        ALTA = "ALTA", "Alta"
        CRITICA = "CRITICA", "Crítica"

    checklist = models.ForeignKey(
        Checklist, on_delete=models.CASCADE, related_name="itens"
    )
    ordem = models.PositiveIntegerField(default=0)
    titulo = models.CharField(max_length=255)
    descricao = models.TextField(blank=True)

    sistema = models.ForeignKey(
        Sistema,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="checklist_itens",
        verbose_name="sistema / equipamento",
    )
    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="checklist_itens",
    )
    prioridade = models.CharField(
        max_length=10, choices=Prioridade.choices, default=Prioridade.MEDIA
    )

    concluido = models.BooleanField(default=False)
    concluido_em = models.DateTimeField(null=True, blank=True)
    concluido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="checklist_itens_concluidos",
    )
    observacao = models.TextField(blank=True)

    class Meta:
        ordering = ["ordem", "id"]

    def __str__(self):
        return f"{self.ordem}. {self.titulo}"


def caminho_foto(instance, filename):
    return f"checklists/{instance.item.checklist_id}/{instance.item_id}/{filename}"


class ChecklistItemFoto(models.Model):
    item = models.ForeignKey(
        ChecklistItem, on_delete=models.CASCADE, related_name="fotos"
    )
    imagem = models.ImageField(upload_to=caminho_foto)
    legenda = models.CharField(max_length=200, blank=True)
    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="checklist_fotos",
    )
    enviado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-enviado_em"]

    def __str__(self):
        return f"Foto de {self.item}"


class ChecklistItemEvento(models.Model):
    class Tipo(models.TextChoices):
        CRIADO = "CRIADO", "Item criado"
        CONCLUIDO = "CONCLUIDO", "Item concluído"
        REABERTO = "REABERTO", "Item reaberto"
        OBSERVACAO = "OBSERVACAO", "Observação alterada"
        FOTO = "FOTO", "Foto anexada"
        FOTO_REMOVIDA = "FOTO_REMOVIDA", "Foto removida"

    item = models.ForeignKey(
        ChecklistItem, on_delete=models.CASCADE, related_name="eventos"
    )
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="checklist_eventos",
    )
    texto = models.TextField(blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.get_tipo_display()} · {self.item}"


class ChecklistImportacao(models.Model):
    checklist = models.ForeignKey(
        Checklist, on_delete=models.CASCADE, related_name="importacoes"
    )
    arquivo = models.FileField(upload_to="checklists/importacoes/%Y/%m/")
    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
    )
    enviado_em = models.DateTimeField(auto_now_add=True)
    linhas_lidas = models.PositiveIntegerField(default=0)
    linhas_criadas = models.PositiveIntegerField(default=0)
    erros = models.TextField(blank=True)

    class Meta:
        ordering = ["-enviado_em"]

    def __str__(self):
        return f"Import {self.pk} → {self.checklist}"


# =========================================================
# INCIDENTES
# =========================================================
class IncidenteSeveridade(models.TextChoices):
    CRITICO = "critico", "Crítico"
    ALTO    = "alto",    "Alto"
    MEDIO   = "medio",   "Médio"
    BAIXO   = "baixo",   "Baixo"


class IncidenteStatus(models.TextChoices):
    ABERTO            = "aberto",            "Aberto"
    EM_ANALISE        = "em_analise",        "Em análise"
    EM_REPARO         = "em_reparo",         "Em reparo"
    AGUARDANDO_PECA   = "aguardando_peca",   "Aguardando peça"
    RESOLVIDO         = "resolvido",         "Resolvido"
    CANCELADO         = "cancelado",         "Cancelado"


class IncidenteTipo(models.TextChoices):
    AVARIA          = "avaria",          "Avaria"
    COLISAO         = "colisao",         "Colisão"
    FALHA_SISTEMA   = "falha_sistema",   "Falha de sistema"
    QUASE_ACIDENTE  = "quase_acidente",  "Quase-acidente"
    OUTRO           = "outro",           "Outro"


class IncidenteQuerySet(models.QuerySet):
    def do_usuario(self, user):
        if not user.is_authenticated:
            return self.none()
        perfil = getattr(user, "perfil", None)
        if user.is_superuser or (perfil and perfil.is_diretor):
            return self
        if not perfil:
            return self.none()
        return self.filter(sistema__in=perfil.sistemas.all())


class Incidente(models.Model):
    codigo          = models.CharField(max_length=20, unique=True, editable=False)
    titulo          = models.CharField(max_length=200)
    tipo            = models.CharField(
        max_length=20, choices=IncidenteTipo.choices,
        default=IncidenteTipo.AVARIA,
    )
    severidade      = models.CharField(
        max_length=10, choices=IncidenteSeveridade.choices,
        default=IncidenteSeveridade.MEDIO,
    )
    status          = models.CharField(
        max_length=20, choices=IncidenteStatus.choices,
        default=IncidenteStatus.ABERTO,
    )

    embarcacao      = models.CharField(max_length=80, blank=True)
    sistema         = models.ForeignKey(
        Sistema,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="incidentes",
        verbose_name="sistema / embarcação",
        help_text="Selecione o sistema/embarcação afetado.",
    )
    local           = models.CharField(max_length=80, blank=True)

    bloqueia_operacao = models.BooleanField(
        "impede o barco de operar",
        default=False,
        help_text="Marque se o L42 não pode sair enquanto isto não for resolvido.",
    )

    descricao       = models.TextField()
    acao_tomada     = models.TextField(blank=True)
    causa_provavel  = models.TextField(blank=True)

    responsavel     = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="incidentes",
    )
    criado_por      = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="incidentes_criados",
    )
    ocorrido_em     = models.DateTimeField(default=timezone.now)
    criado_em       = models.DateTimeField(auto_now_add=True)
    atualizado_em   = models.DateTimeField(auto_now=True)
    resolvido_em    = models.DateTimeField(null=True, blank=True)

    token           = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    objects = IncidenteQuerySet.as_manager()

    class Meta:
        ordering = ["-ocorrido_em"]
        verbose_name = "Incidente"
        verbose_name_plural = "Incidentes"
        indexes = [models.Index(fields=["sistema", "status"])]

    def save(self, *args, **kwargs):
        if not self.codigo:
            prefixo = (self.sistema.nome[:3].upper() if self.sistema else "INC")
            ultimo = (
                Incidente.objects
                .filter(codigo__startswith=f"{prefixo}-")
                .order_by("-id")
                .values_list("codigo", flat=True)
                .first()
            )
            proximo = 1
            if ultimo:
                try:
                    proximo = int(ultimo.split("-")[1]) + 1
                except (IndexError, ValueError):
                    proximo = Incidente.objects.count() + 1
            self.codigo = f"{prefixo}-{proximo:04d}"

        if self.status == IncidenteStatus.RESOLVIDO and not self.resolvido_em:
            self.resolvido_em = timezone.now()

        super().save(*args, **kwargs)

    @property
    def mttr_horas(self):
        if not self.resolvido_em:
            return None
        delta = self.resolvido_em - self.ocorrido_em
        return round(delta.total_seconds() / 3600, 2)

    @property
    def esta_aberto(self):
        return self.status not in (
            IncidenteStatus.RESOLVIDO,
            IncidenteStatus.CANCELADO,
        )

    def get_absolute_url(self):
        return reverse("incidente_detalhe", args=[self.pk])

    def __str__(self):
        return f"{self.codigo} · {self.titulo}"


class IncidenteEvento(models.Model):
    class Tipo(models.TextChoices):
        CRIADO      = "criado",      "Criado"
        COMENTARIO  = "comentario",  "Comentário"
        STATUS      = "status",      "Mudança de status"
        SEVERIDADE  = "severidade",  "Mudança de severidade"
        RESPONSAVEL = "responsavel", "Mudança de responsável"
        ANEXO       = "anexo",       "Anexo adicionado"

    incidente = models.ForeignKey(
        Incidente, on_delete=models.CASCADE, related_name="eventos"
    )
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    texto = models.TextField(blank=True)
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL,
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.incidente.codigo} · {self.get_tipo_display()}"


class IncidenteAnexo(models.Model):
    incidente = models.ForeignKey(
        Incidente, on_delete=models.CASCADE, related_name="anexos"
    )
    imagem = models.FileField(upload_to="incidentes/anexos/%Y/%m/")
    legenda = models.CharField(max_length=200, blank=True)
    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL,
    )
    enviado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-enviado_em"]


# =========================================================
# TELEMETRIA (guinchos, posição, propulsor)
# =========================================================
class LeituraGuincho(models.Model):
    """Cada leitura dos guinchos (portas 7 e 8)."""
    class Tipo(models.TextChoices):
        TRACAO = "TRACAO", "Tração"
        SVP = "SVP", "SVP"

    sistema = models.ForeignKey(
        Sistema, on_delete=models.CASCADE, related_name="leituras_guincho"
    )
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)

    # Tração (porta 7)
    max_rope_len = models.FloatField(null=True, blank=True)
    remain_min_rope_len = models.FloatField(null=True, blank=True)
    sensor_once_rope_len = models.FloatField(null=True, blank=True)
    winch_acc_speed_ratio = models.FloatField(null=True, blank=True)
    winch_turn_rate_value = models.FloatField(null=True, blank=True)

    # SVP (porta 8)
    current_temp = models.FloatField(null=True, blank=True)      # °C
    current_vol = models.FloatField(null=True, blank=True)       # V
    current_ele = models.FloatField(null=True, blank=True)       # A
    current_pull = models.FloatField(null=True, blank=True)      # força
    rope_speed = models.FloatField(null=True, blank=True)        # m/s
    pull_rope_len = models.FloatField(null=True, blank=True)     # m
    winch_rate = models.FloatField(null=True, blank=True)
    current_work_status = models.IntegerField(null=True, blank=True)
    warn = models.CharField(max_length=200, blank=True)
    sys_time = models.CharField(max_length=40, blank=True)

    raw_json = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "leitura de guincho"
        verbose_name_plural = "leituras de guincho"
        indexes = [models.Index(fields=["sistema", "tipo", "-criado_em"])]

    def __str__(self):
        return f"{self.get_tipo_display()} · {self.criado_em:%d/%m %H:%M:%S}"


class LeituraPosicao(models.Model):
    """Posição do barco (frame usv_xy_3d_id)."""
    sistema = models.ForeignKey(
        Sistema, on_delete=models.CASCADE, related_name="leituras_posicao"
    )
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)

    x = models.FloatField(help_text="metros, frame local")
    y = models.FloatField(help_text="metros, frame local")
    z = models.FloatField(default=0.0)
    qw = models.FloatField(default=1.0, help_text="quaternion w (1.0 = sem rotação)")
    timestamp_msg = models.FloatField(help_text="timestamp da mensagem (epoch)")

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "leitura de posição"
        verbose_name_plural = "leituras de posição"
        indexes = [models.Index(fields=["sistema", "-criado_em"])]

    def __str__(self):
        return f"({self.x:.3f}, {self.y:.3f}) · {self.criado_em:%H:%M:%S}"


class LeituraPropulsor(models.Model):
    """Comando de propulsão/leme (tópico 50101_142004)."""
    sistema = models.ForeignKey(
        Sistema, on_delete=models.CASCADE, related_name="leituras_propulsor"
    )
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)

    steer = models.FloatField(null=True, blank=True, help_text="comando de leme")
    modo = models.FloatField(null=True, blank=True, help_text="valor do modo/prop (float)")
    timestamp_msg = models.FloatField(help_text="timestamp da mensagem (epoch)")

    # timestamps individuais dos atuadores
    ts_atuador_1 = models.BigIntegerField(null=True, blank=True)
    ts_atuador_2 = models.BigIntegerField(null=True, blank=True)
    ts_atuador_3 = models.BigIntegerField(null=True, blank=True)
    ts_atuador_4 = models.BigIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "leitura de propulsor"
        verbose_name_plural = "leituras de propulsor"
        indexes = [models.Index(fields=["sistema", "-criado_em"])]

    def __str__(self):
        return f"steer={self.steer} · {self.criado_em:%H:%M:%S}"

class OrigemGPS(models.Model):
    """Última posição GPS conhecida do barco (atualizada automaticamente)."""
    sistema = models.OneToOneField(
        Sistema, on_delete=models.CASCADE, related_name="origem_gps"
    )
    lat = models.FloatField()
    lon = models.FloatField()
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "origem GPS"
        verbose_name_plural = "origens GPS"

    def __str__(self):
        return f"{self.sistema.nome}: ({self.lat:.5f}, {self.lon:.5f})"

class RadarDetectado(models.Model):
    """Posição de um radar/obstáculo detectado."""
    sistema = models.ForeignKey(Sistema, on_delete=models.CASCADE, related_name="radares")
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)
    
    nome = models.CharField(max_length=50)
    x = models.FloatField(help_text="metros (X local)")
    y = models.FloatField(help_text="metros (Y local)")
    distancia = models.FloatField(help_text="metros")
    azimute = models.FloatField(help_text="graus")
    timestamp = models.FloatField()
    qualidade = models.FloatField(default=0.0)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "radar detectado"
        verbose_name_plural = "radares detectados"

class OrigemGPS(models.Model):
    """Última posição GPS conhecida do barco."""
    sistema = models.OneToOneField(
        Sistema, on_delete=models.CASCADE, related_name="origem_gps"
    )
    lat = models.FloatField()
    lon = models.FloatField()
    atualizado_em = models.DateTimeField(auto_now=True)


class RadarDetectado(models.Model):
    """Posição de um radar/obstáculo detectado."""
    sistema = models.ForeignKey(Sistema, on_delete=models.CASCADE, related_name="radares")
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)
    
    nome = models.CharField(max_length=50)
    x = models.FloatField(help_text="metros (X local)")
    y = models.FloatField(help_text="metros (Y local)")
    distancia = models.FloatField(help_text="metros")
    azimute = models.FloatField(help_text="graus")
    timestamp = models.FloatField()
    qualidade = models.FloatField(default=0.0)
from django.conf import settings
from django.db import models
from django.urls import reverse


class MissionPlan(models.Model):
    """Plano detalhado de uma missão: área, parâmetros e rota."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Rascunho"
        PLANNED = "PLANNED", "Planejada"
        UNDER_RISK_ANALYSIS = "UNDER_RISK_ANALYSIS", "Em análise de risco"
        APPROVED = "APPROVED", "Aprovada"
        IN_PROGRESS = "IN_PROGRESS", "Em execução"
        COMPLETED = "COMPLETED", "Concluída"
        ABORTED = "ABORTED", "Abortada"

    class PadraoRota(models.TextChoices):
        LAWN_MOWER = "LAWN_MOWER", "Lawn Mower (varredura)"
        WAYPOINTS = "WAYPOINTS", "Waypoints"

    missao = models.ForeignKey(
        "Missao", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="planos",
    )
    sistema = models.ForeignKey(
        "Sistema", on_delete=models.PROTECT, related_name="mission_plans",
    )

    nome = models.CharField(max_length=160)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT,
    )
    padrao_rota = models.CharField(
        max_length=20, choices=PadraoRota.choices,
        default=PadraoRota.LAWN_MOWER,
    )

    area_geojson = models.JSONField(
        default=dict, blank=True,
        help_text="Polígono GeoJSON (Feature ou Geometry) da área de operação.",
    )

    partida_lat = models.FloatField(null=True, blank=True)
    partida_lon = models.FloatField(null=True, blank=True)
    chegada_lat = models.FloatField(null=True, blank=True)
    chegada_lon = models.FloatField(null=True, blank=True)

    velocidade_planejada_nos = models.FloatField(
        default=3.0, help_text="Velocidade planejada em nós.",
    )
    espacamento_linhas_m = models.FloatField(
        default=50.0, help_text="Distância entre linhas de varredura, em metros.",
    )
    sobreposicao_pct = models.FloatField(
        default=0.0, help_text="Sobreposição entre faixas (0 a 100).",
    )
    margem_seguranca_m = models.FloatField(
        default=10.0, help_text="Margem de segurança em relação a obstáculos.",
    )
    angulo_linhas_graus = models.FloatField(
        default=0.0, help_text="0 = automático (eixo maior do polígono).",
    )

    distancia_total_m = models.FloatField(default=0.0)
    tempo_estimado_min = models.FloatField(default=0.0)
    area_cobertura_m2 = models.FloatField(default=0.0)
    n_waypoints = models.PositiveIntegerField(default=0)

    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name="mission_plans_criados",
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "plano de missão"
        verbose_name_plural = "planos de missão"
        indexes = [models.Index(fields=["sistema", "status"])]

    def __str__(self):
        return f"Plano #{self.pk} · {self.nome}"

    def get_absolute_url(self):
        return reverse("mission_planner:plan_detail", args=[self.pk])


class Route(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Rascunho"
        PLANNED = "PLANNED", "Planejada"
        ACTIVE = "ACTIVE", "Ativa"
        EXECUTED = "EXECUTED", "Executada"
        CANCELLED = "CANCELLED", "Cancelada"

    plano = models.ForeignKey(
        MissionPlan, on_delete=models.CASCADE, related_name="rotas",
    )
    nome = models.CharField(max_length=160, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PLANNED,
    )

    geometria_geojson = models.JSONField(
        default=dict, blank=True,
        help_text="LineString GeoJSON da rota.",
    )

    distancia_total_m = models.FloatField(default=0.0)
    tempo_estimado_min = models.FloatField(default=0.0)

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-criado_em"]

    def __str__(self):
        return f"Rota #{self.pk} · {self.plano.nome}"


class Waypoint(models.Model):
    class Tipo(models.TextChoices):
        PARTIDA = "PARTIDA", "Partida"
        NAVEGACAO = "NAVEGACAO", "Navegação"
        VIRAGEM = "VIRAGEM", "Viragem"
        CHEGADA = "CHEGADA", "Chegada"

    rota = models.ForeignKey(
        Route, on_delete=models.CASCADE, related_name="waypoints",
    )
    ordem = models.PositiveIntegerField(default=0)
    lat = models.FloatField()
    lon = models.FloatField()
    tipo = models.CharField(
        max_length=20, choices=Tipo.choices, default=Tipo.NAVEGACAO,
    )
    rotulo = models.CharField(max_length=80, blank=True)
    velocidade_nos = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["ordem", "id"]

    def __str__(self):
        return f"{self.ordem}. ({self.lat:.5f}, {self.lon:.5f})"


class RouteSegment(models.Model):
    rota = models.ForeignKey(
        Route, on_delete=models.CASCADE, related_name="segmentos",
    )
    ordem = models.PositiveIntegerField(default=0)
    waypoint_inicio = models.ForeignKey(
        Waypoint, on_delete=models.CASCADE, related_name="segmentos_saida",
    )
    waypoint_fim = models.ForeignKey(
        Waypoint, on_delete=models.CASCADE, related_name="segmentos_entrada",
    )

    distancia_m = models.FloatField(default=0.0)
    tempo_estimado_min = models.FloatField(default=0.0)
    rumo_graus = models.FloatField(default=0.0)

    risco_pct = models.FloatField(null=True, blank=True)
    risco_classificacao = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["ordem", "id"]

    def __str__(self):
        return f"Segmento {self.ordem} · {self.distancia_m:.0f} m"


class StatusBateria(models.Model):
    sistema = models.ForeignKey(Sistema, on_delete=models.CASCADE, related_name="baterias")
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)
    temperatura = models.FloatField(null=True, blank=True)
    celulas = models.IntegerField(null=True, blank=True)
    contador = models.FloatField(null=True, blank=True)

class StatusLuz(models.Model):
    sistema = models.ForeignKey(Sistema, on_delete=models.CASCADE, related_name="luzes")
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)
    nome = models.CharField(max_length=100)
    status = models.IntegerField(help_text="0 = OFF, >0 = ON")