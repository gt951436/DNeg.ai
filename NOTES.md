# NOTES.md

## Why the escalation policy is shaped this way

The ladder (AP → Controller → CEO → Owner) mirrors how payment authority
actually works in most businesses. AP clerks resolve straightforward late
payments; anything past 14 days usually means AP has seen it and either
can't pay or won't without a push from above. The Controller stage is
the first human-gated action because contacting a CFO-equivalent about a
delayed invoice without a human reviewer first is a relationship risk.
CEO and Owner contact (30 and 45 days) are reserved for genuinely stuck
accounts where the relationship itself may be at risk.

The **7-day cadence** (no re-send until 7 days have passed) prevents the
Ardley & Sons situation: a $340 invoice that generated four emails in
quick succession. The **small-balance cap** ($1,000) hard-limits escalation
to stage 2 for low-value invoices, regardless of how overdue they are.

Pre-due reminders (7 days before due) are on by default because data shows
most customers pay within a day or two of their own scheduled run — a
nudge before due reduces first-reminder volume significantly.

## What the agent may do without a human

- Send pre-due courtesy reminders (stage 0, AP contact only)
- Send first and second reminders to AP contact (stages 1–2)
- Send internal alerts to the sales owner and collections team (stage 4)
- Classify and log inbound replies, updating hold/freeze state
- Produce the risk report

## What the agent may not do without a human

- Contact a Financial Controller, CEO, or Owner (stages 3, 5, 6)
- Unfreeze a dispute or legal hold
- Update contact details in the CRM based on a CONTACT_CHANGE reply
- Send anything after a COMPLAINT signal
- Interpret a "payment claimed" reply as confirmation of payment

The line is drawn at **relationship risk and irreversibility**. An
automated email to a CEO that arrives during a sensitive renewal
conversation could cost the account. The agent composes these messages and
holds them for sign-off; a human reads the context before clicking send.

## What must be true before this emails a real customer

1. GEMINI_API_KEY is set and tested against the real Gemini API.
2. A human has reviewed at least one full week of replay output and
   confirmed the cadence and tone are acceptable.
3. The contacts CSV has been reconciled with the live CRM - email
   addresses in the pack are synthetic and must be replaced.
4. A de-duplication check runs before sending to catch the case where
   the same invoice appears twice in a batch.
5. An unsubscribe / reply handling inbox exists so real customer replies
   are routed to the agent, not lost.

## What AI was used for

- **LLM (Gemini):** Email intent classification only. It reads a customer
  reply and returns a structured JSON label (e.g., DISPUTE, PROMISE_TO_PAY).
  It does not make any decision about what happens next.
- **Gemini:** Used to build boilerplate (dataclass fields,
  CSV loading, test stubs) and push the initial structure building pace.
- **Where I overrode it:** The AI initially suggested using an LLM to
  *decide* escalation steps. I rejected this entirely - policy decisions
  must be auditable and deterministic. The LLM is used only for the
  extraction step (classifying unstructured text), never for deciding
  what the agent does with the result.
