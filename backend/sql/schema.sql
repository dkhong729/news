-- AI Insight Pulse Database Schema (Production MVP)

CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT,
  display_name TEXT,
  role TEXT NOT NULL DEFAULT 'tech' CHECK (role IN ('admin','vc','biz','tech')),
  timezone TEXT NOT NULL DEFAULT 'Asia/Taipei',
  is_email_verified BOOLEAN NOT NULL DEFAULT FALSE,
  is_email_valid BOOLEAN NOT NULL DEFAULT TRUE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  last_login_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS roles (
  id SERIAL PRIMARY KEY,
  code TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS permissions (
  id SERIAL PRIMARY KEY,
  code TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS role_permissions (
  role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  permission_id INTEGER NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE IF NOT EXISTS user_roles (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (user_id, role_id)
);

CREATE TABLE IF NOT EXISTS user_identities (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,
  provider_sub TEXT NOT NULL,
  email TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (provider, provider_sub)
);

CREATE TABLE IF NOT EXISTS user_preferences (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  subscribe_daily BOOLEAN NOT NULL DEFAULT FALSE,
  delivery_channel TEXT NOT NULL DEFAULT 'email',
  delivery_time TEXT NOT NULL DEFAULT '08:00',
  language TEXT NOT NULL DEFAULT 'zh-TW',
  topics TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  sources TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  max_items INTEGER NOT NULL DEFAULT 10
);

CREATE TABLE IF NOT EXISTS user_sources (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  url TEXT NOT NULL,
  source_type TEXT NOT NULL DEFAULT 'custom',
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sources (
  id SERIAL PRIMARY KEY,
  code TEXT UNIQUE,
  type TEXT NOT NULL,
  name TEXT NOT NULL,
  url TEXT,
  authority_score REAL NOT NULL DEFAULT 50,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS raw_items (
  id SERIAL PRIMARY KEY,
  source_id INTEGER REFERENCES sources(id),
  source_type TEXT NOT NULL,
  item_kind TEXT NOT NULL DEFAULT 'web' CHECK (item_kind IN ('paper','post','event','web')),
  external_id TEXT,
  url TEXT NOT NULL,
  title TEXT,
  content TEXT,
  author TEXT,
  published_at TIMESTAMPTZ,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  content_hash TEXT,
  raw_meta JSONB NOT NULL DEFAULT '{}'::JSONB,
  UNIQUE (url),
  UNIQUE NULLS NOT DISTINCT (source_type, external_id)
);

CREATE TABLE IF NOT EXISTS normalized_items (
  id SERIAL PRIMARY KEY,
  raw_id INTEGER UNIQUE REFERENCES raw_items(id) ON DELETE CASCADE,
  title TEXT,
  summary TEXT,
  why_it_matters TEXT,
  category TEXT NOT NULL CHECK (category IN ('ai_tech','product_biz')),
  content_type TEXT NOT NULL DEFAULT 'web' CHECK (content_type IN ('paper','post','web')),
  tags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  language TEXT NOT NULL DEFAULT 'zh-TW',
  entities JSONB NOT NULL DEFAULT '{}'::JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scores (
  item_id INTEGER PRIMARY KEY REFERENCES normalized_items(id) ON DELETE CASCADE,
  freshness_score REAL NOT NULL DEFAULT 0,
  authority_score REAL NOT NULL DEFAULT 0,
  signal_score REAL NOT NULL DEFAULT 0,
  diversity_penalty REAL NOT NULL DEFAULT 0,
  final_score REAL NOT NULL DEFAULT 0,
  scoring_reason TEXT,
  scored_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS events (
  id SERIAL PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT,
  location TEXT,
  start_at TIMESTAMPTZ,
  end_at TIMESTAMPTZ,
  url TEXT UNIQUE,
  organizer TEXT,
  source_type TEXT,
  source_domain TEXT,
  region TEXT NOT NULL DEFAULT 'global' CHECK (region IN ('taiwan','global')),
  tags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  score REAL NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS subscriptions (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  plan TEXT NOT NULL DEFAULT 'free',
  status TEXT NOT NULL DEFAULT 'active',
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ends_at TIMESTAMPTZ,
  UNIQUE (user_id)
);

CREATE TABLE IF NOT EXISTS deliveries (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  date DATE NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  channel TEXT NOT NULL DEFAULT 'email',
  sent_at TIMESTAMPTZ,
  UNIQUE (user_id, date, channel)
);

CREATE TABLE IF NOT EXISTS delivery_items (
  delivery_id INTEGER NOT NULL REFERENCES deliveries(id) ON DELETE CASCADE,
  item_id INTEGER REFERENCES normalized_items(id) ON DELETE CASCADE,
  event_id INTEGER REFERENCES events(id) ON DELETE CASCADE,
  rank INTEGER,
  reason TEXT,
  PRIMARY KEY (delivery_id, rank)
);

CREATE TABLE IF NOT EXISTS auth_audit_logs (
  id SERIAL PRIMARY KEY,
  ip TEXT,
  action TEXT NOT NULL,
  email TEXT,
  success BOOLEAN NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oauth_states (
  state TEXT PRIMARY KEY,
  ip TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at TIMESTAMPTZ NOT NULL,
  used_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS unsubscribe_tokens (
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at TIMESTAMPTZ NOT NULL,
  used_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS source_health (
  source_key TEXT PRIMARY KEY,
  success_count INTEGER NOT NULL DEFAULT 0,
  failure_count INTEGER NOT NULL DEFAULT 0,
  consecutive_failures INTEGER NOT NULL DEFAULT 0,
  last_success_at TIMESTAMPTZ,
  last_failure_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS source_cache (
  url TEXT PRIMARY KEY,
  status_code INTEGER NOT NULL,
  body TEXT,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  source TEXT
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
  id SERIAL PRIMARY KEY,
  status TEXT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ,
  duration_ms INTEGER,
  result_json JSONB NOT NULL DEFAULT '{}'::JSONB,
  error_message TEXT,
  trigger_source TEXT NOT NULL DEFAULT 'manual'
);

CREATE TABLE IF NOT EXISTS email_delivery_logs (
  id SERIAL PRIMARY KEY,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  email TEXT,
  provider TEXT,
  subject TEXT,
  status TEXT NOT NULL,
  provider_message_id TEXT,
  provider_event TEXT,
  response_code INTEGER,
  detail TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS vc_profiles (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
  firm_name TEXT NOT NULL,
  thesis TEXT NOT NULL DEFAULT '',
  preferred_stages TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  preferred_sectors TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  preferred_geo TEXT NOT NULL DEFAULT 'global',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS gov_resource_records (
  id SERIAL PRIMARY KEY,
  record_type TEXT NOT NULL CHECK (record_type IN ('award','subsidy','incubator','exhibitor','exhibit_schedule')),
  source_category TEXT NOT NULL CHECK (source_category IN ('gov_award','gov_subsidy','incubator_space','exhibitor_list','exhibit_schedule')),
  program_name TEXT,
  event_name TEXT,
  company_name TEXT,
  organization_name TEXT,
  year INTEGER,
  award_name TEXT,
  subsidy_name TEXT,
  date_text TEXT,
  booth_no TEXT,
  url TEXT,
  source_url TEXT NOT NULL,
  source_domain TEXT,
  region TEXT NOT NULL DEFAULT 'taiwan',
  score REAL NOT NULL DEFAULT 0,
  raw_meta JSONB NOT NULL DEFAULT '{}'::JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE NULLS NOT DISTINCT (record_type, source_category, program_name, event_name, company_name, organization_name, year, url, source_url)
);

CREATE INDEX IF NOT EXISTS idx_gov_resource_records_type_year ON gov_resource_records(record_type, year DESC);
CREATE INDEX IF NOT EXISTS idx_gov_resource_records_category ON gov_resource_records(source_category, score DESC);

CREATE TABLE IF NOT EXISTS vc_candidates (
  id SERIAL PRIMARY KEY,
  profile_id INTEGER NOT NULL REFERENCES vc_profiles(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  summary TEXT,
  source_url TEXT NOT NULL,
  source_type TEXT,
  stage TEXT,
  sector TEXT,
  score REAL NOT NULL DEFAULT 0,
  rationale TEXT,
  contact_email TEXT,
  raw_meta JSONB NOT NULL DEFAULT '{}'::JSONB,
  shortlisted BOOLEAN NOT NULL DEFAULT FALSE,
  outreach_status TEXT NOT NULL DEFAULT 'pending',
  meeting_status TEXT NOT NULL DEFAULT 'pending',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (profile_id, source_url, name)
);

CREATE TABLE IF NOT EXISTS vc_outreach_logs (
  id SERIAL PRIMARY KEY,
  candidate_id INTEGER NOT NULL REFERENCES vc_candidates(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  subject TEXT NOT NULL,
  body TEXT NOT NULL,
  sent BOOLEAN NOT NULL DEFAULT FALSE,
  sent_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS vc_meeting_requests (
  id SERIAL PRIMARY KEY,
  candidate_id INTEGER NOT NULL REFERENCES vc_candidates(id) ON DELETE CASCADE,
  proposed_slots TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  selected_slot TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS vc_dd_reports (
  id SERIAL PRIMARY KEY,
  profile_id INTEGER NOT NULL REFERENCES vc_profiles(id) ON DELETE CASCADE,
  candidate_id INTEGER NOT NULL REFERENCES vc_candidates(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  report_json JSONB NOT NULL DEFAULT '{}'::JSONB,
  markdown TEXT,
  confidence REAL NOT NULL DEFAULT 0,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (profile_id, candidate_id)
);

CREATE TABLE IF NOT EXISTS grad_dd_profiles (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
  resume_text TEXT NOT NULL,
  target_schools TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  interests TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  degree_target TEXT NOT NULL DEFAULT 'master',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS grad_lab_candidates (
  id SERIAL PRIMARY KEY,
  profile_id INTEGER NOT NULL REFERENCES grad_dd_profiles(id) ON DELETE CASCADE,
  school TEXT NOT NULL,
  lab_name TEXT NOT NULL,
  lab_url TEXT,
  professor TEXT,
  score REAL NOT NULL DEFAULT 0,
  rationale TEXT,
  evidence JSONB NOT NULL DEFAULT '{}'::JSONB,
  shortlisted BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (profile_id, school, lab_name, lab_url)
);

CREATE TABLE IF NOT EXISTS grad_dd_reports (
  id SERIAL PRIMARY KEY,
  profile_id INTEGER NOT NULL REFERENCES grad_dd_profiles(id) ON DELETE CASCADE,
  report_json JSONB NOT NULL DEFAULT '{}'::JSONB,
  markdown TEXT,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Compatibility migrations for existing databases
ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS password_hash TEXT;
ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS display_name TEXT;
ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS is_email_verified BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS is_email_valid BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;
ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE IF EXISTS users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE IF EXISTS users ADD CONSTRAINT users_role_check CHECK (role IN ('admin','vc','biz','tech'));

ALTER TABLE IF EXISTS raw_items ADD COLUMN IF NOT EXISTS item_kind TEXT NOT NULL DEFAULT 'web';

ALTER TABLE IF EXISTS normalized_items ADD COLUMN IF NOT EXISTS content_type TEXT NOT NULL DEFAULT 'web';
ALTER TABLE IF EXISTS normalized_items ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

ALTER TABLE IF EXISTS scores ADD COLUMN IF NOT EXISTS freshness_score REAL NOT NULL DEFAULT 0;
ALTER TABLE IF EXISTS scores ADD COLUMN IF NOT EXISTS authority_score REAL NOT NULL DEFAULT 0;
ALTER TABLE IF EXISTS scores ADD COLUMN IF NOT EXISTS signal_score REAL NOT NULL DEFAULT 0;
ALTER TABLE IF EXISTS scores ADD COLUMN IF NOT EXISTS diversity_penalty REAL NOT NULL DEFAULT 0;
ALTER TABLE IF EXISTS scores ADD COLUMN IF NOT EXISTS final_score REAL NOT NULL DEFAULT 0;
ALTER TABLE IF EXISTS scores ADD COLUMN IF NOT EXISTS scoring_reason TEXT;
ALTER TABLE IF EXISTS scores ADD COLUMN IF NOT EXISTS scored_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

ALTER TABLE IF EXISTS events ADD COLUMN IF NOT EXISTS source_domain TEXT;
ALTER TABLE IF EXISTS events ADD COLUMN IF NOT EXISTS region TEXT NOT NULL DEFAULT 'global';
ALTER TABLE IF EXISTS events ADD COLUMN IF NOT EXISTS score REAL NOT NULL DEFAULT 0;
ALTER TABLE IF EXISTS events ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

ALTER TABLE IF EXISTS user_preferences ADD COLUMN IF NOT EXISTS subscribe_daily BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE IF EXISTS user_preferences ADD COLUMN IF NOT EXISTS language TEXT NOT NULL DEFAULT 'zh-TW';

INSERT INTO roles (code, name) VALUES
  ('admin', '管理員'),
  ('vc', '創投使用者'),
  ('biz', '商業使用者'),
  ('tech', '技術使用者')
ON CONFLICT (code) DO NOTHING;

INSERT INTO permissions (code, name) VALUES
  ('read_feed', '讀取摘要與活動'),
  ('manage_subscription', '管理訂閱'),
  ('vc_scout_run', '執行 VC Scout'),
  ('vc_dd_run', '執行 VC DD'),
  ('grad_dd_run', '執行學術 DD'),
  ('pipeline_run', '執行資料管線'),
  ('admin_read', '後台唯讀'),
  ('admin_write', '後台寫入')
ON CONFLICT (code) DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
JOIN permissions p ON p.code IN ('read_feed', 'manage_subscription', 'vc_scout_run', 'vc_dd_run')
WHERE r.code = 'vc'
ON CONFLICT DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
JOIN permissions p ON p.code IN ('read_feed', 'manage_subscription', 'vc_scout_run', 'vc_dd_run', 'grad_dd_run')
WHERE r.code = 'biz'
ON CONFLICT DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
JOIN permissions p ON p.code IN ('read_feed', 'manage_subscription', 'vc_scout_run', 'vc_dd_run', 'grad_dd_run')
WHERE r.code = 'tech'
ON CONFLICT DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
JOIN permissions p ON p.code IN (
  'read_feed',
  'manage_subscription',
  'vc_scout_run',
  'vc_dd_run',
  'grad_dd_run',
  'pipeline_run',
  'admin_read',
  'admin_write'
)
WHERE r.code = 'admin'
ON CONFLICT DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_raw_items_published_at ON raw_items(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_raw_items_kind ON raw_items(item_kind);
CREATE INDEX IF NOT EXISTS idx_normalized_items_category ON normalized_items(category);
CREATE INDEX IF NOT EXISTS idx_normalized_items_content_type ON normalized_items(content_type);
CREATE INDEX IF NOT EXISTS idx_scores_final ON scores(final_score DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_scores_item_id_unique ON scores(item_id);
CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_at);
CREATE INDEX IF NOT EXISTS idx_events_region ON events(region);
CREATE INDEX IF NOT EXISTS idx_auth_audit_created_at ON auth_audit_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_vc_candidates_profile_score ON vc_candidates(profile_id, score DESC);
CREATE INDEX IF NOT EXISTS idx_vc_dd_reports_profile_generated ON vc_dd_reports(profile_id, generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_grad_lab_candidates_profile_score ON grad_lab_candidates(profile_id, score DESC);
CREATE INDEX IF NOT EXISTS idx_grad_dd_reports_profile_generated ON grad_dd_reports(profile_id, generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_roles_user ON user_roles(user_id);
CREATE INDEX IF NOT EXISTS idx_role_permissions_role ON role_permissions(role_id);
CREATE INDEX IF NOT EXISTS idx_email_delivery_logs_email ON email_delivery_logs(email, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_started_at ON pipeline_runs(started_at DESC);
