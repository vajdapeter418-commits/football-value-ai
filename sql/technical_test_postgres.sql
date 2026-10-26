-- Provision manually ONLY in a separate synthetic test project/database.
-- Run as schema owner (Neon: neondb_owner), never as application role.
-- psql: -X --set=ON_ERROR_STOP=1 --file=sql/technical_test_postgres.sql
BEGIN;
SET LOCAL search_path = pg_catalog;
SET LOCAL lock_timeout = '10s';
-- Serializes cooperating migration runs; stop other schema writers operationally.
SELECT pg_advisory_xact_lock(706014, 14);
DO $preflight$
DECLARE ns oid; app oid; owner_id oid;
BEGIN
 SELECT oid INTO owner_id FROM pg_roles WHERE rolname = current_user;
 SELECT oid INTO app FROM pg_roles WHERE rolname = 'fva_test_app';
 IF app IS NULL OR app = owner_id OR session_user = 'fva_test_app' THEN
  RAISE EXCEPTION 'A separate pre-existing fva_test_app role is required';
 END IF;
 IF EXISTS (SELECT FROM pg_roles WHERE oid = app AND
     (NOT rolcanlogin OR rolinherit OR rolsuper OR rolcreatedb OR rolcreaterole
      OR rolreplication OR rolbypassrls)) THEN
  RAISE EXCEPTION 'Unsafe fva_test_app role attributes';
 END IF;
 -- Reject even NOINHERIT memberships: SET ROLE can still escalate.
 IF EXISTS (SELECT FROM pg_auth_members WHERE member = app OR roleid = app) THEN
  RAISE EXCEPTION 'fva_test_app must have no role memberships in either direction';
 END IF;
 IF EXISTS (SELECT FROM pg_shdepend WHERE refclassid = 'pg_authid'::regclass
            AND refobjid = app AND deptype = 'o') THEN
  RAISE EXCEPTION 'fva_test_app must not own database objects';
 END IF;
 IF NOT has_database_privilege(current_user, current_database(), 'CREATE') THEN
  RAISE EXCEPTION 'Migration owner requires database CREATE privilege';
 END IF;
 IF NOT has_database_privilege(app, current_database(), 'CONNECT')
    OR has_database_privilege(app, current_database(), 'CREATE')
    OR has_database_privilege(app, current_database(), 'TEMP') THEN
  RAISE EXCEPTION 'fva_test_app requires CONNECT, without database CREATE or TEMP';
 END IF;
 IF EXISTS (SELECT FROM pg_namespace WHERE nspname !~ '^pg_'
            AND nspname <> 'information_schema'
            AND (has_schema_privilege(app, oid, 'CREATE') OR
                 (nspname <> 'public' AND has_schema_privilege(app, oid, 'USAGE')))) THEN
  RAISE EXCEPTION 'fva_test_app has access to another application schema';
 END IF;
 IF EXISTS (SELECT FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
            AND c.relkind IN ('r','p','v','m','f','S') AND
            CASE WHEN c.relkind = 'S' THEN
             has_sequence_privilege(app,c.oid,'USAGE,SELECT,UPDATE')
            ELSE has_table_privilege(app,c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
                 OR has_any_column_privilege(app,c.oid,'SELECT,INSERT,UPDATE,REFERENCES') END)
    OR EXISTS (SELECT FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
               WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
               AND has_function_privilege(app,p.oid,'EXECUTE')) THEN
  RAISE EXCEPTION 'fva_test_app has pre-existing application object privileges';
 END IF;
 -- Owner default ACLs must not silently grant access to unrelated roles.
 IF EXISTS (SELECT FROM pg_default_acl d CROSS JOIN LATERAL aclexplode(d.defaclacl) a
            WHERE d.defaclrole = owner_id AND a.grantee <> owner_id
            AND d.defaclnamespace IN (0, COALESCE(to_regnamespace('fva_technical_test')::oid,0))) THEN
  RAISE EXCEPTION 'Unsafe migration owner default privileges';
 END IF;
 SELECT oid INTO ns FROM pg_namespace WHERE nspname = 'fva_technical_test';
 IF ns IS NULL THEN
  CREATE SCHEMA fva_technical_test;
 ELSE
  IF (SELECT nspowner FROM pg_namespace WHERE oid=ns) <> owner_id THEN
   RAISE EXCEPTION 'Existing test schema must be owned by current_user';
  END IF;
  IF NOT has_schema_privilege(current_user, ns, 'USAGE')
     OR NOT has_schema_privilege(current_user, ns, 'CREATE') THEN
   RAISE EXCEPTION 'Migration owner requires schema USAGE and CREATE';
  END IF;
  -- Namespace dependencies cover tables, types, functions, operators, collations,
  -- text search objects, etc.; a table-only emptiness test is insufficient.
  IF EXISTS (SELECT FROM pg_depend WHERE refclassid='pg_namespace'::regclass
             AND refobjid=ns) THEN
   RAISE EXCEPTION 'Existing test schema is not empty';
  END IF;
  IF EXISTS (SELECT FROM pg_namespace n CROSS JOIN LATERAL
             aclexplode(COALESCE(n.nspacl,acldefault('n',n.nspowner))) a
             WHERE n.oid=ns AND a.grantee <> owner_id) THEN
   RAISE EXCEPTION 'Existing test schema has unexpected grants';
  END IF;
 END IF;
END $preflight$;
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
