# Authentification Téléphone + PIN — Spécification

Date : 2026-08-22
Statut : Approuvé

## Contexte

L'application utilise aujourd'hui une authentification email + mot de passe
(Django `AbstractBaseUser`, `USERNAME_FIELD = "email"`, SimpleJWT
`TokenObtainPairView`). Le modèle `User` a déjà un champ `phone` (texte
libre, non utilisé pour l'auth). Les formulaires de données de base
(Clients, Fournisseurs, Transporteurs, Chauffeurs, Utilisateurs) utilisent
tous un champ téléphone en texte simple, sans indicatif pays ni validation,
via le pattern générique `MasterDataView` + `FieldSchema` + `EntityForm.vue`.

Objectif : remplacer entièrement l'authentification par téléphone (avec
indicatif pays) + PIN à 4 chiffres, et introduire un composant
`CountryPhoneInput` réutilisé partout où un téléphone est saisi.

Contexte de déploiement : application pré-lancement, aucun utilisateur réel
en production — migration "propre" sans contrainte de compatibilité.

## 1. Backend — modèle `User` (`apps/accounts/models.py`)

- `phone` devient `USERNAME_FIELD`, `unique=True`, requis. Stocké normalisé
  (indicatif + chiffres, sans espaces, ex. `+22212345678`), format produit
  par le composant frontend `CountryPhoneInput`.
- `email` reste sur le modèle mais devient **optionnel, non unique**
  (simple champ de contact/notification, plus utilisé pour la connexion).
- Le champ `password` hérité d'`AbstractBaseUser` est **réutilisé pour
  stocker le PIN hashé** — pas de nouvelle colonne, on garde
  `set_password`/`check_password`/le hasher Django gratuitement. Exposé
  côté API sous le nom `pin`, jamais `password`.
- Deux nouveaux champs anti-bruteforce : `failed_pin_attempts =
  IntegerField(default=0)`, `locked_until = DateTimeField(null=True,
  blank=True)`.
- `UserManager.create_user(phone, pin=None, **extra)` remplace la
  signature basée sur l'email.

## 2. Backend — validation PIN & verrouillage de compte

- `AUTH_PASSWORD_VALIDATORS` remplacé par un validateur custom exigeant
  **exactement 4 chiffres**. Le `NumericPasswordValidator` actuel interdit
  justement les mots de passe entièrement numériques : incompatible avec
  un PIN, il doit disparaître.
- `PhonePinTokenObtainPairSerializer` (sous-classe du serializer SimpleJWT)
  surcharge `validate()` :
  - lookup de l'utilisateur par `phone` ; si `locked_until` est dans le
    futur → rejet avec message clair ("compte verrouillé").
  - échec de vérification du PIN → incrémente `failed_pin_attempts` ; à 5
    échecs → `locked_until = now + 15min`.
  - succès → remet les deux compteurs à zéro/null.
- Câblé via une vue custom qui remplace `TokenObtainPairView` dans
  `config/urls.py`. Le chemin `/api/auth/login/` ne change pas, seul le
  corps de la requête change (`{phone, pin}` au lieu de `{email,
  password}`).

## 3. Backend — serializer / admin / migration

- `UserSerializer` : le champ `password` (write-only) devient `pin`
  (write-only, `min_length=4`/`max_length=4`, validateur chiffres
  uniquement). `email` devient optionnel.
- `admin.py` : `ordering`/`list_display`/`fieldsets`/`search_fields`
  passent de `email` à `phone`.
- Une migration : `phone` unique, `email` non-unique + `blank=True`, ajout
  `failed_pin_attempts` et `locked_until`. Pas de migration de données
  (pré-lancement).
- `LANCER_LOCALEMENT.md:143` mis à jour — la note sur le compte de test
  recette (`recette-phase6@test.local` / `Recette123!`) référence des
  identifiants email/mot de passe obsolètes.
- Tests existants (`accounts/tests.py`) : tous les appels
  `create_user(email=..., password=...)` et les POST `{email, password}`
  vers `/auth/login/` sont mis à jour vers la forme téléphone/PIN.

