"""
Data loaders — parse CSVs and inbound reply text files into model objects.
All parsing is strict: bad rows are logged and skipped, not silently ignored.
"""

from __future__ import annotations

import csv
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.models import Contact, Customer, InboundReply, Invoice, Payment

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"


def _parse_date(s: str) -> date:
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def load_customers(path: Path = DATA_DIR / "customers.csv") -> Dict[str, Customer]:
    customers: Dict[str, Customer] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cid = row["customer_id"].strip()
            customers[cid] = Customer(
                customer_id=cid,
                customer_name=row["customer_name"].strip(),
                payment_terms=row["payment_terms"].strip(),
            )
    logger.info("Loaded %d customers", len(customers))
    return customers


def load_contacts(path: Path = DATA_DIR / "contacts.csv") -> Dict[str, List[Contact]]:
    """Returns a dict keyed by customer_id → list of Contact objects."""
    contacts: Dict[str, List[Contact]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cid = row["customer_id"].strip()
            c = Contact(
                customer_id=cid,
                side=row["side"].strip(),
                contact_type=row["contact_type"].strip(),
                name=row["name"].strip(),
                email=row["email"].strip(),
                title=row["title"].strip(),
            )
            contacts.setdefault(cid, []).append(c)
    total = sum(len(v) for v in contacts.values())
    logger.info("Loaded %d contacts across %d customers", total, len(contacts))
    return contacts


def get_contact(
    contacts: Dict[str, List[Contact]],
    customer_id: str,
    contact_type: str,
) -> Optional[Contact]:
    """Return the first matching contact of the given type for a customer."""
    for c in contacts.get(customer_id, []):
        if c.contact_type == contact_type:
            return c
    return None


def load_invoices(path: Path = DATA_DIR / "invoices.csv") -> Dict[str, Invoice]:
    invoices: Dict[str, Invoice] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            iid = row["invoice_id"].strip()
            try:
                invoices[iid] = Invoice(
                    invoice_id=iid,
                    customer_id=row["customer_id"].strip(),
                    issue_date=_parse_date(row["issue_date"]),
                    due_date=_parse_date(row["due_date"]),
                    amount=float(row["amount"]),
                    terms=row["terms"].strip(),
                    status=row["status"].strip(),
                )
            except Exception as e:
                logger.warning("Skipping invoice row %s: %s", iid, e)
    logger.info("Loaded %d invoices", len(invoices))
    return invoices


def load_payments(path: Path = DATA_DIR / "payments.csv") -> Dict[str, List[Payment]]:
    """Returns a dict keyed by invoice_id → list of Payment objects."""
    payments: Dict[str, List[Payment]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            iid = row["invoice_id"].strip()
            try:
                p = Payment(
                    invoice_id=iid,
                    payment_date=_parse_date(row["payment_date"]),
                    amount=float(row["amount"]),
                    method=row["method"].strip(),
                )
                payments.setdefault(iid, []).append(p)
            except Exception as e:
                logger.warning("Skipping payment row for %s: %s", iid, e)
    logger.info("Loaded payments for %d invoices", len(payments))
    return payments


# ── Inbound reply loader ──────────────────────────────────────────────────────

_INVOICE_RE = re.compile(r"\bINV-\d{4}\b")


def _extract_invoice_id(text: str) -> Optional[str]:
    """Extract the first invoice ID mentioned in subject or body."""
    m = _INVOICE_RE.search(text)
    return m.group(0) if m else None


def load_inbound_replies(
    directory: Path = DATA_DIR / "inbound_replies",
) -> List[InboundReply]:
    replies: List[InboundReply] = []
    for filepath in sorted(directory.glob("*.txt")):
        try:
            text = filepath.read_text(encoding="utf-8")
            reply = _parse_reply_file(filepath.name, text)
            replies.append(reply)
        except Exception as e:
            logger.warning("Could not parse reply file %s: %s", filepath.name, e)
    logger.info("Loaded %d inbound replies", len(replies))
    return replies


def _parse_reply_file(filename: str, text: str) -> InboundReply:
    """Parse the simple header + body format of the reply files."""
    lines = text.strip().splitlines()
    headers: dict = {}
    body_lines: list = []
    in_body = False

    for line in lines:
        if in_body:
            body_lines.append(line)
        elif line.strip() == "":
            in_body = True
        else:
            if ":" in line:
                key, _, val = line.partition(":")
                headers[key.strip().lower()] = val.strip()

    from_email = headers.get("from", "")
    date_str = headers.get("date", "")
    subject = headers.get("subject", "")
    body = "\n".join(body_lines).strip()

    reply_date: date
    try:
        reply_date = _parse_date(date_str)
    except Exception:
        reply_date = date(2026, 8, 26)  # fallback to ledger cutoff

    # Try to extract invoice ID from subject first, then body
    invoice_id = _extract_invoice_id(subject) or _extract_invoice_id(body)

    return InboundReply(
        filename=filename,
        from_email=from_email,
        reply_date=reply_date,
        subject=subject,
        body=body,
        invoice_id=invoice_id,
    )