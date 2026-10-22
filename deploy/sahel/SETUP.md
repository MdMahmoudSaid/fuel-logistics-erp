# SAHEL COMMERCE - installation sur le meme VPS (207.180.202.96)

Meme code que AZUR ENERGIE ; seuls changent : domaine, base de donnees, secrets, marque.

## 1. DNS
`sahelcommerce.hasel.food` -> A 207.180.202.96 (Traefik fait le certificat Let's Encrypt).

## 2. Fichiers d'environnement (hors depot, /etc/bessma/, mode 600)
- `sahel-db.env` : POSTGRES_DB / POSTGRES_USER / POSTGRES_PASSWORD (propres a Sahel).
- `sahel-app.env` : comme `fuel-app.env` mais avec
  `BRAND=sahel`, `PUBLIC_HOST=sahelcommerce.hasel.food`,
  `CSRF_TRUSTED_ORIGINS=https://sahelcommerce.hasel.food`,
  `DJANGO_ALLOWED_HOSTS=sahelcommerce.hasel.food,localhost`, un `DJANGO_SECRET_KEY` NEUF,
  et la base Sahel (host `db`).
- `sahel-migrate.env` : idem avec les identifiants de migration.

## 3. Dossier media
`/home/bouye/apps/sahel-commerce/media` (cree vide).

## 4. Premier demarrage
Copier le depot (meme commit que la prod AZUR), remplacer `TAG` dans
`docker-compose.sahel.yml`, puis `docker compose -f deploy/sahel/docker-compose.sahel.yml
build`, `run --rm migrate`, `up -d`, et creer l'admin (`createsuperuser`).

## 5. Mises a jour
Le meme commit est livre aux deux installations : AZUR avec `fuel-deploy` comme
d'habitude, Sahel en reconstruisant avec ce compose (meme bundle).
