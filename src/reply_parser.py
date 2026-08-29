"""
Reply parser — classifies inbound customer emails into structured intents.

Architecture:
  1. Fast deterministic rules (regex / keyword) handle obvious cases first.
     These are free, instant, and don't need an LLM.
  2. If no rule fires, delegate to Gemini with structured JSON output.
  3. If Gemini fails (rate limit, timeout), fall back to UNKNOWN.

The LLM is ONLY used for extraction/classification — it never decides what
the agent does next. Policy decisions stay in policy.py.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date
from typing import Optional

from src.models import InboundReply, ParsedReply, ReplyIntent

logger = logging.getLogger(__name__)

# ── Deterministic rule patterns ───────────────────────────────────────────────

_OOO_PATTERNS = [
    re.compile(r"out of (the )?office", re.I),
    re.compile(r"automatic(ally)? reply", re.I),
    re.compile(r"auto.?reply", re.I),
    re.compile(r"automated response", re.I),
    re.compile(r"on leave until", re.I),
]

_BOUNCE_PATTERNS = [
    re.compile(r"mailer.daemon", re.I),
    re.compile(r"undeliverable", re.I),
    re.compile(r"delivery.*(fail|permanent)", re.I),
    re.compile(r"550\s+5\.1\.1", re.I),
    re.compile(r"does not exist", re.I),
]

_TICKET_PATTERNS = [
    re.compile(r"ticket\s*#?\d+", re.I),
    re.compile(r"been received and a ticket", re.I),
]

_LEGAL_PATTERNS = [
    re.compile(r"legal counsel", re.I),
    re.compile(r"solicitor", re.I),
    re.compile(r"attorney", re.I),
    re.compile(r"litigation", re.I),
]

_DISPUTE_PATTERNS = [
    re.compile(r"(don't|cannot|can't|do not) accept", re.I),
    re.compile(r"(dispute|disputed|disputing)", re.I),
    re.compile(r"hours.*(don't|do not|doesn't).*match", re.I),
    re.compile(r"wrong.*(rate|price|amount)", re.I),
    re.compile(r"old rate", re.I),
    re.compile(r"PO.*(mismatch|wrong|missing)", re.I),
    re.compile(r"holding payment until", re.I),
    re.compile(r"(can't|cannot|do not|don't) approve", re.I),
    re.compile(r"reissuing", re.I),
]

_PAYMENT_CLAIMED_PATTERNS = [
    re.compile(r"(already|was) paid", re.I),
    re.compile(r"nothing outstanding", re.I),
    re.compile(r"settled", re.I),
    re.compile(r"remittance advice", re.I),
]

_PROMISE_PATTERNS = [
    re.compile(r"(will|can) send", re.I),
    re.compile(r"payment (plan|arrangement)", re.I),
    re.compile(r"(paying|pay).*(friday|monday|tuesday|wednesday|thursday|week|month)", re.I),
    re.compile(r"scheduled in our payment run", re.I),
    re.compile(r"payment run on", re.I),
    re.compile(r"(50%|half).*(friday|balance|30th)", re.I),
]

_COMPLAINT_PATTERNS = [
    re.compile(r"take the.*(account|business) elsewhere", re.I),
    re.compile(r"(nine|9|ten|10|years? (old|long)) customer", re.I),
    re.compile(r"do not reply.*(automated|again)", re.I),
    re.compile(r"(fourth|4th|fifth|5th) email", re.I),
]

_CONTACT_CHANGE_PATTERNS = [
    re.compile(r"send all future.*(to|via)", re.I),
    re.compile(r"(new|updated) (email|contact|address)", re.I),
    re.compile(r"forward.*(correspondence|invoices).*(to)", re.I),
    re.compile(r"left the business", re.I),
]

_REMITTANCE_PATTERNS = [
    re.compile(r"remittance advice", re.I),
    re.compile(r"remittance", re.I),
]

_INFO_REQUEST_PATTERNS = [
    re.compile(r"(can you (send|forward|resend)|please send)", re.I),
    re.compile(r"(don't have|no) visibility", re.I),
    re.compile(r"full statement", re.I),
    re.compile(r"breakdown", re.I),
    re.compile(r"(copy|copies) of (the )?invoice", re.I),
    re.compile(r"PO number", re.I),
]


def _match_any(text: str, patterns: list) -> bool:
    return any(p.search(text) for p in patterns)


def _rule_classify(reply: InboundReply) -> Optional[ReplyIntent]:
    """Return an intent if any deterministic rule matches; else None."""
    full_text = f"{reply.subject} {reply.body}"
    sender = reply.from_email.lower()

    # Order matters — more specific patterns first
    if "mailer-daemon" in sender or _match_any(full_text, _BOUNCE_PATTERNS):
        return ReplyIntent.BOUNCE

    if _match_any(full_text, _OOO_PATTERNS):
        return ReplyIntent.OOO

    if _match_any(full_text, _TICKET_PATTERNS):
        return ReplyIntent.TICKET_CREATED

    if _match_any(full_text, _LEGAL_PATTERNS):
        return ReplyIntent.LEGAL

    if _match_any(full_text, _COMPLAINT_PATTERNS):
        return ReplyIntent.COMPLAINT

    if _match_any(full_text, _DISPUTE_PATTERNS):
        return ReplyIntent.DISPUTE

    if _match_any(full_text, _CONTACT_CHANGE_PATTERNS):
        return ReplyIntent.CONTACT_CHANGE

    if _match_any(full_text, _REMITTANCE_PATTERNS):
        return ReplyIntent.REMITTANCE

    if _match_any(full_text, _PAYMENT_CLAIMED_PATTERNS):
        return ReplyIntent.PAYMENT_CLAIMED

    if _match_any(full_text, _PROMISE_PATTERNS):
        return ReplyIntent.PROMISE_TO_PAY

    if _match_any(full_text, _INFO_REQUEST_PATTERNS):
        return ReplyIntent.INFO_REQUEST

    return None


# ── Date extraction helper ────────────────────────────────────────────────────

_DATE_KEYWORDS = {
    "29 august": date(2026, 8, 29),
    "30th": date(2026, 8, 30),
    "friday": None,  # Approximate — would need calendar logic
}

_DATE_RE = re.compile(
    r"\b(\d{1,2})\s*(january|february|march|april|may|june|july|august|september|october|november|december)\b",
    re.I,
)

_MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def _extract_promise_date(text: str, reply_date: date) -> Optional[date]:
    m = _DATE_RE.search(text)
    if m:
        day = int(m.group(1))
        month = _MONTH_MAP[m.group(2).lower()]
        year = reply_date.year
        try:
            return date(year, month, day)
        except ValueError:
            pass
    return None


# ── LLM classifier ────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are an accounts-receivable assistant.
Classify the customer email below into exactly ONE intent from this list:
OOO, PAYMENT_CLAIMED, DISPUTE, LEGAL, PROMISE_TO_PAY, COMPLAINT,
CONTACT_CHANGE, INFO_REQUEST, ACKNOWLEDGEMENT, TICKET_CREATED, BOUNCE,
REMITTANCE, UNKNOWN

Also extract:
- promise_date: ISO date string if a specific payment date was mentioned, else null
- new_contact_email: email address if a new AP contact was given, else null
- reasoning: one sentence explaining your classification

Respond ONLY with valid JSON, no markdown fences:
{"intent": "...", "promise_date": null, "new_contact_email": null, "reasoning": "..."}"""


