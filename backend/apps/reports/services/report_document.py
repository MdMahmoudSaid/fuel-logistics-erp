# Report document builder (docs/superpowers/specs/2026-09-23-rapports-document-
# comptable-design.md, section Architecture / Backend). One ReportSpec per
# report slug declares its tables/columns, orientation, entity and summary;
# build_report_document() turns (rows, params, lang) into the `document`
# payload that BOTH the Vue ReportSheet and the PDF renderer consume, so the
# totals on screen and in the PDF come from the same computation (D2).
#
# Nothing here invents data: every summary value is a sum/count over the rows
# handed in (D7: CANCELLED rows stay displayed but leave amounts, quantities,
# margins and counts), or comes from the query's own statement_context.

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.reports.services.pdf_template import DEFAULT_COMPANY_NAME
from apps.reports.services.report_labels import LABELS

ZERO = Decimal("0.00")
CURRENCY = "XOF"  # D1: official application currency
CANCELLED = "CANCELLED"

# (field, kind[, enum namespace]) - kind: date | text | ref | money |
# unit_money | quantity | enum | status
Column = tuple


@dataclass(frozen=True)
class TableSpec:
    columns: tuple
    emphasis: dict | None = None  # {"field": ..., "equals": ...}: rows printed bold
    section: str | None = None  # only rows whose row["section"] equals it


@dataclass(frozen=True)
class ReportSpec:
    orientation: str
    tables: tuple
    summarize: Callable
    entity: tuple | None = None  # (entity kind, query param)
    period_mode: str = "range"  # or "as_of"
    opening_row: bool = False


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _dec(value):
    return None if value is None else Decimal(str(value))


def _sum(rows, field) -> Decimal:
    return sum((_dec(row.get(field)) for row in rows if row.get(field) is not None), ZERO)


def _to_date(value):
    if isinstance(value, str):
        return parse_date(value) if value else None
    return value


def _fmt_date(value) -> str:
    return value.strftime("%d/%m/%Y")


def _line(key, value, kind, emphasis=False):
    return {"key": key, "value": value, "kind": kind, "emphasis": emphasis}


def _split_cancelled(slug, rows):
    """(rows counted in totals, number of CANCELLED rows excluded) - D7.
    margin-report rows carry no status, so trip statuses are looked up by
    trip_reference (one query, only when there are rows)."""
    if slug == "margin-report":
        if not rows:
            return [], 0
        from apps.trips.models import Trip

        cancelled_refs = set(
            Trip.objects.filter(
                reference__in=[row["trip_reference"] for row in rows], status=Trip.Status.CANCELLED
            ).values_list("reference", flat=True)
        )
        kept = [row for row in rows if row["trip_reference"] not in cancelled_refs]
    else:
        kept = [row for row in rows if row.get("status") != CANCELLED]
    return kept, len(rows) - len(kept)


# ---------------------------------------------------------------------------
# Summaries: (rows, statement_context) -> list of summary lines
# ---------------------------------------------------------------------------


def _party_statement_summary(direction):
    def summarize(slug, rows, context):
        opening = _dec(context.get("opening_balance")) or ZERO
        debit, credit = _sum(rows, "debit"), _sum(rows, "credit")
        net = direction * (debit - credit)
        closing = opening + net
        lines = [
            _line("opening_balance", opening, "money"),
            _line("total_debit", debit, "money"),
            _line("total_credit", credit, "money"),
            _line("net_movement", net, "money"),
        ]
        if rows:
            gap = _dec(rows[-1]["balance"]) - closing
            if gap:
                lines.append(_line("reconciliation_gap", gap, "money"))
        lines.append(_line("closing_balance", closing, "money", True))
        return lines

    return summarize


