# Slide RAG — Extrinsic Hint-Quality Ablation

**3 samples** × **3 arms** × **1 repeats** = 9 hints generated via `supervisor.diagnose_and_hint` (the real production path).

## Per-arm means (mean, 95% bootstrap CI over per-sample averages)

| Arm | judge_quality | level_compliance | no_leakage | citation_rate | guardrail_fallback_rate |
|---|---|---|---|---|---|
| no_rag | 0.400 [0.300, 0.600] | 0.867 [0.600, 1.000] | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| curated | 0.697 [0.550, 0.940] | 0.867 [0.600, 1.000] | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| curated_slides | 0.450 [0.000, 0.950] | 0.867 [0.600, 1.000] | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |

## Citation correctness (curated_slides arm only, samples with a gold slide)

Of hints that cite a LAB, 0.0% cite the *correct* lab (n=2).

## Paired deltas (curated_slides − curated, i.e. slide RAG's marginal effect)

| Metric | Mean Δ | 95% CI |
|---|---|---|
| judge_quality | -0.247 | [-0.550, +0.010] |
| level_compliance | +0.000 | [+0.000, +0.000] |
| no_leakage | +0.000 | [+0.000, +0.000] |
| citation_rate | +0.000 | [+0.000, +0.000] |

## Safety: guardrail fallback rate by arm (HR-schema leak caught before serving)

- `curated`: 0.0% of hints fell back to rule-based due to a guardrail hit
- `curated_slides`: 0.0% of hints fell back to rule-based due to a guardrail hit
- Raw HR-schema terms in a *served* hint: 0 (must be 0 — non-zero is a guardrail bug, not a RAG measurement)

## Per-error-type breakdown (judge_quality, curated_slides arm)

| Error type | n | mean judge score |
|---|---|---|
| column_error | 1 | 0.000 |
| relation_error | 1 | 0.950 |
| syntax_error | 1 | 0.400 |