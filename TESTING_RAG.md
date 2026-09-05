# Testing the Slide-Material RAG Layer

Evaluation methodology and results for the course-grounded retrieval layer described in
[SLIDE_RAG.md](SLIDE_RAG.md). Written for the thesis evaluation chapter.

Branch: `testing`. All numbers below are reproducible from the commands in §7.

## 1. Why this evaluation exists

The slide-material RAG layer (hybrid BM25 ⊕ dense retrieval with RRF fusion over 8 DB66 lab
decks, 314 chunks) was built and wired into `run_pipeline_llm`, but **had never been measured**.
The existing evaluation code did not touch it:

- `backend/evaluation/run_eval_llm_judge.py` generates hints with the *rule-based*
  `generate_sql_hint` and retrieves only from the curated knowledge base — slide RAG is
  invisible to it.
- `backend/evaluation/run_ablation.py` ablates hint *escalation levels* (policy v1 vs v2),
  not retrieval.

So the design claimed a hybrid retriever with three specific justifications — that BM25 recovers
exact-keyword recall dense embeddings blur, that RRF fusion beats either mode alone, and that the
Oracle-HR-schema leakage trap is contained — and had evidence for none of them.

This harness produces that evidence as three studies over one shared dataset.

## 2. Dataset

`backend/evaluation/data/slide_rag_eval.csv` — 40 samples in the schema
`load_eval_dataset_from_csv` already parsed, plus one new column.

| Provenance | n | Notes |
|---|---|---|
| Existing `EVAL_DATASET`, exported verbatim | 15 | Unchanged, so prior evaluations stay comparable |
| Newly authored | 25 | Realistic buggy student queries + PostgreSQL error messages |

The 25 new samples spread over the five *query* labs — LAB 4 (SELECT), 6 (JOIN), 7 (OUTER JOIN),
8 (GROUP BY), 9 (SUBQUERY). LAB 1/2/3 teach DDL/DML, are tagged `category: ddl_dml`, excluded from
query-error retrieval by default, and unrunnable under `code_executor.py`'s `SELECT`/`WITH`/`EXPLAIN`
allowlist — so they get no samples.

**New column `gold_slides`**: `;`-separated `lab:page` references (e.g. `6:35;6:36`) naming the
slide(s) that *should* be retrieved for that error. Hand-labeled against the real decks and
verified page-by-page against extracted slide titles.

36 of 40 samples carry a gold label. Four (`relation_01`, `type_01`, `no_error_01`, `l4_03`) are
deliberately blank: no query-category lab covers their topic. They are skipped by the retrieval
study and retained for the hint study.

Supporting change: `EvalSample` gained `gold_slides: tuple[str, ...] = ()` plus one parse line —
existing callers are unaffected by the default.

## 3. Study 1 — Intrinsic retrieval quality

Does `search_slides()` return the right slide? No LLM, no API cost, fully deterministic. Run first,
because it validates the gold labels before any paid token is spent.

### Arms

| Arm | Implementation |
|---|---|
| `dense` | `_dense_candidates(q, {"category": "query"}, k)` — embeddings only |
| `bm25` | `_bm25_candidates(q, allowed_ids, k)` — lexical only |
| `hybrid` | `search_slides(q, error_type="", n_results=k)` — RRF fusion, no boost |
| `hybrid_boost` | `search_slides(q, error_type=sample.error_type, n_results=k)` — production path |

The two single-mode arms import the private helpers directly. This keeps a `mode=` parameter out of
production code while the two fusion arms still run through the real public entry point.

The query string is built from the same template `supervisor.py` uses at call time
(`"SQL error: {error_type}. Student query: {q}. Error: {msg}"`). Any drift here would produce
numbers describing a retriever nobody actually runs.

### Metrics

Recall@k, MRR, and nDCG@k at k ∈ {1, 3, 5}, binary relevance, gold = the `gold_slides` set matched
on `lab_no:page`. Plus **LabRecall@5** — did the top 5 include the right *deck*, even on the wrong
slide. All reported with 95% bootstrap confidence intervals.

### Results (36 gold-labeled samples)

