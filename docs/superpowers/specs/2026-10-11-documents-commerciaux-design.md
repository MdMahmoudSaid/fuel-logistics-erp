# Documents commerciaux — design (2026-10-11)

Validé en conversation le 2026-10-11. Modèles fournis par le client : proforma
Vivo Energy N°062409-26, bon de livraison Sahel Commerce N°004, liste des
camions Sahel Commerce du 29/06/2026.

## Objectif

Remplacer la page « Offres commerciales » par une section **Documents** qui
regroupe quatre documents imprimables et téléchargeables en PDF :

| Document | Destinataire | Rôle |
|---|---|---|
| Proforma | client | offre de prix (l'actuelle offre commerciale, renommée) |
| Bon de livraison | client | atteste qu'un ou plusieurs trajets lui ont été livrés |
| Bon de chargement | fournisseur / dépôt qui charge | liste des camions préparés et leurs capacités |
| Bon de commande | fournisseur | commande de produit : quantités, prix, conditions |

Ce sont **uniquement des documents** : aucun effet sur la comptabilité, le
stock, la trésorerie, les trajets ou les factures. Rien d'autre dans
l'application ne lit ces documents.

## Décisions

- D1 — Documents **enregistrés et numérotés** (liste, réouverture,
  modification, re-téléchargement, réimpression).
- D2 — Lignes **pré-remplies depuis l'application et modifiables** ; ajout
  de lignes manuelles toujours possible.
- D3 — Coordonnées de l'entreprise saisies dans une page **Paramètres →
  Informations de l'entreprise**, utilisées par tous les PDF.
- D4 — Bon de commande = **produits, quantités, prix**, pré-remplissable
  depuis une commande fournisseur.
- D5 — Un modèle par type de document (pas de modèle générique JSON).
- D6 — Montant en lettres (« Arrêté à la somme de ») calculé par un helper
  maison fr/en/ar, sans nouvelle dépendance Python.

## 1. Navigation

Nouvelle section de menu **DOCUMENTS** (icône document) avec quatre entrées :
Proformas, Bons de livraison, Bons de chargement, Bons de commande.
L'entrée « Offres commerciales » sous VENTES disparaît. Les anciennes routes
`/quotations…` redirigent vers `/documents/proformas…`.

Chaque page : titre, filtre (statut ou partenaire), bouton orange
« Nouveau … », tableau (numéro, partenaire, date, total ou quantité, statut),
actions par ligne : Ouvrir, Télécharger PDF, Imprimer, Dupliquer (proforma).

Permissions : Proformas et Bons de livraison → module `sales` ; Bons de
chargement et Bons de commande → module `purchasing`. Informations de
l'entreprise → module `admin` (même droit que les autres paramètres).

## 2. Informations de l'entreprise

Modèle singleton `CompanyProfile` (app `core`) : nom, slogan, NIF, RC,
adresse, ville, téléphone, e-mail, site web. Modèle `CompanyBankAccount`
(banque, code SWIFT, numéro de compte, ordre d'affichage, actif).
Ces comptes sont **distincts** des comptes de trésorerie (`BankAccount`) :
purement informatifs, imprimés sur les documents.

Page Paramètres → « Informations de l'entreprise » : un formulaire et la liste
des comptes bancaires (ajouter / modifier / désactiver). Si le profil est
vide, les PDF retombent sur le nom actuel « AZUR ÉNERGIE » et masquent les
lignes vides.

Le logo reste le logo actuel de l'application.

## 3. Proforma (ex-offre commerciale)

Le modèle `Quotation` et ses lignes sont conservés (aucune donnée perdue) ;
seul le nom affiché change : « Proforma ». Les références existantes `DEV-…`
restent ; les nouvelles utilisent le préfixe `PF`.

Champs ajoutés :
- `payment_terms` (texte court, ex. « Avance de 30 % obligatoire ») ;
- `show_bank_accounts` (booléen, vrai par défaut).

PDF inspiré du modèle Vivo, avec le style de l'application :
1. Bandeau : logo + nom de l'entreprise à gauche ; « FACTURE PROFORMA »
   et N° à droite.
2. Deux cartes côte à côte : **Client facturé** (nom, adresse, téléphone)
   et **Informations** (date, échéance « Comptant » ou date de validité,
   devise, statut).
3. Tableau Libellé / Quantité / Unité / Prix unitaire / Montant, lignes
   alternées.
4. Cadre « Total à payer » en évidence ; « Arrêté à la somme de : <montant en
   lettres> ».
5. Conditions de paiement, notes.
6. Comptes bancaires (tableau banque / SWIFT / numéro) si activé.
7. Pied de page : nom, adresse, téléphone, e-mail, NIF/RC de l'entreprise.

## 4. Bon de livraison

Modèle `DeliveryNote` : numéro (`BL`, numérotation mensuelle comme les
autres références), client (obligatoire), date, lieu d'émission (ville),
adresse de livraison, notes, créé par. Lignes `DeliveryNoteLine` : trajet
(optionnel), produit/désignation, quantité, citerne, tracteur, manquant,
observation, ordre.

Création :
1. Choisir le client.
2. La liste de ses trajets **livrés** s'affiche (référence, date, camion,
   quantité) ; l'utilisateur coche un ou plusieurs trajets.
3. Les lignes se remplissent : désignation = produit, quantité = quantité
   reçue si le contrôle de livraison existe sinon quantité chargée,
   citerne / tracteur = camion du trajet, manquant = perte du contrôle de
   livraison (vide sinon).
4. Tout reste modifiable ; ligne manuelle possible.

Un trajet peut figurer sur plusieurs bons (réimpression, bon refait) — un
avertissement s'affiche s'il est déjà sur un autre bon, sans blocage.

PDF inspiré du bon N°004 : bandeau entreprise (nom, slogan, NIF), lieu et
date, « Bon de livraison N° », client, adresse de livraison ; tableau
N° / Désignation / Quantité / Citerne / Tracteur / Manquant / Observation
avec total des quantités ; deux cadres de signature « Le réceptionnaire » et
« Le fournisseur » ; pied de page entreprise.

## 5. Bon de chargement

Modèle `LoadingSheet` : numéro (`BCH`), date, fournisseur / dépôt de
chargement (fournisseur de l'application ou texte libre), « au compte de »
(texte, par défaut le nom de l'entreprise), référence (texte libre : cession,
commande…), produit, axe / destination, notes, créé par. Lignes
`LoadingSheetLine` : camion (optionnel), tracteur, citerne, capacité (L),
produit, N° BE, axe, ordre.

Création, en deux étapes :
1. **Informations** : les champs ci-dessus (la référence peut être choisie
   parmi les commandes fournisseur / lettres de cession, ou tapée).
2. **Camions** : sélection multiple dans la flotte active (recherche par
   tracteur / citerne) ; tracteur, citerne, capacité se remplissent ;
   produit et axe reprennent ceux de l'étape 1 ; N° BE saisi par camion.
   Ligne manuelle possible (camion hors flotte).

PDF inspiré de la liste du 29/06 : titre « Liste des camions au compte de
<…> », date, référence ; tableau N° / Tracteur / Citerne / Capacité (L) /
Produit / N° BE / Axe ; total des litres et nombre de camions ; pied de
page entreprise. Format paysage.

## 6. Bon de commande

Modèle `PurchaseOrderDocument` : numéro (`BCF`), fournisseur (obligatoire),
date, lieu de livraison, date de livraison souhaitée, conditions de
paiement, notes, devise, total (calculé), statut (Brouillon / Envoyé),
créé par. Lignes : produit (optionnel), désignation, quantité, unité, prix
unitaire, montant (calculé).

Pré-remplissage optionnel depuis une commande fournisseur : fournisseur,
produit, quantité, prix unitaire.

PDF construit comme la proforma, titre « BON DE COMMANDE », carte
« Fournisseur » à la place de « Client facturé », sans comptes bancaires,
avec cadre de signature « Pour l'entreprise ».

## 7. Règles communes

- Backend : nouvelle app `commercial_documents` (bon de livraison, bon de
  chargement, bon de commande) ; la proforma reste dans `quotations`.
  Référence générée par `generate_monthly_reference` avec reprise sur
  collision, comme les devis.
- Chaque viewset expose `GET …/{id}/pdf/?lang=fr|en|ar` ; les PDF sont
  rendus avec reportlab dans un module de gabarit partagé (bandeau,
  cartes, tableau, signatures, pied de page entreprise, sens droite-à-gauche
  pour l'arabe).
- Imprimer = ouvrir le PDF dans un nouvel onglet et lancer l'impression.
- Montant en lettres : helper `amount_in_words(amount, lang)` (fr, en, ar),
  entiers jusqu'aux milliards, devise en suffixe.
- Libellés fr / en / ar pour toute l'interface et les PDF.
- Suppression autorisée (documents purement informatifs) avec
  confirmation.

## 8. Tests

- Backend : numérotation, contrôles (client / fournisseur obligatoires,
  quantités positives), endpoint de pré-remplissage des trajets livrés,
  calcul des totaux, montant en lettres (fr/en/ar), chaque PDF généré sans
  erreur dans les trois langues, permissions par module, profil entreprise
  vide → PDF valide.
- Frontend : listes, formulaires (sélection de trajets / camions,
  pré-remplissage), nouvelle navigation, page Informations de l'entreprise.
- Vérification visuelle des quatre PDF en fr et ar sur une copie de base.

## Hors périmètre

Envoi par e-mail, signature électronique, conversion proforma → facture,
lien automatique bon de commande → commande fournisseur.