def _llm_classify(reply: InboundReply, config: dict) -> dict:
    """Call Gemini API. Returns parsed JSON dict or raises on failure."""
    try:
        import google.generativeai as genai
    except ImportError:
        raise ImportError("google-generativeai not installed. Run: pip install google-generativeai")

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY environment variable not set.")

    genai.configure(api_key=api_key)

    llm_config = config.get("llm", {})
    models_to_try = llm_config.get(
        "models", 
        ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
    )

    email_text = (
        f"From: {reply.from_email}\n"
        f"Date: {reply.reply_date}\n"
        f"Subject: {reply.subject}\n\n"
        f"{reply.body}"
    )

    last_error = None
    for model_name in models_to_try:
        try:
            model = genai.GenerativeModel(
                model_name=model_name,
                generation_config={"temperature": llm_config.get("temperature", 0.0)},
                system_instruction=_SYSTEM_PROMPT,
            )
            response = model.generate_content(email_text)
            raw = response.text.strip()
            # Strip markdown fences if model ignores instructions
            raw = re.sub(r"^```json\s*|```$", "", raw, flags=re.MULTILINE).strip()
            return json.loads(raw)
        except Exception as e:
            logger.warning("LLM model %s failed: %s", model_name, e)
            last_error = e

    raise RuntimeError(f"All LLM models failed. Last error: {last_error}")


# ── Public interface ───────────────────────────────────────────────────────────

def parse_reply(
    reply: InboundReply,
    policy_config: dict,
    use_llm: bool = True,
) -> ParsedReply:
    """
    Classify a single inbound reply.
    Uses deterministic rules first; falls back to LLM for ambiguous cases.
    """
    raw_extraction: dict = {}

    # 1. Try deterministic rules
    rule_intent = _rule_classify(reply)

    if rule_intent is not None:
        intent = rule_intent
        raw_extraction = {"source": "rule", "intent": intent.value}
    elif use_llm:
        # 2. Fall back to LLM
        try:
            result = _llm_classify(reply, policy_config)
            raw_extraction = {**result, "source": "llm"}
            intent_str = result.get("intent", "UNKNOWN").upper()
            try:
                intent = ReplyIntent(intent_str)
            except ValueError:
                intent = ReplyIntent.UNKNOWN
        except Exception as e:
            logger.error("LLM classification failed for %s: %s", reply.filename, e)
            intent = ReplyIntent.UNKNOWN
            raw_extraction = {"source": "llm_failed", "error": str(e)}
    else:
        intent = ReplyIntent.UNKNOWN
        raw_extraction = {"source": "rule", "intent": "UNKNOWN"}

    # Extract promise date from body text
    promise_date: Optional[date] = None
    if intent == ReplyIntent.PROMISE_TO_PAY:
        promise_date = (
            _extract_promise_date(reply.body, reply.reply_date)
            or raw_extraction.get("promise_date")
        )
        if isinstance(promise_date, str):
            try:
                from datetime import datetime
                promise_date = datetime.strptime(promise_date, "%Y-%m-%d").date()
            except Exception:
                promise_date = None

    new_contact_email: Optional[str] = raw_extraction.get("new_contact_email")

    logger.info(
        "Reply %s → %s [%s]",
        reply.filename,
        intent.value,
        raw_extraction.get("source", "?"),
    )

    return ParsedReply(
        reply=reply,
        intent=intent,
        promise_date=promise_date,
        new_contact_email=new_contact_email,
        raw_extraction=raw_extraction,
    )


def parse_all_replies(
    replies: list,
    policy_config: dict,
    use_llm: bool = True,
) -> list:
    """Classify all inbound replies."""
    return [parse_reply(r, policy_config, use_llm=use_llm) for r in replies]