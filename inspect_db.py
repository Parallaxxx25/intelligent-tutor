import asyncio
from sqlalchemy import create_engine, text

def inspect_database():
    print("🔍 Inspecting the Database...\n")
    engine = create_engine('postgresql://tutor:tutor_pass@localhost:5435/tutor_db')
    query = """
    SELECT table_schema, table_name 
    FROM information_schema.tables 
    WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
    ORDER BY table_schema, table_name
    """

    with engine.connect() as conn:
        res = conn.execute(text(query))
        tables = [(row[0], row[1]) for row in res]
        
        for schema, table in tables:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {schema}.{table}")).scalar()
            print(f"--- Schema: {schema} | Table: {table} (Count: {count}) ---")
            
            try:
                res2 = conn.execute(text(f"SELECT * FROM {schema}.{table} LIMIT 2"))
                cols = list(res2.keys())
                rows = [list(r) for r in res2]
                if not rows:
                    print("  No rows.\n")
                else:
                    for r in rows:
                        print("  ", dict(zip(cols, r)))
                    print()
            except Exception as e:
                print(f"  Error reading {schema}.{table}: {e}\n")

if __name__ == "__main__":
    inspect_database()
