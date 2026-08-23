-- Read-only role for student query execution (code_executor.py).
--
-- The app's own tables (users, test_cases, interaction_history, ...) live in
-- `public`; BikeStores lives in `production` and `sales`. A student query
-- runs under this role so it physically cannot read the app schema, no
-- matter what the regex blocklist in code_executor.py misses.
--
-- Idempotent — safe to re-run. Run once against the target database
-- (faculty server or local dev), then set POSTGRES_URL_EXEC to a DSN using
-- this role's credentials.
--
-- Usage: psql "$POSTGRES_URL_SYNC" -f scripts/provision_student_ro.sql

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'student_ro') THEN
        CREATE ROLE student_ro WITH LOGIN PASSWORD 'CHANGE_ME_student_ro_pass';
    END IF;
END
$$;

REVOKE ALL ON SCHEMA public FROM student_ro;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM student_ro;

GRANT USAGE ON SCHEMA production TO student_ro;
GRANT USAGE ON SCHEMA sales TO student_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA production TO student_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA sales TO student_ro;

-- Cover tables created after this script runs (e.g. a reseed).
ALTER DEFAULT PRIVILEGES IN SCHEMA production GRANT SELECT ON TABLES TO student_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA sales GRANT SELECT ON TABLES TO student_ro;