def _treasury_summary(slug, rows, context):
    opening = _dec(context.get("opening_balance")) or ZERO
    transfers = _dec(context.get("transfers_net")) or ZERO
    total_in = sum((_dec(r["amount"]) for r in rows if r["type"] == "MONEY_IN"), ZERO)
    total_out = sum((_dec(r["amount"]) for r in rows if r["type"] == "MONEY_OUT"), ZERO)
    equation = opening + total_in - total_out + transfers
    closing = _dec(context.get("closing_balance"))
    lines = [
        _line("opening_balance", opening, "money"),
        _line("total_in", total_in, "money"),
        _line("total_out", total_out, "money"),
        _line("internal_transfers", transfers, "money"),
    ]
    if closing is None:
        closing = equation
    elif closing != equation:
        lines.append(_line("reconciliation_gap", closing - equation, "money"))
    lines.append(_line("closing_balance", closing, "money", True))
    return lines


def _transporter_summary(slug, rows, context):
    return [
        _line("total_base_amount", _sum(rows, "base_amount"), "money"),
        _line("total_deduction", _sum(rows, "deduction_amount"), "money"),
        _line("total_advance", _sum(rows, "advance_applied"), "money"),
        _line("total_net", _sum(rows, "net_amount"), "money", True),
    ]


def _truck_history_summary(slug, rows, context):
    kept, cancelled = _split_cancelled(slug, rows)
    return [
        _line("trips_count", len(kept), "count"),
        _line("total_quantity", _sum(kept, "quantity_loaded"), "quantity"),
        _line("margin_total", _sum(kept, "current_margin"), "money"),
        _line("cancelled_excluded", cancelled, "count"),
    ]


def _trip_summary(slug, rows, context):
    kept, cancelled = _split_cancelled(slug, rows)
    return [
        _line("trips_count", len(kept), "count"),
        _line("total_quantity", _sum(kept, "quantity_loaded"), "quantity"),
        _line("cancelled_excluded", cancelled, "count"),
    ]


def _purchase_summary(slug, rows, context):
    kept, cancelled = _split_cancelled(slug, rows)
    return [
        _line("orders_count", len(kept), "count"),
        _line("total_quantity", _sum(kept, "quantity_litres"), "quantity"),
        _line("total_amount", _sum(kept, "total_amount"), "money", True),
        _line("cancelled_excluded", cancelled, "count"),
    ]


def _sales_summary(slug, rows, context):
    return [
        _line("total_delivered", _sum(rows, "delivered_quantity"), "quantity"),
        _line("total_subtotal", _sum(rows, "subtotal"), "money", True),
    ]


def _expense_summary(slug, rows, context):
    return [
        _line("expenses_count", len(rows), "count"),
        _line("total_amount", _sum(rows, "amount"), "money", True),
    ]


def _capital_summary(slug, rows, context):
    holders = [r for r in rows if r.get("section") == "shareholder"]
    contributions = [r for r in rows if r.get("section") == "contribution"]
    return [
        _line("opening_contributions_total", _sum(holders, "opening_contribution"), "money"),
        _line("later_contributions_total", _sum(holders, "later_contributions"), "money"),
        _line("total_capital", _sum(holders, "gross_capital"), "money", True),
        _line("period_contributions_total", _sum(contributions, "amount"), "money"),
        _line("contributions_count", len(contributions), "count"),
    ]


def _general_expense_summary(slug, rows, context):
    detail = [r for r in rows if r.get("section") == "expense"]
    kept = [r for r in detail if r.get("status") != CANCELLED]
    by_status = lambda status: sum(1 for r in kept if r["status"] == status)  # noqa: E731
    return [
        _line("expenses_count", len(kept), "count"),
        _line("total_amount", _sum(kept, "total_amount"), "money"),
        _line("paid_total", _sum(kept, "paid_amount"), "money"),
        _line("remaining_total", _sum(kept, "remaining_amount"), "money", True),
        _line("unpaid_count", by_status("UNPAID"), "count"),
        _line("partially_paid_count", by_status("PARTIALLY_PAID"), "count"),
        _line("paid_count", by_status("PAID"), "count"),
        _line("cancelled_excluded", len(detail) - len(kept), "count"),
    ]


