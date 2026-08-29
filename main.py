"""
Collections Agent(DNeg.ai) - single entry point.

Usage:
    python main.py [--no-llm] [--start YYYY-MM-DD] [--end YYYY-MM-DD]

Options:
    --no-llm      Skip LLM email classification (use rules only). Useful
                  when GEMINI_API_KEY is not available.
    --start       Replay start date (default: earliest invoice issue date).
    --end         Replay end date (default: 2026-08-26, the ledger cutoff).

Outputs:
    output/replay.jsonl      — every action the agent would have taken
    output/risk_report.json  — risk assessment for currently open invoices
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

# ── Bootstrap ──────────────────────────────────────────────────────────────────

load_dotenv()  # Load GEMINI_API_KEY from .env if present

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


def _parse_args():
    p = argparse.ArgumentParser(description="Collections Agent — dry-run replay")
    p.add_argument("--no-llm", action="store_true", help="Disable LLM classification")
    p.add_argument("--start", type=str, default=None, help="Replay start date (YYYY-MM-DD)")
    p.add_argument("--end", type=str, default=None, help="Replay end date (YYYY-MM-DD)")
    return p.parse_args()


def _parse_date_arg(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main() -> None:
    args = _parse_args()

    # ── Load config ────────────────────────────────────────────────────────────
    config_path = Path(__file__).parent / "config" / "policy.yaml"
    with open(config_path, encoding="utf-8") as f:
        policy_config = yaml.safe_load(f)
    logger.info("Policy config loaded from %s", config_path)

    # ── Load data ──────────────────────────────────────────────────────────────
    from src.loaders import (
        load_contacts,
        load_customers,
        load_inbound_replies,
        load_invoices,
        load_payments,
    )

    customers = load_customers()
    contacts = load_contacts()
    invoices = load_invoices()
    payments = load_payments()
    raw_replies = load_inbound_replies()

    # ── Parse inbound replies ─────────────────────────────────────────────────
    from src.reply_parser import parse_all_replies

    use_llm = not args.no_llm
    if use_llm and not os.environ.get("GEMINI_API_KEY"):
        logger.warning(
            "GEMINI_API_KEY not set. Falling back to rule-based classification only. "
            "Set it in .env or environment, or pass --no-llm to suppress this warning."
        )
        use_llm = False

    logger.info(
        "Classifying %d inbound replies (LLM=%s) …",
        len(raw_replies), use_llm,
    )
    parsed_replies = parse_all_replies(raw_replies, policy_config, use_llm=use_llm)

    # ── Run replay ─────────────────────────────────────────────────────────────
    from src.replay import run_replay

    output_dir = Path(__file__).parent / "output"
    replay_path = output_dir / "replay.jsonl"

    start_date = _parse_date_arg(args.start) if args.start else None
    end_date = _parse_date_arg(args.end) if args.end else None

    logger.info("Running dry-run replay …")
    final_states = run_replay(
        invoices=invoices,
        payments=payments,
        customers=customers,
        contacts=contacts,
        parsed_replies=parsed_replies,
        policy_config=policy_config,
        output_path=replay_path,
        start_date=start_date,
        end_date=end_date,
    )

    logger.info("Replay log written → %s", replay_path)

    # ── Risk assessment ────────────────────────────────────────────────────────
    from src.risk import score_open_invoices

    ledger_cutoff = end_date or date(2026, 8, 26)
    logger.info("Scoring open invoices as of %s …", ledger_cutoff)

    risk_flags = score_open_invoices(
        invoices=invoices,
        payments=payments,
        customers=customers,
        contacts=contacts,
        states=final_states,
        policy_config=policy_config,
        as_of=ledger_cutoff,
    )

    # Write risk report
    risk_path = output_dir / "risk_report.json"
    risk_output = {
        "generated_at": datetime.now().isoformat(),
        "as_of_date": ledger_cutoff.isoformat(),
        "summary": {
            "total_open": len(risk_flags),
            "HIGH": sum(1 for f in risk_flags if f.risk_level == "HIGH"),
            "MEDIUM": sum(1 for f in risk_flags if f.risk_level == "MEDIUM"),
            "LOW": sum(1 for f in risk_flags if f.risk_level == "LOW"),
            "total_outstanding": round(sum(f.outstanding for f in risk_flags), 2),
        },
        "flags": [
            {
                "invoice_id": f.invoice_id,
                "customer_id": f.customer_id,
                "customer_name": f.customer_name,
                "due_date": f.due_date.isoformat(),
                "invoice_amount": f.invoice_amount,
                "outstanding": f.outstanding,
                "days_overdue": f.days_overdue,
                "risk_level": f.risk_level,
                "risk_score": f.risk_score,
                "reasons": f.reasons,
                "freeze_status": f.freeze_status,
            }
            for f in risk_flags
        ],
    }

    with open(risk_path, "w", encoding="utf-8") as f:
        json.dump(risk_output, f, indent=2)

    logger.info("Risk report written → %s", risk_path)

    # ── Summary ────────────────────────────────────────────────────────────────
    summary = risk_output["summary"]
    print("\n" + "=" * 60)
    print("  Collections Agent — Run Complete")
    print("=" * 60)
    print(f"  Replay log:     {replay_path}")
    print(f"  Risk report:    {risk_path}")
    print(f"\n  Open invoices as of {ledger_cutoff}:")
    print(f"    HIGH risk:   {summary['HIGH']}")
    print(f"    MEDIUM risk: {summary['MEDIUM']}")
    print(f"    LOW risk:    {summary['LOW']}")
    print(f"    Total outstanding: ${summary['total_outstanding']:,.2f}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()