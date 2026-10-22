# Marques (brands)

Une seule base de code, plusieurs clients qui ne different que par le nom et le logo.
La marque est choisie a la construction par `VITE_BRAND` (defaut `azur`) :

    VITE_BRAND=sahel npm run build

Chaque dossier contient : `brand.json` (noms, couleurs), `icon.png` (logo carre transparent,
512x512), `favicon.png` (64x64), `pwa-icon-192.png`, `pwa-icon-512.png`.
Le plugin de `vite.config.ts` en tire le titre de la page, le manifest PWA et les icones.
Cote backend : variable `BRAND` (voir backend/apps/core/brand.py).
Nouveau client = nouveau dossier ici + une entree dans brand.py + son logo dans backend/apps/reports/assets/.
