from django.db import migrations

PRODUCTS = [
    {"name": "Gasoil", "code": "gasoil"},
    {"name": "Essence", "code": "essence"},
]


def seed_products(apps, schema_editor):
    Product = apps.get_model("core", "Product")
    for entry in PRODUCTS:
        Product.objects.update_or_create(code=entry["code"], defaults={"name": entry["name"]})


def unseed_products(apps, schema_editor):
    Product = apps.get_model("core", "Product")
    Product.objects.filter(code__in=[p["code"] for p in PRODUCTS]).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [migrations.RunPython(seed_products, unseed_products)]
