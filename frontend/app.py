import streamlit as st
import requests
import json
import pandas as pd

# Constants
API_BASE_URL = "http://localhost:8000/api"
USER_ID = 1  # Hardcoded for playground purposes

st.set_page_config(page_title="AI SQL Tutor Playground", layout="wide")

st.title("🧠 AI SQL Tutor Playground")
st.markdown(
    "An interactive SQL sandbox revealing the AI's internal state (Redis & ChromaDB)."
)

# Session State for User IDs & currently selected problem
if "problem_id" not in st.session_state:
    st.session_state.problem_id = 1
if "sql_query" not in st.session_state:
    st.session_state.sql_query = ""
if "execution_result" not in st.session_state:
    st.session_state.execution_result = None
if "hint_result" not in st.session_state:
    st.session_state.hint_result = None
if "raw_output" not in st.session_state:
    st.session_state.raw_output = None

# Sidebar: Controls
with st.sidebar:
    st.header("⚙️ Configuration")

    # Fetch problems
    try:
        problems_response = requests.get(f"{API_BASE_URL}/problems")
        if problems_response.ok:
            problems = problems_response.json()
            problem_options = {p["title"]: p["id"] for p in problems}
            selected_problem_title = st.selectbox(
                "Select Problem", options=list(problem_options.keys())
            )
            st.session_state.problem_id = problem_options[selected_problem_title]
    except Exception as e:
        st.error("Failed to connect to the backend API.")
        st.stop()

# Layout
col1, col2, col3 = st.columns([1, 1.5, 1])

# Column 1: Problem Context
with col1:
    st.header("📝 Problem Context")
    if st.session_state.problem_id:
        prob_res = requests.get(
            f"{API_BASE_URL}/problems/{st.session_state.problem_id}"
        )
        if prob_res.ok:
            problem_data = prob_res.json()
            st.subheader(problem_data.get("title", "Unknown Problem"))
            st.markdown(f"**Difficulty:** {problem_data.get('difficulty', 'N/A')}")
            st.write(problem_data.get("description", ""))
            st.markdown("**Expected Output Schema:**")
            st.code(problem_data.get("schema_info", ""))

            # Show a test case
            if problem_data.get("test_cases"):
                st.markdown("**Example Test Case:**")
                tc = problem_data["test_cases"][0]
                expected_output_raw = tc.get("expected_output", "")
                expected_output = expected_output_raw

                # Some test cases store plain text descriptions, not JSON payloads.
                if isinstance(expected_output_raw, str) and expected_output_raw.strip():
                    try:
                        expected_output = json.loads(expected_output_raw)
                    except json.JSONDecodeError:
                        expected_output = expected_output_raw

                if isinstance(expected_output, (dict, list)):
                    st.json({"Expected": expected_output})
                else:
                    st.write({"Expected": expected_output or "N/A"})

# Column 2: SQL Sandbox
with col2:
    st.header("💻 SQL Sandbox")
    sql_input = st.text_area("Write your SQL query here:", height=250, key="sql_query")

    col_submit, col_hint = st.columns([1, 1])

    with col_submit:
        if st.button("Execute & Submit", type="primary", use_container_width=True):
            with st.spinner("Executing and grading..."):
                # First run raw execution
                raw_res = requests.post(
                    f"{API_BASE_URL}/debug/execute_sql", params={"query": sql_input}
                )
                if raw_res.ok:
                    st.session_state.raw_output = raw_res.json()
                else:
                    st.session_state.raw_output = None

                payload = {
                    "user_id": USER_ID,
                    "problem_id": st.session_state.problem_id,
                    "code": sql_input,
                }
                res = requests.post(f"{API_BASE_URL}/submit", json=payload)
                if res.ok:
                    st.session_state.execution_result = res.json()
                else:
                    st.error(f"Error submitting code: {res.text}")

    with col_hint:
        # Note: the pipeline automatically generates hints if an error happens.
        # But we also have a Give Hint button to explicitly show the generated hint.
        if st.button("Give Hint", use_container_width=True):
            with st.spinner("Generating hint..."):
                payload = {
                    "user_id": USER_ID,
                    "problem_id": st.session_state.problem_id,
                    "code": sql_input,
                }
                res = requests.post(f"{API_BASE_URL}/submit", json=payload)
                if res.ok:
                    data = res.json()
                    st.session_state.execution_result = data
                    st.session_state.hint_result = data.get("hint")
                else:
                    st.error("Failed to generate hint.")

    st.subheader("Execution Output")

    if st.session_state.raw_output and isinstance(st.session_state.raw_output, dict):
        if st.session_state.raw_output.get("success"):
            df = pd.DataFrame(
                st.session_state.raw_output.get("rows", []),
                columns=st.session_state.raw_output.get("columns", []),
            )
            st.dataframe(df, use_container_width=True)
        else:
            st.error(
                st.session_state.raw_output.get("error_message", "Check syntax error")
            )

    if st.session_state.execution_result:
        res_data = st.session_state.execution_result
        if res_data.get("overall_passed"):
            st.success("✅ Solution Passed All Test Cases!")
        else:
            st.error("❌ Submission Failed Test Cases")

        diag = res_data.get("diagnosis")
        if diag:
            st.warning(f"**Error Type:** {diag.get('error_type')}")

        # Display grading results
        grading = res_data.get("grading", {})
        if grading:
            st.write(
                f"Passed {grading.get('passed_tests', 0)} / {grading.get('total_tests', 0)} test cases."
            )

        # Display hint if available
        hint_data = st.session_state.hint_result or res_data.get("hint")
        if hint_data:
            st.info(
                f"**Hint (Level {hint_data.get('hint_level')}):** {hint_data.get('hint_text')}"
            )

# Column 3: AI Memory Viewer
with col3:
    st.header("🧠 AI Internal State")

    st.subheader("Short-term Memory (Redis)")
    st.caption("Tracks current session attempts, errors, and hint escalations.")
    try:
        redis_res = requests.get(
            f"{API_BASE_URL}/debug/memory/redis/{USER_ID}/{st.session_state.problem_id}"
        )
        if redis_res.ok:
            redis_data = redis_res.json()
            st.json(redis_data)
        else:
            st.write("No session data found.")
    except Exception:
        st.write("Could not fetch Redis state.")

    st.markdown("---")

    st.subheader("Long-term Memory (ChromaDB)")
    st.caption("Embeds semantic patterns of past struggles and queries for retrieval.")
    try:
        chroma_res = requests.get(f"{API_BASE_URL}/debug/memory/chroma/{USER_ID}")
        if chroma_res.ok:
            chroma_data = chroma_res.json()
            if chroma_data.get("status") == "success" and chroma_data.get("results"):
                docs = chroma_data["results"].get("documents", [])
                metas = chroma_data["results"].get("metadatas", [])
                if docs:
                    st.write(f"Total Stored Interactions: **{len(docs)}**")
                    with st.expander("View Embeddings Data"):
                        for i in range(len(docs)):
                            st.markdown(f"**Interaction {i+1}**")
                            st.json(metas[i])
                            st.text(docs[i])
                else:
                    st.write("No long-term memory records found.")
            else:
                st.write("No long-term memory records found.")
        else:
            st.write("Could not fetch ChromaDB state.")
    except Exception:
        st.write("Could not fetch ChromaDB state.")
