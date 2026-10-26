-- Read-only checks after migration, as neondb_owner in the separate Neon project.
-- Infrastructure/project identity must also be checked in the Neon console.
SELECT current_database(), session_user, current_user;
SELECT nspname, pg_get_userbyid(nspowner) AS owner
FROM pg_namespace WHERE nspname = 'fva_technical_test';
SELECT id, app, format FROM fva_technical_test.identity;
SELECT count(*) AS event_count FROM fva_technical_test.events;
SELECT c.relname, c.relkind, pg_get_userbyid(c.relowner) AS owner
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='fva_technical_test' ORDER BY c.relname;
SELECT rolname, rolcanlogin, rolinherit, rolsuper, rolcreatedb,
       rolcreaterole, rolreplication, rolbypassrls
FROM pg_roles WHERE rolname='fva_test_app';
-- Expect zero rows, including indirect SET ROLE paths (all memberships forbidden).
SELECT pg_get_userbyid(roleid) AS granted_role, pg_get_userbyid(member) AS member
FROM pg_auth_members
WHERE roleid='fva_test_app'::regrole OR member='fva_test_app'::regrole;
SELECT has_database_privilege('fva_test_app',current_database(),'CONNECT') AS connect_expected_true,
       has_database_privilege('fva_test_app',current_database(),'CREATE') AS create_expected_false,
       has_database_privilege('fva_test_app',current_database(),'TEMP') AS temp_expected_false,
       has_schema_privilege('fva_test_app','public','CREATE') AS public_create_expected_false,
       has_schema_privilege('fva_test_app','fva_technical_test','USAGE') AS usage_expected_true,
       has_schema_privilege('fva_test_app','fva_technical_test','CREATE') AS schema_create_expected_false;
SELECT has_table_privilege('fva_test_app','fva_technical_test.events','SELECT') AS select_expected_true,
       has_table_privilege('fva_test_app','fva_technical_test.events','INSERT') AS insert_expected_true,
       has_table_privilege('fva_test_app','fva_technical_test.events','UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') AS unsafe_expected_false,
       has_column_privilege('fva_test_app','fva_technical_test.identity','id','UPDATE') AS id_update_expected_true,
       has_column_privilege('fva_test_app','fva_technical_test.identity','recorded_at','UPDATE') AS clock_update_expected_false,
       has_column_privilege('fva_test_app','fva_technical_test.identity','recording_transaction','UPDATE') AS xid_update_expected_false;
SELECT p.proname, pg_get_userbyid(p.proowner) AS owner, p.prosecdef, p.proconfig,
       has_function_privilege('fva_test_app',p.oid,'EXECUTE') AS app_execute,
       p.proacl
FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
WHERE n.nspname='fva_technical_test' ORDER BY p.proname;
-- reserve_recording_time: app_execute=true; guard_event: false.
-- Both: SECURITY DEFINER, search_path=pg_catalog, no PUBLIC EXECUTE.
SELECT table_name, grantee, privilege_type
FROM information_schema.table_privileges
WHERE table_schema='fva_technical_test' ORDER BY table_name,grantee,privilege_type;
SELECT table_name,column_name,grantee,privilege_type
FROM information_schema.column_privileges
WHERE table_schema='fva_technical_test' ORDER BY table_name,column_name,grantee,privilege_type;
-- Expect zero rows: app owns nothing anywhere in this cluster.
SELECT classid::regclass, objid, dbid FROM pg_shdepend
WHERE refclassid='pg_authid'::regclass AND refobjid='fva_test_app'::regrole AND deptype='o';
