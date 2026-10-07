from django import forms
from django.contrib.auth import get_user_model

from .models import Demanda, Perfil, Prioridade, Sistema, Status, Tipo

User = get_user_model()


def _equipe_ativa():
    """Quem pode receber demandas: todos os ativos, exceto diretores."""
    return User.objects.filter(is_active=True).exclude(perfil__papel=Perfil.Papel.DIRETOR).order_by("first_name", "username")


class DemandaForm(forms.ModelForm):
    class Meta:
        model = Demanda
        fields = ["titulo", "tipo","classe", "sistema", "prioridade", "item_faltante", "quantidade",
                  "bloqueia_operacao", "descricao", "responsavel", "prazo", "status"]
        widgets = {
            "descricao": forms.Textarea(attrs={"rows": 5}),
            "prazo": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsavel"].queryset = _equipe_ativa()
        self.fields["responsavel"].label_from_instance = lambda u: u.get_full_name() or u.username
        self.fields["responsavel"].empty_label = "Ninguém ainda"
        if not self.instance.pk:  # nova demanda sempre nasce pendente
            del self.fields["status"]

    def clean(self):
        dados = super().clean()
        if dados.get("tipo") == Tipo.FALTANTE and not dados.get("item_faltante"):
            self.add_error("item_faltante", "Diga qual item está faltando.")
        return dados


class AtualizacaoForm(forms.Form):
    status = forms.ChoiceField(label="Novo status", required=False,
                               choices=[("", "Manter status atual")] + list(Status.choices))
    texto = forms.CharField(label="Comentário", required=False,
                            widget=forms.Textarea(attrs={"rows": 3, "placeholder": "O que foi feito, o que falta, o que bloqueia..."}))

    def clean(self):
        dados = super().clean()
        if not dados.get("status") and not (dados.get("texto") or "").strip():
            raise forms.ValidationError("Escreva um comentário ou escolha um novo status.")
        return dados


class FiltroDemandaForm(forms.Form):
    q = forms.CharField(required=False, label="Buscar", widget=forms.TextInput(attrs={"placeholder": "Título, item, código..."}))
    status = forms.ChoiceField(required=False, label="Status",
                               choices=[("", "Todos"), ("ABERTAS", "Em aberto")] + list(Status.choices))
    prioridade = forms.ChoiceField(required=False, label="Prioridade", choices=[("", "Todas")] + list(Prioridade.choices))
    tipo = forms.ChoiceField(required=False, label="Tipo", choices=[("", "Todos")] + list(Tipo.choices))
    sistema = forms.ModelChoiceField(required=False, label="Sistema", queryset=Sistema.objects.all(), empty_label="Todos")
    responsavel = forms.ModelChoiceField(required=False, label="Responsável", queryset=User.objects.none(), empty_label="Todos")
    atrasadas = forms.BooleanField(required=False, label="Só atrasadas")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsavel"].queryset = User.objects.filter(is_active=True).order_by("first_name", "username")
        self.fields["responsavel"].label_from_instance = lambda u: u.get_full_name() or u.username


class UsuarioForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]
        labels = {"first_name": "Nome", "last_name": "Sobrenome", "email": "E-mail"}


class PerfilForm(forms.ModelForm):
    class Meta:
        model = Perfil
        fields = ["cargo", "telefone"]
from django import forms

from .models import Missao


class MissaoForm(forms.ModelForm):
    class Meta:
        model = Missao
        fields = (
            "titulo",
            "objetivo",
            "local",
            "responsavel",
            "status",
            "inicio_previsto",
            "observacoes",
        )

        widgets = {
            "titulo": forms.TextInput(
                attrs={
                    "placeholder": "Ex.: Levantamento hidrográfico — Porto do Açu",
                }
            ),
            "objetivo": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Descreva o objetivo da missão...",
                }
            ),
            "local": forms.TextInput(
                attrs={
                    "placeholder": "Ex.: Porto do Açu",
                }
            ),
            "inicio_previsto": forms.DateTimeInput(
                attrs={
                    "type": "datetime-local",
                }
            ),
            "observacoes": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Observações operacionais...",
                }
            ),
        }