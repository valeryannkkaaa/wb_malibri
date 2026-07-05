-- WB Advert module — Phase 0 schema (TZ §4)
-- Apply when PostgreSQL portal is available: psql $DATABASE_URL -f 001_advert_schema.sql

CREATE TYPE advert_status AS ENUM ('new', 'active', 'paused', 'blocked', 'liquidation');
CREATE TYPE advert_category_type AS ENUM ('goods', 'clothing', 'liquidation');
CREATE TYPE advert_schedule_mode AS ENUM ('always_on', 'night_off', 'custom');
CREATE TYPE advert_volume_priority AS ENUM ('margin_first', 'balanced', 'volume_first');
CREATE TYPE advert_campaign_type AS ENUM (
  'search_manual', 'recommendations_manual', 'unified_bid', 'cpc_fallback'
);
CREATE TYPE advert_bid_type AS ENUM ('manual', 'unified');
CREATE TYPE advert_payment_type AS ENUM ('cpm', 'cpc');
CREATE TYPE advert_placement AS ENUM ('search', 'recommendations', 'combined');
CREATE TYPE advert_keyword_class AS ENUM ('primary', 'secondary', 'longtail', 'irrelevant');
CREATE TYPE advert_keyword_status AS ENUM ('all', 'managed', 'excluded', 'pending_100_shows');
CREATE TYPE advert_target_grade AS ENUM ('top_1_3', 'pos_4_10', 'pos_10_20');
CREATE TYPE advert_snapshot_type AS ENUM ('keyword', 'shelf', 'campaign', 'global');
CREATE TYPE advert_decision_actor AS ENUM ('optimizer', 'manager', 'system');
CREATE TYPE advert_decision_action AS ENUM (
  'keep', 'raise_bid', 'lower_bid', 'exclude_keyword', 'retest_keyword',
  'pause_campaign', 'resume_campaign', 'topup_budget', 'skip', 'alert'
);
CREATE TYPE unit_economics_source AS ENUM ('manual', 'import', 'calculated');