def _trip_fee_debt_summary(slug, rows, context):
    lines = [r for r in rows if r.get("section") == "line"]
    return [
        _line("debt_lines_count", len(lines), "count"),
        _line("total_amount", _sum(lines, "total_amount"), "money"),
        _line("paid_total", _sum(lines, "paid_amount"), "money"),
        _line("remaining_total", _sum(lines, "remaining_amount"), "money", True),
    ]


def _general_debt_summary(slug, rows, context):
    by = lambda section: [r for r in rows if r.get("section") == section]  # noqa: E731
    suppliers, transporters, fees = by("supplier"), by("transporter"), by("trip_fee")
    remaining = "remaining_amount"
    return [
        _line("suppliers_debt_subtotal", _sum(suppliers, remaining), "money"),
        _line("transporters_debt_subtotal", _sum(transporters, remaining), "money"),
        _line("trip_fees_debt_subtotal", _sum(fees, remaining), "money"),
        _line("total_debts", _sum(rows, remaining), "money", True),
        _line("supplier_lines_count", len(suppliers), "count"),
        _line("transporter_lines_count", len(transporters), "count"),
        _line("trip_fee_lines_count", len(fees), "count"),
    ]


def _general_receivable_summary(slug, rows, context):
    invoices = [r for r in rows if r["line_type"] == "invoice"]
    credits = [r for r in rows if r["line_type"] == "credit"]
    totals = [r for r in rows if r["line_type"] == "customer_total"]
    return [
        _line("customers_with_balance_count", len(totals), "count"),
        _line("open_invoices_count", len(invoices), "count"),
        _line("receivable_invoiced_total", _sum(invoices, "invoiced_amount"), "money"),
        _line("receivable_received_total", _sum(invoices + credits, "received_amount"), "money"),
        _line("unallocated_credit_total", _sum(credits, "received_amount"), "money"),
        _line("total_receivable", _sum(totals, "remaining_amount"), "money", True),
    ]


def _outstanding_summary(count_key):
    def summarize(slug, rows, context):
        return [
            _line(count_key, len(rows), "count"),
            _line("total_outstanding", _sum(rows, "outstanding"), "money", True),
        ]

    return summarize


def _fuel_stock_summary(slug, rows, context):
    # The query's own TOTAL row is the total; it is never added to the sums.
    reliquat = _sum([r for r in rows if r["component"] == "SUPPLIER_RELIQUAT"], "quantity")
    unsold = _sum([r for r in rows if r["component"] == "LOADED_UNSOLD"], "quantity")
    totals = [r for r in rows if r["component"] == "TOTAL"]
    total = _dec(totals[-1]["quantity"]) if totals else reliquat + unsold
    lines = [_line("supplier_reliquat", reliquat, "quantity"), _line("loaded_unsold", unsold, "quantity")]
    if total != reliquat + unsold:
        lines.append(_line("reconciliation_gap", total - (reliquat + unsold), "quantity"))
    lines.append(_line("total_stock", total, "quantity", True))
    return lines


def _loss_summary(slug, rows, context):
    return [
        _line("total_loaded", _sum(rows, "loaded_quantity"), "quantity"),
        _line("total_received", _sum(rows, "received_quantity"), "quantity"),
        _line("total_loss", _sum(rows, "loss_quantity"), "quantity"),
        _line("total_chargeable", _sum(rows, "chargeable_loss_quantity"), "quantity", True),
    ]


def _margin_summary(slug, rows, context):
    kept, cancelled = _split_cancelled(slug, rows)
    return [
        _line("total_quantity_loaded", _sum(kept, "quantity_loaded"), "quantity"),
        _line("total_invoiced", _sum(kept, "quantity_invoiced"), "quantity"),
        _line("total_real_cost", _sum(kept, "real_total_cost"), "money"),
        _line("margin_total", _sum(kept, "current_margin"), "money", True),
        _line("cancelled_excluded", cancelled, "count"),
    ]


