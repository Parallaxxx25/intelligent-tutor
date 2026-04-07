content = open('backend/db/seed.py', encoding='utf-8').read()
start = content.find('SEED_PROBLEMS: list[dict] = [')
end = content.find('# ---------------------------------------------------------------------------', start)

new_code = """def load_problems_from_csv() -> list[dict]:
    import csv
    problems = []
    csv_path = Path(__file__).resolve().parents[2] / "sql-problem" / "Practice-Assignment-Bike shop-2025.csv"
    
    if not csv_path.exists():
        logger.warning(f"CSV file not found: {csv_path}")
        return problems
        
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            seq = str(row.get("ลำดับ", "")).strip()
            if not seq or not row.get("Practice Answer"):
                continue
                
            topic = str(row.get("Topic Evaluated", "SQL")).strip()
            # use only first line of topic for short title
            short_topic = topic.split('\\n')[0].strip()

            prac_en = str(row.get("Practice Question (English)", "")).strip()
            prac_th = str(row.get("Practice Question (Thai)", "")).strip()
            prac_ans = str(row.get("Practice Answer", "")).strip()
            
            if prac_ans and prac_ans.lower() not in ["none", "null", ""]:
                problems.append({
                    "title": f"Practice {seq} - {short_topic}",
                    "description": f"{prac_en}\\n\\n{prac_th}",
                    "difficulty": Difficulty.EASY,
                    "language": Language.SQL,
                    "topic": topic,
                    "starter_code": "-- Write your query here\\n",
                    "test_cases": [{
                        "expected_query": prac_ans,
                        "check_order": "ORDER BY" in prac_ans.upper(),
                        "description": "Practice expected output"
                    }],
                    "gold_standard": {
                        "solution_code": prac_ans,
                        "explanation": "Solve the problem using the corresponding SQL constructs."
                    }
                })

            assign_en = str(row.get("Assignment Question (English)", "")).strip()
            assign_th = str(row.get("Assignment Question (Thai)", "")).strip()
            assign_ans = str(row.get("Assignment Answer", "")).strip()
            
            if assign_ans and assign_ans.lower() not in ["none", "null", ""]:
                problems.append({
                    "title": f"Assignment {seq} - {short_topic}",
                    "description": f"{assign_en}\\n\\n{assign_th}",
                    "difficulty": Difficulty.MEDIUM,
                    "language": Language.SQL,
                    "topic": topic,
                    "starter_code": "-- Write your query here\\n",
                    "test_cases": [{
                        "expected_query": assign_ans,
                        "check_order": "ORDER BY" in assign_ans.upper(),
                        "description": "Assignment expected output"
                    }],
                    "gold_standard": {
                        "solution_code": assign_ans,
                        "explanation": "Solve the problem using the corresponding SQL constructs."
                    }
                })
                
    return problems\n\n"""

patched_content = content[:start] + new_code + content[end:]
confirmation = input(
    "This will overwrite backend/db/seed.py in the repository. "
    "Type 'yes' to continue: "
).strip()
if confirmation != 'yes':
    raise SystemExit("Aborted without modifying backend/db/seed.py.")

open('backend/db/seed.py', 'w', encoding='utf-8').write(patched_content)
