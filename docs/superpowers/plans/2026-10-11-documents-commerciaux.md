# Documents commerciaux — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Section « Documents » : Proforma (ex-offre commerciale), Bon de livraison, Bon de chargement, Bon de commande — enregistrés, numérotés, PDF fr/en/ar téléchargeables et imprimables, plus une page « Informations de l'entreprise ».

**Architecture (économe en code/tokens) :**
- **Un seul moteur PDF** : on étend `report_pdf.render_report_pdf` (déjà fr/en/ar + RTL + tableaux + résumé) avec 3 clés optionnelles (`company` enrichi, `blocks`, `signatures`). Chaque PDF = un petit *builder* qui retourne `(document, rows)`.
- **Une app `commercial_documents`** avec une base abstraite (`BaseDocument`, `BaseLine`), un `BaseDocumentSerializer` (lignes imbriquées, remplacement complet) et un `BaseDocumentViewSet` (référence auto + action `pdf`). Les 3 documents = 3 sous-classes courtes.
- **Frontend générique** : un `DocumentList.vue` piloté par une config, un `LinesTable.vue` éditable, 3 formulaires minces. La proforma garde `QuotationForm.vue`.

**Tech Stack:** Django/DRF, reportlab, Vue 3 + vue-i18n, pytest, vitest.

**Spec:** `docs/superpowers/specs/2026-10-11-documents-commerciaux-design.md`

## Global Constraints

- Aucun effet comptable/stock/trésorerie : rien hors de ces documents ne les lit.
- Références : `generate_monthly_reference(model, "reference", PREFIX)` + 5 essais sur `IntegrityError` ; préfixes `PF` (proforma), `BL`, `BCH`, `BCF`. Les anciennes `DEV-…` restent.
- Permissions : proforma + bon de livraison → `sales` ; bon de chargement + bon de commande → `purchasing` ; profil entreprise → `admin`.
- Libellés fr/en/ar partout (UI + PDF). Montant en lettres sans nouvelle dépendance.
- Texte libre dans un PDF : toujours via les helpers existants (`_p` / `para_text`), jamais de markup brut.
- Tests : `DATABASE_URL=postgres://postgres:postgres@localhost:55435/fuel_erp_empty_test .venv/bin/python -m pytest -q --create-db -p no:cacheprovider <cible>` (depuis `backend/`) ; frontend `npx vitest run <cible>`, `npx vue-tsc -b`, `npx eslint`, `npx prettier --check`.
- Pas de commit/déploiement sans le feu vert de l'utilisateur (le lot reste non commité) ; fichiers stagés un par un le moment venu.
- Locales : modifier `fr.json`/`en.json`/`ar.json` uniquement par script Python `json.load` → `json.dump(indent=2, ensure_ascii=False)` + `\n`, puis prettier. **Jamais `sed -i` sur un fichier de locale.**

## Review Focus

1. Profil entreprise vide (première utilisation) → tous les PDF se génèrent, lignes vides masquées, nom « AZUR ÉNERGIE ». *(test Task 3)*
2. Trajet déjà sur un autre bon de livraison → avertissement, pas de blocage ; trajet sans contrôle de livraison → quantité chargée, manquant vide. *(test Task 5)*
3. Ligne manuelle sans camion/trajet (camion hors flotte) → acceptée si désignation ou tracteur renseigné. *(test Task 5)*
4. Montants ronds/limites en lettres : 0, 1, 80, 1 000 000, 387 500 000 en fr/en/ar. *(test Task 2)*
5. PDF arabe avec noms latins (client, tracteur) → pas d'erreur de rendu, sens RTL. *(test Task 6)*

---

### Task 1: Profil entreprise (backend)

**Files:**
- Modify: `backend/apps/core/models.py` (ajout en fin), `backend/apps/core/serializers.py`, `backend/apps/core/views.py`, `backend/apps/core/urls.py`
- Create: migration `core/00xx_company_profile.py` (via makemigrations)
- Test: `backend/apps/core/test_company_profile.py`

**Interfaces:**
- Produces: `CompanyProfile.load() -> CompanyProfile` (singleton pk=1, créé vide si absent) ; `CompanyProfile.pdf_company() -> dict` = `{"name", "tagline", "lines": [str...], "banks": [{"bank","swift","account"}...]}` (lignes vides retirées, nom par défaut `DEFAULT_COMPANY_NAME`) ; API `GET/PATCH /api/settings/company/` (champs + `bank_accounts` imbriqués, remplacement complet).

- [ ] **Step 1: Test**

```python
import pytest
from rest_framework.test import APIClient
from apps.accounts.models import Role, User
from apps.core.models import CompanyProfile


def _client(role=Role.NAME_ADMIN):
    user = User.objects.create_user(phone="+222CPROF", pin="1234", role=Role.objects.get(name=role))
    c = APIClient(); c.force_authenticate(user); return c


@pytest.mark.django_db
def test_empty_profile_falls_back_to_default_name():
    info = CompanyProfile.load().pdf_company()
    assert info["name"] == "AZUR ÉNERGIE" and info["lines"] == [] and info["banks"] == []


@pytest.mark.django_db
def test_patch_profile_and_banks():
    c = _client()
    r = c.patch("/api/settings/company/", {
        "name": "Sahel Commerce", "tax_id": "071002548J", "phone": "76 68 04 84",
        "bank_accounts": [{"bank": "ECOBANK", "swift": "ECOCSNDA", "account_number": "SN094 01001"}],
    }, format="json")
    assert r.status_code == 200, r.data
    info = CompanyProfile.load().pdf_company()
    assert info["name"] == "Sahel Commerce"
    assert "NIF : 071002548J" in info["lines"]
    assert info["banks"] == [{"bank": "ECOBANK", "swift": "ECOCSNDA", "account": "SN094 01001"}]
```

- [ ] **Step 2: Run → FAIL** (`ImportError CompanyProfile`).
- [ ] **Step 3: Implement**

