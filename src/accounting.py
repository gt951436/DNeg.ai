"""
Accounting helpers — computes what was actually known on a given historical date.
The key rule: as_of_date sees ONLY payments received on or before that date.
This is what prevents "future leakage" in the replay simulation.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from src.models import Invoice, Payment


def amount_paid_as_of(
    invoice_id: str,
    payments: Dict[str, List[Payment]],
    as_of: date,
) -> float:
    """Sum of payments received for an invoice on or before as_of."""
    total = 0.0
    for p in payments.get(invoice_id, []):
        if p.payment_date <= as_of:
            total += p.amount
    return round(total, 2)


def outstanding_balance(
    invoice: Invoice,
    payments: Dict[str, List[Payment]],
    as_of: date,
) -> float:
    """Outstanding balance of an invoice as of a given date (min 0)."""
    paid = amount_paid_as_of(invoice.invoice_id, payments, as_of)
    balance = round(invoice.amount - paid, 2)
    return max(balance, 0.0)


def is_fully_paid_as_of(
    invoice: Invoice,
    payments: Dict[str, List[Payment]],
    as_of: date,
) -> bool:
    return outstanding_balance(invoice, payments, as_of) == 0.0


def days_overdue(invoice: Invoice, as_of: date) -> int:
    """
    Days past due as of a given date. Negative means not yet due.
    Only valid for invoices not fully paid as of that date.
    """
    return (as_of - invoice.due_date).days


def was_known_as_of(invoice: Invoice, as_of: date) -> bool:
    """An invoice is only visible from its issue_date onward."""
    return invoice.issue_date <= as_of


def open_invoices_as_of(
    invoices: Dict[str, Invoice],
    payments: Dict[str, List[Payment]],
    as_of: date,
) -> List[Invoice]:
    """
    Returns invoices that:
    1. Were issued on or before as_of
    2. Are not fully paid as of as_of
    """
    result = []
    for inv in invoices.values():
        if not was_known_as_of(inv, as_of):
            continue
        if is_fully_paid_as_of(inv, payments, as_of):
            continue
        result.append(inv)
    return result


def days_to_pay_historical(
    invoice: Invoice,
    payments: Dict[str, List[Payment]],
) -> Optional[int]:
    """
    For a paid invoice, how many days after due_date was it actually settled?
    Negative means early payment. Returns None if no payments exist.
    """
    inv_payments = payments.get(invoice.invoice_id, [])
    if not inv_payments:
        return None
    # Use the date the invoice was fully settled
    cumulative = 0.0
    for p in sorted(inv_payments, key=lambda x: x.payment_date):
        cumulative += p.amount
        if cumulative >= invoice.amount - 0.01:
            return (p.payment_date - invoice.due_date).days
    return None


def customer_avg_days_late(
    customer_id: str,
    invoices: Dict[str, Invoice],
    payments: Dict[str, List[Payment]],
) -> Optional[float]:
    """
    Average days-late across all *paid* invoices for this customer.
    Returns None if no paid invoices with payment data.
    """
    lates = []
    for inv in invoices.values():
        if inv.customer_id != customer_id:
            continue
        if inv.status != "paid":
            continue
        d = days_to_pay_historical(inv, payments)
        if d is not None:
            lates.append(d)
    if not lates:
        return None
    return round(sum(lates) / len(lates), 1)


def customer_late_rate(
    customer_id: str,
    invoices: Dict[str, Invoice],
    payments: Dict[str, List[Payment]],
) -> Optional[float]:
    """
    Fraction of paid invoices that were paid after due date.
    Returns None if no paid invoices.
    """
    total = 0
    late = 0
    for inv in invoices.values():
        if inv.customer_id != customer_id:
            continue
        if inv.status != "paid":
            continue
        d = days_to_pay_historical(inv, payments)
        if d is None:
            continue
        total += 1
        if d > 0:
            late += 1
    if total == 0:
        return None
    return round(late / total, 3)
