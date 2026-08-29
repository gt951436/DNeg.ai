"""Tests for the reply parser — verifies deterministic rules fire correctly."""

import pytest
from datetime import date

from src.models import InboundReply, ReplyIntent
from src.reply_parser import parse_reply, _rule_classify


def _reply(
    body: str,
    subject: str = "RE: Invoice INV-2001",
    from_email: str = "ap@customer.com",
    reply_date: date = date(2026, 8, 20),
    invoice_id: str = "INV-2001",
):
    return InboundReply(
        filename="test.txt",
        from_email=from_email,
        reply_date=reply_date,
        subject=subject,
        body=body,
        invoice_id=invoice_id,
    )


MOCK_POLICY = {
    "llm": {"models": ["gemini-3.6-flash"], "temperature": 0.0},
    "promise_hold_days": 14,
    "ooo_hold_days": 5,
    "complaint_freeze": True,
    "contact_change_hold": True,
    "payment_claimed_hold_days": 5,
}


class TestRuleClassify:

    def test_ooo_detected(self):
        r = _reply(
            body="I am out of the office until 1 September.",
            subject="Automatic reply: Invoice reminder",
        )
        assert _rule_classify(r) == ReplyIntent.OOO

    def test_auto_reply_ooo(self):
        r = _reply(body="This is an automated response.")
        assert _rule_classify(r) == ReplyIntent.OOO

    def test_bounce_from_mailer_daemon(self):
        r = _reply(
            body="Delivery to the following recipient failed permanently: 550 5.1.1",
            from_email="mailer-daemon@example.com",
            subject="Undeliverable: Invoice INV-2001",
        )
        assert _rule_classify(r) == ReplyIntent.BOUNCE

    def test_dispute_hours_mismatch(self):
        r = _reply(
            body="The hours billed don't match what our project lead signed off. Old rate applied."
        )
        assert _rule_classify(r) == ReplyIntent.DISPUTE

    def test_legal_counsel(self):
        r = _reply(body="All further correspondence should be directed to our legal counsel.")
        assert _rule_classify(r) == ReplyIntent.LEGAL

    def test_payment_claimed_already_paid(self):
        r = _reply(body="This was already paid on 11 August by ACH, reference 8842190.")
        assert _rule_classify(r) == ReplyIntent.PAYMENT_CLAIMED

    def test_payment_claimed_settled(self):
        r = _reply(body="We've already settled this one. Nothing outstanding at our end.")
        assert _rule_classify(r) == ReplyIntent.PAYMENT_CLAIMED

    def test_promise_to_pay_payment_run(self):
        r = _reply(body="Confirmed — scheduled in our payment run on 29 August.")
        assert _rule_classify(r) == ReplyIntent.PROMISE_TO_PAY

    def test_promise_to_pay_instalment(self):
        r = _reply(body="We can send 50% this Friday and the balance on the 30th.")
        assert _rule_classify(r) == ReplyIntent.PROMISE_TO_PAY

    def test_complaint_account_threat(self):
        r = _reply(
            body="If someone chases me again I will take the whole account elsewhere. "
                 "Do not reply to this with another automated message."
        )
        assert _rule_classify(r) == ReplyIntent.COMPLAINT

    def test_contact_change(self):
        r = _reply(
            body="Ravi Menon has left the business. Please send all future invoices "
                 "to ap-team@vantage.com going forward."
        )
        assert _rule_classify(r) == ReplyIntent.CONTACT_CHANGE

    def test_ticket_created(self):
        r = _reply(
            body="Your message has been received and a ticket has been created in our "
                 "Accounts Payable portal. Ticket #44219."
        )
        assert _rule_classify(r) == ReplyIntent.TICKET_CREATED

    def test_remittance_advice(self):
        r = _reply(
            body="Remittance advice attached for payment run 24 August. INV-2430  15,018.00",
            subject="Remittance advice - INV-2430",
        )
        assert _rule_classify(r) == ReplyIntent.REMITTANCE

    def test_info_request_po(self):
        r = _reply(body="We never received this. Can you resend it with the PO number on it?")
        assert _rule_classify(r) == ReplyIntent.INFO_REQUEST

    def test_ambiguous_returns_none(self):
        r = _reply(body="?")
        assert _rule_classify(r) is None


class TestParseReply:
    """Integration test — parse_reply with rules only (no LLM)."""

    def test_parse_ooo_reply(self):
        r = _reply(
            body="I am out of the office until 1 September with limited access to email.",
            subject="Automatic reply: Invoice INV-2324 - payment reminder",
        )
        result = parse_reply(r, MOCK_POLICY, use_llm=False)
        assert result.intent == ReplyIntent.OOO

    def test_parse_dispute_sets_no_promise(self):
        r = _reply(body="We can't approve this. Holding payment until resolved.")
        result = parse_reply(r, MOCK_POLICY, use_llm=False)
        assert result.intent == ReplyIntent.DISPUTE
        assert result.promise_date is None

    def test_parse_promise_extracts_date(self):
        r = _reply(
            body="Confirmed - this is scheduled in our payment run on 29 August. You'll have it that day."
        )
        result = parse_reply(r, MOCK_POLICY, use_llm=False)
        assert result.intent == ReplyIntent.PROMISE_TO_PAY
        assert result.promise_date == date(2026, 8, 29)