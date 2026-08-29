"""
Risk scorer for currently open invoices.

Produces an explainable risk assessment for each open invoice as of
the ledger cutoff date (2026-08-26).

No ML model — intentionally rule-based and transparent.
The assessors can read the reason and immediately understand it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

from src.accounting import (
    customer_avg_days_late,
    customer_late_rate,
    days_overdue,
    outstanding_balance,
)
from src.models import Contact, Customer, Invoice, InvoiceState, Payment

logger = logging.getLogger(__name__)


@dataclass
class RiskFlag:
    invoice_id: str
    customer_id: str
    customer_name: str
    due_date: date
    invoice_amount: float
    outstanding: float
    days_overdue: int
    risk_level: str          # "HIGH" | "MEDIUM" | "LOW"
    risk_score: int          # 0–100 composite
    reasons: List[str]
    freeze_status: List[str]  # active freezes from agent state


def score_open_invoices(
    invoices: Dict[str, Invoice],
    payments: Dict[str, List[Payment]],
    customers: Dict[str, Customer],
    contacts: Dict[str, List[Contact]],
    states: Dict[str, InvoiceState],
    policy_config: dict,
    as_of: date,
) -> List[RiskFlag]:
    """
    Score all open invoices as of as_of date.
    Returns list sorted by risk_score descending.
    """
    risk_cfg = policy_config.get("risk", {})
    high_threshold = risk_cfg.get("high_days_overdue", 14)
    medium_threshold = risk_cfg.get("medium_days_overdue", 0)
    chronic_threshold = risk_cfg.get("chronic_late_threshold", 0.5)
    large_balance = risk_cfg.get("large_balance_threshold", 50000.0)

    flags: List[RiskFlag] = []

    for inv in invoices.values():
        if inv.issue_date > as_of:
            continue  # Not yet issued as of this date

        outstanding = outstanding_balance(inv, payments, as_of)
        if outstanding <= 0:
            continue  # Fully paid

        overdue = days_overdue(inv, as_of)
        cid = inv.customer_id
        customer = customers.get(cid)
        if not customer:
            continue

        reasons: List[str] = []
        score = 0

        # ── Factor 1: Days overdue ─────────────────────────────────────────
        if overdue >= high_threshold:
            score += 40
            reasons.append(f"Already {overdue} days overdue (threshold: {high_threshold})")
        elif overdue >= medium_threshold:
            score += 20
            reasons.append(f"{overdue} days overdue")
        elif overdue < 0:
            reasons.append(f"Not yet due ({-overdue} days remaining)")

        # ── Factor 2: Customer historical late-payment rate ────────────────
        late_rate = customer_late_rate(cid, invoices, payments)
        avg_late = customer_avg_days_late(cid, invoices, payments)

        if late_rate is not None:
            if late_rate >= chronic_threshold:
                score += 25
                reasons.append(
                    f"Chronic payer: {late_rate:.0%} of historical invoices paid late "
                    f"(avg {avg_late:.1f} days late)" if avg_late else
                    f"Chronic payer: {late_rate:.0%} of invoices paid late"
                )
            elif late_rate > 0.2:
                score += 10
                reasons.append(f"Occasional late payer ({late_rate:.0%} of invoices paid late)")
            else:
                reasons.append(f"Generally reliable payer ({late_rate:.0%} late rate)")

        # ── Factor 3: Large absolute exposure ─────────────────────────────
        if outstanding >= large_balance:
            score += 20
            reasons.append(f"Large exposure: ${outstanding:,.2f} outstanding")
        elif outstanding >= large_balance * 0.5:
            score += 10
            reasons.append(f"Moderate exposure: ${outstanding:,.2f} outstanding")

        # ── Factor 4: Active freezes / disputes ───────────────────────────
        state = states.get(inv.invoice_id)
        freeze_status: List[str] = []
        if state:
            if state.frozen_legal:
                score += 30
                reasons.append("LEGAL freeze active — customer referred to counsel")
                freeze_status.append("LEGAL")
            if state.frozen_dispute:
                score += 20
                reasons.append("DISPUTE freeze active — amount contested")
                freeze_status.append("DISPUTE")
            if state.frozen_complaint:
                score += 10
                reasons.append("COMPLAINT freeze — customer escalated")
                freeze_status.append("COMPLAINT")
            if state.payment_claimed:
                score += 5
                reasons.append("Customer claims prior payment — unverified")
                freeze_status.append("PAYMENT_CLAIMED")
            if state.bounced_contacts:
                score += 10
                reasons.append(
                    f"Email bounce recorded for: {', '.join(state.bounced_contacts)}"
                )
                freeze_status.append("BOUNCE")

        # ── Factor 5: Invoice approaching due within 7 days ───────────────
        if -7 <= overdue < 0 and late_rate is not None and late_rate >= 0.5:
            score += 10
            reasons.append(
                f"Due in {-overdue} days; customer has {late_rate:.0%} historical late rate"
            )

        # ── Clamp score ───────────────────────────────────────────────────
        score = min(score, 100)

        # ── Risk level assignment ─────────────────────────────────────────
        if score >= 55 or overdue >= high_threshold:
            risk_level = "HIGH"
        elif score >= 25 or overdue >= medium_threshold:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        flags.append(RiskFlag(
            invoice_id=inv.invoice_id,
            customer_id=cid,
            customer_name=customer.customer_name,
            due_date=inv.due_date,
            invoice_amount=inv.amount,
            outstanding=outstanding,
            days_overdue=overdue,
            risk_level=risk_level,
            risk_score=score,
            reasons=reasons,
            freeze_status=freeze_status,
        ))

    flags.sort(key=lambda f: f.risk_score, reverse=True)
    logger.info(
        "Risk assessment: %d open invoices — HIGH: %d, MEDIUM: %d, LOW: %d",
        len(flags),
        sum(1 for f in flags if f.risk_level == "HIGH"),
        sum(1 for f in flags if f.risk_level == "MEDIUM"),
        sum(1 for f in flags if f.risk_level == "LOW"),
    )
    return flags