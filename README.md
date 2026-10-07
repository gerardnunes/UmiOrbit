# L42 · Gestão do barco autônomo

Sistema em Django para registrar demandas e itens faltantes do L42, com dois perfis:

| Perfil | O que pode fazer |
|---|---|
| **Trabalhador** | Criar, editar, assumir e atualizar demandas; registrar itens faltantes; comentar e mudar status |
| **Diretor** | Somente visualizar: estado atual do barco, o que está em andamento, faltantes, equipe e histórico |

O **Painel** mostra se o barco está *apto*, *apto com restrições* ou *não apto para operar*:
- **Não apto**: existe demanda em aberto marcada como "impede o barco de operar".
- **Apto com restrições**: nada impede a saída, mas há demanda Crítica ou Alta em aberto.
- **Apto**: nenhuma pendência grave.

## Rodar localmente

```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed                # dados de exemplo (opcional)
python manage.py createsuperuser     # seu acesso de administrador
python manage.py runserver
```
Abra http://127.0.0.1:8000/ . Usuários do `seed`: `ana`, `carlos` (trabalhadores) e `diretor`, com senha `<usuario>12345`. **Troque as senhas.**

## Cadastrar pessoas e diretores

1. Acesse `/admin/` > Usuários > Adicionar (todo usuário novo nasce como trabalhador).
2. Para criar um diretor: na lista de usuários, marque a pessoa e use a ação **"Definir como DIRETOR"** (ou edite o usuário e mude o papel no bloco "Perfil").
3. Os sistemas do barco (Casco, Propulsão, Energia...) também são editáveis no admin.

## Produção

Variáveis de ambiente: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=0`, `DJANGO_ALLOWED_HOSTS=seudominio.com`, `DJANGO_CSRF_ORIGINS=https://seudominio.com`.

```bash
python manage.py collectstatic --noinput
gunicorn l42.wsgi
```
O banco padrão é SQLite (ótimo para equipe pequena). Para PostgreSQL, altere `DATABASES` em `l42/settings.py`.

## Testes
```bash
python manage.py test
```
