"""
Policy engine — pure, deterministic, config-driven.

Given:
  - an Invoice
  - its InvoiceState (what has the agent already done / been told?)
  - the current as_of date
  - the loaded policy config

Returns a Decision: what to do next, or nothing.

This is the brain of the agent. It never calls an LLM.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional

from src.accounting import days_overdue, outstanding_balance
from src.models import Invoice, InvoiceState, Payment

logger = logging.getLogger(__name__)


@dataclass
class Decision:
    """What the policy engine decided for one invoice on one day."""
    action: str              # "SEND_REMINDER" | "ESCALATE" | "INTERNAL_ALERT" | "HOLD" | "NO_ACTION"
    stage: int
    stage_label: str
    recipient_tier: str      # contact_type of primary recipient
    cc_internal: List[str]   # provider-side contact types to CC
    auto_send: bool
    reason: str
    days_overdue: int
    outstanding: float


_NO_ACTION = Decision(
    action="NO_ACTION",
    stage=0,
    stage_label="none",
    recipient_tier="",
    cc_internal=[],
    auto_send=True,
    reason="No action required",
    days_overdue=0,
    outstanding=0.0,
)


class PolicyEngine:
    def __init__(self, config: dict) -> None:
        self.config = config
        self.ladder: List[dict] = sorted(
            config.get("escalation_ladder", []),
            key=lambda x: x["days_overdue"],
        )
        self.pre_due: dict = config.get("pre_due", {})
        self.cadence_days: int = config.get("reminder_cadence_days", 7)
        self.small_balance_ceiling: float = config.get("small_balance_ceiling", 1000.0)
        self.small_balance_max_stage: int = config.get("small_balance_max_stage", 2)

    def decide(
        self,
        invoice: Invoice,
        state: InvoiceState,
        payments: Dict[str, List[Payment]],
        as_of: date,
    ) -> Decision:
        """
        Core decision logic. Called once per open invoice per simulation day.
        """
        outstanding = outstanding_balance(invoice, payments, as_of)
        if outstanding <= 0:
            return _NO_ACTION  # Paid in full — nothing to do

        overdue = days_overdue(invoice, as_of)

        # ── Freeze checks ──────────────────────────────────────────────────────
        if state.frozen_legal:
            return Decision(
                action="NO_ACTION", stage=state.current_stage,
                stage_label="legal_freeze",
                recipient_tier="", cc_internal=[], auto_send=True,
                reason="Legal freeze — all contact paused pending counsel",
                days_overdue=overdue, outstanding=outstanding,
            )

        if state.frozen_dispute:
            return Decision(
                action="NO_ACTION", stage=state.current_stage,
                stage_label="dispute_freeze",
                recipient_tier="", cc_internal=[], auto_send=True,
                reason="Dispute freeze — amount contested, awaiting resolution",
                days_overdue=overdue, outstanding=outstanding,
            )

        if state.frozen_complaint:
            return Decision(
                action="NO_ACTION", stage=state.current_stage,
                stage_label="complaint_freeze",
                recipient_tier="", cc_internal=[], auto_send=True,
                reason="Complaint freeze — human must review before any contact",
                days_overdue=overdue, outstanding=outstanding,
            )

        if state.payment_claimed:
            return Decision(
                action="HOLD", stage=state.current_stage,
                stage_label="payment_verification",
                recipient_tier="", cc_internal=[], auto_send=True,
                reason="Customer claims payment already made — awaiting verification",
                days_overdue=overdue, outstanding=outstanding,
            )

        if state.frozen_contact_change:
            return Decision(
                action="HOLD", stage=state.current_stage,
                stage_label="contact_change_pending",
                recipient_tier="", cc_internal=[], auto_send=True,
                reason="Contact change flagged — human must update CRM before next contact",
                days_overdue=overdue, outstanding=outstanding,
            )

        # ── Hold checks ────────────────────────────────────────────────────────
        if state.is_on_hold(as_of):
            return Decision(
                action="HOLD", stage=state.current_stage,
                stage_label="hold",
                recipient_tier="", cc_internal=[], auto_send=True,
                reason=f"Reminder hold active until {state.hold_until}",
                days_overdue=overdue, outstanding=outstanding,
            )

        # ── Cadence check — don't spam ─────────────────────────────────────────
        if state.last_action_date:
            days_since = (as_of - state.last_action_date).days
            if days_since < self.cadence_days:
                return _NO_ACTION

        # ── Pre-due reminder ───────────────────────────────────────────────────
        pre_due_cfg = self.pre_due
        if (
            pre_due_cfg.get("enabled", False)
            and overdue == -pre_due_cfg.get("days_before_due", 7)
        ):
            return Decision(
                action="SEND_REMINDER", stage=0,
                stage_label="pre_due_reminder",
                recipient_tier=pre_due_cfg.get("recipient", "ap_contact"),
                cc_internal=[],
                auto_send=pre_due_cfg.get("auto_send", True),
                reason=f"Invoice due in {pre_due_cfg.get('days_before_due', 7)} days — pre-due courtesy notice",
                days_overdue=overdue, outstanding=outstanding,
            )

        # ── Not yet due (beyond pre-due window) ───────────────────────────────
        if overdue < 0:
            return _NO_ACTION

        # ── Small balance cap ──────────────────────────────────────────────────
        is_small = outstanding < self.small_balance_ceiling

        # ── Find the appropriate escalation stage ──────────────────────────────
        applicable = [s for s in self.ladder if overdue >= s["days_overdue"]]
        if not applicable:
            return _NO_ACTION  # overdue but not yet past first threshold

        target = applicable[-1]  # Highest applicable stage
        stage_num: int = target["stage"]
        stage_label: str = target["label"]

        # Apply small-balance cap
        if is_small and stage_num > self.small_balance_max_stage:
            target = next(
                (s for s in reversed(self.ladder)
                 if s["stage"] <= self.small_balance_max_stage and overdue >= s["days_overdue"]),
                self.ladder[0],
            )
            stage_num = target["stage"]
            stage_label = target["label"]

        # Already at this stage — don't re-trigger unless cadence allows
        # (cadence already checked above, so proceed)

        recipients: List[str] = target.get("recipients", [])
        cc_internal: List[str] = target.get("cc_internal", [])
        auto_send: bool = target.get("auto_send", True)

        # Stage 4 is internal only — no customer recipient
        if not recipients:
            action_type = "INTERNAL_ALERT"
            recipient_tier = "internal"
        elif stage_num > state.current_stage or True:
            action_type = "ESCALATE" if stage_num > 1 else "SEND_REMINDER"
            recipient_tier = recipients[0]
        else:
            action_type = "SEND_REMINDER"
            recipient_tier = recipients[0] if recipients else "internal"

        reason = self._build_reason(stage_label, overdue, outstanding, state, is_small)

        return Decision(
            action=action_type,
            stage=stage_num,
            stage_label=stage_label,
            recipient_tier=recipient_tier,
            cc_internal=cc_internal,
            auto_send=auto_send,
            reason=reason,
            days_overdue=overdue,
            outstanding=outstanding,
        )

    def _build_reason(
        self,
        label: str, overdue: int, outstanding: float,
        state: InvoiceState, is_small: bool,
    ) -> str:
        parts = [f"Invoice {overdue} days overdue (outstanding: ${outstanding:,.2f})"]
        if is_small:
            parts.append("small balance — escalation capped")
        if state.promise_date:
            parts.append(f"customer promised payment by {state.promise_date}")
        return "; ".join(parts)