CREATE TABLE IF NOT EXISTS wb_credentials (
  id SERIAL PRIMARY KEY,
  token_encrypted TEXT NOT NULL,
  token_scope JSONB,
  is_active BOOLEAN NOT NULL DEFAULT true,
  last_check_at TIMESTAMPTZ,
  last_error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS advert_profiles (
  id SERIAL PRIMARY KEY,
  product_id INT NOT NULL UNIQUE,
  nm_id VARCHAR(20) NOT NULL,
  advert_enabled BOOLEAN NOT NULL DEFAULT false,
  advert_status advert_status NOT NULL DEFAULT 'new',
  category_type advert_category_type NOT NULL DEFAULT 'goods',
  schedule_mode advert_schedule_mode NOT NULL DEFAULT 'always_on',
  schedule_wake_hour SMALLINT,
  schedule_sleep_hour SMALLINT DEFAULT 23,
  max_bid_kopecks INT NOT NULL DEFAULT 150000,
  max_topup_kopecks INT NOT NULL DEFAULT 300000,
  min_test_hours SMALLINT NOT NULL DEFAULT 2,
  volume_priority advert_volume_priority NOT NULL DEFAULT 'balanced',
  last_optimize_at TIMESTAMPTZ,
  last_sync_at TIMESTAMPTZ,
  parser_enabled BOOLEAN NOT NULL DEFAULT true,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_advert_profiles_nm_id ON advert_profiles (nm_id);
CREATE INDEX IF NOT EXISTS idx_advert_profiles_status ON advert_profiles (advert_status);

CREATE TABLE IF NOT EXISTS advert_campaign_links (
  id SERIAL PRIMARY KEY,
  advert_profile_id INT NOT NULL REFERENCES advert_profiles(id) ON DELETE CASCADE,
  wb_campaign_id BIGINT NOT NULL,
  campaign_type advert_campaign_type NOT NULL DEFAULT 'search_manual',
  bid_type advert_bid_type NOT NULL DEFAULT 'manual',
  payment_type advert_payment_type NOT NULL DEFAULT 'cpm',
  placement advert_placement NOT NULL DEFAULT 'search',
  is_active BOOLEAN NOT NULL DEFAULT true,
  current_bid_kopecks INT,
  min_bid_kopecks INT,
  wb_status VARCHAR(32),
  synced_at TIMESTAMPTZ,
  UNIQUE (advert_profile_id, wb_campaign_id)
);

CREATE TABLE IF NOT EXISTS advert_keywords (
  id SERIAL PRIMARY KEY,
  advert_profile_id INT NOT NULL REFERENCES advert_profiles(id) ON DELETE CASCADE,
  campaign_link_id INT REFERENCES advert_campaign_links(id) ON DELETE SET NULL,
  keyword VARCHAR(512) NOT NULL,
  normquery_id VARCHAR(128),
  keyword_class advert_keyword_class NOT NULL DEFAULT 'primary',
  status advert_keyword_status NOT NULL DEFAULT 'pending_100_shows',
  shows_total INT NOT NULL DEFAULT 0,
  shows_period INT NOT NULL DEFAULT 0,
  clicks_period INT NOT NULL DEFAULT 0,
  spend_kopecks_period INT NOT NULL DEFAULT 0,
  orders_period INT NOT NULL DEFAULT 0,
  target_grade advert_target_grade NOT NULL DEFAULT 'top_1_3',
  current_bid_kopecks INT,
  is_custom_bid BOOLEAN NOT NULL DEFAULT false,
  ctr_calculated DECIMAL(8,4),
  cpc_calculated_kopecks INT,
  frequency_monthly INT,
  last_parsed_position SMALLINT,
  last_parsed_at TIMESTAMPTZ,
  excluded_at TIMESTAMPTZ,
  excluded_reason VARCHAR(64),
  retest_after DATE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (advert_profile_id, keyword)
);

CREATE TABLE IF NOT EXISTS advert_snapshots (
  id BIGSERIAL PRIMARY KEY,
  advert_profile_id INT NOT NULL REFERENCES advert_profiles(id) ON DELETE CASCADE,
  keyword_id INT REFERENCES advert_keywords(id) ON DELETE SET NULL,
  snapshot_type advert_snapshot_type NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL,
  parsed_position SMALLINT,
  api_position SMALLINT,
  shows INT,
  clicks INT,
  spend_kopecks INT,
  orders_delta INT,
  ctr DECIMAL(8,4),
  cpc_kopecks INT,
  bid_kopecks INT,
  price_rub DECIMAL(10,2),
  delivery_days SMALLINT,
  stock_total INT,
  meta JSONB
);
CREATE INDEX IF NOT EXISTS idx_advert_snapshots_profile_time ON advert_snapshots (advert_profile_id, recorded_at DESC);

CREATE TABLE IF NOT EXISTS advert_decisions (
  id BIGSERIAL PRIMARY KEY,
  advert_profile_id INT NOT NULL REFERENCES advert_profiles(id) ON DELETE CASCADE,
  keyword_id INT REFERENCES advert_keywords(id) ON DELETE SET NULL,
  campaign_link_id INT REFERENCES advert_campaign_links(id) ON DELETE SET NULL,
  decided_at TIMESTAMPTZ NOT NULL,
  actor advert_decision_actor NOT NULL,
  action advert_decision_action NOT NULL,
  reason_code VARCHAR(64) NOT NULL,
  reason_text TEXT,
  before_state JSONB NOT NULL DEFAULT '{}',
  after_state JSONB NOT NULL DEFAULT '{}',
  applied BOOLEAN NOT NULL DEFAULT false,
  wb_response JSONB,
  error TEXT
);

CREATE TABLE IF NOT EXISTS unit_economics (
  id SERIAL PRIMARY KEY,
  product_id INT NOT NULL UNIQUE,
  nm_id VARCHAR(20) NOT NULL,
  cost_price_rub DECIMAL(10,2) NOT NULL,
  retail_price_rub DECIMAL(10,2) NOT NULL,
  margin_pct DECIMAL(6,2) NOT NULL,
  max_drr_pct DECIMAL(6,2) NOT NULL DEFAULT 15,
  max_cpc_kopecks INT,
  max_cpm_kopecks INT,
  target_margin_pct DECIMAL(6,2),
  wb_commission_pct DECIMAL(6,2),
  logistics_rub DECIMAL(10,2),
  source unit_economics_source NOT NULL DEFAULT 'import',
  valid_from DATE NOT NULL DEFAULT CURRENT_DATE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS advert_project_settings (
  id SERIAL PRIMARY KEY,
  project_id INT NOT NULL UNIQUE,
  optimizer_mode VARCHAR(32) NOT NULL DEFAULT 'suggest-only',
  parser_region VARCHAR(64),
  telegram_chat_id VARCHAR(64),
  settings JSONB NOT NULL DEFAULT '{}',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