| Arm | Recall@1 | Recall@3 | Recall@5 | MRR | nDCG@5 | LabRecall@5 |
|---|---|---|---|---|---|---|
| dense | 0.014 | 0.028 | 0.069 | 0.051 | 0.045 | 0.833 |
| bm25 | 0.028 | 0.056 | 0.083 | 0.076 | 0.064 | 0.806 |
| hybrid | 0.014 | 0.069 | 0.139 | 0.070 | 0.080 | 0.833 |
| **hybrid_boost** | 0.014 | **0.125** | **0.167** | **0.090** | **0.100** | **0.889** |

**The design's ordering holds.** On Recall@3, Recall@5, MRR and nDCG@5:
`hybrid_boost > hybrid > bm25 > dense`. Fusion beats either single mode, and the `error_type` soft
boost (`*= 1.5`) adds a further gain on top of fusion — the first evidence for either choice.

### Per-lab breakdown (Recall@5, `hybrid_boost`)

| Lab | n | Recall@5 |
|---|---|---|
| 4 (SELECT) | 7 | 0.143 |
| 6 (JOIN) | 10 | 0.000 |
| 7 (OUTER JOIN) | 5 | 0.100 |
| 8 (GROUP BY) | 7 | 0.500 |
| 9 (SUBQUERY) | 7 | 0.143 |

### Interpreting the low absolute numbers

Exact-page Recall@5 is low across the board while LabRecall@5 is 0.889. The retriever finds the
right *deck* reliably and the right *page* rarely. Two causes, both investigated:

1. **Near-duplicate slide structure.** LAB 6 pages 35, 36, 40, 41 are titled
   "4. CREATING JOINS WITH THE ON CLAUSE", "4. RETRIEVING RECORDS WITH THE ON CLAUSE",
   "5. CREATING JOINS WITH THE USING CLAUSE", "5. RETRIEVING RECORDS WITH THE USING CLAUSE".
   For `join_01` (gold `6:35`) the retriever returned `6:40` and `6:6` — semantically adjacent
   slides teaching the same concept, scored as misses by exact-page matching. LAB 6's 0.000 is
   this effect at its worst; its LabRecall@5 is 7/10.
2. **Taxonomy gaps.** `timeout_01`, `logic_01` and `ambiguity_01` retrieve no LAB 6 chunk at all.
   Their `error_type` is not among the types `slide_ingest.py` tags LAB 6 chunks with, so the soft
   boost never fires for them.

Exact-page recall is therefore a **lower bound** on usable retrieval, not a measure of it. Both
numbers are reported; LabRecall@5 is the one that reflects what reaches the student, since the
retriever returns a *parent* window (slide ± 1 neighbour) to the LLM regardless.

## 4. Study 2 — Extrinsic hint quality

Does slide context make hints better? Three arms, each running the **real production path**
(`supervisor.diagnose_and_hint`) — unlike the pre-existing judge runner, which tested rule-based
hints only.

| Arm | Curated KB | Slide RAG |
|---|---|---|
| `no_rag` | off | off |
| `curated` | on | off |
| `curated_slides` | on | on |

Arms switch **without any production code change**. `diagnose_and_hint` imports
`retrieve_relevant_context` inside the function body and reads `SLIDE_RAG_ENABLED` from
`get_settings()` at call time, so the runner monkeypatches the module attribute and sets the
environment variable, clearing the `lru_cache` on each switch.

`diagnose_and_hint` needs a graded submission, so each sample is given a synthetic `grading_raw`
carrying one failed test plus the sample's error message and type.

**Repeats.** Hint generation runs at `temperature=0.7`, so a single pass is not a measurement.
The full sweep runs 3 times; per-sample scores are averaged across repeats before any arm
comparison. Total: 40 × 3 arms × 3 repeats = 360 hints, ~720 Gemini calls and 360 judge calls.

### Metrics per hint

| Metric | Source |
|---|---|
| `judge_quality_score` | `OpenRouterJudge` (`openai/gpt-oss-120b`), reused unchanged |
| `hint_level_compliance` | `ragas_evaluator`, reused unchanged |
| `no_solution_leakage` | `ragas_evaluator`, reused unchanged |
| `guardrail_fallback` | `hint.source == "rule_based" and hint.fallback_reason == "guardrail"` |
| `citation_rate` / `citation_correct` | a `LAB <n>` word-boundary match in the hint, checked against `gold_slides` |

**Statistics.** Paired per-sample deltas (`curated_slides − curated`, `curated − no_rag`) with 95%
bootstrap confidence intervals over 10 000 resamples, stdlib `random`. A CI communicates effect
size at n=40 better than a bare p-value, and avoids adding scipy for one number.

