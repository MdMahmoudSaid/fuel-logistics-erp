# Fuel Logistics ERP — Plan de Refonte UI/UX (Design System « Jauge »)

Ce document constitue la spécification technique et ergonomique de référence pour la refonte intégrale de l'interface utilisateur. Il doit être exécuté étape par étape par Claude Code.

---

## 0. Règles Non Négociables (UX & Design Guidelines)

1. **Usage de l'Orange (`#F97316`) :**
   - Signifie uniquement « action » ou « marque ».
   - Un seul bouton primaire orange par écran.
   - **L'orange N'EST JAMAIS un statut.** Aucun badge orange n'existe dans l'application.
2. **Accessibilité & Contraste (WCAG AA) :**
   - **Jamais de texte blanc sur `#F97316`.** Le texte sur bouton primaire est obligatoirement foncé (`--bitume` / `#12171C`) pour garantir le contraste AA (6.1:1).
   - Sur fond clair, utiliser la variante `--orange-fonce` (`#C2410C`) pour le texte et les icônes.
3. **Format des Données Numériques :**
   - Tout chiffre de volume (Litres), montant financier (MRU/EUR), plaque d'immatriculation ou identifiant (ID Trajet) utilise la police **`IBM Plex Mono`** avec `font-variant-numeric: tabular-nums`, aligné à droite dans les tableaux.
4. **Ergonomie Tactile Mobile-First :**
   - Zone tactile minimale de **48 px** pour tous les contrôles, et **56 px** pour les actions terrain (validation de livraison, saisie de jauge).
   - `font-size: 16px` minimum sur tous les `<input>` pour éviter le zoom automatique iOS.
5. **Zéro Scroll Horizontal :**
   - Aucun tableau à défilement horizontal sous 768 px. Tout tableau HTML se transforme en liste de cartes empilées (`Card Layout`).

---

## 1. Tokens Design System

### Palette de Couleurs CSS (`src/styles/tokens.css`)

```css
:root {
  /* Surfaces */
  --bitume:        #12171C;  /* sidebar, header, nav basse, modales */
  --bitume-2:      #1C242B;  /* survol sur fond sombre, séparateurs sombres */
  --sable:         #F6F4EF;  /* canvas global de l'application */
  --surface:       #FFFFFF;  /* cartes, formulaires */
  --ligne:         #E4E1D8;  /* bordures 1px */
  --ligne-forte:   #D8D5CC;

  /* Texte */
  --texte:         #12171C;
  --texte-2:       #6B6A64;
  --texte-3:       #9A9891;  /* placeholders, métadonnées */

  /* Marque / Action */
  --orange:        #F97316;  /* fond de bouton primaire, logo, actif */
  --orange-fonce:  #C2410C;  /* texte et icônes orange sur fond clair */
  --orange-tint:   #FDEBD3;

  /* Statuts (Fond Claire / Texte Sombre) */
  --livre:         #0E9F6E;  --livre-tint:    #D6F2E6;  --livre-texte:   #0A5C41;
  --transit:       #2563EB;  --transit-tint:  #DBEAFE;  --transit-texte: #1E3A8A;
  --ecart:         #B45309;  --ecart-tint:    #FDEBD3;  --ecart-texte:   #7C3D06;
  --critique:      #DC2626;  --critique-tint: #FBDDDD;  --critique-texte:#8F1D1D;
}