```python
# core/models.py
class CompanyProfile(TimeStampedModel):
    """Coordonnées imprimées sur les documents (spec 2026-10-11 §2).
    Singleton (pk=1), comme LossToleranceConfig."""
    name = models.CharField(max_length=150, blank=True)
    tagline = models.CharField(max_length=150, blank=True)
    tax_id = models.CharField(max_length=50, blank=True)       # NIF
    trade_register = models.CharField(max_length=80, blank=True)  # RC
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=60, blank=True)
    email = models.CharField(max_length=150, blank=True)
    website = models.CharField(max_length=150, blank=True)

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        return cls.objects.get_or_create(pk=1)[0]

    def pdf_company(self) -> dict:
        from apps.reports.services.pdf_template import DEFAULT_COMPANY_NAME
        lines = [
            " · ".join(x for x in [self.address, self.city] if x),
            " · ".join(x for x in [self.phone and f"Tél. : {self.phone}", self.email, self.website] if x),
            " · ".join(x for x in [self.tax_id and f"NIF : {self.tax_id}",
                                   self.trade_register and f"RC : {self.trade_register}"] if x),
        ]
        return {
            "name": self.name or DEFAULT_COMPANY_NAME,
            "tagline": self.tagline,
            "lines": [l for l in lines if l],
            "banks": [{"bank": b.bank, "swift": b.swift, "account": b.account_number}
                      for b in self.bank_accounts.filter(is_active=True)],
        }


class CompanyBankAccount(models.Model):
    """Compte imprimé sur les documents - sans lien avec la trésorerie."""
    profile = models.ForeignKey(CompanyProfile, on_delete=models.CASCADE, related_name="bank_accounts")
    bank = models.CharField(max_length=100)
    swift = models.CharField(max_length=30, blank=True)
    account_number = models.CharField(max_length=80)
    position = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["position", "id"]
```

Serializer `CompanyProfileSerializer` (tous les champs + `bank_accounts = CompanyBankAccountSerializer(many=True, required=False)`, `update()` remplace les comptes si fournis, `position` = index). Vue `CompanyProfileView(APIView)` calquée sur `LossToleranceConfigView` (GET → `CompanyProfile.load()`, PATCH partiel), `permission_classes=[HasModulePermission]`, `module = "admin"` ; route `settings/company/`. `makemigrations core`.

- [ ] **Step 4: Run → PASS**.

---

### Task 2: Montant en lettres

**Files:**
- Create: `backend/apps/reports/services/amount_words.py`
- Test: `backend/apps/reports/test_amount_words.py`

