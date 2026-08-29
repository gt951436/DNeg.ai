"""
Action formatter — turns a policy Decision into a concrete ActionRecord
with a full message body, subject line, and recipient details.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Dict, List, Optional

from src.models import (
    ActionRecord,
    Contact,
    Customer,
    Invoice,
)
from src.policy import Decision

logger = logging.getLogger(__name__)

# ── Email templates ────────────────────────────────────────────────────────────

_TEMPLATES = {
    "pre_due_reminder": (
        "Friendly reminder: Invoice {invoice_id} (${amount:,.2f}) is due on {due_date}",
        """\
Dear {contact_name},

I hope this message finds you well. This is a courtesy reminder that invoice \
{invoice_id} for ${amount:,.2f} is due on {due_date}.

Please let us know if you have any questions or need a copy of the invoice.

Kind regards,
{sender_name}
Accounts Receivable""",
    ),

    "first_reminder": (
        "Invoice {invoice_id} — payment due {due_date}",
        """\
Dear {contact_name},

Invoice {invoice_id} for ${amount:,.2f} was due on {due_date} and remains unpaid.

Please arrange payment at your earliest convenience. If payment has already been \
sent, please disregard this notice and accept our thanks.

If you have any questions, please reply to this email.

Best regards,
{sender_name}
Accounts Receivable""",
    ),

    "second_reminder": (
        "Second reminder: Invoice {invoice_id} — {days_overdue} days overdue",
        """\
Dear {contact_name},

This is a follow-up to our earlier notice. Invoice {invoice_id} for ${amount:,.2f} \
is now {days_overdue} days overdue (due date: {due_date}).

Outstanding balance: ${outstanding:,.2f}

Please make payment by return or contact us to discuss. If there is a query \
against this invoice, please let us know so we can assist.

Best regards,
{sender_name}
Accounts Receivable""",
    ),

    "controller_escalation": (
        "Overdue balance requiring attention — Invoice {invoice_id} ({days_overdue} days)",
        """\
Dear {contact_name},

I am writing to bring to your attention an outstanding balance on your account.

Invoice {invoice_id} for ${amount:,.2f} is now {days_overdue} days past its due date \
of {due_date}. The outstanding balance is ${outstanding:,.2f}.

We have previously contacted your accounts payable team and have not yet received \
payment or a response. We would appreciate your assistance in resolving this matter.

Please let us know when we can expect payment or whether there is anything on your \
side that is preventing settlement.

Kind regards,
{sender_name}
Accounts Receivable""",
    ),

    "internal_sales_alert": (
        "[INTERNAL] Overdue escalation alert — {customer_name} / {invoice_id}",
        """\
Hi {contact_name},

This is an automated internal alert. The following invoice has reached the 21-day \
overdue threshold and no resolution has been received.

Customer:   {customer_name}
Invoice:    {invoice_id}
Amount:     ${amount:,.2f}
Due date:   {due_date}
Days overdue: {days_overdue}
Outstanding: ${outstanding:,.2f}

Action required: Please contact the account and escalate internally before \
the CEO contact stage is triggered in {days_to_next} days.

Collections Team (automated)""",
    ),

    "ceo_escalation": (
        "Outstanding invoice — {invoice_id} — urgent",
        """\
Dear {contact_name},

I am reaching out directly regarding an overdue balance on your company's account \
with us.

Invoice {invoice_id} for ${amount:,.2f} has been outstanding since {due_date} \
and is now {days_overdue} days overdue. The outstanding balance is ${outstanding:,.2f}.

We have contacted your AP team and financial controller without receiving a \
resolution. I wanted to bring this to your personal attention in the hope that \
we can resolve this promptly.

Please feel free to contact me directly. We value our relationship with \
{customer_name} and want to reach a resolution that works for both sides.

Sincerely,
{sender_name}
Accounts Receivable""",
    ),

    "owner_escalation": (
        "Final notice: Invoice {invoice_id} — {days_overdue} days overdue",
        """\
Dear {contact_name},

I am writing to you as the final step before this matter is referred for \
external collection.