## 4. Frontend — `CountryPhoneInput.vue` (nouveau, `components/ui/`)

- Le v-model est une **chaîne normalisée unique** (ex. `+22212345678`),
  même format que ce que stocke le backend — aucun changement de forme de
  données côté `FieldSchema`/`EntityForm` (toujours un seul `CharField`
  par entité).
- Fichier de données statique `countries.ts` (`{iso2, dialCode}[]`) avec
  la liste standard complète des indicatifs E.164, **Mauritanie (+222),
  Mali (+223), Sénégal (+221), Niger (+227) épinglés en tête de liste**.
  Les noms de pays sont résolus à l'affichage via l'API native
  `Intl.DisplayNames` dans la locale active (fr/en/ar) — pas de nouvelle
  dépendance, pas de traduction manuelle de ~195 noms de pays.
- UI : bouton dropdown indicatif (drapeau emoji + code) ouvrant une liste
  recherchable (style `SearchableSelect.vue` existant, filtre par nom,
  code ISO ou indicatif — ex. "Mauri" filtre sur Mauritanie), à côté d'un
  champ numérique pour le numéro national.
- Règles de validation par pays : `{ MR: 8, ML: 8, SN: 9, NE: 8 }`
  chiffres exacts ; plage générique `6–14` chiffres pour les autres pays.
  Appliqué via `pattern`/`minlength`/`maxlength` natifs HTML (cohérent
  avec le style existant du projet — `EntityForm` s'appuie déjà uniquement
  sur la validation native du navigateur).

## 5. Frontend — intégration dans les formulaires existants

- `FieldType` gagne `'phone'` et `'pin'` (`components/master-data/types.ts`).
  `EntityForm.vue` : deux nouvelles branches — `'phone'` →
  `<CountryPhoneInput>`, `'pin'` → input numérique
  (`inputmode="numeric"`, `maxlength="4"`, `pattern="\d{4}"`).
- `MasterDataView.vue` (ligne 27) : le filtre de colonnes de table exclut
  aussi `'pin'`, comme `'password'` aujourd'hui.
- Changement d'une ligne `type: 'text' → type: 'phone'` dans
  `CustomerView.vue:14`, `SupplierView.vue:15`, `TransporterView.vue:14`,
  `DriverView.vue:13`. Aucun changement backend pour ces 4 entités (leur
  `phone` reste une simple info de contact).
- `UserView.vue` : champ `phone` → type `'phone'` ; champ `password` →
  champ `pin` (type `'pin'`, clé `'pin'`).
- `LoginView.vue` : `Input` email → `CountryPhoneInput` ; `Input` mot de
  passe → input PIN numérique à 4 chiffres.
- `stores/auth.ts` : `login(email, password)` → `login(phone, pin)`, corps
  POST `{phone, pin}` ; interface `User` — `email` devient optionnel.

## 6. i18n

- Nouvelles clés `auth.phoneLabel`/`auth.pinLabel` (fr/en/ar) remplaçant
  `emailLabel`/`passwordLabel` ; `auth.invalidCredentials` mis à jour ;
  nouvelle clé `auth.accountLocked` pour le cas de verrouillage.
- `masterData.fields.phone` inchangé ; ajout `masterData.fields.pin`
  ("Code PIN").

## 7. Tests

- Backend : mise à jour des appels `create_user` dans `accounts/tests.py`
  vers `phone`/`pin` ; nouveaux tests pour le verrouillage après 5 échecs
  et la validation du format PIN.
- Frontend : mise à jour `LoginView.spec.ts` et `auth.spec.ts` ; nouveau
  `CountryPhoneInput.spec.ts` (filtre de recherche pays, validation par
  pays) ; mise à jour `MasterDataView.spec.ts` si nécessaire.
- Vérification finale : `npm run build` et `npm run test` (frontend) +
  suite pytest (backend).

## Hors périmètre

- Pas de flux "PIN oublié" / réinitialisation self-service (hors scope de
  cette demande).
- Pas de migration de données réelles (pré-lancement).
- Pas de nouvelle dépendance npm/pip pour la liste des pays (utilisation
  d'`Intl.DisplayNames`).
