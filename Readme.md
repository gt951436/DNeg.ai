# DNeg.ai (Delta Negative.ai)

DNeg.ai is a rule-based, config-driven accounts receivable collections agent designed to systematically reduce the delta of remaining dues/invoices down to zero. It features a dry-run replay simulation, explainable risk reporting, and an LLM-assisted hybrid email classification engine.

---

## 🏗️ Architecture & Core Philosophy

This system is designed around a strict **Deterministic Core + Probabilistic Edge** philosophy. 

Generative AI is powerful, but it should never have the autonomy to decide whether a CEO receives an aggressive legal threat over a delayed payment. Therefore, the LLM is restricted to being the "eyes" of the system (reading unstructured text and extracting intent), while pure, highly-tested Python acts as the "brain" (making escalation decisions based on strict corporate policy).

### Execution Flow & Architecture

```text
+----------------------------------------------------------------------------------------------------+
|                                      DATA SOURCES & CONFIG                                         |
|  +--------------------+  +--------------------+  +----------------------------------------------+  |
|  |   CSV LEDGERS      |  |  INBOUND EMAILS    |  |               policy.yaml                    |  |
|  | (Invoices,         |  | (Raw Text Replies) |  | (Thresholds, Escalation Stages, Timings,     |  |
|  |  Payments, CRM)    |  |                    |  |  LLM configurations)                         |  |
|  +---------+----------+  +---------+----------+  +-----------------------+----------------------+  |
+------------|-----------------------|-------------------------------------|-------------------------+
             |                       |                                     |
             |                       v                                     |
             |    +-----------------------------------------------+        |
             |    |         HYBRID EMAIL CLASSIFICATION           |        |
             |    |                                               |        |
             |    |  +-----------------------------------------+  |        |
             |    |  | RULE-BASED PARSER (15 Regex Patterns)   |  |        |
             |    |  +-------------------+---------------------+  |        |
             |    |                      |                        |        |
             |    |                [Ambiguous?]                   |        |
             |    |                /          \                   |        |
             |    |             YES            NO                 |        |
             |    |             /                \                |        |
             |    |  +---------v----------+       \               |        |
             |    |  |   LLM HIERARCHY    |        \              |        |
             |    |  | (Gemini 3.6 -> 3.5 |         \             |        |
             |    |  |  -> 3.1 Flash Lite)|          \            |        |
             |    |  +---------+----------+           |           |        |
             |    |            |                      |           |        |
             |    |            +----------+-----------+           |        |
             |    |                       |                       |        |
             |    |                       v                       |        |
             |    |            STRUCTURED INTENT                  |        |
             |    |       (OOO, DISPUTE, PROMISE_TO_PAY)          |        |
             |    +-----------------------+-----------------------+        |
             |                            |                                |
+------------|----------------------------|--------------------------------|-------------------------+
|            |                            |                                |                          |
|            |                            v                                |                          |
|            |            +-------------------------------+                |                          |
|            |            |        INVOICE STATE          |                |                          |
|            |            | (Freezes, Holds, Escalations) |                |                          |
|            |            +---------------+---------------+                |                          |
|            |                            |                                v                          |
|            v                            |                  +-----------------------------------+    |
| +-------------------------+             |                  |           POLICY ENGINE           |    |
| |   ACCOUNTING ENGINE     |             |                  | (Deterministic Rules Engine)      |    |
| | (Strict 'as_of' math -  +------------>+----------------->+                                   |    |
| |  Prevents Future Leaks) |             |                  | Checks:                           |    |
| +-------------------------+             |                  | - Is invoice frozen?              |    |
|            |                            |                  | - Did we email within 7 days?     |    |
|            |                            |                  | - How many days overdue?          |    |
|            |                            |                  | - Small balance ceiling limit?    |    |
|            |                            |                  +-----------------+-----------------+    |
|            |                            |                                    |                      |
|            |                            |                                    v                      |
|            |                            |                            [DECISION MADE]                |
|            |                            |                                 / | \                     |
|            |                            |              +-----------------+  |  +------------------+ |
|            |                            |              |                    |                     | |
|            |                            |              v                    v                     v |
|            |                            |      +-------+-------+    +-------+------+      +-------+-+
|            |                            |      |   NO_ACTION   |    | SEND (AP)    |      | ESCALATE|
|            |                            |      | (Frozen, Hold)|    | (Stage 0-2)  |      | (Stg 3-6|
|            |                            |      +---------------+    +-------+------+      +-------+-+
|            |                            |                                   |                     | |
|            |                            |                                   v                     | |
|            |                            |                           (auto_send: true)             | |
|            |                            |                                   |                     | |
|            |                            |                                   |  (auto_send: false) | |
|            |                            |                                   |          |          | |
|            |                            |                                   |    [HUMAN GATE]     | |
+------------|----------------------------|-----------------------------------|----------|----------|-+
             |                            |                                   |          |
             |                            |                                   v          v
             v                            v                       +-----------------------------------+
 +-------------------------+  +-----------------------+           |          replay.jsonl             |
 |   FINAL LEDGER (Aug 26) |  | FINAL INVOICE STATES  |           | (Chronological Log of 1,388       |
 +-----------+-------------+  +-----------+-----------+           |  exact actions taken & reasons)   |
             |                            |                       +-----------------------------------+
             +--------------+-------------+
                            |
                            v
               +-------------------------+
               |     RISK ASSESSOR       |
               | (Calculates late rates, |
               |  avg days late, bounds) |
               +------------+------------+
                            |
                            v
               +-------------------------+
               |   risk_report.json      |
               | (HIGH / MEDIUM / LOW)   |
               +-------------------------+
```