# ---------------------------------------------------------------------------
# Specs
# ---------------------------------------------------------------------------

_STATEMENT_COLUMNS = (
    ("date", "date"),
    ("type", "enum", "statementType"),
    ("reference", "ref"),
    ("debit", "money"),
    ("credit", "money"),
    ("balance", "money"),
)
_TREASURY_COLUMNS = (
    ("date", "date"),
    ("type", "enum", "transactionType"),
    ("amount", "money"),
    ("reference", "ref"),
    ("balance", "money"),
)
_TRIP_ID = (("trip_reference", "ref"), ("client", "text"))

REPORT_SPECS = {
    "customer-statement": ReportSpec(
        "portrait", (TableSpec(_STATEMENT_COLUMNS),), _party_statement_summary(1),
        entity=("customer", "customer_id"), opening_row=True,
    ),
    "supplier-statement": ReportSpec(
        "portrait", (TableSpec(_STATEMENT_COLUMNS),), _party_statement_summary(1),
        entity=("supplier", "supplier_id"), opening_row=True,
    ),
    "shareholder-statement": ReportSpec(
        "portrait", (TableSpec(_STATEMENT_COLUMNS),), _party_statement_summary(-1),
        entity=("shareholder", "shareholder_id"), opening_row=True,
    ),
    "bank-statement": ReportSpec(
        "portrait", (TableSpec(_TREASURY_COLUMNS),), _treasury_summary,
        entity=("bank_account", "bank_account_id"), opening_row=True,
    ),
    "cash-statement": ReportSpec(
        "portrait", (TableSpec(_TREASURY_COLUMNS),), _treasury_summary,
        entity=("cash_account", "cash_account_id"), opening_row=True,
    ),
    "transporter-statement": ReportSpec(
        "portrait",
        (TableSpec((("date", "date"), ("trip_reference", "ref"), ("base_amount", "money"),
                    ("deduction_amount", "money"), ("advance_applied", "money"), ("net_amount", "money"))),),
        _transporter_summary, entity=("transporter", "transporter_id"),
    ),
    "truck-history": ReportSpec(
        "portrait",
        (TableSpec((("trip_reference", "ref"), ("loading_date", "date"), ("status", "status", "tripStatus"),
                    ("quantity_loaded", "quantity"), ("client", "text"), ("current_margin", "money"))),),
        _truck_history_summary, entity=("truck", "truck_id"),
    ),
    "trip-report": ReportSpec(
        "landscape",
        (TableSpec((("trip_reference", "ref"), ("loading_date", "date"), ("status", "status", "tripStatus"),
                    ("truck", "text"), ("transporter", "text"), ("supplier", "text"), ("product", "text"),
                    ("quantity_loaded", "quantity"), ("client", "text"))),),
        _trip_summary,
    ),
    "purchase-report": ReportSpec(
        "landscape",
        (TableSpec((("reference", "ref"), ("purchase_date", "date"), ("supplier", "text"), ("product", "text"),
                    ("quantity_litres", "quantity"), ("unit_price", "unit_money"), ("total_amount", "money"),
                    ("status", "status", "purchaseOrderStatus"))),),
        _purchase_summary, entity=("supplier", "supplier_id"),
    ),
    "sales-report": ReportSpec(
        "landscape",
        (TableSpec((("trip_reference", "ref"), ("date", "date"), ("customer", "text"), ("product", "text"),
                    ("delivered_quantity", "quantity"), ("unit_selling_price", "unit_money"),
                    ("subtotal", "money"))),),
        _sales_summary, entity=("customer", "customer_id"),
    ),
    "expense-report": ReportSpec(
        "portrait",
        (TableSpec((("date", "date"), ("category", "enum", "expenseCategory"), ("amount", "money"),
                    ("calculation_method", "enum", "expenseCalcMethod"),
                    ("status", "status", "expenseStatus"))),),
        _expense_summary,
    ),
    "capital-report": ReportSpec(
        "portrait",
        (
            TableSpec(
                (("shareholder", "text"), ("participation_percent", "percent"),
                 ("opening_contribution", "money"), ("later_contributions", "money"),
                 ("gross_capital", "money"), ("capital_percent", "percent")),
                section="shareholder",
            ),
            TableSpec(
                (("date", "date"), ("shareholder", "text"), ("amount", "money"),
                 ("account", "text"), ("reference", "ref"), ("notes", "text")),
                section="contribution",
            ),
        ),
        _capital_summary,
    ),
    "general-expense-report": ReportSpec(
        "landscape",
        (
            TableSpec(
                (("date", "date"), ("category", "enum", "expenseCategory"), ("notes", "text"),
                 ("calculation_method", "enum", "expenseCalcMethod"), ("total_amount", "money"),
                 ("paid_amount", "money"), ("remaining_amount", "money"),
                 ("status", "status", "expenseStatus")),
                section="expense",
            ),
            TableSpec(
                (("category", "enum", "expenseCategory"), ("count", "text"), ("total_amount", "money"),
                 ("paid_amount", "money"), ("remaining_amount", "money")),
                section="category_total",
            ),
        ),
        _general_expense_summary,
    ),
    "trip-fee-debt-report": ReportSpec(
        "landscape",
        (
            TableSpec(
                (("fee_type", "enum", "feeType"), ("date", "date"), ("trips", "text"),
                 ("notes", "text"), ("total_amount", "money"), ("paid_amount", "money"),
                 ("remaining_amount", "money"), ("status", "status", "expenseStatus")),
                section="line",
            ),
            TableSpec(
                (("fee_type", "enum", "feeType"), ("count", "text"), ("total_amount", "money"),
                 ("paid_amount", "money"), ("remaining_amount", "money")),
                section="type_total",
            ),
        ),
        _trip_fee_debt_summary,
        entity=("fee_type", "fee_type"), period_mode="as_of",
    ),
    "general-debt-report": ReportSpec(
        "landscape",
        (
            TableSpec(
                (("supplier", "text"), ("reference", "ref"), ("date", "date"), ("total_amount", "money"),
                 ("paid_amount", "money"), ("remaining_amount", "money"),
                 ("status", "status", "expenseStatus")),
                section="supplier",
            ),
            TableSpec(
                (("transporter", "text"), ("trip_reference", "ref"), ("date", "date"),
                 ("total_amount", "money"), ("paid_amount", "money"), ("remaining_amount", "money"),
                 ("status", "status", "expenseStatus")),
                section="transporter",
            ),
            TableSpec(
                (("fee_type", "enum", "feeType"), ("date", "date"), ("trips", "text"), ("notes", "text"),
                 ("total_amount", "money"), ("paid_amount", "money"), ("remaining_amount", "money"),
                 ("status", "status", "expenseStatus")),
                section="trip_fee",
            ),
        ),
        _general_debt_summary,
        period_mode="as_of",
    ),
    "general-receivable-report": ReportSpec(
        "landscape",
        (
            TableSpec(
                (("customer", "text"), ("line_type", "enum", "receivableLine"), ("reference", "ref"),
                 ("date", "date"), ("trip_reference", "ref"), ("invoiced_amount", "money"),
                 ("received_amount", "money"), ("remaining_amount", "money")),
                emphasis={"field": "line_type", "equals": "customer_total"},
            ),
        ),
        _general_receivable_summary,
        period_mode="as_of",
    ),
    "customer-outstanding": ReportSpec(
        "portrait", (TableSpec((("customer", "text"), ("outstanding", "money"))),),
        _outstanding_summary("customers_count"), period_mode="as_of",
    ),
    "supplier-outstanding": ReportSpec(
        "portrait", (TableSpec((("supplier", "text"), ("outstanding", "money"))),),
        _outstanding_summary("suppliers_count"), period_mode="as_of",
    ),
    "transporter-outstanding": ReportSpec(
        "portrait", (TableSpec((("transporter", "text"), ("outstanding", "money"))),),
        _outstanding_summary("transporters_count"), period_mode="as_of",
    ),
    "fuel-stock": ReportSpec(
        "portrait",
        (TableSpec((("component", "enum", "fuelComponent"), ("reference", "ref"), ("quantity", "quantity")),
                   emphasis={"field": "component", "equals": "TOTAL"}),),
        _fuel_stock_summary, period_mode="as_of",
    ),
    "loss-report": ReportSpec(
        "landscape",
        (TableSpec((("trip_reference", "ref"), ("control_date", "date"), ("loaded_quantity", "quantity"),
                    ("received_quantity", "quantity"), ("loss_quantity", "quantity"),
                    ("tolerance_quantity", "quantity"), ("chargeable_loss_quantity", "quantity"),
                    ("verified_at", "date"), ("notes", "text"))),),
        _loss_summary,
    ),
    "margin-report": ReportSpec(
        "landscape",
        (
            TableSpec(_TRIP_ID + (("product", "text"), ("quantity", "quantity"), ("quantity_loaded", "quantity"),
                                  ("quantity_invoiced", "quantity"), ("transporter_loss_quantity", "quantity"),
                                  ("company_absorbed_loss_quantity", "quantity"),
                                  ("supplier_unit_price", "unit_money"), ("unit_selling_price", "unit_money"))),
            TableSpec(_TRIP_ID + (("transport_cost", "money"), ("customs_cost", "money"), ("transit_cost", "money"),
                                  ("road_transit_cost", "money"), ("border_cost", "money"),
                                  ("loading_cost", "money"), ("additional_costs", "money"),
                                  ("real_total_cost", "money"))),
            TableSpec(_TRIP_ID + (("transporter_loss_indemnity", "money"), ("company_absorbed_loss_amount", "money"),
                                  ("unit_cost", "unit_money"), ("unit_profit", "unit_money"),
                                  ("current_margin", "money"))),
        ),
        _margin_summary,
    ),
}


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def _resolve_entity(spec, params, slug, lang):
    """{"label", "name"} for the selected entity, or None. A missing, unknown
    or malformed id never raises - the report itself already ran."""
    if spec.entity is None:
        return None
    kind, param = spec.entity
    value = params.get(param)
    if kind == "fee_type":
        # Fixed vocabulary, not a model; an empty selection means "all".
        value = value or "all"
        name = LABELS[lang].get(f"enum.feeType.{value}", str(value))
        return {"label": LABELS[lang]["entity.fee_type"], "name": name}
    if value in (None, ""):
        return None
    from apps.customers.models import Customer
    from apps.finance.models import BankAccount, CashAccount, Shareholder
    from apps.suppliers.models import Supplier
    from apps.transport.models import Transporter, Truck

    model = {
        "customer": Customer, "supplier": Supplier, "transporter": Transporter, "truck": Truck,
        "bank_account": BankAccount, "cash_account": CashAccount, "shareholder": Shareholder,
    }[kind]
    try:
        obj = model.objects.filter(pk=value).first()
    except (ValueError, TypeError):
        return None
    if obj is None:
        return None
    if kind == "truck":
        name = f"{obj.internal_id} ({obj.tractor_registration} / {obj.tanker_registration})"
    else:
        name = obj.name
    return {"label": LABELS[lang][f"entity.{kind}"], "name": name}


