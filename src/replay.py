"""
Dry-run replay engine.

Simulates the agent across the full 18-month history (Mar 2025 – Aug 2026).

Key invariant: on any given simulation day, the agent sees ONLY:
  - Invoices issued on or before that day
  - Payments received on or before that day
  - Inbound replies received on or before that day

This prevents future leakage entirely.

Output: a JSONL file where each line is one action the agent would have taken.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from src.accounting import (
    is_fully_paid_as_of,
    open_invoices_as_of,
    outstanding_balance,
)
from src.actions import build_action_record
from src.loaders import get_contact
from src.models import (
    ActionRecord,
    Contact,
    Customer,
    InboundReply,
    Invoice,
    InvoiceState,
    ParsedReply,
    Payment,
)
from src.policy import PolicyEngine
from src.state import StateManager

logger = logging.getLogger(__name__)


def _date_range(start: date, end: date):
    """Inclusive date range, one day at a time."""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _action_to_dict(record: ActionRecord) -> dict:
    """Serialize ActionRecord to a JSON-serializable dict."""
    d = asdict(record)
    d["as_of_date"] = record.as_of_date.isoformat()
    return d


def run_replay(
    invoices: Dict[str, Invoice],
    payments: Dict[str, List[Payment]],
    customers: Dict[str, Customer],
    contacts: Dict[str, List[Contact]],
    parsed_replies: List[ParsedReply],
    policy_config: dict,
    output_path: Path,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> Dict[str, InvoiceState]:
    """
    Run the full simulation. Returns final agent states (used by risk scorer).

    Args:
        invoices: All invoices from the dataset.
        payments: All payments keyed by invoice_id.
        customers: Customer registry.
        contacts: Contacts keyed by customer_id.
        parsed_replies: All inbound email replies, pre-classified.
        policy_config: Loaded policy.yaml dict.
        output_path: Where to write the JSONL replay log.
        start_date: Simulation start (default: earliest invoice issue date).
        end_date: Simulation end (default: ledger cutoff 2026-08-26).

    Returns:
        Dict of InvoiceState objects (final state of each invoice).
    """
    # ── Date boundaries ────────────────────────────────────────────────────────
    if start_date is None:
        start_date = min(inv.issue_date for inv in invoices.values())
    if end_date is None:
        end_date = date(2026, 8, 26)  # Ledger cutoff per README

    logger.info(
        "Starting replay: %s → %s (%d days)",
        start_date, end_date, (end_date - start_date).days,
    )

    # ── Build reply index by date ──────────────────────────────────────────────
    # replies_by_date[date] = list of ParsedReply received that day
    replies_by_date: Dict[date, List[ParsedReply]] = {}
    for pr in parsed_replies:
        d = pr.reply.reply_date
        replies_by_date.setdefault(d, []).append(pr)

    # ── Initialise state and policy ───────────────────────────────────────────
    engine = PolicyEngine(policy_config)
    state_mgr = StateManager()

    # Pre-initialise state for all invoices
    for inv in invoices.values():
        state_mgr.initialize_invoice(inv.invoice_id, inv.customer_id)

    # ── Open output log ───────────────────────────────────────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    action_count = 0

    with open(output_path, "w", encoding="utf-8") as log_file:

        # ── Day-by-day simulation ──────────────────────────────────────────────
        for today in _date_range(start_date, end_date):

            # 1. Process inbound replies received today
            for pr in replies_by_date.get(today, []):
                if pr.reply.invoice_id:
                    # Ensure state exists for this invoice
                    inv = invoices.get(pr.reply.invoice_id)
                    if inv:
                        state_mgr.initialize_invoice(inv.invoice_id, inv.customer_id)
                state_mgr.apply_reply(pr, policy_config)

                # Log reply events that trigger a state change
                if pr.intent.value not in ("ACKNOWLEDGEMENT", "UNKNOWN"):
                    reply_record = {
                        "event": "INBOUND_REPLY",
                        "as_of_date": today.isoformat(),
                        "filename": pr.reply.filename,
                        "invoice_id": pr.reply.invoice_id,
                        "from": pr.reply.from_email,
                        "intent": pr.intent.value,
                        "reason": pr.raw_extraction.get("reasoning", ""),
                        "promise_date": pr.promise_date.isoformat() if pr.promise_date else None,
                        "classified_by": pr.raw_extraction.get("source", "unknown"),
                    }
                    log_file.write(json.dumps(reply_record) + "\n")

            # 2. Evaluate each open invoice as of today
            open_today = open_invoices_as_of(invoices, payments, today)

            for inv in open_today:
                state = state_mgr.get(inv.invoice_id, inv.customer_id)
                customer = customers.get(inv.customer_id)
                if not customer:
                    continue

                # Make a decision
                decision = engine.decide(inv, state, payments, today)

                if decision.action in ("NO_ACTION",):
                    continue

                # Find sender contact (collections)
                sender = get_contact(contacts, inv.customer_id, "collections")

                # Format the action
                record = build_action_record(
                    as_of=today,
                    invoice=inv,
                    customer=customer,
                    contacts=contacts,
                    decision=decision,
                    sender_contact=sender,
                )

                if record is None:
                    continue

                # Write to log
                log_file.write(json.dumps(_action_to_dict(record)) + "\n")
                action_count += 1

                # Update state (record what we did)
                state_mgr.record_action(inv.invoice_id, decision.stage, today)

            # Flush periodically (every month)
            if today.day == 1:
                log_file.flush()
                logger.debug("Replay progress: %s (actions so far: %d)", today, action_count)

    logger.info(
        "Replay complete. Total actions logged: %d → %s",
        action_count, output_path,
    )

    # Return final states for risk scoring
    return state_mgr._states