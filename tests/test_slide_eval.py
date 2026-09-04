"""
Unit tests for the slide-RAG evaluation harness's pure metric functions
(backend/evaluation/slide_retrieval_eval.py, run_slide_ablation.py).

Synthetic-data assertions only -- no DB, no persisted index, no API calls.
Confirms the metrics are computed correctly; the actual retriever/hint
numbers come from running the two eval scripts directly against the real
index, not from this file.

Version: 2026-08-29
"""

from __future__ import annotations

from backend.evaluation.eval_dataset import load_eval_dataset_from_csv
from backend.evaluation.run_slide_ablation import bootstrap_ci as ablation_bootstrap_ci
from backend.evaluation.run_slide_ablation import spearman_rho
from backend.evaluation.slide_retrieval_eval import (
    bootstrap_ci,
    mrr,
    ndcg_at_k,
    recall_at_k,
)


class TestRecallAtK:
    def test_hit_at_top(self):
        assert recall_at_k(["6:21", "6:22", "7:9"], {"6:21"}, k=1) == 1.0

    def test_miss(self):
        assert recall_at_k(["6:22", "7:9"], {"6:21"}, k=5) == 0.0

    def test_partial_multi_gold(self):
        # 1 of 2 gold docs retrieved -> recall 0.5
        assert recall_at_k(["6:21", "9:1"], {"6:21", "6:22"}, k=5) == 0.5

    def test_beyond_k_not_counted(self):
        assert recall_at_k(["9:1", "9:2", "6:21"], {"6:21"}, k=2) == 0.0

    def test_empty_gold_is_undefined(self):
        assert recall_at_k(["6:21"], set(), k=5) is None


class TestMRR:
    def test_first_position(self):
        assert mrr(["6:21", "7:9"], {"6:21"}) == 1.0

    def test_third_position(self):
        assert mrr(["9:1", "9:2", "6:21"], {"6:21"}) == 1 / 3

    def test_not_found(self):
        assert mrr(["9:1", "9:2"], {"6:21"}) == 0.0


class TestNDCG:
    def test_perfect_ranking_is_one(self):
        # gold at rank 1 -> DCG == IDCG -> nDCG == 1.0
        assert ndcg_at_k(["6:21", "9:1"], {"6:21"}, k=5) == 1.0

    def test_worse_rank_scores_lower_than_perfect(self):
        perfect = ndcg_at_k(["6:21", "9:1"], {"6:21"}, k=5)
        worse = ndcg_at_k(["9:1", "6:21"], {"6:21"}, k=5)
        assert 0.0 < worse < perfect

    def test_no_hit_is_zero(self):
        assert ndcg_at_k(["9:1", "9:2"], {"6:21"}, k=5) == 0.0


class TestBootstrapCI:
    def test_constant_values_bracket_the_constant(self):
        mean, lo, hi = bootstrap_ci([0.5] * 20, n_resamples=500)
        assert mean == 0.5
        assert lo == 0.5 == hi

    def test_ci_brackets_true_mean_for_varied_data(self):
        values = [0.0, 1.0] * 10  # true mean 0.5
        mean, lo, hi = bootstrap_ci(values, n_resamples=2000)
        assert mean == 0.5
        assert lo <= 0.5 <= hi

    def test_empty_input_is_zero(self):
        assert bootstrap_ci([]) == (0.0, 0.0, 0.0)

    def test_ablation_module_has_the_same_behavior(self):
        # sibling copy in run_slide_ablation.py -- same contract, not
        # imported from one shared module (see that file's docstring)
        assert ablation_bootstrap_ci([0.5] * 10, n_resamples=200) == (0.5, 0.5, 0.5)


class TestSpearmanRho:
    def test_perfect_agreement_is_one(self):
        assert spearman_rho([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0

    def test_perfect_disagreement_is_minus_one(self):
        assert spearman_rho([1, 2, 3, 4], [40, 30, 20, 10]) == -1.0

    def test_too_few_points_is_zero(self):
        assert spearman_rho([1.0], [2.0]) == 0.0


class TestGoldSlidesCsvRoundtrip:
    def test_loads_semicolon_separated_gold_slides(self, tmp_path):
        csv_path = tmp_path / "mini.csv"
        csv_path.write_text(
            "sample_id,error_type,student_query,error_message,problem_description,"
            "hint_level,attempt_count,gold_slides\n"
            'x1,join_error,"SELECT 1","err","desc",1,1,"6:21;6:22"\n'
            'x2,relation_error,"SELECT 2","err","desc",1,1,""\n',
            encoding="utf-8",
        )
        samples = load_eval_dataset_from_csv(str(csv_path))
        assert samples[0].gold_slides == ("6:21", "6:22")
        assert samples[1].gold_slides == ()


if __name__ == "__main__":
    import sys

    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