def _period(spec, params, labels, generated_on):
    if spec.period_mode == "as_of":
        return {"mode": "as_of", "from": None, "to": None,
                "text": labels["ui.period_as_of"].format(date=_fmt_date(generated_on))}
    date_from, date_to = _to_date(params.get("date_from")), _to_date(params.get("date_to"))
    iso = lambda d: d.isoformat() if d else None  # noqa: E731
    if date_from and date_to:
        mode, text = "range", labels["ui.period_range"].format(**{"from": _fmt_date(date_from), "to": _fmt_date(date_to)})
    elif date_from:
        mode, text = "range", labels["ui.period_from"].format(**{"from": _fmt_date(date_from)})
    elif date_to:
        mode, text = "range", labels["ui.period_to"].format(to=_fmt_date(date_to))
    else:
        mode, text = "open", labels["ui.period_open"]
    return {"mode": mode, "from": iso(date_from), "to": iso(date_to), "text": text}


def _custom_category_names(rows, field, known):
    """{code: ExpenseCategory.name} for the category codes present in `rows`
    that the label catalog does not translate (user-created categories)."""
    codes = {row.get(field) for row in rows if row.get(field)} - set(known)
    if not codes:
        return {}
    from apps.finance.models import ExpenseCategory

    return dict(ExpenseCategory.objects.filter(code__in=codes).values_list("code", "name"))


