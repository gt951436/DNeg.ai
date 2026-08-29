"""Tests for the accounting module - these are the most safety-critical."""

import pytest
from datetime import date
from src.accounting import (
    amount_paid_as_of,
    outstanding_balance,
    is_fully_paid_as_of,
    days_overdue,
    open_invoices_as_of,
    customer_avg_days_late,
    customer_late_rate,
)
from src.models import Invoice, Payment


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _inv(iid="INV-0001", cid="C-01", due=date(2026, 1, 15), amount=1000.0, status="open"):
    return Invoice(
        invoice_id=iid,
        customer_id=cid,
        issue_date=date(2026, 1, 1),
        due_date=due,
        amount=amount,
        terms="Net 30",
        status=status,
    )


def _pay(iid="INV-0001", payment_date=date(2026, 1, 15), amount=1000.0):
    return Payment(invoice_id=iid, payment_date=payment_date, amount=amount, method="ACH")


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestAmountPaidAsOf:
    def test_full_payment_on_due_date_visible(self):
        payments = {"INV-0001": [_pay(payment_date=date(2026, 1, 15), amount=1000.0)]}
        assert amount_paid_as_of("INV-0001", payments, date(2026, 1, 15)) == 1000.0

    def test_future_payment_not_visible(self):
        """Key leakage test: payment tomorrow must NOT be visible today."""
        payments = {"INV-0001": [_pay(payment_date=date(2026, 1, 20), amount=1000.0)]}
        assert amount_paid_as_of("INV-0001", payments, date(2026, 1, 19)) == 0.0

    def test_partial_payments_summed(self):
        payments = {
            "INV-0001": [
                _pay(payment_date=date(2026, 1, 10), amount=400.0),
                _pay(payment_date=date(2026, 1, 15), amount=600.0),
            ]
        }
        assert amount_paid_as_of("INV-0001", payments, date(2026, 1, 15)) == 1000.0

    def test_only_past_payments_included_in_partial(self):
        payments = {
            "INV-0001": [
                _pay(payment_date=date(2026, 1, 10), amount=400.0),
                _pay(payment_date=date(2026, 1, 15), amount=600.0),
            ]
        }
        # On Jan 12, only the first payment has happened
        assert amount_paid_as_of("INV-0001", payments, date(2026, 1, 12)) == 400.0

    def test_no_payments_returns_zero(self):
        assert amount_paid_as_of("INV-9999", {}, date(2026, 1, 15)) == 0.0


class TestOutstandingBalance:
    def test_unpaid_invoice_full_outstanding(self):
        inv = _inv(amount=5000.0)
        assert outstanding_balance(inv, {}, date(2026, 1, 15)) == 5000.0

    def test_fully_paid_returns_zero(self):
        inv = _inv(amount=1000.0)
        payments = {"INV-0001": [_pay(amount=1000.0, payment_date=date(2026, 1, 14))]}
        assert outstanding_balance(inv, payments, date(2026, 1, 15)) == 0.0

    def test_partial_payment(self):
        inv = _inv(amount=1000.0)
        payments = {"INV-0001": [_pay(amount=400.0, payment_date=date(2026, 1, 10))]}
        assert outstanding_balance(inv, payments, date(2026, 1, 15)) == 600.0

    def test_never_goes_negative(self):
        inv = _inv(amount=500.0)
        payments = {"INV-0001": [_pay(amount=700.0, payment_date=date(2026, 1, 10))]}
        assert outstanding_balance(inv, payments, date(2026, 1, 15)) == 0.0


class TestDaysOverdue:
    def test_exactly_on_due_date(self):
        inv = _inv(due=date(2026, 1, 15))
        assert days_overdue(inv, date(2026, 1, 15)) == 0

    def test_one_day_overdue(self):
        inv = _inv(due=date(2026, 1, 15))
        assert days_overdue(inv, date(2026, 1, 16)) == 1

    def test_not_yet_due_is_negative(self):
        inv = _inv(due=date(2026, 1, 15))
        assert days_overdue(inv, date(2026, 1, 10)) == -5


class TestOpenInvoicesAsOf:
    def test_future_invoice_not_visible(self):
        """Invoice issued tomorrow should NOT appear in today's open list."""
        inv = Invoice(
            invoice_id="INV-FUTURE",
            customer_id="C-01",
            issue_date=date(2026, 1, 16),  # Tomorrow
            due_date=date(2026, 2, 15),
            amount=1000.0,
            terms="Net 30",
            status="open",
        )
        result = open_invoices_as_of({"INV-FUTURE": inv}, {}, as_of=date(2026, 1, 15))
        assert len(result) == 0

    def test_paid_invoice_excluded(self):
        inv = _inv()
        payments = {"INV-0001": [_pay(amount=1000.0, payment_date=date(2026, 1, 14))]}
        result = open_invoices_as_of({"INV-0001": inv}, payments, date(2026, 1, 15))
        assert len(result) == 0

    def test_open_invoice_included(self):
        inv = _inv()
        result = open_invoices_as_of({"INV-0001": inv}, {}, date(2026, 1, 16))
        assert len(result) == 1


class TestCustomerStats:
    def _make_data(self):
        invoices = {
            "INV-A": Invoice("INV-A", "C-01", date(2026, 1, 1), date(2026, 1, 31), 1000.0, "Net 30", "paid"),
            "INV-B": Invoice("INV-B", "C-01", date(2026, 2, 1), date(2026, 2, 28), 1000.0, "Net 30", "paid"),
        }
        # INV-A paid on time, INV-B paid 10 days late
        payments = {
            "INV-A": [Payment("INV-A", date(2026, 1, 31), 1000.0, "ACH")],
            "INV-B": [Payment("INV-B", date(2026, 3, 10), 1000.0, "ACH")],  # 10 days late
        }
        return invoices, payments

    def test_late_rate(self):
        invoices, payments = self._make_data()
        rate = customer_late_rate("C-01", invoices, payments)
        assert rate == 0.5  # 1 of 2 invoices late

    def test_avg_days_late(self):
        invoices, payments = self._make_data()
        avg = customer_avg_days_late("C-01", invoices, payments)
        # INV-A: 0 days late, INV-B: 10 days late -> avg 5.0
        assert avg == 5.0