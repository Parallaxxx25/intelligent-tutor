"""
Ablation: v1 (attempt-count-only) vs v2 (multi-signal) hint escalation.

Runs synthetic multi-attempt sessions through both
``escalation_policy.attempt_count_floor`` (v1) and
``escalation_policy.decide_hint_level`` (v2), turn by turn, and reports a
side-by-side comparison table per scenario plus a summary of how often the
two policies disagree. This is the deterministic-vs-adaptive comparison
artifact for the thesis evaluation section - see
docs/hint-escalation-policy-v2.md.

Each scenario models a plausible student session: topic_mastery is fixed
per scenario (read once at the problem boundary, per design - see decision
4 in the design doc), while error_type/query/dwell vary per attempt. At
each turn, the v2 decision is computed from the history of *prior* turns
only (never the current one) - the same contract routes.py follows via
backend/db/queries.py.

Usage:
    python -m backend.evaluation.run_ablation
    python -m backend.evaluation.run_ablation --output csv --csv-path ablation_v1_vs_v2.csv
"""

from __future__ import annotations

import argparse
import csv
import io
from dataclasses import dataclass
from datetime import datetime, timezone

from backend.agents.escalation_policy import (
    EscalationSignals,
    POLICY_VERSION,
    attempt_count_floor,
    decide_hint_level,
)


@dataclass
class Turn:
    error_type: str
    query: str
    dwell_seconds: float | None = None  # gap since the previous submission


@dataclass
class Scenario:
    name: str
    description: str
    turns: list[Turn]
    topic_mastery: str | None = None
    starter_code: str | None = "-- Write your query here\n"


@dataclass
class TurnResult:
    scenario: str
    attempt: int
    error_type: str
    dwell_seconds: float | None
    v1_level: int
    v2_level: int
    v2_drivers: str


SCENARIOS: list[Scenario] = [
    Scenario(
        name="stuck_on_one_concept",
        description=(
            "Same conceptual error (join_error) four attempts running, plenty "
            "of dwell time between each - genuine, sustained struggle."
        ),
        turns=[
            Turn("join_error", "SELECT o.id, c.name FROM orders o, customers c", 60.0),
            Turn("join_error", "SELECT o.id, c.name FROM orders o, customers c WHERE 1=1", 90.0),
            Turn("join_error", "SELECT o.id, c.name FROM orders JOIN customers", 120.0),
            Turn("join_error", "SELECT o.id, c.name FROM orders JOIN customers ON true", 75.0),
        ],
    ),
    Scenario(
        name="flailing",
        description=(
            "A different shallow/conceptual error every attempt - guessing, "
            "not stuck on one concept. No driver should ever fire."
        ),
        turns=[
            Turn("syntax_error", "SELECT name FROM", 30.0),
            Turn("column_error", "SELECT nam FROM customers", 30.0),
            Turn("relation_error", "SELECT name FROM customer", 30.0),
            Turn("ambiguity_error", "SELECT id FROM orders o, customers c", 30.0),
        ],
    ),
    Scenario(
        name="fast_resubmit_spammer",
        description=(
            "Identical query resubmitted within seconds, repeatedly - evidence "
            "the hint isn't being read (Fan et al. 2024), not of needing more."
        ),
        turns=[
            Turn("join_error", "SELECT o.id, c.name FROM orders o, customers c", 60.0),
            Turn("join_error", "SELECT o.id, c.name FROM orders o, customers c", 4.0),
            Turn("join_error", "SELECT o.id, c.name FROM orders o, customers c", 3.0),
            Turn("join_error", "SELECT o.id, c.name FROM orders o, customers c", 5.0),
        ],
    ),
    Scenario(
        name="mastered_topic",
        description=(
            "Student already ADVANCED elsewhere on this topic, but genuinely "
            "struggles here too - grace delays escalation, doesn't withhold it."
        ),
        topic_mastery="advanced",
        turns=[
            Turn("aggregation_error", "SELECT dept, name, COUNT(*) FROM t GROUP BY dept", 45.0),
            Turn("aggregation_error", "SELECT dept, name, COUNT(*) FROM t GROUP BY dept, name", 45.0),
            Turn("aggregation_error", "SELECT dept, COUNT(name) FROM t GROUP BY dept", 45.0),
            Turn("aggregation_error", "SELECT dept, COUNT(*) FROM t GROUP BY dept HAVING 1=1", 45.0),
            Turn("aggregation_error", "SELECT dept, COUNT(*) FROM t WHERE dept IS NOT NULL GROUP BY dept", 45.0),
        ],
    ),
    Scenario(
        name="typo_then_conceptual",
        description=(
            "Two shallow typos first (never escalate, however often repeated), "
            "then the error shifts to a genuine conceptual gap."
        ),
        turns=[
            Turn("syntax_error", "SELECT nam FROM customers", 20.0),
            Turn("syntax_error", "SELECT name FROM customer", 20.0),
            Turn("join_error", "SELECT o.id, c.name FROM orders o, customers c", 40.0),
            Turn("join_error", "SELECT o.id, c.name FROM orders o, customers c WHERE 1=1", 40.0),
            Turn("join_error", "SELECT o.id, c.name FROM orders JOIN customers", 40.0),
        ],
    ),
]


