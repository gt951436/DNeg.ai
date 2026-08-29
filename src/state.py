"""
Agent state manager — tracks per-invoice state across the replay timeline.
This is the agent's memory: what has it done, what has it been told, what is blocked.
"""

from __future__ import annotations

from datetime import date
from typing import Dict

from src.models import InvoiceState, ParsedReply, ReplyIntent


class StateManager:
    """
    Manages InvoiceState objects for all invoices.
    Updated on each day of the replay as replies are processed.
    """

    def __init__(self) -> None:
        self._states: Dict[str, InvoiceState] = {}

    def get(self, invoice_id: str, customer_id: str) -> InvoiceState:
        if invoice_id not in self._states:
            self._states[invoice_id] = InvoiceState(
                invoice_id=invoice_id,
                customer_id=customer_id,
            )
        return self._states[invoice_id]

    def apply_reply(self, parsed: ParsedReply, policy: dict) -> None:
        """
        Mutate the InvoiceState based on a classified reply.
        This is how inbound emails feed back into the agent's decisions.
        """
        invoice_id = parsed.reply.invoice_id
        if not invoice_id:
            return  # Cannot tie to an invoice — log only

        # We need customer_id; derive it lazily from existing state
        # (caller must ensure state already exists or pass customer_id)
        state = self._states.get(invoice_id)
        if state is None:
            return  # Unknown invoice — skip

        as_of = parsed.reply.reply_date
        intent = parsed.intent

        if intent == ReplyIntent.DISPUTE:
            state.frozen_dispute = True

        elif intent == ReplyIntent.LEGAL:
            state.frozen_legal = True

        elif intent == ReplyIntent.COMPLAINT:
            if policy.get("complaint_freeze", True):
                state.frozen_complaint = True

        elif intent == ReplyIntent.PROMISE_TO_PAY:
            hold_days = policy.get("promise_hold_days", 14)
            if parsed.promise_date:
                # Hold until promised date + 2 days grace
                from datetime import timedelta
                state.hold_until = parsed.promise_date + timedelta(days=2)
                state.promise_date = parsed.promise_date
            else:
                from datetime import timedelta
                state.hold_until = as_of + timedelta(days=hold_days)

        elif intent == ReplyIntent.OOO:
            hold_days = policy.get("ooo_hold_days", 5)
            from datetime import timedelta
            # Only extend hold if there's no existing (later) hold
            candidate = as_of + timedelta(days=hold_days)
            if state.hold_until is None or candidate > state.hold_until:
                state.hold_until = candidate

        elif intent == ReplyIntent.PAYMENT_CLAIMED:
            # Pause and flag for human verification
            state.payment_claimed = True
            hold_days = policy.get("payment_claimed_hold_days", 5)
            from datetime import timedelta
            state.hold_until = as_of + timedelta(days=hold_days)

        elif intent == ReplyIntent.CONTACT_CHANGE:
            if policy.get("contact_change_hold", True):
                state.frozen_contact_change = True

        elif intent == ReplyIntent.BOUNCE:
            if parsed.reply.from_email not in state.bounced_contacts:
                state.bounced_contacts.append(parsed.reply.from_email)

    def record_action(self, invoice_id: str, stage: int, as_of: date) -> None:
        """Update state after the agent sends (or logs) an action."""
        state = self._states.get(invoice_id)
        if state:
            state.current_stage = max(state.current_stage, stage)
            state.last_action_date = as_of

    def initialize_invoice(self, invoice_id: str, customer_id: str) -> None:
        """Ensure an InvoiceState exists before the replay loop touches it."""
        if invoice_id not in self._states:
            self._states[invoice_id] = InvoiceState(
                invoice_id=invoice_id,
                customer_id=customer_id,
            )