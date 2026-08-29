# Part 2 — Thought Exercise: Predicting Concrete Defects

*One page. No code. Technical only.*

## What can be built and why

With three projects, 90–150 captioned photos (defect type only), and mix
design documents, you can build a **defect classification model** — given a
photo of a defect, identify what type it is (crack, spalling, delamination,
etc.). A CNN or Vision-Language model fine-tuned on labelled images would
be straightforward and genuinely useful for QA inspection speed.

You can also build a **mix design ↔ defect type correlation analysis** —
a statistical summary showing which mix parameters co-occur with which
defect types across the three projects. With three data points this is
descriptive, not predictive, but it gives the client a concrete artefact
and a template for growing the dataset.

## What cannot be built and what I would tell the client

"Predict defects before they happen" requires knowing what conditions
produce defects before pouring. That demands *pre-pour process variables*
(ambient temperature, humidity, water-cement ratio at batch plant,
placement method, curing protocol) matched to the *outcome* (defect or
no defect) on the same element. None of this is in what you've given us.

Critically, the current dataset has no **negative examples** — photos of
elements that cured correctly. A model trained only on defects learns to
classify defect types; it cannot predict whether a given pour will produce
a defect at all. I would tell the client this clearly before any contract
is signed, and I would tell them that with continued collection this is
solvable within 6–12 months.

## Three data items to ask for

**1. Pour log / batch records for every element in the three projects.**
This is the most important ask. Each pour should have: date, time,
ambient temp, humidity, water-cement ratio, admixture doses, slump
reading, and element ID. This links process conditions to outcomes.
Without it, there is no predictive model — only classification.

**2. Element-level outcome labels — including the good pours.**
For every structural element cast in the three projects, a binary label:
*defect found / not found*. The captions we have only cover defective
elements. We need the denominator. This is what unlocks a true
defect-probability model rather than a defect-type classifier.

**3. Inspection timing for each photo.**
When was the defect first observed relative to pour date? Early
(plastic shrinkage) vs. late (corrosion, alkali-silica) defects have
completely different causal chains and require different interventions.
This unlocks time-to-defect modelling and separates mix-related causes
from curing/environmental causes.
