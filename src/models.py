"""
Data models for DNeg.ai (Delta Negative.ai).
Pure dataclasses / Pydantic-style — no external dependencies beyond stdlib.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


# ── Enumerations ──────────────────────────────────────────────────────────────

class PaymentTerms(str, Enum):
    NET_30 = "Net 30"
    NET_45 = "Net 45"
    NET_60 = "Net 60"


class InvoiceStatus(str, Enum):
    PAID = "paid"
    OPEN = "open"


class ContactType(str, Enum):
    AP_CONTACT = "ap_contact"
    CONTROLLER = "controller"
    CEO = "ceo"
    OWNER = "owner"
    SALES_OWNER = "sales_owner"
    COLLECTIONS = "collections"


class ContactSide(str, Enum):
    CUSTOMER = "customer"
    PROVIDER = "provider"


class ReplyIntent(str, Enum):
    """Semantic intent extracted from an inbound customer email."""
    OOO = "OOO"                          # Out-of-office / auto-reply
    PAYMENT_CLAIMED = "PAYMENT_CLAIMED"  # Customer says they already paid
    DISPUTE = "DISPUTE"                  # Customer disputes amount / hours / rate
    LEGAL = "LEGAL"                      # Legal counsel involvement
    PROMISE_TO_PAY = "PROMISE_TO_PAY"    # Explicit commitment with a date or plan
    COMPLAINT = "COMPLAINT"              # Strong frustration / threat to leave
    CONTACT_CHANGE = "CONTACT_CHANGE"    # New contact or AP address provided
    INFO_REQUEST = "INFO_REQUEST"        # Asking for more info / copy of invoice
    ACKNOWLEDGEMENT = "ACKNOWLEDGEMENT"  # Soft acknowledgement, no commitment
    TICKET_CREATED = "TICKET_CREATED"    # Auto-portal ticket confirmation
    BOUNCE = "BOUNCE"                    # Hard email bounce
    REMITTANCE = "REMITTANCE"            # Remittance advice sent
    UNKNOWN = "UNKNOWN"                  # Could not classify


class ActionType(str, Enum):
    SEND_REMINDER = "SEND_REMINDER"
    ESCALATE = "ESCALATE"
    INTERNAL_ALERT = "INTERNAL_ALERT"
    HOLD = "HOLD"
    FLAG = "FLAG"
    NO_ACTION = "NO_ACTION"


# ── Core data models ──────────────────────────────────────────────────────────

@dataclass
class Customer:
    customer_id: str
    customer_name: str
    payment_terms: str   # e.g. "Net 45"

    @property
    def terms_days(self) -> int:
        return int(self.payment_terms.split()[1])


@dataclass
class Contact:
    customer_id: str
    side: str            # "customer" | "provider"
    contact_type: str    # ContactType value
    name: str
    email: str
    title: str


@dataclass
class Invoice:
    invoice_id: str
    customer_id: str
    issue_date: date
    due_date: date
    amount: float
    terms: str
    status: str          # InvoiceStatus value


@dataclass
class Payment:
    invoice_id: str
    payment_date: date
    amount: float
    method: str


@dataclass
class InboundReply:
    filename: str
    from_email: str
    reply_date: date
    subject: str
    body: str
    invoice_id: Optional[str]  # Extracted from subject/body, may be None


@dataclass
class ParsedReply:
    """Result of LLM or rule-based classification of an InboundReply."""
    reply: InboundReply
    intent: ReplyIntent
    promise_date: Optional[date]  # Only if PROMISE_TO_PAY
    new_contact_email: Optional[str]  # Only if CONTACT_CHANGE
    raw_extraction: dict  # Full LLM JSON output for audit


# ── Agent state models ────────────────────────────────────────────────────────

@dataclass
class InvoiceState:
    """Mutable state the agent maintains per invoice during replay."""
    invoice_id: str
    customer_id: str

    # Stage tracking
    current_stage: int = 0         # Which escalation stage was last triggered
    last_action_date: Optional[date] = None  # Date of last outbound action

    # Freeze flags (set by reply parsing)
    frozen_dispute: bool = False
    frozen_legal: bool = False
    frozen_complaint: bool = False
    frozen_contact_change: bool = False  # Awaiting human to update contact

    # Hold expiry
    hold_until: Optional[date] = None   # Pause reminders until this date

    # Promise tracking
    promise_date: Optional[date] = None  # If customer promised to pay by X

    # Payment claimed — waiting for verification
    payment_claimed: bool = False

    # Bounce tracking
    bounced_contacts: list = field(default_factory=list)

    def is_frozen(self) -> bool:
        return self.frozen_dispute or self.frozen_legal or self.frozen_complaint

    def is_on_hold(self, as_of: date) -> bool:
        if self.hold_until and as_of <= self.hold_until:
            return True
        return False


@dataclass
class ActionRecord:
    """A single action the agent would take — written to the replay log."""
    as_of_date: date
    invoice_id: str
    customer_id: str
    customer_name: str
    invoice_amount: float
    days_overdue: int
    action_type: str          # ActionType value
    stage: int
    stage_label: str
    recipient_tier: str       # e.g. "ap_contact", "controller", "internal"
    recipient_name: str
    recipient_email: str
    cc_names: list
    subject: str
    message_body: str
    auto_send: bool
    reason: str               # Why this action was taken
    triggered_by_reply: Optional[str] = None  # filename of reply that triggered it