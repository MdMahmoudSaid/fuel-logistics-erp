# Notes et demandes du client — Modifications et évolutions de l’application

Cahier des charges — Modifications et évolutions de l’application

1. Objectif général

L’objectif de ces évolutions est d’améliorer le système de gestion de l’entreprise, notamment pour :

- Le suivi des dettes.
- La gestion des clients, fournisseurs et transporteurs.
- La gestion des chargements et des voyages.
- Le calcul du prix de revient réel.
- La définition des prix de vente.
- Le calcul automatique des bénéfices.
- La gestion des paiements.
- La gestion de la trésorerie et des banques.
- La gestion des associés/actionnaires.
- Le suivi des bénéfices par voyage et par période.

⸻

2. Tableau de bord

Le Tableau de bord doit fournir une vision financière globale et rapide de la situation de l’entreprise.

2.1. Total des dettes

Ajouter une section dédiée aux dettes.

En haut :

Total des dettes

Ce montant représente l’ensemble des dettes de l’entreprise.

En dessous :

Afficher le détail par catégorie :

- Dettes Fournisseurs.
- Dettes Transporteurs.
- Dettes Douanes.
- Autres dettes éventuelles.

Exemple :

Total des dettes : 50 000 000 MRU

Détail :

- Fournisseurs : 30 000 000 MRU
- Transporteurs : 10 000 000 MRU
- Douanes : 10 000 000 MRU

⸻

2.2. Total des montants clients

Ajouter une section :

Montant total des clients

Le montant total doit apparaître en haut.

En dessous, afficher le détail par client :

- Client A → 5 000 000 MRU
- Client B → 3 500 000 MRU
- Client C → 2 000 000 MRU

Le système doit afficher le total ainsi que le détail des montants dus par chaque client.

⸻

2.3. Total des montants bancaires

Ajouter une section :

Montant total des banques

Le système doit afficher en haut le montant total disponible dans tous les comptes bancaires de l’entreprise.

En dessous, afficher le solde de chaque banque :

- Banque A → 10 000 000 MRU
- Banque B → 7 000 000 MRU
- Banque C → 5 000 000 MRU

⸻

3. Processus de chargement

Le workflow de création d’un chargement doit être modifié.

3.1. Client non obligatoire au début

Lors de la création d’un Nouveau Chargement :

- Le Client ne doit pas être obligatoire.
- Le Client ne doit pas être sélectionné au début du processus.
- La destination initiale doit être :

Stock de l’entreprise

Après la fin du processus logistique et le calcul de tous les coûts, le Client pourra être sélectionné pour effectuer la vente.

⸻

4. Calcul du Prix de revient

Après la fin du processus logistique, le système doit calculer automatiquement le Prix de revient réel du produit.

Tous les coûts liés au voyage doivent être pris en compte.

Exemple :

- Fournisseur : 500 MRU/L
- Transporteur : 60 MRU/L
- Transit : 10 MRU/L
- Douane : 250 MRU/L

Calcul :

500 + 60 + 10 + 250 = 820 MRU/L

Ces valeurs sont uniquement des exemples. Elles doivent être dynamiques et pouvoir varier selon chaque voyage et les coûts réels.

Le système doit également permettre d’ajouter d’éventuels frais supplémentaires liés au voyage.

Principe :

Prix de revient = Total des coûts du voyage / Quantité

⸻

5. Frais du Transporteur

Lors de l’enregistrement des Frais de trajet / Frais du transporteur :

5.1. Sélection du transporteur

Une Dropdown List doit permettre de sélectionner le Transporteur parmi les transporteurs enregistrés dans le système.

5.2. Calcul automatique

Le coût du transport doit être défini par litre.

Exemple :

- Quantité : 45 000 L
- Prix transport : 60 MRU/L

Le système calcule automatiquement :

45 000 × 60 = 2 700 000 MRU

5.3. Création automatique de la dette

Après l’enregistrement des frais du transporteur :

- Le montant doit être enregistré comme Dette de l’entreprise envers le Transporteur.
- La dette doit apparaître dans la section Dettes Transporteurs.
- La dette doit être liée au Transporteur concerné.

⸻

6. Prix de vente

Après le calcul du Prix de revient, le système doit permettre de définir le prix de vente.

6.1. Prix différent selon le Client

Le prix de vente ne doit pas nécessairement être identique pour tous les clients.

Il doit être possible de définir un Prix de vente différent pour chaque Client.

Exemple :

Prix de revient :

800 MRU/L

Prix de vente :

- Client A → 900 MRU/L
- Client B → 950 MRU/L
- Client C → 850 MRU/L

⸻

6.2. Calcul automatique du bénéfice

Le système doit calculer automatiquement le bénéfice.

Exemple :

Prix de vente : 900 MRU/L

Prix de revient : 800 MRU/L

Bénéfice : 100 MRU/L

Le bénéfice doit être visible directement dans le système.

⸻

6.3. Vente à perte

Si l’utilisateur saisit un prix de vente inférieur au prix de revient, le système doit afficher une alerte claire.

Exemple :

Attention : ce prix de vente entraîne une perte.

Selon la règle métier choisie par l’entreprise, le système pourra empêcher ou demander une confirmation avant de valider une vente à perte.

