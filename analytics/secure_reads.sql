-- Apply AFTER each dbt build: rebuilt tables need the same tenant policy.
-- A DBA provisions LOGIN roles and grants this NOLOGIN role only at a trusted
-- BI gateway; app.tenant_id is set by that gateway, never supplied SQL by users.
DO $$ BEGIN
 IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='analytics_reader') THEN
  CREATE ROLE analytics_reader NOLOGIN NOSUPERUSER NOBYPASSRLS;
 END IF;
END $$;
DO $$ DECLARE item record; BEGIN
 FOR item IN SELECT table_schema,table_name FROM information_schema.columns
  WHERE column_name='tenant_id' AND table_schema IN ('raw','analytics')
    AND table_name <> 'tenant_readers' AND table_name NOT IN (SELECT table_name FROM information_schema.views)
 LOOP
  EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY',item.table_schema,item.table_name);
  EXECUTE format('DROP POLICY IF EXISTS tenant_read ON %I.%I',item.table_schema,item.table_name);
  EXECUTE format('CREATE POLICY tenant_read ON %I.%I FOR SELECT TO analytics_reader USING (tenant_id = (SELECT tenant_id FROM raw.tenant_readers WHERE role_name=current_user))',item.table_schema,item.table_name);
  EXECUTE format('GRANT SELECT ON %I.%I TO analytics_reader',item.table_schema,item.table_name);
 END LOOP;
END $$;
GRANT USAGE ON SCHEMA raw TO analytics_reader;
DO $$ BEGIN IF EXISTS (SELECT FROM pg_namespace WHERE nspname='analytics') THEN
 GRANT USAGE ON SCHEMA analytics TO analytics_reader;
END IF; END $$;

DROP POLICY IF EXISTS own_mapping ON raw.tenant_readers;
CREATE POLICY own_mapping ON raw.tenant_readers FOR SELECT TO analytics_reader USING(role_name=current_user);
GRANT SELECT ON raw.tenant_readers TO analytics_reader;
