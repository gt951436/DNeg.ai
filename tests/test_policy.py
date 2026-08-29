"""Tests for the policy engine — verifies freeze and escalation logic."""

import pytest
from datetime import date
from unittest.mock import MagicMock

import yaml
from pathlib import Path

from src.models import Invoice, InvoiceState, Payment
from src.policy import PolicyEngine


# Load real policy config for integration-style tests
_CONFIG_PATH = Path(__file__).parent.parent / "config" / "policy.yaml"
with open(_CONFIG_PATH) as f:
    POLICY = yaml.safe_load(f)

PAYMENTS: dict = {}  # Empty payments — invoice always fully unpaid


def _inv(
    iid="INV-TEST",
    cid="C-01",
    issue=date(2026, 1, 1),
    due=date(2026, 2, 1),
    amount=5000.0,
):
    return Invoice(
        invoice_id=iid,
        customer_id=cid,
        issue_date=issue,
        due_date=due,
        amount=amount,
        terms="Net 30",
        status="open",
    )


def _state(**kwargs) -> InvoiceState:
    s = InvoiceState(invoice_id="INV-TEST", customer_id="C-01")
    for k, v in kwargs.items():
        setattr(s, k, v)
    return s


class TestPolicyEngine:
    def setup_method(self):
        self.engine = PolicyEngine(POLICY)

    def test_no_action_before_pre_due_window(self):
        inv = _inv(due=date(2026, 2, 1))
        state = _state()
        # 30 days before due — no action
        decision = self.engine.decide(inv, state, PAYMENTS, date(2026, 1, 2))
        assert decision.action == "NO_ACTION"

    def test_pre_due_reminder_fires_at_7_days(self):
        inv = _inv(due=date(2026, 2, 1))
        state = _state()
        # Exactly 7 days before due
        decision = self.engine.decide(inv, state, PAYMENTS, date(2026, 1, 25))
        assert decision.action == "SEND_REMINDER"
        assert decision.stage_label == "pre_due_reminder"
        assert decision.auto_send is True

    def test_first_reminder_fires_at_day_1_overdue(self):
        inv = _inv(due=date(2026, 2, 1))
        state = _state()
        decision = self.engine.decide(inv, state, PAYMENTS, date(2026, 2, 2))
        assert decision.action == "SEND_REMINDER"
        assert decision.stage == 1
        assert decision.auto_send is True

    def test_controller_escalation_requires_human_signoff(self):
        inv = _inv(due=date(2026, 1, 1))
        state = _state()
        # 14 days overdue
        decision = self.engine.decide(inv, state, PAYMENTS, date(2026, 1, 15))
        assert decision.stage == 3
        assert decision.auto_send is False  # Must require human approval

    def test_ceo_contact_requires_human_signoff(self):
        inv = _inv(due=date(2026, 1, 1))
        state = _state()
        decision = self.engine.decide(inv, state, PAYMENTS, date(2026, 1, 31))
        assert decision.stage == 5  # CEO stage
        assert decision.auto_send is False

    def test_legal_freeze_blocks_all_actions(self):
        inv = _inv(due=date(2026, 1, 1))
        state = _state(frozen_legal=True)
        # Even 60 days overdue, frozen_legal must block
        decision = self.engine.decide(inv, state, PAYMENTS, date(2026, 3, 1))
        assert decision.action == "NO_ACTION"

    def test_dispute_freeze_blocks_action(self):
        inv = _inv(due=date(2026, 1, 1))
        state = _state(frozen_dispute=True)
        decision = self.engine.decide(inv, state, PAYMENTS, date(2026, 1, 20))
        assert decision.action == "NO_ACTION"

    def test_complaint_freeze_blocks_action(self):
        inv = _inv(due=date(2026, 1, 1))
        state = _state(frozen_complaint=True)
        decision = self.engine.decide(inv, state, PAYMENTS, date(2026, 1, 20))
        assert decision.action == "NO_ACTION"

    def test_hold_blocks_action(self):
        inv = _inv(due=date(2026, 1, 1))
        state = _state(hold_until=date(2026, 2, 14))
        decision = self.engine.decide(inv, state, PAYMENTS, date(2026, 2, 10))
        assert decision.action == "HOLD"

    def test_hold_expired_allows_action(self):
        inv = _inv(due=date(2026, 1, 1))
        state = _state(hold_until=date(2026, 1, 10))
        decision = self.engine.decide(inv, state, PAYMENTS, date(2026, 1, 25))
        assert decision.action != "HOLD"
        assert decision.action not in ("NO_ACTION",)

    def test_small_balance_caps_escalation_stage(self):
        # Amount below small_balance_ceiling (1000)
        inv = _inv(due=date(2026, 1, 1), amount=500.0)
        state = _state()
        # 45 days overdue — would normally be owner stage, but capped
        decision = self.engine.decide(inv, state, PAYMENTS, date(2026, 2, 15))
        assert decision.stage <= POLICY["small_balance_max_stage"]

    def test_cadence_prevents_daily_spam(self):
        inv = _inv(due=date(2026, 1, 1))
        # Last action was yesterday — within cadence window
        state = _state(last_action_date=date(2026, 1, 10), current_stage=1)
        decision = self.engine.decide(inv, state, PAYMENTS, date(2026, 1, 11))
        assert decision.action == "NO_ACTION"

    def test_payment_claimed_triggers_hold(self):
        inv = _inv(due=date(2026, 1, 1))
        state = _state(payment_claimed=True)
        decision = self.engine.decide(inv, state, PAYMENTS, date(2026, 1, 20))
        assert decision.action == "HOLD"