def run_scenario(scenario: Scenario) -> list[TurnResult]:
    """Replay one scenario turn by turn, building history from strictly
    prior turns (never the current one) - matches production's contract."""
    error_type_history: list[str] = []
    query_history: list[str] = []
    hint_level_history: list[int] = []
    results: list[TurnResult] = []

    for i, turn in enumerate(scenario.turns, start=1):
        v1_level = attempt_count_floor(i)

        signals = EscalationSignals(
            attempt_count=i,
            error_type=turn.error_type,
            error_type_history=tuple(error_type_history),
            query_history=tuple(query_history),
            hint_level_history=tuple(hint_level_history),
            seconds_since_prev=turn.dwell_seconds,
            topic_mastery=scenario.topic_mastery,
            current_query=turn.query,
            starter_code=scenario.starter_code,
        )
        decision = decide_hint_level(signals)

        results.append(
            TurnResult(
                scenario=scenario.name,
                attempt=i,
                error_type=turn.error_type,
                dwell_seconds=turn.dwell_seconds,
                v1_level=v1_level,
                v2_level=decision.level,
                v2_drivers=", ".join(decision.drivers) if decision.drivers else "-",
            )
        )

        # Production always serves the v2-decided level -- next turn's
        # history reflects what actually happened, not the v1 counterfactual.
        error_type_history.append(turn.error_type)
        query_history.append(turn.query)
        hint_level_history.append(decision.level)

    return results


def run_ablation() -> list[TurnResult]:
    results: list[TurnResult] = []
    for scenario in SCENARIOS:
        results.extend(run_scenario(scenario))
    return results


def format_markdown(results: list[TurnResult]) -> str:
    lines = [
        f"# Hint Escalation Ablation: v1 (attempt-count-only) vs {POLICY_VERSION}",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
    ]

    by_scenario: dict[str, list[TurnResult]] = {}
    for r in results:
        by_scenario.setdefault(r.scenario, []).append(r)

    scenario_by_name = {s.name: s for s in SCENARIOS}
    total_turns = len(results)
    diverged = sum(1 for r in results if r.v1_level != r.v2_level)

    lines.append(
        f"**Summary:** {diverged}/{total_turns} attempts diverge from the v1 level "
        f"across {len(SCENARIOS)} scenarios."
    )
    lines.append("")

    for name, rows in by_scenario.items():
        scenario = scenario_by_name[name]
        scenario_diverged = sum(1 for r in rows if r.v1_level != r.v2_level)
        lines.append(f"## {name} ({scenario_diverged}/{len(rows)} diverged)")
        lines.append("")
        lines.append(scenario.description)
        lines.append("")
        lines.append("| Attempt | Error Type | Dwell (s) | v1 Level | v2 Level | v2 Drivers |")
        lines.append("|---|---|---|---|---|---|")
        for r in rows:
            marker = " **<-diverges**" if r.v1_level != r.v2_level else ""
            dwell = f"{r.dwell_seconds:.0f}" if r.dwell_seconds is not None else "-"
            lines.append(
                f"| {r.attempt} | {r.error_type} | {dwell} | {r.v1_level} | "
                f"{r.v2_level}{marker} | {r.v2_drivers} |"
            )
        lines.append("")

    return "\n".join(lines)


def format_csv(results: list[TurnResult]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "policy_version",
            "scenario",
            "attempt",
            "error_type",
            "dwell_seconds",
            "v1_level",
            "v2_level",
            "diverged",
            "v2_drivers",
        ]
    )
    for r in results:
        writer.writerow(
            [
                POLICY_VERSION,
                r.scenario,
                r.attempt,
                r.error_type,
                r.dwell_seconds if r.dwell_seconds is not None else "",
                r.v1_level,
                r.v2_level,
                int(r.v1_level != r.v2_level),
                r.v2_drivers,
            ]
        )
    return buf.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ablation: v1 (attempt-count-only) vs v2 (multi-signal) hint escalation",
    )
    parser.add_argument("--output", choices=["markdown", "csv"], default="markdown")
    parser.add_argument("--csv-path", type=str, default=None)
    args = parser.parse_args()

    results = run_ablation()

    if args.output == "csv":
        csv_text = format_csv(results)
        path = args.csv_path or "ablation_v1_vs_v2.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            f.write(csv_text)
        print(f"CSV written to: {path}")
        print(csv_text)
    else:
        print(format_markdown(results))


if __name__ == "__main__":
    main()
