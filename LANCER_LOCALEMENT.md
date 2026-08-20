# Lancer l'application en local

Ce guide résume les commandes pour démarrer, utiliser et arrêter l'app toi-même, sans passer par moi.

Stack : Django + DRF + PostgreSQL (`backend/`), Vue 3 + TypeScript (`frontend/`).

---

## 1. Prérequis

- **Docker Desktop** installé et lancé (méthode recommandée, tout est conteneurisé).
- Ou, pour lancer sans Docker : Python 3.12+, Node 18+, PostgreSQL 16 installés localement (voir section 6).

Vérifier que Docker tourne :

```bash
docker info
```

Si ça échoue avec "Cannot connect to the Docker daemon", ouvre Docker Desktop (ou `open -a Docker` sur Mac) et réessaie après quelques secondes.

---

## 2. Premier lancement

Depuis la racine du projet (`fuel-logistics-erp/`) :

```bash
# 1. Copier le fichier d'environnement (une seule fois)
cp .env.example .env

# 2. Construire les images et démarrer les 3 services (db, backend, frontend)
docker compose up --build
```

Le premier `--build` télécharge/installe les dépendances (peut prendre quelques minutes). Les migrations Django s'appliquent automatiquement au démarrage du backend.

Une fois démarré :

- **Frontend** : http://localhost:5173
- **Backend API** : http://localhost:8000/api/
- **Doc API (Swagger)** : http://localhost:8000/api/docs/
- **PostgreSQL** : `localhost:55434` (voir `.env` pour les identifiants)

---

## 3. Lancements suivants

Pas besoin de `--build` sauf si tu as changé une dépendance (`requirements/*.txt` ou `package.json`) :

```bash
docker compose up -d
```

`-d` = en arrière-plan (détaché). Sans `-d`, les logs s'affichent dans le terminal et `Ctrl+C` arrête tout.

Pour arrêter :

```bash
docker compose down
```

`docker compose down` supprime les conteneurs mais **garde les données** (volume `postgres_data`). Pour tout effacer y compris la base :

```bash
docker compose down -v
```

---

## 4. Commandes utiles

```bash
# Voir les logs en direct (tous les services)
docker compose logs -f

# Logs d'un seul service
docker compose logs -f backend
docker compose logs -f frontend

# État des conteneurs
docker compose ps

# Reconstruire seulement le backend (après ajout d'une dépendance Python)
docker compose build backend
docker compose up -d backend

# Ouvrir un shell dans le conteneur backend
docker compose exec backend bash

# Lancer le shell Django (pour du debug/manipulation manuelle de données)
docker compose exec backend python manage.py shell

# Créer un compte administrateur
docker compose exec backend python manage.py createsuperuser

# Appliquer les migrations manuellement (normalement automatique au démarrage)
docker compose exec backend python manage.py migrate
```

---

## 5. Lancer les tests

```bash
# Backend (pytest)
docker compose exec backend pytest

# Frontend (vitest)
docker compose exec frontend npm run test:unit
```

---

## 6. Alternative sans Docker

**Backend**

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements/dev.txt
python manage.py migrate
python manage.py runserver
```

Nécessite un PostgreSQL local qui tourne, avec les identifiants renseignés dans `backend/.env` (ou variables d'environnement équivalentes à `.env.example`).

**Frontend**

```bash
cd frontend
npm install
npm run dev
```

---

## 7. Notes

- Le code est monté en volume (`./backend:/app`, `./frontend:/app`) : les modifications de fichiers sont prises en compte à chaud (hot reload), aucun rebuild nécessaire pour du simple code.
- Un rebuild (`docker compose build`) n'est nécessaire que si tu ajoutes/changes une dépendance dans `requirements/*.txt` ou `package.json`.
- Un compte de test créé pendant la recette Phase 6 existe encore en base (si tu n'as pas fait `down -v`) : `recette-phase6@test.local` / `Recette123!` (rôle Admin).
