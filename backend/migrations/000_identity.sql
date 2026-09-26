CREATE TABLE app_users (
  id TEXT PRIMARY KEY, email TEXT UNIQUE, display_name TEXT NOT NULL,
  password_hash TEXT, role TEXT NOT NULL CHECK(role IN ('admin','user')),
  status TEXT NOT NULL CHECK(status IN ('pending_setup','active','disabled')),
  email_verified BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), last_login_at TIMESTAMPTZ
);
CREATE TABLE auth_sessions (
  token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES app_users(id),
  expires_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX auth_sessions_user ON auth_sessions(user_id);
CREATE TABLE auth_codes (
  email TEXT NOT NULL, purpose TEXT NOT NULL, code_hash TEXT NOT NULL,
  payload TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
  expires_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY(email,purpose)
);
CREATE TABLE auth_limits (key TEXT PRIMARY KEY, hits INTEGER NOT NULL, reset_at TIMESTAMPTZ NOT NULL);
CREATE TABLE server_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE admin_events (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  actor_id TEXT REFERENCES app_users(id), target_id TEXT,
  action TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
