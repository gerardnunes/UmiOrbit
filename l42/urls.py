from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "L42 · Administração"
admin.site.site_title = "L42"
admin.site.index_title = "Gestão do barco autônomo"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("operacao.urls")),
]
