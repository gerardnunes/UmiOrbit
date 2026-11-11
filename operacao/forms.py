from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from .models import (
    Checklist,
    ChecklistImportacao,
    Demanda,
    Incidente,
    IncidenteAnexo,
    IncidenteEvento,
    IncidenteSeveridade,
    IncidenteStatus,
    IncidenteTipo,
    Missao,
    MissionPlan,      # <-- adicionar
    Perfil,
    Prioridade,
    Route,            # <-- adicionar
    Sistema,
    Status,
    StatusMissao,
    Tipo,
    Waypoint,         # <-- adicionar
)


User = get_user_model()


# =========================================================
# HELPERS
# =========================================================
def _sistemas_do_usuario(user, incluir_inativos=False):
    """Sistemas visíveis ao usuário (admin vê todos)."""
    if user is None or not user.is_authenticated:
        return Sistema.objects.none()

    base = Sistema.objects.all() if incluir_inativos else Sistema.objects.filter(ativo=True)
    perfil = getattr(user, "perfil", None)

    if user.is_superuser or (perfil and perfil.is_diretor):
        return base
    if perfil:
        return base.filter(pk__in=perfil.sistemas.values("pk"))
    return Sistema.objects.none()


def _equipe_ativa():
    """Quem pode receber demandas: ativos, exceto diretores."""
    return (
        User.objects.filter(is_active=True)
        .exclude(perfil__papel=Perfil.Papel.DIRETOR)
        .order_by("first_name", "username")
    )


# =========================================================
# DEMANDA
# =========================================================
class DemandaForm(forms.ModelForm):
    class Meta:
        model = Demanda
        fields = [
            "titulo",
            "tipo",
            "classe",
            "sistema",
            "missao",
            "prioridade",
            "item_faltante",
            "quantidade",
            "bloqueia_operacao",
            "descricao",
            "responsavel",
            "prazo",
            "status",
        ]
        widgets = {
            "descricao": forms.Textarea(attrs={"rows": 5}),
            "prazo": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        # ----- Sistema -----
        if self.user is not None:
            sistemas_qs = _sistemas_do_usuario(self.user)
            self.fields["sistema"].queryset = sistemas_qs
            if sistemas_qs.count() == 1:
                self.fields["sistema"].initial = sistemas_qs.first()
        self.fields["sistema"].required = True

        # ----- Missão -----
        qs_missao = Missao.objects.filter(
            status__in=[
                StatusMissao.PREPARACAO,
                StatusMissao.EM_OPERACAO,
                StatusMissao.PAUSADA,
            ]
        )
        if self.user is not None:
            qs_missao = qs_missao.filter(sistema__in=_sistemas_do_usuario(self.user))

        # Mantém a missão atual no qs se estiver editando
        if self.instance and self.instance.pk and self.instance.missao_id:
            qs_missao = Missao.objects.filter(
                Q(pk=self.instance.missao_id) | Q(pk__in=qs_missao.values("pk"))
            ).order_by("-criado_em")

        self.fields["missao"].queryset = qs_missao.order_by("-criado_em")
        self.fields["missao"].required = False
        self.fields["missao"].empty_label = "— Sem missão (por fora) —"

        # ----- Responsável -----
        self.fields["responsavel"].queryset = _equipe_ativa()
        self.fields["responsavel"].label_from_instance = (
            lambda u: u.get_full_name() or u.username
        )
        self.fields["responsavel"].empty_label = "Ninguém ainda"

        # ----- Status -----
        if not self.instance.pk:
            self.fields.pop("status", None)

    def clean(self):
        dados = super().clean()
        if dados.get("tipo") == Tipo.FALTANTE and not dados.get("item_faltante"):
            self.add_error("item_faltante", "Diga qual item está faltando.")
        return dados


# =========================================================
# ATUALIZAÇÃO
# =========================================================
class AtualizacaoForm(forms.Form):
    status = forms.ChoiceField(
        label="Novo status",
        required=False,
        choices=[("", "Manter status atual")] + list(Status.choices),
    )
    texto = forms.CharField(
        label="Comentário",
        required=False,
        widget=forms.Textarea(attrs={
            "rows": 3,
            "placeholder": "O que foi feito, o que falta, o que bloqueia...",
        }),
    )

    def clean(self):
        dados = super().clean()
        if not dados.get("status") and not (dados.get("texto") or "").strip():
            raise forms.ValidationError(
                "Escreva um comentário ou escolha um novo status."
            )
        return dados


# =========================================================
# FILTRO DE DEMANDA
# =========================================================
class FiltroDemandaForm(forms.Form):
    q = forms.CharField(
        required=False, label="Buscar",
        widget=forms.TextInput(attrs={"placeholder": "Título, item, código..."}),
    )
    status = forms.ChoiceField(
        required=False, label="Status",
        choices=[("", "Todos"), ("ABERTAS", "Em aberto")] + list(Status.choices),
    )
    prioridade = forms.ChoiceField(
        required=False, label="Prioridade",
        choices=[("", "Todas")] + list(Prioridade.choices),
    )
    tipo = forms.ChoiceField(
        required=False, label="Tipo",
        choices=[("", "Todos")] + list(Tipo.choices),
    )
    sistema = forms.ModelChoiceField(
        required=False, label="Sistema",
        queryset=Sistema.objects.none(),
        empty_label="Todos",
    )
    responsavel = forms.ModelChoiceField(
        required=False, label="Responsável",
        queryset=User.objects.none(),
        empty_label="Todos",
    )
    atrasadas = forms.BooleanField(required=False, label="Só atrasadas")

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        self.fields["responsavel"].queryset = (
            User.objects.filter(is_active=True)
            .order_by("first_name", "username")
        )
        self.fields["responsavel"].label_from_instance = (
            lambda u: u.get_full_name() or u.username
        )

        # Sistema: se user foi passado, filtra; senão, todos os ativos
        if self.user is not None:
            self.fields["sistema"].queryset = _sistemas_do_usuario(self.user)
        else:
            self.fields["sistema"].queryset = Sistema.objects.filter(ativo=True)


# =========================================================
# USUÁRIO / PERFIL
# =========================================================
class UsuarioForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]
        labels = {
            "first_name": "Nome",
            "last_name": "Sobrenome",
            "email": "E-mail",
        }