### Results (40 samples × 3 arms × 3 repeats = 360 hints)

| Arm | judge_quality | level_compliance | no_leakage | citation_rate |
|---|---|---|---|---|
| `no_rag` | 0.760 [0.684, 0.826] | 0.868 [0.808, 0.922] | 1.000 | 0.000 |
| `curated` | 0.769 [0.696, 0.836] | 0.859 [0.801, 0.915] | 1.000 | 0.000 |
| `curated_slides` | 0.772 [0.707, 0.833] | 0.875 [0.819, 0.928] | 1.000 | 0.108 [0.050, 0.175] |

Paired deltas, `curated_slides − curated`:

| Metric | Mean Δ | 95% CI | Reading |
|---|---|---|---|
| judge_quality | +0.003 | [−0.058, +0.065] | **No detectable effect** |
| level_compliance | +0.016 | [−0.001, +0.033] | No detectable effect |
| no_leakage | +0.000 | [+0.000, +0.000] | Unchanged (floor effect, all arms perfect) |
| citation_rate | +0.108 | [+0.050, +0.175] | **Real effect, CI excludes zero** |

**The headline result is a null result on hint quality.** Slide RAG's marginal effect on
`judge_quality` is +0.003 with a CI spanning zero — indistinguishable from noise. The curated KB
over no RAG at all is likewise flat (0.769 vs 0.760). The only metric slide RAG moves is
`citation_rate`, where the effect is real and the CI excludes zero.

This is an honest and reportable finding, not a failure. On a ~30k-token corpus, with a judge
scoring pedagogical quality of a hint whose *level* and *structure* are already fixed by the
escalation policy and few-shot examples, retrieval has little room to move the score. What
retrieval demonstrably adds is **provenance**, not quality.

Per-error-type spread in the `curated_slides` arm is wide — `timeout_error` 0.933 and
`logic_error` 0.887 at the top, `syntax_error` 0.488, `ambiguity_error` 0.530 and `no_error` 0.300
at the bottom — suggesting the judge rewards conceptual hints over mechanical ones, independent of
retrieval.

## 5. Study 3 — Safety and grounding

The documented trap: slides teach **Oracle SQL against the HR sample schema**
(`employees`, `departments`, `locations`), while students query **PostgreSQL BikeStores**. Leaking
HR table names into a hint is wrong information, not a style problem.

The measurement is indirect by necessity. `validate_output` already sanitizes or falls back to a
rule-based hint on an HR-schema hit, so scanning the *served* hint would read ~0 by construction
and prove nothing. So:

- **Primary signal** — `guardrail_fallback` rate, `curated_slides` vs `curated`. If slide context
  raises HR leakage, arm C shows more guardrail-triggered fallbacks than arm B.
- **Cross-check** — `guardrails._HR_SCHEMA_LEAK_PATTERN` over every served hint. This must be 0
  everywhere. A non-zero value is a guardrail bug, not a RAG result.

### Results — the cross-check failed, and found a production bug

| Signal | Result |
|---|---|
| `guardrail_fallback` rate, all arms | 0.0% |
| HR-schema terms in a **served** hint | **27 of 360 (7.5%)** |

The cross-check was supposed to read 0. It read 27, so by the rule stated above this is a guardrail
defect, not a RAG measurement.

**Slide RAG is not the cause.** The 27 leaks split across arms as `curated` 11,
`curated_slides` 11, `no_rag` 5 — they occur even with retrieval switched off entirely. The source
is the model's own generic SQL knowledge: level-3 hints are instructed to show "a SIMILAR but
DIFFERENT SQL example", and Gemini reaches for the textbook `employees` / `departments` / `salary`
example, which happens to collide with the Oracle HR schema the detector watches for.

**Root cause** — `backend/guardrails.py:224`:

```python
result = GuardrailResult()
result.sanitized_content = llm_response   # unconditional copy of the RAW response
```

`sanitized_content` is documented as "cleaned version (if fixable)" but is populated verbatim
before any check runs. Its consumer in `supervisor.py` reads it as a flag meaning
"all violations were repaired":

```python
if not output_check.passed:
    if output_check.sanitized_content:      # always truthy
        llm_hint_text = output_check.sanitized_content   # the raw text, unmodified
    else:
        ...                                  # rule-based fallback — unreachable
```

