"""
Mastery Tracker — promotes a student's MasteryLevel from a graded attempt.

Promotion only; a bad attempt never demotes a level already earned.
"""

from __future__ import annotations

import logging

from backend.db.models import MasteryLevel, StudentProgress

logger = logging.getLogger(__name__)

# Declaration order in the enum is the progression order.
_ORDER = list(MasteryLevel)


def update_mastery(
    progress: StudentProgress,
    score: float,
    attempts: int,
) -> MasteryLevel:
    """
    Promote ``progress.mastery_level`` based on this attempt's score.

    EXPERT needs a perfect score within 2 attempts; the rest are score
    thresholds (0.9 / 0.7 / 0.4). Mutates ``progress``; the caller's session
    commits.
    """
    current = progress.mastery_level or MasteryLevel.NOVICE

    if score >= 1.0 and attempts <= 2:
        new_level = MasteryLevel.EXPERT
    elif score >= 0.9:
        new_level = MasteryLevel.ADVANCED
    elif score >= 0.7:
        new_level = MasteryLevel.INTERMEDIATE
    elif score >= 0.4:
        new_level = MasteryLevel.BEGINNER
    else:
        new_level = current

    if _ORDER.index(new_level) > _ORDER.index(current):
        progress.mastery_level = new_level
        logger.info(
            "Student %s promoted to %s for problem %s.",
            progress.user_id, new_level, progress.problem_id,
        )
        return new_level

    return current