class PerfilForm(forms.ModelForm):
    class Meta:
        model = Perfil
        fields = ["cargo", "telefone"]


# =========================================================
# MISSÃO
# =========================================================
class MissaoForm(forms.ModelForm):
    class Meta:
        model = Missao
        fields = (
            "sistema",
            "titulo",
            "objetivo",
            "local",
            "responsavel",
            "status",
            "inicio_previsto",
            "observacoes",
        )
        widgets = {
            "titulo": forms.TextInput(attrs={
                "placeholder": "Ex.: Levantamento hidrográfico — Porto do Açu",
            }),
            "objetivo": forms.Textarea(attrs={
                "rows": 4,
                "placeholder": "Descreva o objetivo da missão...",
            }),
            "local": forms.TextInput(attrs={
                "placeholder": "Ex.: Porto do Açu",
            }),
            "inicio_previsto": forms.DateTimeInput(attrs={
                "type": "datetime-local",
            }),
            "observacoes": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": "Observações operacionais...",
            }),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        if self.user is not None:
            sistemas_qs = _sistemas_do_usuario(self.user)
            self.fields["sistema"].queryset = sistemas_qs
            if sistemas_qs.count() == 1:
                self.fields["sistema"].initial = sistemas_qs.first()

        self.fields["sistema"].required = True