⸻

7. Nouveau Payment Client

La page Nouveau Payment Client doit être améliorée.

7.1. Option « Vers moi »

Ajouter une nouvelle option :

Vers moi

dans les options/destinations du paiement.

7.2. Upload d’une image

Ajouter un champ permettant de :

Télécharger une image

Cette image peut servir de preuve de paiement ou de document justificatif.

7.3. Note

Ajouter un champ :

Note

permettant d’ajouter une remarque concernant le paiement.

7.4. Total de la dette du Client

Lorsqu’un Client est sélectionné dans Nouveau Payment Client, le système doit afficher automatiquement :

Total de la dette du Client

Ce montant doit correspondre à la somme des montants dus sur les factures du Client.

⸻

8. Paiement des dettes Fournisseurs

Lorsqu’une dette Fournisseur est remboursée, partiellement ou totalement, le paiement doit être effectué via :

Virement bancaire

La transaction doit être liée au compte bancaire utilisé afin de permettre :

- Le suivi du paiement.
- La diminution de la dette Fournisseur.
- La mise à jour de la trésorerie.
- La traçabilité de l’opération bancaire.

⸻

9. Trésorerie / Finance — Actionnaires / Associés

Ajouter une nouvelle page ou section :

Actionnaires / Associés

dans :

Trésorerie / Finance

⸻

9.1. Gestion des associés

Le système doit permettre d’ajouter et de gérer tous les associés.

Exemple :

- Ahmed
- Mohamed
- Abdallah

Pour chaque associé, définir :

Pourcentage de participation

⸻

9.2. Partage automatique des bénéfices

Lors du partage des bénéfices, le système doit calculer automatiquement la part de chaque associé selon son pourcentage.

Exemple :

- Ahmed → 80 %
- Mohamed → 10 %
- Abdallah → 10 %

Pour un bénéfice total de :

1 000 000 MRU

Le système calcule :

- Ahmed → 800 000 MRU
- Mohamed → 100 000 MRU
- Abdallah → 100 000 MRU

Chaque associé reçoit donc exactement le pourcentage enregistré dans son profil.

⸻

9.3. Avance / Dette entre associés

Ajouter la possibilité d’enregistrer une :

Avance / Dette entre associés

Exemple :

Mohamed demande une avance à Ahmed.

Le système doit permettre d’enregistrer :

- Associé demandeur.
- Associé prêteur.
- Montant.
- Date.
- Statut.
- Montant remboursé.
- Montant restant.

⸻

9.4. Retrait d’argent d’un associé

Ajouter un bouton permettant d’enregistrer :

Retrait d’argent de l’associé

Le système doit permettre de suivre :

- Les bénéfices dus à l’associé.
- Les montants déjà reçus.
- Les retraits effectués.
- Le montant restant dû.
- Les avances ou dettes entre associés.

⸻

10. Suivi des bénéfices

Le système doit permettre un suivi détaillé des bénéfices.

10.1. Bénéfice par Chargement / Voyage

Pour chaque Chargement / Voyage, l’utilisateur doit pouvoir consulter le bénéfice réalisé.

Les informations suivantes doivent être disponibles :

- Quantité.
- Prix Fournisseur.
- Frais Transporteur.
- Frais Transit.
- Frais Douane.
- Frais supplémentaires.
- Prix de revient.
- Prix de vente.
- Bénéfice.

Le bénéfice doit être calculé après déduction de tous les frais liés au voyage.

⸻

10.2. Bénéfices sur une période

Ajouter un filtre permettant de sélectionner :

Du [Date début] au [Date fin]

Le système doit ensuite afficher :

- Le bénéfice total de la période.
- Le nombre de chargements/voyages.
- Le bénéfice de chaque voyage.
- Le total cumulé des bénéfices.

Exemple :

Du 01/08/2026 au 31/08/2026

Bénéfice total : 15 000 000 MRU

Avec la possibilité de consulter le détail des voyages ayant généré ce bénéfice.

⸻

11. Workflow global

Le workflow général doit suivre cette logique :

Chargement

↓

Stock de l’entreprise

↓

Ajout de tous les coûts et frais

↓

Calcul du Prix de revient

↓

Sélection du Client

↓

Définition du Prix de vente

↓

Calcul automatique du Bénéfice

↓

Vente

↓

Mise à jour Clients / Dettes / Trésorerie

↓

Reporting des bénéfices

⸻

12. Résultat attendu

À travers ces évolutions, l’application doit permettre à la direction d’avoir une vision complète et précise de :

- La trésorerie disponible.
- Les soldes bancaires.
- Les montants dus par les clients.
- Les dettes Fournisseurs.
- Les dettes Transporteurs.
- Les dettes Douanes.
- Le coût réel de chaque voyage.
- Le Prix de revient par litre.
- Le Prix de vente par Client.
- Le bénéfice réel de chaque voyage.
- Le bénéfice total sur une période donnée.
- La part de bénéfice de chaque associé.
- Les retraits effectués par chaque associé.
- Les avances et dettes entre associés.

L’objectif final est de transformer l’application en un système complet de gestion des opérations, coûts, ventes, dettes, trésorerie et bénéfices.
