import sqlalchemy
from sqlalchemy import create_engine, text

def inspect_database():
    print("🔍 Inspecting the Database...")
    url = 'postgresql://tutor:tutor_pass@localhost:5435/tutor_db'
    engine = create_engine(url)
    
    query = """
    SELECT table_schema, table_name, table_type
    FROM information_schema.tables 
    WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
    ORDER BY table_schema, table_name
    """

    with engine.connect() as conn:
        res = conn.execute(text(query))
        tables = res.fetchall()
        
        if not tables:
            print("❌ No tables found in the database!")
            return

        print(f"✅ Found {len(tables)} tables/views:\n")
        
        for schema, name, t_type in tables:
            print(f"📍 {t_type}: {schema}.{name}")
            try:
                count = conn.execute(text(f'SELECT COUNT(*) FROM "{schema}"."{name}"')).scalar()
                print(f"   Rows: {count}")
                
                # Show columns
                res_cols = conn.execute(text(f'SELECT * FROM "{schema}"."{name}" LIMIT 0'))
                print(f"   Columns: {', '.join(res_cols.keys())}")
                
                # Show sample
                res_sample = conn.execute(text(f'SELECT * FROM "{schema}"."{name}" LIMIT 1'))
                row = res_sample.fetchone()
                if row:
                    print(f"   Sample: {row._asdict()}")
            except Exception as e:
                print(f"   ⚠️ Could not read: {e}")
            print("-" * 40)

if __name__ == "__main__":
    try:
        inspect_database()
    except Exception as e:
        print(f"💥 Failed to connect: {e}")