# =========================================================
# CHECKLIST
# =========================================================
class ChecklistForm(forms.ModelForm):
    class Meta:
        model = Checklist
        fields = ["titulo", "descricao", "sistema", "missao", "status"]
        widgets = {
            "descricao": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        if self.user is not None:
            sistemas_qs = _sistemas_do_usuario(self.user)
            self.fields["sistema"].queryset = sistemas_qs
            if sistemas_qs.count() == 1:
                self.fields["sistema"].initial = sistemas_qs.first()

            qs_missao = Missao.objects.filter(
                sistema__in=_sistemas_do_usuario(self.user),
                status__in=[
                    StatusMissao.PREPARACAO,
                    StatusMissao.EM_OPERACAO,
                    StatusMissao.PAUSADA,
                ],
            ).order_by("-criado_em")
        else:
            qs_missao = Missao.objects.filter(
                status__in=[
                    StatusMissao.PREPARACAO,
                    StatusMissao.EM_OPERACAO,
                    StatusMissao.PAUSADA,
                ],
            ).order_by("-criado_em")

        # Mantém a missão atual no qs se estiver editando
        if self.instance and self.instance.pk and self.instance.missao_id:
            qs_missao = Missao.objects.filter(
                Q(pk=self.instance.missao_id) | Q(pk__in=qs_missao.values("pk"))
            ).order_by("-criado_em")

        self.fields["missao"].queryset = qs_missao
        self.fields["sistema"].required = False
        self.fields["missao"].required = False


class ChecklistImportForm(forms.Form):
    arquivo = forms.FileField(
        label="Planilha Excel (.xlsx)",
        help_text=(
            "Colunas esperadas: Ordem, Título, Descrição, Sistema, "
            "Prioridade, Responsável. "
            "A coluna 'Sistema' da planilha é IGNORADA — "
            "todos os itens herdam o sistema do checklist."
        ),
    )
    criar_sistemas = forms.BooleanField(
        required=False,
        initial=False,
        label="(ignorado) Criar sistemas que não existirem no banco",
        help_text="Este campo não é mais usado: o sistema é herdado do checklist.",
    )
    substituir = forms.BooleanField(
        required=False,
        label="Apagar itens atuais antes de importar",
    )

    def clean_arquivo(self):
        f = self.cleaned_data["arquivo"]
        if not f.name.lower().endswith((".xlsx", ".xlsm")):
            raise forms.ValidationError("Envie um arquivo .xlsx (Excel 2007+).")
        if f.size > 10 * 1024 * 1024:
            raise forms.ValidationError("Arquivo muito grande (máx. 10 MB).")
        return f


# =========================================================
# INCIDENTES
# =========================================================
class IncidenteForm(forms.ModelForm):
    class Meta:
        model = Incidente
        fields = [
            "titulo", "tipo", "severidade", "status",
            "embarcacao", "sistema", "local", "bloqueia_operacao",
            "descricao", "acao_tomada", "causa_provavel",
            "responsavel", "ocorrido_em",
        ]
        widgets = {
            "titulo":          forms.TextInput(attrs={"class": "form-control"}),
            "tipo":            forms.Select(attrs={"class": "form-control"}),
            "severidade":      forms.Select(attrs={"class": "form-control"}),
            "status":          forms.Select(attrs={"class": "form-control"}),
            "embarcacao":      forms.TextInput(attrs={"class": "form-control"}),
            "sistema":         forms.Select(attrs={"class": "form-control"}),
            "local":           forms.TextInput(attrs={"class": "form-control"}),
            "bloqueia_operacao": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "descricao":       forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "acao_tomada":     forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "causa_provavel":  forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "responsavel":     forms.Select(attrs={"class": "form-control"}),
            "ocorrido_em":     forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        self.fields["ocorrido_em"].input_formats = ["%Y-%m-%dT%H:%M"]

        # Sistema
        if self.user is not None:
            sistemas_qs = _sistemas_do_usuario(self.user)
            if sistemas_qs.count() == 1:
                self.fields["sistema"].initial = sistemas_qs.first()
            self.fields["sistema"].queryset = sistemas_qs
        else:
            self.fields["sistema"].queryset = Sistema.objects.filter(ativo=True)
        self.fields["sistema"].required = False

        # Mantém sistema inativo no queryset se estiver editando
        if self.instance and self.instance.pk and self.instance.sistema_id:
            qs_atual = self.fields["sistema"].queryset
            if not qs_atual.filter(pk=self.instance.sistema_id).exists():
                self.fields["sistema"].queryset = Sistema.objects.filter(
                    Q(pk=self.instance.sistema_id)
                    | Q(pk__in=qs_atual.values("pk"))
                ).order_by("ordem", "nome")

        # Responsável
        self.fields["responsavel"].queryset = _equipe_ativa()
        self.fields["responsavel"].label_from_instance = (
            lambda u: u.get_full_name() or u.username
        )
        self.fields["responsavel"].empty_label = "Ninguém ainda"
        self.fields["responsavel"].required = False


class IncidenteEventoForm(forms.ModelForm):
    class Meta:
        model = IncidenteEvento
        fields = ["texto"]
        widgets = {
            "texto": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Escreva um comentário sobre o incidente...",
            }),
        }