Invoice {invoice_id} for ${amount:,.2f} has been outstanding since {due_date} \
and is now {days_overdue} days past due. Despite multiple contacts with your \
team, the outstanding balance of ${outstanding:,.2f} remains unsettled.

We would very much prefer to resolve this directly with you. Please reply to \
this email or call us at your earliest opportunity.

If we do not hear from you within 7 days, we will have no option but to \
refer this balance to our collections partner.

Sincerely,
{sender_name}
Accounts Receivable""",
    ),
}

# Default template for unknown stage labels
_DEFAULT_TEMPLATE = (
    "Invoice {invoice_id} — follow-up required ({days_overdue} days overdue)",
    "Dear {contact_name},\n\nPlease settle invoice {invoice_id} for ${amount:,.2f} "
    "(due: {due_date}, overdue: {days_overdue} days, outstanding: ${outstanding:,.2f}).\n\n"
    "Regards,\n{sender_name}\nAccounts Receivable",
)


def _get_template(label: str):
    return _TEMPLATES.get(label, _DEFAULT_TEMPLATE)


def build_action_record(
    as_of: date,
    invoice: Invoice,
    customer: Customer,
    contacts: Dict[str, List[Contact]],
    decision: Decision,
    sender_contact: Optional[Contact] = None,
    triggered_by_reply: Optional[str] = None,
) -> Optional[ActionRecord]:
    """
    Convert a policy Decision into a fully formatted ActionRecord.
    Returns None if the decision requires no outbound action (NO_ACTION/HOLD
    that doesn't need logging).
    """
    if decision.action == "NO_ACTION":
        return None

    cid = customer.customer_id
    all_contacts = contacts.get(cid, [])

    def find_contact(ctype: str) -> Optional[Contact]:
        for c in all_contacts:
            if c.contact_type == ctype:
                return c
        return None

    # Determine primary recipient
    recipient: Optional[Contact] = None
    if decision.recipient_tier and decision.recipient_tier != "internal":
        recipient = find_contact(decision.recipient_tier)

    # Internal alert: send to provider side only
    if decision.action == "INTERNAL_ALERT" or not recipient:
        primary_name = "Collections Team"
        primary_email = ""
        for ctype in decision.cc_internal:
            c = find_contact(ctype)
            if c:
                primary_email = c.email
                primary_name = c.name
                break
        recipient_tier = "internal"
    else:
        primary_name = recipient.name
        primary_email = recipient.email
        recipient_tier = decision.recipient_tier

    # CC contacts (provider side)
    cc_contacts = []
    for ctype in decision.cc_internal:
        c = find_contact(ctype)
        if c:
            cc_contacts.append(f"{c.name} <{c.email}>")

    # Sender
    sender_name = sender_contact.name if sender_contact else "AR Team"

    # Template
    subject_tpl, body_tpl = _get_template(decision.stage_label)

    days_to_next = 9  # days to next escalation stage (approximate)

    fmt = {
        "invoice_id": invoice.invoice_id,
        "customer_name": customer.customer_name,
        "amount": invoice.amount,
        "due_date": invoice.due_date.strftime("%d %b %Y"),
        "days_overdue": max(decision.days_overdue, 0),
        "outstanding": decision.outstanding,
        "contact_name": primary_name.split()[0] if primary_name else "Team",
        "sender_name": sender_name,
        "days_to_next": days_to_next,
    }

    subject = subject_tpl.format(**fmt)
    body = body_tpl.format(**fmt)

    # Map action type for internal alerts
    action_type = decision.action
    if action_type == "INTERNAL_ALERT":
        recipient_tier = "internal"

    return ActionRecord(
        as_of_date=as_of,
        invoice_id=invoice.invoice_id,
        customer_id=invoice.customer_id,
        customer_name=customer.customer_name,
        invoice_amount=invoice.amount,
        days_overdue=decision.days_overdue,
        action_type=action_type,
        stage=decision.stage,
        stage_label=decision.stage_label,
        recipient_tier=recipient_tier,
        recipient_name=primary_name,
        recipient_email=primary_email,
        cc_names=cc_contacts,
        subject=subject,
        message_body=body,
        auto_send=decision.auto_send,
        reason=decision.reason,
        triggered_by_reply=triggered_by_reply,
    )