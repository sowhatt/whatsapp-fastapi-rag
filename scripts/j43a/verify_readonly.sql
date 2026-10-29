-- Review-only catalogue checks. No connection target or credential embedded.
-- This file is not automatically executed against staging by any J4.3A tool.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '10s';
SELECT current_database() AS database_name, current_schema() AS schema_name,
       current_user AS runtime_role, current_setting('server_version_num') AS version;
SELECT rolname, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, rolreplication,
       rolcanlogin, rolinherit FROM pg_roles WHERE rolname=current_user;
SELECT parent.rolname AS granted_role, member.rolname AS member,
       a.admin_option, a.inherit_option, a.set_option
FROM pg_auth_members a JOIN pg_roles parent ON parent.oid=a.roleid
JOIN pg_roles member ON member.oid=a.member WHERE member.rolname=current_user;
SELECT schemaname,tablename,tableowner,rowsecurity FROM pg_tables
WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY 1,2;
SELECT n.nspname,c.relname,c.relrowsecurity,c.relforcerowsecurity,
       has_table_privilege(current_user,c.oid,'SELECT') AS can_read,
       has_table_privilege(current_user,c.oid,'INSERT') AS can_insert,
       has_table_privilege(current_user,c.oid,'UPDATE') AS can_update,
       has_table_privilege(current_user,c.oid,'DELETE') AS can_delete,
       has_table_privilege(current_user,c.oid,'TRUNCATE') AS can_truncate
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE c.relkind='r' AND n.nspname='public' ORDER BY c.relname;
SELECT schemaname,tablename,policyname,roles,cmd,qual,with_check
FROM pg_policies WHERE schemaname='public' ORDER BY tablename,policyname;
COMMIT;