class IncidenteAnexoForm(forms.ModelForm):
    class Meta:
        model = IncidenteAnexo
        fields = ["imagem", "legenda"]
        widgets = {
            "imagem":  forms.FileInput(attrs={"class": "form-control"}),
            "legenda": forms.TextInput(attrs={"class": "form-control"}),
        }


# =========================================================
# CADASTRO / SELEÇÃO DE SISTEMAS
# =========================================================
class CadastroForm(forms.ModelForm):
    """Formulário público de cadastro. Cria User + Perfil não aprovado."""
    first_name = forms.CharField(label="Nome", max_length=150)
    last_name = forms.CharField(label="Sobrenome", max_length=150)
    email = forms.EmailField(label="E-mail")
    password1 = forms.CharField(
        label="Senha", widget=forms.PasswordInput, min_length=8,
    )
    password2 = forms.CharField(
        label="Confirme a senha", widget=forms.PasswordInput, min_length=8,
    )
    cargo = forms.CharField(label="Cargo / função", max_length=80, required=False)
    telefone = forms.CharField(label="Telefone", max_length=30, required=False)

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Usuário (login)"
        self.fields["username"].help_text = (
            "Será seu login. Use letras, números, ponto ou underline."
        )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Já existe uma conta com este e-mail.")
        return email

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Este usuário já está em uso.")
        return username

    def clean(self):
        d = super().clean()
        if d.get("password1") and d.get("password2") and d["password1"] != d["password2"]:
            self.add_error("password2", "As senhas não conferem.")
        return d

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.set_password(self.cleaned_data["password1"])
        user.is_active = True
        if commit:
            user.save()
            Perfil.objects.update_or_create(
                user=user,
                defaults={
                    "papel": Perfil.Papel.TRABALHADOR,
                    "cargo": self.cleaned_data.get("cargo", ""),
                    "telefone": self.cleaned_data.get("telefone", ""),
                    "aprovado": False,
                    "escolheu_sistemas": False,
                },
            )
        return user


class SelecionarSistemasForm(forms.Form):
    """Checkbox múltiplo de Sistemas ativos."""
    sistemas = forms.ModelMultipleChoiceField(
        queryset=Sistema.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        required=True,
        label="Selecione os sistemas que você cobre",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sistemas"].queryset = (
            Sistema.objects.filter(ativo=True).order_by("ordem", "nome")
        )


