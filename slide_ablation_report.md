# Slide RAG — Extrinsic Hint-Quality Ablation

**40 samples** × **3 arms** × **3 repeats** = 360 hints generated via `supervisor.diagnose_and_hint` (the real production path).

## Per-arm means (mean, 95% bootstrap CI over per-sample averages)

| Arm | judge_quality | level_compliance | no_leakage | citation_rate | guardrail_fallback_rate |
|---|---|---|---|---|---|
| no_rag | 0.760 [0.684, 0.826] | 0.868 [0.808, 0.922] | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| curated | 0.769 [0.696, 0.836] | 0.859 [0.801, 0.915] | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| curated_slides | 0.772 [0.707, 0.833] | 0.875 [0.819, 0.928] | 1.000 [1.000, 1.000] | 0.108 [0.050, 0.175] | 0.000 [0.000, 0.000] |

## Citation correctness (curated_slides arm only, samples with a gold slide)

Of hints that cite a LAB, 10.2% cite the *correct* lab (n=108).

## Paired deltas (curated_slides − curated, i.e. slide RAG's marginal effect)

| Metric | Mean Δ | 95% CI |
|---|---|---|
| judge_quality | +0.003 | [-0.058, +0.065] |
| level_compliance | +0.016 | [-0.001, +0.033] |
| no_leakage | +0.000 | [+0.000, +0.000] |
| citation_rate | +0.108 | [+0.050, +0.175] |

## Safety: guardrail fallback rate by arm (HR-schema leak caught before serving)

- `curated`: 0.0% of hints fell back to rule-based due to a guardrail hit
- `curated_slides`: 0.0% of hints fell back to rule-based due to a guardrail hit
- Raw HR-schema terms in a *served* hint: 27 (must be 0 — non-zero is a guardrail bug, not a RAG measurement)

## Per-error-type breakdown (judge_quality, curated_slides arm)

| Error type | n | mean judge score |
|---|---|---|
| aggregation_error | 20 | 0.878 |
| ambiguity_error | 6 | 0.530 |
| column_error | 6 | 0.765 |
| join_error | 27 | 0.862 |
| logic_error | 18 | 0.887 |
| no_error | 3 | 0.300 |
| relation_error | 3 | 0.647 |
| subquery_error | 18 | 0.704 |
| syntax_error | 9 | 0.488 |
| timeout_error | 3 | 0.933 |
| type_error | 6 | 0.750 |