So the output guardrail detects the violation correctly (verified: `validate_output` returns
`passed=False` with the right HR violation message) and is then defeated by its own sanitize path.
The rule-based fallback branch in the LLM hint pipeline is dead code, which is also why
`guardrail_fallback` reads 0.0% across all 360 hints — not because nothing violated, but because
that branch cannot be reached.

Violations with a real sanitizer survive this: solution leakage (§1) and harsh tone (§4) overwrite
`sanitized_content` with genuinely cleaned text, and length (§5) truncates. Violations *without* a
sanitizer — HR-schema leakage and profanity — are served to the student verbatim.

**Proposed fix** — delete line 224. Every sanitizer already writes
`result.sanitized_content or llm_response`, so they are unaffected, while `sanitized_content` stays
`None` when nothing was actually cleaned, making the fallback branch reachable again.

Not applied here: it is a live safety path, and it changes served output (hints that leak would
become rule-based fallbacks), so it belongs in its own change with its own regression pass. It also
predates this work — the evaluation harness surfaced it, which is what an evaluation is for.

**Note on the metric.** `guardrail_fallback` measures *fallbacks*, not *violations*, so it is blind
to the sanitize path by construction. After the fix it becomes meaningful; until then the raw
pattern cross-check is the only trustworthy safety signal here.

## 6. Study 4 — Human validation

`--emit-human-sheet` writes 30 hints sampled stratified across arms `curated` and `curated_slides`
(15 each), shuffled, with the arm column omitted. The arm mapping lives in a separate key file so
it is not visible while rating.

Ratings are Likert 1–5 on pedagogical helpfulness. `--score-human` reads the filled sheet back and
reports mean Likert per arm plus **Spearman ρ between human rating and `judge_quality_score`** —
the judge-validity number, which is what makes the LLM-judge results in Study 2 defensible.

Single-hint Likert at n=30 is noisier than blind A/B pairs. Expect wide error bars, and be prepared
to report "no significant human-rated difference" as an honest result rather than a failure.

## 7. Reproducing

```bash
# Prerequisite: persist the index once, or every arm re-embeds 314 chunks
python -m backend.rag.build_slide_index

# Unit tests for the metric functions — no API needed
pytest tests/test_slide_eval.py -v

# Regression: the one production change broke nothing
pytest tests/test_slide_rag.py tests/test_guardrails.py -v

# Study 1 — free, deterministic. Run FIRST.
python -m backend.evaluation.slide_retrieval_eval

# Studies 2+3 — smoke test first (~18 LLM calls), then the full run
python -m backend.evaluation.run_slide_ablation --repeats 1 --limit 3
python -m backend.evaluation.run_slide_ablation --repeats 3 --output csv \
    --csv-path slide_ablation.csv --emit-human-sheet

# Study 4 — after filling in the rating column
python -m backend.evaluation.run_slide_ablation --score-human human_rating_sheet.csv
```

Sanity gate between studies: `hybrid` Recall@5 must beat both single-mode arms. If it does not, the
gold labels are wrong or the query template has drifted — fix that before spending judge tokens.

## 8. Citation rate — measured, diagnosed, and fixed

Slide RAG produced a lab citation in **10.8% of hints** [CI 5.0%, 17.5%] in the Study 2 run above,
against exactly 0% in both arms without slide context. The effect was real — the CI excluded zero
— but small. Of the gold-labeled `curated_slides` runs, 10.2% cited the *correct* lab, meaning
nearly every citation that did appear was the right one. The retriever was not citing badly; it was
citing rarely.

> An earlier 3-sample smoke test showed 0% and was misread as "citations never happen". At n=3 the
> expected count was under one hint. The full run corrected it — recorded here because it is a
> worked example of why the smoke test is a plumbing check, never a measurement.

The rarity was a **prompt-instruction gap, not a retrieval failure**.

`supervisor.py` appends a note to the RAG context telling the model to "cite the slide", but that
note's actual job is the dialect warning, and the hint prompt's `RULES:` block — which is what the
model follows — never asked for a citation. Neither did the `HINT_FEW_SHOT` examples, so nothing
demonstrated the format either. Gemini therefore paraphrased the slide content without ever writing
"LAB 6", and the citation detector correctly found nothing.

Verified directly on `join_02` (gold `6:36`): slide context was retrieved and the hint was
pedagogically correct, but named no lab.

