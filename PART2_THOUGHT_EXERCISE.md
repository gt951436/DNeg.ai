# Part 2 — Thought Exercise: Predicting Concrete Defects

## What can be built and why

With the three projects, 90–150 captioned defect photos, and mix-design documents, we can build a **proof-of-concept defect classification or retrieval system**: given a photo of an existing defect, identify or retrieve the most likely defect type. A pretrained vision model with a lightweight classifier or embedding-based approach would be a sensible starting point; I would validate the data quality and class balance before deciding whether fine-tuning is justified.

We can also produce a **descriptive analysis of mix-design parameters and observed defect types**. This could identify hypotheses worth investigating, but it should not be presented as predictive evidence: if a mix design is shared across a project, the effective number of independent mix-design observations may be only three projects.

## What cannot be built and what I would tell the client

I would **not claim that the supplied data can predict defects before they happen**.

Pre-event prediction requires observations that exist before the outcome occurs, linked to an element or pour: for example, material/batch conditions, placement conditions, environmental conditions, curing, and ultimately whether that specific element developed a defect.

The current photos are selected examples of **known defects**, with defect-type labels. They therefore support learning *what an existing defect looks like*, but not estimating *whether a future element will develop a defect*. In particular, there are no comparable non-defective elements providing the denominator needed to estimate defect probability.

I would explain this to the client before promising a predictive system. The right path is to first establish an element-level dataset that links pre-pour/process conditions to both defective and non-defective outcomes, then validate whether those relationships generalize to unseen projects.

## Three data items to ask for

**1. Element-level pour and batch records for every cast element.**

For each element/pour, I would want a stable element/pour ID linking the mix and batch to date/time, material quantities, water-cement ratio, admixture dosage, measured slump, placement method, environmental conditions, and relevant curing conditions. This creates the pre-outcome feature set required for prediction.

**2. Element-level inspection outcomes, including non-defective elements.**

For every cast element, provide the inspection result — defect or no defect — plus defect type and, if available, severity and the date the defect was first observed. This supplies the missing denominator and lets us move from classifying known defects to estimating the probability and type of a future defect.

**3. More historical projects with the same element-level schema.**

I would ask for additional completed projects containing the same linked mix/process/inspection/outcome data. More projects are more valuable than simply more defect photos because they let us test whether a relationship generalizes to a genuinely unseen project rather than learning project-specific patterns. This is what would make a predictive model credible rather than merely descriptive.

*(Note: Inspection timing is particularly valuable within this dataset because it defines the prediction horizon and helps distinguish defects that emerge at different stages, but I would prioritize the three requests above to establish the fundamental predictive baseline first.)*