**Interfaces:**
- Produces: `amount_in_words(amount: Decimal | int, lang: str, currency: str = "FCFA") -> str` (partie entière, jusqu'aux milliards ; `XOF` affiché `FCFA`).

- [ ] **Step 1: Test**

```python
import pytest
from apps.reports.services.amount_words import amount_in_words as w

@pytest.mark.parametrize("n,lang,expected", [
    (0, "fr", "Zéro FCFA"),
    (80, "fr", "Quatre-vingts FCFA"),
    (1000000, "fr", "Un million FCFA"),
    (387500000, "fr", "Trois cent quatre-vingt-sept millions cinq cent mille FCFA"),
    (387500000, "en", "Three hundred eighty-seven million five hundred thousand FCFA"),
    (1, "en", "One FCFA"),
    (1000, "ar", "ألف فرنك"),
    (387500000, "ar", "ثلاثمائة وسبعة وثمانون مليونا وخمسمائة ألف فرنك"),
])
def test_amount_in_words(n, lang, expected):
    assert w(n, lang) == expected
```

- [ ] **Step 2: Run → FAIL**.
- [ ] **Step 3: Implement** — un module unique, trois fonctions `_fr(n)`, `_en(n)`, `_ar(n)` par groupes de 3 chiffres (milliard/million/mille), règles :
  - fr : tirets entre dizaines-unités (rectification 1990 : tirets partout sauf avant/après « million(s) » et « milliard(s) »), « et un » pour 21/31/41/51/61/71, « quatre-vingts »/« cents » pluriels seulement en fin de nombre, « mille » invariable, « million(s) ».
  - en : `hundred`, `thousand`, `million`, `billion`, tiret pour 21–99.
  - ar : unités/dizaines « واحد وعشرون », centaines « مائة، مائتان، ثلاثمائة… », groupes joints par « و », pluriels simplifiés : ألف / ألفان / آلاف (3-10) / ألف (≥11) ; مليون / مليونان / ملايين / مليونا (≥11) ; مليار idem ; devise « فرنك ».
  - Capitaliser la première lettre (fr/en) ; `int(amount)` (centimes ignorés : montants XOF entiers).
- [ ] **Step 4: Run → PASS** (ajuster l'implémentation, pas les attentes).

---

### Task 3: Moteur PDF étendu

**Files:**
- Modify: `backend/apps/reports/services/report_pdf.py` (`_header_block`, `build_report_flowables`, nouveau `_blocks`, `_signatures`, `_footer`)
- Test: `backend/apps/reports/test_document_pdf_engine.py`

**Interfaces:**
- Consumes: `CompanyProfile.pdf_company()` (Task 1).
- Produces: clés optionnelles du `document` lues par `render_report_pdf` :
  - `company`: `{"name", "tagline"?, "lines"?: [str]}` → slogan sous le nom ; `lines` en pied de document (petit, gris, centré).
  - `blocks`: `[{"title"?: str, "text": str, "boxed"?: bool}]` → après le résumé (ex. « Arrêté à la somme de », conditions).
  - `signatures`: `[str]` → rangée de cadres de signature (hauteur 25 mm) en fin de document.
  - `summary` peut être `[]` (aucun bloc rendu).
  Toutes absentes = rendu actuel inchangé (rapports existants intacts).

- [ ] **Step 1: Test**

```python
from apps.reports.services.report_pdf import render_report_pdf

def _doc(lang, **extra):
    d = {"company": {"name": "AZUR ÉNERGIE"}, "title": "T", "lang": lang,
         "direction": "rtl" if lang == "ar" else "ltr", "orientation": "portrait",
         "info": [], "tables": [{"title": "", "columns": [
             {"field": "a", "label": "A", "kind": "text", "align": "start"}]}],
         "opening_balance": None, "summary": [], "labels": {"page": "Page"}, "empty_text": "-"}
    d.update(extra); return d

def test_engine_without_new_keys_still_renders():
    assert render_report_pdf(_doc("fr"), [{"a": "x"}]).startswith(b"%PDF")

def test_engine_with_blocks_signatures_and_company_lines_in_arabic():
    doc = _doc("ar", company={"name": "Sahel", "tagline": "Un partenaire", "lines": ["NIF : 1"]},
               blocks=[{"title": "المبلغ", "text": "ألف فرنك", "boxed": True}],
               signatures=["المستلم", "المورد"])
    assert render_report_pdf(doc, [{"a": "BP 8795 MD"}]).startswith(b"%PDF")
```

- [ ] **Step 2: Run → FAIL** sur le 2e test (`summary=[]` et les nouvelles clés ne sont pas encore gérées). Le contenu d'un PDF compressé n'est pas lisible en clair : on vérifie le rendu sans exception ici, et le visuel en Task 10.
- [ ] **Step 3: Implement** — dans `_header_block` : si `company.get("tagline")`, `Paragraph` italique gris sous le nom. Dans `build_report_flowables` : `if document["summary"]: elements.append(_summary_block(...))`, puis `_blocks(document, available, rtl)` (chaque bloc : titre gras 9 pt + texte 9 pt, `boxed` → `Table` 1 cellule avec `BOX 0.8 INK` et fond `TOTAL_FILL`), puis `_signatures(...)` (`Table` d'une ligne, une colonne par libellé, `BOX` par cellule, `KeepTogether`), puis `_footer(...)` (`HRFlowable` + lignes `company["lines"]` 7 pt `MUTED` centrées). Utiliser `_p()` pour tout texte (gère arabe/RTL).
- [ ] **Step 4: Run → PASS** + `pytest apps/reports -q` (aucune régression).

---

### Task 4: Proforma (backend)

**Files:**
- Modify: `backend/apps/quotations/models.py` (2 champs), `serializers.py` (champs), `views.py` (préfixe `PF`, `pdf()` → nouveau builder, nom de fichier `proforma-…`)
- Create: `backend/apps/reports/services/proforma_pdf.py` ; migration `quotations/00xx_proforma_fields.py`
- Delete: `backend/apps/reports/services/quotation_pdf.py` (remplacé ; retirer ses imports/tests)
- Test: ajouts dans `backend/apps/quotations/tests.py`

**Interfaces:**
- Consumes: `amount_in_words` (Task 2), `CompanyProfile.pdf_company()` (Task 1), clés moteur (Task 3).
- Produces: `build_priced_document(*, title, number, party_label, party: dict, info: list, lines, total, currency, payment_terms, notes, lang, banks: bool, signatures: list[str]) -> (document, rows)` dans `proforma_pdf.py` — **réutilisé par le bon de commande (Task 6)** ; `render_proforma_pdf(quotation, lang) -> bytes`.

- [ ] **Step 1: Tests**

```python
@pytest.mark.django_db
def test_new_proforma_reference_uses_pf_prefix_and_terms():
    client, _ = _sales_client("PF1")
    r = client.post("/api/quotations/", {
        "customer_name": "SAHEL COMMERCE", "issue_date": "2026-09-24",
        "payment_terms": "Avance de 30% obligatoire", "show_bank_accounts": True,
        "lines": [{"description": "Gasoil export", "quantity": "500", "unit": "M3", "unit_price": "775000"}],
    }, format="json")
    assert r.status_code == 201, r.data
    assert r.data["reference"].startswith("PF-")
    assert r.data["total_amount"] == "387500000.00"


@pytest.mark.django_db
@pytest.mark.parametrize("lang", ["fr", "en", "ar"])
def test_proforma_pdf_in_every_language(lang):
    from apps.reports.services.proforma_pdf import build_proforma_document
    client, _ = _sales_client(f"PF{lang}")
    q = client.post("/api/quotations/", {"customer_name": "SAHEL", "issue_date": "2026-09-24",
        "lines": [{"description": "Gasoil", "quantity": "500", "unit": "M3", "unit_price": "775000"}]},
        format="json").data
    document, rows = build_proforma_document(Quotation.objects.get(pk=q["id"]), lang)
    assert rows[0]["amount"] == Decimal("387500000.00")
    words = {"fr": "millions", "en": "million", "ar": "مليون"}[lang]
    assert words in document["blocks"][0]["text"]  # montant en lettres
    pdf = client.get(f"/api/quotations/{q['id']}/pdf/?lang={lang}")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert "proforma-" in pdf["Content-Disposition"]
```

- [ ] **Step 2: Run → FAIL**.
- [ ] **Step 3: Implement**
  - Modèle : `payment_terms = models.CharField(max_length=255, blank=True)`, `show_bank_accounts = models.BooleanField(default=True)` ; ajouter aux `fields` du serializer ; `_REFERENCE_PREFIX = "PF"`.
  - `proforma_pdf.py` : dictionnaire `_TEXT` fr/en/ar (title « Facture proforma »/« Proforma invoice »/« فاتورة شكلية », `billed_to`, `date`, `due`, `cash` « Comptant », `validity`, `currency`, `lines`, `designation`, `quantity`, `unit`, `unit_price`, `amount`, `total_ht`, `total_to_pay` « Total à payer », `in_words` « Arrêté à la somme de », `terms` « Conditions de paiement », `notes`, `banks` « Comptes bancaires », `bank`, `swift`, `account`, `supplier`, `order_title` « Bon de commande », `delivery_place`, `delivery_date`, `for_company` « Pour l'entreprise », `empty`).
  - `build_priced_document(...)` : `company = CompanyProfile.load().pdf_company()` ; `info` = party (nom, adresse, téléphone) + infos passées ; table 1 colonnes `designation(text) / quantity(quantity,end) / unit(text) / unit_price(unit_money,end) / amount(money,end)` (`section: "lines"`) ; si `banks` et `company["banks"]` → table 2 `section: "banks"` colonnes bank/swift/account ; `summary = [{"label": total_to_pay, "value": total, "kind": "money", "emphasis": True}]` ; `blocks = [{"title": in_words, "text": amount_in_words(total, lang, currency), "boxed": True}]` + terms + notes si non vides ; `signatures` passées ; `orientation "portrait"`.
  - `build_proforma_document(q, lang)` → `build_priced_document(title=f"{_t('title')} N° {q.reference}", party_label=billed_to, party={nom: q.customer_display_name, address/phone du client si FK}, info=[date, échéance (validité ou « Comptant »), devise], banks=q.show_bank_accounts, signatures=[])` ; `render_proforma_pdf`.
  - Vue `pdf()` : `render_proforma_pdf`, `filename="proforma-{reference}.pdf"`. Supprimer `quotation_pdf.py` et adapter les tests qui l'importaient (`grep -rn quotation_pdf backend`).
- [ ] **Step 4: Run** `pytest apps/quotations apps/reports -q` → PASS.

---

### Task 5: App `commercial_documents` (modèles, API, pré-remplissage)

**Files:**
- Create: `backend/apps/commercial_documents/{__init__,apps,models,serializers,views,urls}.py`, migration `0001_initial.py`
- Modify: `backend/config/settings/base.py` (INSTALLED_APPS), `backend/config/urls.py`
- Test: `backend/apps/commercial_documents/tests.py`

**Interfaces:**
- Produces:
  - Modèles `DeliveryNote(+DeliveryNoteLine)`, `LoadingSheet(+LoadingSheetLine)`, `PurchaseOrderDocument(+PurchaseOrderLine)`; lignes `related_name="lines"`, champ `position`.
  - API (`ModelViewSet`) : `/api/delivery-notes/` (sales), `/api/loading-sheets/` (purchasing), `/api/purchase-order-documents/` (purchasing) ; filtres `customer`/`supplier` ; `GET …/{id}/pdf/?lang=` (builder fourni Task 6 via attribut de classe `pdf_builder` = chemin pointé `"module:function"`).
  - `GET /api/delivery-notes/deliverable-trips/?customer=<id>` → `[{"trip", "reference", "loading_date", "product", "quantity", "tanker", "tractor", "missing", "other_notes": ["BL-…"]}]` (trajets `client=customer`, statut `DELIVERED|COMPLETED`, tri date desc).
  - `DeliveryNoteLine.from_trip(trip) -> dict` (valeurs de ligne pré-remplies).

- [ ] **Step 1: Tests** (helpers `_client(module_role)` = admin comme dans `quotations/tests.py`; trajet via les fixtures existantes de `apps/trips/tests.py` — réutiliser sa fabrique `_make_trip`/équivalent, `grep -n "^def _" apps/trips/tests.py`)

```python
@pytest.mark.django_db
def test_delivery_note_from_trips_with_reference_and_lines(admin_client, delivered_trip):
    trips = admin_client.get(f"/api/delivery-notes/deliverable-trips/?customer={delivered_trip.client_id}").data
    assert trips[0]["tractor"] == delivered_trip.truck.tractor_registration
    line = {k: trips[0][k] for k in ("trip", "quantity", "tanker", "tractor", "missing")}
    r = admin_client.post("/api/delivery-notes/", {
        "customer": delivered_trip.client_id, "date": "2026-04-18", "place": "Bamako",
        "delivery_address": "Keneba", "lines": [{**line, "designation": "GASOIL"}]}, format="json")
    assert r.status_code == 201, r.data
    assert r.data["reference"].startswith("BL-")
    again = admin_client.get(f"/api/delivery-notes/deliverable-trips/?customer={delivered_trip.client_id}").data
    assert again[0]["other_notes"] == [r.data["reference"]]   # avertissement, pas de blocage


@pytest.mark.django_db
def test_trip_without_delivery_control_uses_loaded_quantity(delivered_trip):
    from apps.commercial_documents.models import DeliveryNoteLine
    delivered_trip.delivery_control.delete() if hasattr(delivered_trip, "delivery_control") else None
    delivered_trip.refresh_from_db()
    data = DeliveryNoteLine.from_trip(delivered_trip)
    assert data["quantity"] == delivered_trip.quantity_loaded and data["missing"] is None


@pytest.mark.django_db
def test_loading_sheet_manual_line_and_blank_line_rejected(admin_client):
    ok = admin_client.post("/api/loading-sheets/", {"date": "2026-06-29", "supplier_name": "Dépôt Moussala",
        "on_behalf_of": "SAHEL COMMERCE", "product_name": "GASOIL", "route": "MOUSSALA",
        "lines": [{"tractor": "BA 2947 MD", "tanker": "BA 1591 MD", "capacity_litres": "45000", "be_number": "NUM006"}]},
        format="json")
    assert ok.status_code == 201 and ok.data["reference"].startswith("BCH-")
    assert ok.data["total_litres"] == "45000.00"
    bad = admin_client.post("/api/loading-sheets/", {"date": "2026-06-29", "supplier_name": "X",
        "lines": [{"capacity_litres": "45000"}]}, format="json")
    assert bad.status_code == 400


@pytest.mark.django_db
def test_purchase_order_total_and_supplier_required(admin_client, supplier, gasoil):
    r = admin_client.post("/api/purchase-order-documents/", {"supplier": supplier.id, "date": "2026-10-11",
        "lines": [{"product": gasoil.id, "quantity": "180000", "unit": "L", "unit_price": "750"}]}, format="json")
    assert r.status_code == 201 and r.data["reference"].startswith("BCF-")
    assert r.data["total_amount"] == "135000000.00"
    assert admin_client.post("/api/purchase-order-documents/", {"date": "2026-10-11",
        "lines": [{"description": "x", "quantity": "1", "unit_price": "1"}]}, format="json").status_code == 400


@pytest.mark.django_db
def test_module_permissions(sales_only_client):
    assert sales_only_client.get("/api/delivery-notes/").status_code == 200
    assert sales_only_client.get("/api/loading-sheets/").status_code == 403
```

Fixtures locales (dans le fichier) : `admin_client`, `sales_only_client` (rôle créé avec `permissions={"sales": ["view","create","edit"]}`), `supplier`, `gasoil` (`Product.objects.get(code="gasoil")`), `delivered_trip` (trajet DELIVERED avec `client` et `DeliveryControl` loss=200).

- [ ] **Step 2: Run → FAIL**.
- [ ] **Step 3: Implement**

```python
# models.py
class BaseDocument(TimeStampedModel):
    reference = models.CharField(max_length=50, unique=True)
    date = models.DateField()
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="+")

    class Meta:
        abstract = True
        ordering = ["-date", "-id"]

class BaseLine(models.Model):
    position = models.PositiveIntegerField(default=0)
    class Meta:
        abstract = True
        ordering = ["position", "id"]

class DeliveryNote(BaseDocument):
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="delivery_notes")
    place = models.CharField(max_length=100, blank=True)
    delivery_address = models.CharField(max_length=255, blank=True)

class DeliveryNoteLine(BaseLine):
    note = models.ForeignKey(DeliveryNote, on_delete=models.CASCADE, related_name="lines")
    trip = models.ForeignKey("trips.Trip", null=True, blank=True, on_delete=models.SET_NULL, related_name="delivery_note_lines")
    designation = models.CharField(max_length=150)
    quantity = models.DecimalField(max_digits=14, decimal_places=2)
    tanker = models.CharField(max_length=30, blank=True)
    tractor = models.CharField(max_length=30, blank=True)
    missing = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    observation = models.CharField(max_length=255, blank=True)

    @staticmethod
    def from_trip(trip) -> dict:
        control = getattr(trip, "delivery_control", None)
        return {"trip": trip.id, "designation": trip.product.name.upper(),
                "quantity": control.received_quantity if control else trip.quantity_loaded,
                "tanker": trip.truck.tanker_registration, "tractor": trip.truck.tractor_registration,
                "missing": control.loss_quantity if control else None}

class LoadingSheet(BaseDocument):
    supplier = models.ForeignKey("suppliers.Supplier", null=True, blank=True, on_delete=models.PROTECT, related_name="loading_sheets")
    supplier_name = models.CharField(max_length=150, blank=True)
    on_behalf_of = models.CharField(max_length=150, blank=True)
    source_reference = models.CharField(max_length=100, blank=True)
    product_name = models.CharField(max_length=100, blank=True)
    route = models.CharField(max_length=100, blank=True)
    # contrainte: supplier ou supplier_name (CheckConstraint, comme Quotation)

class LoadingSheetLine(BaseLine):
    sheet = models.ForeignKey(LoadingSheet, on_delete=models.CASCADE, related_name="lines")
    truck = models.ForeignKey("transport.Truck", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    tractor = models.CharField(max_length=30, blank=True)
    tanker = models.CharField(max_length=30, blank=True)
    capacity_litres = models.DecimalField(max_digits=10, decimal_places=2)
    product_name = models.CharField(max_length=100, blank=True)
    be_number = models.CharField(max_length=50, blank=True)
    route = models.CharField(max_length=100, blank=True)

class PurchaseOrderDocument(BaseDocument):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SENT = "SENT", "Sent"
    supplier = models.ForeignKey("suppliers.Supplier", on_delete=models.PROTECT, related_name="purchase_order_documents")
    supplier_order = models.ForeignKey("purchasing.SupplierOrder", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    delivery_place = models.CharField(max_length=150, blank=True)
    delivery_date = models.DateField(null=True, blank=True)
    payment_terms = models.CharField(max_length=255, blank=True)
    currency = models.CharField(max_length=10, default="XOF")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    total_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0, editable=False)

class PurchaseOrderLine(BaseLine):
    order = models.ForeignKey(PurchaseOrderDocument, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey("core.Product", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    description = models.CharField(max_length=255, blank=True)
    quantity = models.DecimalField(max_digits=14, decimal_places=2)
    unit = models.CharField(max_length=20, blank=True)
    unit_price = models.DecimalField(max_digits=14, decimal_places=4)
    line_total = models.DecimalField(max_digits=16, decimal_places=2, editable=False)

    def save(self, *a, **k):
        self.line_total = (self.quantity * self.unit_price).quantize(Decimal("0.01"))
        super().save(*a, **k)
```

Contraintes : quantités/capacités `> 0`, prix `>= 0` (CheckConstraint).

```python
# serializers.py
class BaseDocumentSerializer(serializers.ModelSerializer):
    """Lignes imbriquées, remplacement complet (même règle que QuotationSerializer)."""
    line_fk = None  # nom du FK ligne -> document
    def validate_lines(self, lines):
        if not lines:
            raise serializers.ValidationError("Au moins une ligne est requise.")
        return lines
    def _sync(self, doc, lines):
        model = self.fields["lines"].child.Meta.model
        doc.lines.all().delete()
        for i, data in enumerate(lines):
            model.objects.create(**{self.line_fk: doc}, position=i, **data)
        self.after_lines(doc)
    def after_lines(self, doc):
        pass
    @transaction.atomic
    def create(self, data):
        lines = data.pop("lines"); doc = super().create(data); self._sync(doc, lines); return doc
    @transaction.atomic
    def update(self, doc, data):
        lines = data.pop("lines", None); doc = super().update(doc, data)
        if lines is not None: self._sync(doc, lines)
        return doc
```

Sous-classes : `DeliveryNoteSerializer` (`customer_detail` = `CustomerBriefSerializer`), `LoadingSheetSerializer` (+ `total_litres` `SerializerMethodField` = somme des capacités ; ligne `validate` : `tractor` ou `tanker` ou `truck` requis), `PurchaseOrderDocumentSerializer` (`after_lines` recalcule `total_amount` ; ligne `validate` : produit ou description). `read_only_fields = ["reference", "created_by", ...]`. Document `validate` : `LoadingSheet` → `supplier` ou `supplier_name`.

```python
# views.py
class BaseDocumentViewSet(viewsets.ModelViewSet):
    permission_classes = [HasModulePermission]
    prefix = ""; pdf_builder = ""; filename = ""

    def perform_create(self, serializer):
        model = serializer.Meta.model
        for _ in range(5):
            try:
                with transaction.atomic():
                    serializer.save(reference=generate_monthly_reference(model, "reference", self.prefix),
                                    created_by=self.request.user)
                return
            except IntegrityError:
                continue
        raise IntegrityError("Référence unique impossible à générer.")

    @action(detail=True, methods=["get"])
    def pdf(self, request, pk=None):
        module, func = self.pdf_builder.split(":")
        render = getattr(importlib.import_module(module), func)
        doc = self.get_object()
        response = HttpResponse(render(doc, request.query_params.get("lang", "fr")), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{self.filename}-{doc.reference}.pdf"'
        return response
```

3 sous-classes (`module`, `prefix`, `pdf_builder="apps.reports.services.document_pdfs:render_delivery_note_pdf"` etc., `filename` `bon-livraison`/`bon-chargement`/`bon-commande`, `queryset` avec `select_related`/`prefetch_related("lines")`, `filterset_fields`). `DeliveryNoteViewSet.deliverable_trips` = `@action(detail=False, url_path="deliverable-trips")` : `Trip.objects.filter(client_id=…, status__in=[DELIVERED, COMPLETED]).select_related("truck","product","delivery_control")`, `other_notes` via `DeliveryNoteLine.objects.filter(trip_id__in=…).values_list("trip_id","note__reference")`. Enregistrer l'app + `path("api/", include("apps.commercial_documents.urls"))`. `makemigrations commercial_documents`.

- [ ] **Step 4: Run** `pytest apps/commercial_documents -q` → PASS (la route `pdf` est testée Task 6).

---

### Task 6: PDF des 3 documents

**Files:**
- Create: `backend/apps/reports/services/document_pdfs.py`
- Test: ajouts dans `backend/apps/commercial_documents/tests.py`

**Interfaces:**
- Consumes: `build_priced_document` (Task 4), `CompanyProfile.pdf_company()`, moteur (Task 3).
- Produces: `render_delivery_note_pdf(note, lang)`, `render_loading_sheet_pdf(sheet, lang)`, `render_purchase_order_pdf(order, lang)` → `bytes` (+ `build_*_document` → `(document, rows)` pour les tests).

- [ ] **Step 1: Tests**

```python
@pytest.mark.django_db
@pytest.mark.parametrize("lang", ["fr", "en", "ar"])
def test_every_document_pdf_renders(admin_client, delivered_trip, supplier, lang):
    created = [
        ("delivery-notes", {"customer": delivered_trip.client_id, "date": "2026-04-18",
            "lines": [{"designation": "GASOIL", "quantity": "45000", "tanker": "BP 8795 MD", "tractor": "AZ 7969 MD"}]}),
        ("loading-sheets", {"date": "2026-06-29", "supplier_name": "Moussala",
            "lines": [{"tractor": "BA 2947 MD", "tanker": "BA 1591 MD", "capacity_litres": "45000"}]}),
        ("purchase-order-documents", {"supplier": supplier.id, "date": "2026-10-11",
            "lines": [{"description": "Gasoil", "quantity": "1000", "unit": "L", "unit_price": "750"}]}),
    ]
    for path, body in created:
        doc = admin_client.post(f"/api/{path}/", body, format="json").data
        r = admin_client.get(f"/api/{path}/{doc['id']}/pdf/?lang={lang}")
        assert r.status_code == 200 and r.content.startswith(b"%PDF"), path


@pytest.mark.django_db
def test_delivery_note_document_totals_and_signatures(admin_client, delivered_trip):
    from apps.commercial_documents.models import DeliveryNote
    from apps.reports.services.document_pdfs import build_delivery_note_document
    body = {"customer": delivered_trip.client_id, "date": "2026-04-18", "lines": [
        {"designation": "GASOIL", "quantity": "45000"}, {"designation": "GASOIL", "quantity": "45000"}]}
    note = DeliveryNote.objects.get(pk=admin_client.post("/api/delivery-notes/", body, format="json").data["id"])
    document, rows = build_delivery_note_document(note, "fr")
    assert [r["number"] for r in rows] == [1, 2]
    assert document["summary"][0]["value"] == Decimal("90000.00")
    assert document["signatures"] == ["Le réceptionnaire", "Le fournisseur"]


@pytest.mark.django_db
def test_loading_sheet_document_is_landscape_with_litre_total(admin_client):
    from apps.commercial_documents.models import LoadingSheet
    from apps.reports.services.document_pdfs import build_loading_sheet_document
    body = {"date": "2026-06-29", "supplier_name": "Moussala", "on_behalf_of": "SAHEL COMMERCE",
            "lines": [{"tractor": "T", "capacity_litres": "45000"}] * 4}
    sheet = LoadingSheet.objects.get(pk=admin_client.post("/api/loading-sheets/", body, format="json").data["id"])
    document, _ = build_loading_sheet_document(sheet, "fr")
    assert document["orientation"] == "landscape"
    assert "SAHEL COMMERCE" in document["title"]
    assert document["summary"][0]["value"] == Decimal("180000.00")
```

- [ ] **Step 2: Run → FAIL**.
- [ ] **Step 3: Implement** — `_TEXT` fr/en/ar (delivery_title « Bon de livraison N° », receiver « Le réceptionnaire », supplier_sig « Le fournisseur », customer, delivery_address, place_date « {place}, le {date} », number « N° », designation, quantity, tanker « Citerne », tractor « Tracteur », missing « Manquant », observation, total_qty « Quantité totale (L) », loading_title « Liste des camions au compte de {name} », supplier « Fournisseur / dépôt », reference « Référence », product, route « Axe », capacity « Capacité (L) », be « N° BE », trucks « Camions », total_litres « Total (L) »). Chaque builder :
  - `company = CompanyProfile.load().pdf_company()` ; `document` = mêmes clés que `invoice_pdf.build_invoice_document` + `company`, `blocks` (notes si non vides), `signatures`.
  - Bon de livraison : info = lieu/date, client, adresse de livraison ; colonnes number/designation/quantity/tanker/tractor/missing/observation ; `summary=[total_qty]` (emphasis) ; `signatures=[receiver, supplier_sig]` ; portrait.
  - Bon de chargement : titre `loading_title.format(name=sheet.on_behalf_of or company["name"])` ; info = date, fournisseur (FK nom ou `supplier_name`), référence, produit, axe ; colonnes number/tractor/tanker/capacity/product/be/route ; `summary=[trucks (kind "text" nombre), total_litres (emphasis)]` ; landscape ; pas de signatures.
  - Bon de commande : `build_priced_document(title=f"{order_title} N° {ref}", party_label=supplier, party=fournisseur (nom/adresse/téléphone), info=[date, livraison souhaitée, lieu de livraison, devise], banks=False, signatures=[for_company])`.
  - Pour `summary` de kind texte : vérifier `_summary_text` (`report_pdf.py:110`) ; ajouter le kind `"quantity"` s'il manque.
- [ ] **Step 4: Run** `pytest apps/commercial_documents apps/quotations apps/reports -q` → PASS.

---

### Task 7: Frontend — Informations de l'entreprise

**Files:**
- Create: `frontend/src/modules/settings/CompanyProfileSettings.vue`, `frontend/src/modules/settings/__tests__/CompanyProfileSettings.spec.ts`
- Modify: `frontend/src/modules/settings/{api,types}.ts`, `frontend/src/router/index.ts` (route `settings/company`, name `company-settings`), `frontend/src/modules/shell/AppShell.vue` (entrée Paramètres, `module: 'admin'`, icône `building` ou existante), locales (`settings.company.*`, `navigation.companySettings`).

**Interfaces:**
- Produces: `fetchCompanyProfile(): Promise<CompanyProfile>`, `updateCompanyProfile(p: Partial<CompanyProfile>): Promise<CompanyProfile>` ; type `CompanyProfile { name, tagline, tax_id, trade_register, address, city, phone, email, website, bank_accounts: CompanyBankAccount[] }`, `CompanyBankAccount { id?, bank, swift, account_number, is_active }`.

- [ ] **Step 1: Spec** — monte la page avec `fetchCompanyProfile` mocké, change le nom, ajoute un compte (bouton `data-test="add-bank"`), clique `data-test="save-company"` → `updateCompanyProfile` appelé avec `bank_accounts` de longueur 1.
- [ ] **Step 2: Run → FAIL**.
- [ ] **Step 3: Implement** — calqué sur `LossToleranceSettings.vue` : `Card` « Coordonnées » (grille 2 colonnes `Input` : nom, slogan, NIF, RC, adresse, ville, téléphone, e-mail, site), `Card` « Comptes bancaires » (lignes banque / SWIFT / numéro / actif + supprimer ; bouton « Ajouter un compte »), `FormActions` Enregistrer, `AppAlert` succès/erreur ; aide en tête : « Ces informations apparaissent sur les proformas, bons de livraison, de chargement et de commande. »
- [ ] **Step 4: Run** spec + `vue-tsc -b` → PASS.

---

### Task 8: Frontend — Section Documents, liste générique, Proforma

**Files:**
- Create: `frontend/src/modules/documents/{api,types,configs}.ts`, `frontend/src/modules/documents/DocumentList.vue`, `frontend/src/modules/documents/__tests__/DocumentList.spec.ts`
- Modify: `frontend/src/router/index.ts`, `frontend/src/modules/shell/AppShell.vue`, `frontend/src/modules/quotations/{QuotationForm.vue,api.ts}`, locales (`documents.*`, `navigation.groups.documents`, `navigation.{proformas,deliveryNotes,loadingSheets,purchaseOrders}` ; libellés « Offre commerciale » → « Proforma » dans `quotations.*`), spec existante `QuotationList`/navigation si elle cible les anciens libellés.
- Delete: `frontend/src/modules/quotations/QuotationList.vue` (+ sa spec ; remplacée par `DocumentList` config `proforma`).

**Interfaces:**
- Produces:
  - `documents/api.ts` : `documentApi(path: string)` → `{ list(params), get(id), create(body), update(id, body), remove(id) }` via `createResourceApi` ; `downloadDocumentPdf(path, id, filename, lang)` ; `printDocumentPdf(path, id, lang)` (blob → `URL.createObjectURL` → `window.open` → `print()` sur `load`) ; `fetchDeliverableTrips(customerId)`.
  - `configs.ts` : `DocumentConfig { key: 'proforma'|'delivery'|'loading'|'purchase'; path: string; module: string; titleKey; newKey; emptyKey; formRoute: string; filename: string; partyKey: 'customer_name'|'customer'|'supplier'|'supplier_name'; amountField?: 'total_amount'|'total_litres'; statusField?: string }` et `DOCUMENT_CONFIGS: Record<key, DocumentConfig>` (proforma → path `/quotations/`, filename `proforma`, formRoute `proforma-detail`).
  - Routes : `documents/:kind(proformas|delivery-notes|loading-sheets|purchase-orders)` → `DocumentList` (prop `kind`), `documents/proformas/new|:id` → `QuotationForm`, `documents/delivery-notes/new|:id`, `documents/loading-sheets/new|:id`, `documents/purchase-orders/new|:id` (Task 9) ; redirections `quotations` → `documents/proformas`, `quotations/:id` → `documents/proformas/:id`.

- [ ] **Step 1: Spec** — `DocumentList` avec `kind="delivery-notes"` : liste mockée → affiche référence + client ; clic `data-test="doc-pdf"` → `downloadDocumentPdf` ; clic `data-test="doc-print"` → `printDocumentPdf` ; bouton `data-test="doc-new"` → route `delivery-note-new` ; `kind="proformas"` → affiche le filtre statut et `Dupliquer`.
- [ ] **Step 2: Run → FAIL**.
- [ ] **Step 3: Implement** — `DocumentList.vue` reprend le gabarit de l'ancien `QuotationList.vue` (titre, filtre statut si `statusField`, bouton orange, tableau Référence / Partenaire / Date / Montant ou Litres / Statut / actions Ouvrir · PDF · Imprimer · Dupliquer(proforma) · Supprimer (`ConfirmDialog`)). Nav : nouveau groupe `{ key: 'documents', titleKey: 'navigation.groups.documents', items: [proformas(sales), deliveryNotes(sales), loadingSheets(purchasing), purchaseOrders(purchasing)] }` placé après VENTES ; retirer `quotations` de VENTES. `QuotationForm` : titres « Proforma », champs `payment_terms` (Input) et `show_bank_accounts` (case), boutons PDF/Imprimer, routes `proforma-*` ; `exportQuotationPdf` → nom `proforma-…`.
- [ ] **Step 4: Run** `vitest run src/modules/documents src/modules/quotations src/modules/shell` + `vue-tsc -b` → PASS.

---

### Task 9: Frontend — 3 formulaires

**Files:**
- Create: `frontend/src/modules/documents/{LinesTable.vue,DeliveryNoteForm.vue,LoadingSheetForm.vue,PurchaseOrderForm.vue}`, `frontend/src/modules/documents/__tests__/DocumentForms.spec.ts`
- Modify: `frontend/src/router/index.ts`, locales (`documents.delivery.*`, `documents.loading.*`, `documents.purchase.*`, `documents.lines.*`).

**Interfaces:**
- Consumes: `documentApi`, `fetchDeliverableTrips`, `downloadDocumentPdf`, `printDocumentPdf` (Task 8) ; `customerResource`, `supplierResource`, `truckResource`, `supplierOrderResource`, `productResource` existants (`grep -rn "createResourceApi" src/modules/*/api.ts`).
- Produces: `LinesTable.vue` props `{ columns: { field: string; labelKey: string; type: 'text'|'number'; width?: string }[]; modelValue: Record<string, unknown>[] }`, emits `update:modelValue` ; bouton « Ajouter une ligne » + suppression par ligne ; total optionnel prop `totalField`.

- [ ] **Step 1: Spec** (3 tests)
  1. Bon de livraison : choisir le client → `fetchDeliverableTrips` appelé ; cocher 2 trajets → 2 lignes pré-remplies (tracteur visible) ; trajet avec `other_notes` → badge « Déjà sur BL-… » ; Enregistrer → `create` reçoit `lines.length === 2`.
  2. Bon de chargement : étape 1 (fournisseur libre, au compte de, produit, axe) → « Suivant » ; étape 2 : sélection de 2 camions → lignes avec capacité, produit/axe repris de l'étape 1 ; total litres affiché.
  3. Bon de commande : choisir une commande fournisseur → fournisseur, produit, quantité, prix remplis ; total = quantité × prix.
- [ ] **Step 2: Run → FAIL**.
- [ ] **Step 3: Implement**
  - `DeliveryNoteForm.vue` : en-tête (client `SearchableSelect`, date, lieu, adresse de livraison préremplie avec `customer.address`, notes) ; carte « Trajets livrés » (cases à cocher : référence, date, camion, quantité, badge déjà sur un bon) ; cocher → ajoute la ligne de `from_trip`, décocher → retire ; `LinesTable` colonnes designation/quantity/tanker/tractor/missing/observation ; actions Enregistrer, PDF, Imprimer (après enregistrement).
  - `LoadingSheetForm.vue` : étape 1 « Informations » (fournisseur : select fournisseurs + option « Autre » → texte ; date ; au compte de (défaut nom entreprise via `fetchCompanyProfile`) ; référence (texte, suggestions commandes fournisseur / lettres de cession) ; produit ; axe) ; étape 2 « Camions » (recherche + cases sur camions actifs : tracteur, citerne, capacité) → lignes ; `LinesTable` colonnes tractor/tanker/capacity_litres/product_name/be_number/route avec total ; une fiche existante s'ouvre directement à l'étape 2 avec l'étape 1 repliable.
  - `PurchaseOrderForm.vue` : fournisseur, « Pré-remplir depuis une commande fournisseur » (select), date, lieu et date de livraison, conditions, devise, statut ; `LinesTable` colonnes description/quantity/unit/unit_price + montant calculé et total.
  - Tous : erreurs API affichées via `AppAlert`, redirection vers `…/:id` après création.
- [ ] **Step 4: Run** `vitest run src/modules/documents` + `vue-tsc -b` + `eslint src/modules/documents` + `prettier --check src/locales/*.json src/modules/documents` → PASS.

---

### Task 10: Vérification finale

- [ ] **Step 1:** Suites complètes : backend (commande Global Constraints, sans cible) ; frontend `npx vitest run`, `npx vue-tsc -b`, `npx eslint src`.
- [ ] **Step 2:** Copie de base (recette QA habituelle : `createdb` copie de `fuel_erp_empty_test`, `migrate`, runserver 127.0.0.1:8001, Playwright avec `/api` routé vers 8001) : renseigner le profil entreprise (données fictives), créer une proforma (500 M3 × 775 000), un bon de livraison (2 trajets livrés), un bon de chargement (4 camions), un bon de commande ; télécharger chaque PDF en fr et ar, les ouvrir et vérifier visuellement (montant en lettres, signatures, total litres, pied de page, RTL) ; vérifier Imprimer (nouvel onglet). Supprimer la copie.
- [ ] **Step 3:** Rapport à l'utilisateur ; attendre son feu vert pour commit/déploiement (nouvelles migrations : `core`, `quotations`, `commercial_documents`).
