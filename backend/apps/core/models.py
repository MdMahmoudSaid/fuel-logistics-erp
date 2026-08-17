from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base adding created/updated timestamps to every domain model."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Product(TimeStampedModel):
    """Fuel product (Gasoil, Essence, ...). See spec §5."""

    name = models.CharField(max_length=100, unique=True)
    code = models.SlugField(max_length=20, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