### Fix applied

One `RULES:` line in `diagnose_and_hint`'s `hint_prompt`
(`- If a reference above is titled 'DB66 LAB N', name the lab in plain language ... rather than
only describing the concept`) plus one new `HINT_FEW_SHOT` example demonstrating the phrasing
("As covered in LAB 6, ...") — the few-shot examples are what the model imitates most reliably, so
the rule alone would have been inconsistent.

Re-running `join_02` after the fix:

> "Remember, as covered in LAB 7, the `ON` condition specifies the columns that link the two
> tables. You need to find the column that actually connects `products` to `brands`."

The citation mechanism now fires — but it names **LAB 7**, not the gold **LAB 6**. Checked directly
against `search_slides()` for this query: retrieval itself ranked LAB 7 above LAB 6. The model is
citing faithfully; the wrong lab number here is a retrieval miss (§3's `join_02`-class near-duplicate
problem), not a fabricated or mismatched citation. The prompt fix does exactly what it was meant to
do — surface whatever the retriever hands it — and citation accuracy is now bounded by Study 1's
retrieval quality, not by prompt wording.

Because this changes a live, user-facing prompt, it landed as its own commit with its own
regression pass (72/72 tests in `test_llm_pipeline.py`, `test_guardrails.py`, `test_slide_rag.py`)
rather than inside the evaluation harness. **Studies 1–3 above describe the system before this
fix** — the 10.8%/10.2% figures are the pre-fix baseline this change was built to raise. A
follow-up ablation run would show whether it moved `judge_quality` (unlikely, per Study 2) and by
how much it moved `citation_rate` (expected to rise materially, bounded above by Study 1's
LabRecall@5 of 0.889).

## 9. What was built

| File | Change |
|---|---|
| `backend/rag/slide_retriever.py` | +6 lines: `id`/`lab_no`/`page` in `search_slides` output, so a caller can tell which chunk came back. The only production edit. |
| `backend/evaluation/eval_dataset.py` | +7 lines: `gold_slides` field and its CSV parse |
| `backend/evaluation/data/slide_rag_eval.csv` | New — 40 samples, 36 gold-labeled |
| `backend/evaluation/slide_retrieval_eval.py` | New — Study 1, 4 arms, Recall@k / MRR / nDCG / LabRecall |
| `backend/evaluation/run_slide_ablation.py` | New — Studies 2–4, 3 arms, judge + safety + bootstrap + human sheet |
| `tests/test_slide_eval.py` | New — 19 tests over the metric functions |

Metric helpers, the bootstrap, and Spearman ρ live inside the two evaluation scripts. A shared
`slide_metrics.py` for six short functions with one caller each would be indirection without
benefit.

### Verification performed

- 19/19 metric unit tests pass — hand-built rankings with known Recall/MRR/nDCG values, a constant
  input whose bootstrap CI must bracket the constant, and a perfectly-ranked pair whose ρ must be 1.
- 65/65 regression tests pass (`test_slide_rag.py`, `test_guardrails.py`) after the production edit.
- Gold labels verified page-by-page: every `lab:page` resolves to a real extracted slide, titles
  cross-checked against each sample's error.
- Study 1 run to completion; the sanity gate passes.
- Studies 2–3 run to completion: 360 hints, 0 failed generations, 0 judge errors.
- Study 4 sheet emitted (`human_rating_sheet.csv`, 30 hints, arm-blinded); ratings outstanding.

### Summary of findings

| # | Finding | Status |
|---|---|---|
| 1 | Hybrid RRF + error-type boost beats both single-mode retrievers on Recall@3/5, MRR, nDCG | Design justified |
| 2 | Exact-page recall is low (0.167) while deck-level recall is high (0.889) — near-duplicate slides | Reported as measurement artifact |
| 3 | Slide RAG has **no measurable effect on hint quality** (Δ +0.003, CI spans zero) | Null result, reportable |
| 4 | Slide RAG raises citation rate 0% → 10.8% (CI excludes zero) | Only demonstrated benefit |
| 5 | 27/360 served hints leak HR-schema names; output guardrail defeated by `guardrails.py:224` | **Fixed**, own commit + regression tests |
| 6 | Citations were rare (10.8%) because no prompt rule or few-shot example asked for them | **Fixed**, own commit; remaining accuracy bounded by Study 1 retrieval |