class ChecklistForm(forms.ModelForm):
    class Meta:
        model = Checklist
        fields = ["titulo", "descricao", "sistema", "missao", "status"]
        widgets = {
            "descricao": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        if self.user is not None:
            sistemas_qs = _sistemas_do_usuario(self.user)
            self.fields["sistema"].queryset = sistemas_qs
            if sistemas_qs.count() == 1:
                self.fields["sistema"].initial = sistemas_qs.first()

            qs_missao = Missao.objects.filter(
                sistema__in=_sistemas_do_usuario(self.user),
                status__in=[
                    StatusMissao.PREPARACAO,
                    StatusMissao.EM_OPERACAO,
                    StatusMissao.PAUSADA,
                ],
            ).order_by("-criado_em")
        else:
            qs_missao = Missao.objects.filter(
                status__in=[
                    StatusMissao.PREPARACAO,
                    StatusMissao.EM_OPERACAO,
                    StatusMissao.PAUSADA,
                ],
            ).order_by("-criado_em")

        # Mantém a missão atual no qs se estiver editando
        if self.instance and self.instance.pk and self.instance.missao_id:
            qs_missao = Missao.objects.filter(
                Q(pk=self.instance.missao_id) | Q(pk__in=qs_missao.values("pk"))
            ).order_by("-criado_em")

        self.fields["missao"].queryset = qs_missao
        self.fields["sistema"].required = False
        self.fields["missao"].required = False
# =========================================================
# MISSION PLANNER
# =========================================================
from django.core.exceptions import ValidationError as _DjangoValidationError


class MissionPlanForm(forms.ModelForm):
    area_geojson = forms.JSONField(
        widget=forms.HiddenInput(attrs={"id": "id_area_geojson"}),
        required=True,
    )

    class Meta:
        model = MissionPlan
        fields = (
            "nome", "sistema", "missao", "padrao_rota",
            "partida_lat", "partida_lon",
            "chegada_lat", "chegada_lon",
            "velocidade_planejada_nos", "espacamento_linhas_m",
            "sobreposicao_pct", "margem_seguranca_m",
            "angulo_linhas_graus", "area_geojson",
        )
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control"}),
            "sistema": forms.Select(attrs={"class": "form-control"}),
            "missao": forms.Select(attrs={"class": "form-control"}),
            "padrao_rota": forms.Select(attrs={"class": "form-control"}),
            "partida_lat": forms.NumberInput(attrs={"class": "form-control", "step": "0.000001"}),
            "partida_lon": forms.NumberInput(attrs={"class": "form-control", "step": "0.000001"}),
            "chegada_lat": forms.NumberInput(attrs={"class": "form-control", "step": "0.000001"}),
            "chegada_lon": forms.NumberInput(attrs={"class": "form-control", "step": "0.000001"}),
            "velocidade_planejada_nos": forms.NumberInput(attrs={"class": "form-control", "step": "0.1"}),
            "espacamento_linhas_m": forms.NumberInput(attrs={"class": "form-control", "step": "1"}),
            "sobreposicao_pct": forms.NumberInput(attrs={"class": "form-control", "step": "1"}),
            "margem_seguranca_m": forms.NumberInput(attrs={"class": "form-control", "step": "1"}),
            "angulo_linhas_graus": forms.NumberInput(attrs={"class": "form-control", "step": "1"}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        # Reusa o helper que já existe neste arquivo
        if self.user is not None:
            sistemas_qs = _sistemas_do_usuario(self.user)
            self.fields["sistema"].queryset = sistemas_qs
            if sistemas_qs.count() == 1:
                self.fields["sistema"].initial = sistemas_qs.first()

        self.fields["sistema"].required = True

        self.fields["missao"].queryset = (
            Missao.objects.select_related("sistema").order_by("-criado_em")[:50]
        )
        self.fields["missao"].required = False
        self.fields["missao"].empty_label = "— Sem missão vinculada —"

    def clean_area_geojson(self):
        geo = self.cleaned_data.get("area_geojson")
        if not geo:
            raise _DjangoValidationError("Desenhe a área de operação no mapa.")
        if isinstance(geo, dict) and geo.get("type") == "Feature":
            geo = geo.get("geometry") or {}
        if not isinstance(geo, dict) or geo.get("type") not in ("Polygon", "MultiPolygon"):
            raise _DjangoValidationError("A área precisa ser um polígono.")
        if not geo.get("coordinates"):
            raise _DjangoValidationError("Geometria vazia.")
        return geo

    def clean(self):
        cleaned = super().clean()
        sistema = cleaned.get("sistema")
        missao = cleaned.get("missao")
        if missao and sistema and missao.sistema_id != sistema.pk:
            self.add_error("missao", "A missão selecionada não pertence a este sistema.")
        return cleaned