---

## 🚀 Getting Started & Local Setup

### Prerequisites
- **Python**: Version 3.10 or higher is required.
- **Gemini API Key**: (Optional but recommended) Required to enable the full LLM-assisted classification. If not provided, DNeg.ai automatically falls back to rules-only mode.

### Step-by-Step Local Setup

1. **Clone the Repository**
   ```bash
   git clone https://github.com/gt951436/DNeg.ai.git
   cd DNeg.ai
   ```

2. **Create and Activate a Virtual Environment**
   Using a virtual environment prevents packaging conflicts with other projects.
   ```powershell
   # Windows (PowerShell)
   python -m venv venv
   .\venv\Scripts\activate

   # macOS/Linux (Bash)
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install Dependencies**
   Pip install the required pinned dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Environment Variables**
   Copy the template environment file:
   ```bash
   cp .env.example .env
   ```
   Open the newly created `.env` file and input your API key:
   ```env
   GEMINI_API_KEY=XQ.XXXXN6JOxxxxUbWQ9JvfFHhC_gyTV3cCxYDm2PKbzexxxxxxxxx
   ```

---

### Key Design Decisions

1. **No Future Leakage (`accounting.py`)**: The core invariant of the replay engine is strict temporal isolation. When evaluating an invoice on `Day D`, the agent can *only* see invoices issued on or before `Day D` and payments received on or before `Day D`.
2. **Hybrid Classification (`reply_parser.py`)**: Inbound emails are first passed through 15 strict regex rules. If an email is obvious (e.g., "Out of office", "Remittance attached"), it is classified instantly for $0 and 0 latency. Only ambiguous emails are routed to the LLM.
3. **Model Fallback Hierarchy (`config/policy.yaml`)**: The LLM configuration is designed for production reliability. It attempts classification through a defined hierarchy: `gemini-3.6-flash` → `gemini-3.5-flash` → `gemini-3.5-flash-lite` → `gemini-3.1-flash-lite`.
4. **Human Gates (`policy.py`)**: Standard AP reminders are flagged for automatic sending (`auto_send: true`). However, any escalation to a Financial Controller, CEO, or Owner is strictly flagged as `auto_send: false`, ensuring a human reviews the context before risking a client relationship.
5. **Config-Driven (`policy.yaml`)**: All escalation timings, thresholds, small-balance caps, and LLM settings are decoupled from the code. A policy manager can adjust the rules without a developer.

---

## ⚙️ How It Works (The Data Flow)

1. **Data Loading**: Reads all CSVs (ledgers, CRM contacts) and raw email text files.
2. **Classification**: Parses the 20 historical inbound replies. Determinstic rules catch most; the LLM processes the ambiguous edge cases (e.g., an email containing just "?").
3. **The Replay Engine**: The system simulates 18 months day-by-day (Mar 2025 – Aug 2026).
   - Applies newly received emails to update invoice states (e.g., applying a `dispute` freeze).
   - Calculates the exact open balance of every invoice *as of that specific day*.
   - Evaluates the policy engine to determine the correct action (Reminder, Escalate, Hold).
   - Formats the exact email template and logs the action.
4. **Risk Scoring**: At the end of the simulation, the system evaluates all invoices that remain open. It calculates historical customer behavior (average days late, late rate) and combines it with the current invoice state to generate an explainable `HIGH`/`MEDIUM`/`LOW` risk score.

---

## 🧪 Complete Step-by-Step Testing Flow

Follow these steps to run the safety checks, execute the 18-month simulation, and verify output logs.

### 1. Run the Unit Tests (Safety Checks)
Verify the core accounting logic and policy constraints:
```powershell
python -m pytest tests/ -v
```
*All 48 tests should pass in under a second.*

### 2. Run the Replay Simulation
Execute the main application. This will classify the emails (using the Gemini API key in `.env`), run the 18-month simulation day-by-day, and generate the risk report.
```powershell
python main.py
```
*(Note: If you do not have an internet connection or an API key, run `python main.py --no-llm` to fall back to rules-only mode).*

### 3. Inspect the Outputs
Once the run is complete, inspect the generated artifacts in the `output/` directory:

- **`output/replay.jsonl`**: Contains exactly 1,388 actions. Each JSON line details a single daily evaluation, email body, recipient tier, and reason.
- **`output/risk_report.json`**: An explainable ledger risk analysis of the remaining 44 open invoices.

---

## 📝 Part 2: Thought Exercise

Please refer to [`PART2_THOUGHT_EXERCISE.md`](PART2_THOUGHT_EXERCISE.md) for the one-page analysis regarding the concrete defect prediction model, including what can be built, what cannot, and the three specific data artifacts required from the client.
