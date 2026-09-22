-- Grant the non-owner runtime role only application DML and canonical auth-profile reads.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'smartroute_runtime') THEN
        CREATE ROLE smartroute_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA smartroute TO smartroute_runtime;
REVOKE CREATE ON SCHEMA smartroute FROM smartroute_runtime;
GRANT SELECT, INSERT, UPDATE ON smartroute.users, smartroute.workspaces, smartroute.api_keys TO smartroute_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON
    smartroute.provider_credentials, smartroute.models, smartroute.workspace_settings,
    smartroute.requests, smartroute.request_attempts, smartroute.testlab_runs,
    smartroute.router_models TO smartroute_runtime;
GRANT USAGE ON SCHEMA neon_auth TO smartroute_runtime;
GRANT SELECT (id, email, name, "emailVerified") ON neon_auth."user" TO smartroute_runtime;
ALTER ROLE smartroute_runtime SET statement_timeout = '15s';
ALTER ROLE smartroute_runtime SET idle_in_transaction_session_timeout = '15s';