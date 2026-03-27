"""
Mastery Tracker — Aggregates and updates student proficiency across SQL topics.

Responsible for:
  - Transitioning MasteryLevel (NOVICE, BEGINNER, INTERMEDIATE, ADVANCED, EXPERT)
  - Calculating rolling topic performance
  - Determining if a student is "stuck"
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import StudentProgress, MasteryLevel

logger = logging.getLogger(__name__)

class MasteryTracker:
    """Class to manage student progress and level transitions."""

    async def update_mastery(
        self, 
        db: AsyncSession, 
        user_id: int, 
        problem_id: int, 
        score: float, 
        attempts: int,
        topic: str = "general"
    ) -> MasteryLevel:
        """
        Evaluate and update a student's mastery level for a specific problem.
        
        Logic for transitions:
        - NOVICE: Default level.
        - BEGINNER: Achieved best_score >= 0.4.
        - INTERMEDIATE: Achieved best_score >= 0.7.
        - ADVANCED: Achieved best_score >= 0.9.
        - EXPERT: Achieved best_score == 1.0 within 1-2 attempts.
        
        Note: Future updates might aggregate levels across multiple problems for a topic.
        """
        result = await db.execute(
            select(StudentProgress).where(
                StudentProgress.user_id == user_id,
                StudentProgress.problem_id == problem_id
            )
        )
        progress = result.scalars().first()
        
        if not progress:
            # Should skip if initialization was successful, but handle gracefully.
            return MasteryLevel.NOVICE

        current_level = progress.mastery_level
        new_level = current_level

        # Evaluate transitions
        if score >= 1.0 and attempts <= 2:
            new_level = MasteryLevel.EXPERT
        elif score >= 0.9:
            new_level = MasteryLevel.ADVANCED
        elif score >= 0.7:
            new_level = MasteryLevel.INTERMEDIATE
        elif score >= 0.4:
            new_level = MasteryLevel.BEGINNER

        # Only allow level progression (don't downgrade mastery)
        # Assuming levels are ordered logic: NOVICE < BEGINNER < INTERMEDIATE < ADVANCED < EXPERT
        level_order = [
            MasteryLevel.NOVICE, 
            MasteryLevel.BEGINNER, 
            MasteryLevel.INTERMEDIATE, 
            MasteryLevel.ADVANCED, 
            MasteryLevel.EXPERT
        ]
        
        if level_order.index(new_level) > level_order.index(current_level):
            progress.mastery_level = new_level
            logger.info("Student %d promoted to %s for problem %d.", user_id, new_level, problem_id)
            # Commit handled by the outer session management layer
        
        return new_level

    async def get_topic_mastery(self, db: AsyncSession, user_id: int, topic: str) -> MasteryLevel:
        """
        Aggregate mastery across all problems within a specific topic.
        
        Returns the mode (most frequent) level of the student for that topic.
        """
        # Join with Problem table once topic filtering is required.
        # For now, we take an average of the mastery scores or a simple count.
        # This is a placeholder for more advanced topic-level mastery rules.
        return MasteryLevel.NOVICE

# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_mastery_tracker: Optional[MasteryTracker] = None

def get_mastery_tracker() -> MasteryTracker:
    """Return the global MasteryTracker instance."""
    global _mastery_tracker
    if _mastery_tracker is None:
        _mastery_tracker = MasteryTracker()
    return _mastery_tracker
