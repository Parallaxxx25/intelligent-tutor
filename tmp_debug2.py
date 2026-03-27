from backend.agents.supervisor import run_pipeline_llm
from backend.db.schemas import CodeSubmission
from unittest.mock import patch


@patch("backend.rag.retriever.retrieve_relevant_context")
@patch("backend.llm.generate_structured_response")
@patch("backend.llm.generate_response")
@patch("backend.agents.supervisor.run_sql_tests")
def run(mock_tests, mock_gen, mock_structured, mock_rag):
    sample_submission = CodeSubmission(
        user_id=1,
        problem_id=1,
        code="SELECT\n  name\nFROM employee\nWHERE\n  salary > 50000",
    )
    sample_test_cases = [
        {
            "expected_output": "",
            "input_data": "SELECT name FROM employees WHERE salary > 50000",
            "test_case_id": 1,
        }
    ]
    mock_tests.return_value = {
        "passed": False,
        "passed_tests": 0,
        "score": 0.0,
        "student_error": 'relation "employee" does not exist',
        "test_results": [],
        "total_tests": 1,
    }
    mock_rag.return_value = []

    mock_structured.return_value = {
        "error_type": "relation_error",
        "error_message": "Table 'employee' does not exist",
        "problematic_clause": "FROM",
        "severity": "medium",
        "recommended_hint_level": 1,
        "pedagogical_rationale": "First attempt, gentle nudge.",
    }

    mock_gen.side_effect = RuntimeError("Gemini quota exceeded")

    try:
        result = run_pipeline_llm(
            submission=sample_submission,
            problem_description="Select employee names",
            problem_topic="SELECT basics",
            test_cases=sample_test_cases,
            attempt_count=1,
        )
        print("FINISHED PIPELINE!")
        print(repr(result.hint))
    except Exception as e:
        print("ERROR:", e)
    finally:
        from backend.tools.hint_generator import generate_sql_hint

        print(
            "TEST generate_sql_hint:",
            generate_sql_hint(
                error_type="relation_error",
                error_message="Table 'employee' does not exist",
                student_query="SELECT * FROM employee",
                attempt_count=1,
                problem_description="Select employee names",
                problematic_clause="FROM",
            ),
        )


if __name__ == "__main__":
    run()
