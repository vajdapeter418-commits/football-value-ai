-- Provision manually ONLY in a separate synthetic test project/database.
-- Run as migration owner, never as application role. Replace role name as needed.
BEGIN;
CREATE SCHEMA fva_technical_test;
REVOKE ALL ON SCHEMA fva_technical_test FROM PUBLIC;
CREATE TABLE fva_technical_test.identity (
 id integer PRIMARY KEY CHECK(id=1), app text NOT NULL, format text NOT NULL,
 recorded_at timestamptz, recording_transaction bigint
);
INSERT INTO fva_technical_test.identity (id,app,format) VALUES
 (1,'football-value-ai-market-test','TESZT-postgres-v1');
CREATE TABLE fva_technical_test.events (
 seq bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 request_id uuid NOT NULL UNIQUE,
 request_hash text NOT NULL CHECK(length(request_hash)=64),
 kind text NOT NULL CHECK(kind IN ('observations','results')),
 fixture_id text NOT NULL CHECK(fixture_id LIKE 'TESZT-%'),
 observed_at timestamptz NOT NULL,
 recorded_at timestamptz NOT NULL UNIQUE,
 entry jsonb NOT NULL,
 CHECK(entry->'payload'->>'fixture_id'=fixture_id),
 CHECK((entry->'payload'->>'recorded_at')::timestamptz=recorded_at)
);
-- Only this DB function can reserve the immutable server recording time.
CREATE FUNCTION fva_technical_test.reserve_recording_time() RETURNS timestamptz
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE stamp timestamptz;
BEGIN
 UPDATE fva_technical_test.identity
 SET recorded_at=GREATEST(clock_timestamp(), recorded_at + interval '1 microsecond'),
     recording_transaction=txid_current()
 WHERE id=1 RETURNING recorded_at INTO STRICT stamp;
 RETURN stamp;
END $$;
CREATE FUNCTION fva_technical_test.guard_event() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE stamp timestamptz; xid bigint;
BEGIN
 SELECT recorded_at, recording_transaction INTO STRICT stamp, xid
 FROM fva_technical_test.identity WHERE id=1 FOR UPDATE;
 IF stamp IS NULL OR NEW.recorded_at IS DISTINCT FROM stamp OR xid IS DISTINCT FROM txid_current() THEN
  RAISE EXCEPTION 'Invalid DB recording time';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_event BEFORE INSERT ON fva_technical_test.events
 FOR EACH ROW EXECUTE FUNCTION fva_technical_test.guard_event();
REVOKE ALL ON ALL TABLES IN SCHEMA fva_technical_test FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA fva_technical_test FROM PUBLIC;
-- Dedicated non-owner LOGIN role must already exist, with no inherited production
-- access and no CREATE privilege on database or public schema.
GRANT EXECUTE ON FUNCTION fva_technical_test.reserve_recording_time() TO fva_test_app;
GRANT USAGE ON SCHEMA fva_technical_test TO fva_test_app;
GRANT SELECT ON fva_technical_test.identity TO fva_test_app;
-- PostgreSQL row locks require UPDATE privilege; grant only immutable id column.
GRANT UPDATE(id) ON fva_technical_test.identity TO fva_test_app;
GRANT SELECT, INSERT ON fva_technical_test.events TO fva_test_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA fva_technical_test TO fva_test_app;
COMMIT;