def _column(slug, spec_column, labels, rows=()):
    field, kind = spec_column[0], spec_column[1]
    label = labels.get(f"field.{slug}.{field}") or labels[f"field.{field}"]
    column = {
        "field": field,
        "label": label,
        "kind": kind,
        "align": "end" if kind in ("money", "unit_money", "quantity", "percent") else "start",
    }
    if kind in ("enum", "status"):
        column["namespace"] = spec_column[2]
        prefix = f"enum.{spec_column[2]}."
        column["enum_labels"] = {k[len(prefix):]: v for k, v in labels.items() if k.startswith(prefix)}
        if spec_column[2] == "expenseCategory":
            # Never show a technical code: custom categories use their own name.
            column["enum_labels"].update(_custom_category_names(rows, field, column["enum_labels"]))
    return column


def build_report_document(
    report_type: str,
    rows: list[dict],
    params: dict,
    lang: str,
    *,
    statement_context: dict | None = None,
    generated_on=None,
) -> dict:
    spec = REPORT_SPECS[report_type]
    lang = lang if lang in LABELS else "fr"
    labels = LABELS[lang]
    generated_on = generated_on or timezone.localdate()
    context = statement_context or {}
    entity = _resolve_entity(spec, params, report_type, lang)
    period = _period(spec, params, labels, generated_on)

    info = [
        {"key": "generated_on", "label": labels["ui.generated_on"], "value": _fmt_date(generated_on)},
        {"key": "period", "label": labels["ui.period"], "value": period["text"]},
    ]
    if entity:
        info.append({"key": "entity", "label": entity["label"], "value": entity["name"]})
    info.append({"key": "currency", "label": labels["ui.currency"], "value": CURRENCY})

    tables = []
    for index, table in enumerate(spec.tables, start=1):
        title_key = f"table.{report_type}.{index}"
        tables.append(
            {
                "key": f"t{index}",
                "title": labels.get(title_key),
                "columns": [_column(report_type, column, labels, rows) for column in table.columns],
                "emphasis": table.emphasis,
                "section": table.section,
            }
        )

    summary = [
        {**line, "label": labels[f"summary.{line['key']}"]}
        for line in spec.summarize(report_type, rows, context)
    ]
    opening = None
    if spec.opening_row:
        opening = {
            "label": labels["summary.opening_balance"],
            "value": _dec(context.get("opening_balance")) or ZERO,
            "column": "balance",
        }

    return {
        "title": labels[f"title.{report_type}"],
        "company": {"name": DEFAULT_COMPANY_NAME},
        "generated_on": generated_on.isoformat(),
        "lang": lang,
        "direction": "rtl" if lang == "ar" else "ltr",
        "currency": CURRENCY,
        "orientation": spec.orientation,
        "period": period,
        "entity": entity,
        "info": info,
        "tables": tables,
        "opening_balance": opening,
        "summary": summary,
        "empty_text": labels["ui.empty_text"],
        "labels": {"page": labels["ui.page"]},
    }
