BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 0001

CREATE TABLE platform_users (
    telegram_user_id BIGINT NOT NULL,
    first_name VARCHAR(128) NOT NULL,
    username VARCHAR(64),
    locale VARCHAR(8) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (telegram_user_id)
);

CREATE INDEX ix_platform_users_created_at ON platform_users (created_at);

CREATE TABLE saas_plans (
    name VARCHAR(40) NOT NULL,
    limits JSON NOT NULL,
    features JSON NOT NULL,
    prices JSON NOT NULL,
    active BOOLEAN NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (name)
);

CREATE INDEX ix_saas_plans_created_at ON saas_plans (created_at);

CREATE TABLE auth_sessions (
    token_hash VARCHAR(64) NOT NULL,
    telegram_user_id BIGINT NOT NULL,
    user_id VARCHAR(36),
    bot_id VARCHAR(36),
    kind VARCHAR(10) NOT NULL,
    expires_at BIGINT NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(user_id) REFERENCES platform_users (id),
    UNIQUE (token_hash)
);

CREATE INDEX ix_auth_sessions_created_at ON auth_sessions (created_at);

CREATE INDEX ix_auth_sessions_expires_at ON auth_sessions (expires_at);

CREATE TABLE platform_support_tickets (
    user_id VARCHAR(36) NOT NULL,
    subject VARCHAR(120) NOT NULL,
    text VARCHAR(3000) NOT NULL,
    status VARCHAR(20) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(user_id) REFERENCES platform_users (id)
);

CREATE INDEX ix_platform_support_tickets_created_at ON platform_support_tickets (created_at);

CREATE TABLE tenants (
    name VARCHAR(100) NOT NULL,
    owner_user_id VARCHAR(36) NOT NULL,
    status VARCHAR(30) NOT NULL,
    suspended_at BIGINT,
    deleted_at BIGINT,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(owner_user_id) REFERENCES platform_users (id)
);

CREATE INDEX ix_tenants_created_at ON tenants (created_at);

CREATE TABLE audit_logs (
    tenant_id VARCHAR(36),
    actor_id VARCHAR(64) NOT NULL,
    action VARCHAR(80) NOT NULL,
    entity_id VARCHAR(64),
    data JSON NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_audit_logs_created_at ON audit_logs (created_at);

CREATE INDEX ix_audit_logs_tenant_id ON audit_logs (tenant_id);

CREATE TABLE bot_creation_requests (
    telegram_user_id BIGINT NOT NULL,
    request_id INTEGER NOT NULL,
    expires_at BIGINT NOT NULL,
    consumed_bot_id VARCHAR(36),
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (request_id),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_bot_creation_requests_created_at ON bot_creation_requests (created_at);

CREATE INDEX ix_bot_creation_requests_telegram_user_id ON bot_creation_requests (telegram_user_id);

CREATE INDEX ix_bot_creation_requests_tenant_id ON bot_creation_requests (tenant_id);

CREATE TABLE coupons (
    code VARCHAR(32) NOT NULL,
    percent_off INTEGER NOT NULL,
    max_redemptions INTEGER NOT NULL,
    expires_at BIGINT NOT NULL,
    active BOOLEAN NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (tenant_id, code),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_coupons_created_at ON coupons (created_at);

CREATE INDEX ix_coupons_tenant_id ON coupons (tenant_id);

CREATE TABLE events (
    bot_id VARCHAR(36),
    contact_id VARCHAR(36),
    type VARCHAR(50) NOT NULL,
    data JSON NOT NULL,
    dedup_key VARCHAR(180) NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (tenant_id, dedup_key),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_events_bot_id ON events (bot_id);

CREATE INDEX ix_events_created_at ON events (created_at);

CREATE INDEX ix_events_tenant_id ON events (tenant_id);

CREATE INDEX ix_events_type ON events (type);

CREATE TABLE feature_flags (
    key VARCHAR(60) NOT NULL,
    enabled BOOLEAN NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (tenant_id, id),
    UNIQUE (tenant_id, key)
);

CREATE INDEX ix_feature_flags_created_at ON feature_flags (created_at);

CREATE INDEX ix_feature_flags_tenant_id ON feature_flags (tenant_id);

CREATE TABLE jobs (
    tenant_id VARCHAR(36),
    bot_id VARCHAR(36),
    kind VARCHAR(40) NOT NULL,
    payload JSON NOT NULL,
    dedup_key VARCHAR(200) NOT NULL,
    status VARCHAR(20) NOT NULL,
    run_at BIGINT NOT NULL,
    lease_until BIGINT,
    lease_owner VARCHAR(36),
    attempts INTEGER NOT NULL,
    last_error_code VARCHAR(80),
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (dedup_key)
);

CREATE INDEX ix_job_due ON jobs (status, run_at, tenant_id);

CREATE INDEX ix_jobs_created_at ON jobs (created_at);

CREATE INDEX ix_jobs_tenant_id ON jobs (tenant_id);

CREATE TABLE managed_bots (
    telegram_bot_id BIGINT NOT NULL,
    owner_telegram_user_id BIGINT NOT NULL,
    public_id VARCHAR(36) NOT NULL,
    username VARCHAR(64) NOT NULL,
    name VARCHAR(64) NOT NULL,
    status VARCHAR(30) NOT NULL,
    published BOOLEAN NOT NULL,
    config_version INTEGER NOT NULL,
    last_update_at BIGINT,
    health JSON NOT NULL,
    last_error_code VARCHAR(60),
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (public_id),
    UNIQUE (telegram_bot_id),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_managed_bots_created_at ON managed_bots (created_at);

CREATE INDEX ix_managed_bots_tenant_id ON managed_bots (tenant_id);

CREATE TABLE onboarding (
    user_id VARCHAR(36) NOT NULL,
    step INTEGER NOT NULL,
    data JSON NOT NULL,
    completed BOOLEAN NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    FOREIGN KEY(user_id) REFERENCES platform_users (id),
    UNIQUE (tenant_id, id),
    UNIQUE (tenant_id, user_id)
);

CREATE INDEX ix_onboarding_created_at ON onboarding (created_at);

CREATE INDEX ix_onboarding_tenant_id ON onboarding (tenant_id);

CREATE TABLE payment_provider_configs (
    provider VARCHAR(40) NOT NULL,
    enabled BOOLEAN NOT NULL,
    approved_for_activity BOOLEAN NOT NULL,
    public_config JSON NOT NULL,
    secrets_ciphertext JSON,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (tenant_id, id),
    UNIQUE (tenant_id, provider)
);

CREATE INDEX ix_payment_provider_configs_created_at ON payment_provider_configs (created_at);

CREATE INDEX ix_payment_provider_configs_tenant_id ON payment_provider_configs (tenant_id);

CREATE TABLE provider_events (
    tenant_id VARCHAR(36) NOT NULL,
    provider VARCHAR(40) NOT NULL,
    account_key VARCHAR(80) NOT NULL,
    external_id VARCHAR(255) NOT NULL,
    payload_hash VARCHAR(64) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (provider, account_key, external_id)
);

CREATE INDEX ix_provider_events_created_at ON provider_events (created_at);

CREATE INDEX ix_provider_events_tenant_id ON provider_events (tenant_id);

CREATE TABLE saas_invoices (
    invoice_payload VARCHAR(128) NOT NULL,
    plan_id VARCHAR(36) NOT NULL,
    telegram_user_id BIGINT NOT NULL,
    amount_xtr BIGINT NOT NULL,
    status VARCHAR(20) NOT NULL,
    checkout_url VARCHAR(1024),
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(plan_id) REFERENCES saas_plans (id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (invoice_payload),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_saas_invoices_created_at ON saas_invoices (created_at);

CREATE INDEX ix_saas_invoices_tenant_id ON saas_invoices (tenant_id);

CREATE TABLE saas_subscriptions (
    plan_id VARCHAR(36) NOT NULL,
    kind VARCHAR(30) NOT NULL,
    status VARCHAR(20) NOT NULL,
    trial_ends_at BIGINT NOT NULL,
    current_period_end BIGINT NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(plan_id) REFERENCES saas_plans (id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (tenant_id),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_saas_subscriptions_created_at ON saas_subscriptions (created_at);

CREATE INDEX ix_saas_subscriptions_tenant_id ON saas_subscriptions (tenant_id);

CREATE TABLE tags (
    name VARCHAR(40) NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (tenant_id, id),
    UNIQUE (tenant_id, name)
);

CREATE INDEX ix_tags_created_at ON tags (created_at);

CREATE INDEX ix_tags_tenant_id ON tags (tenant_id);

CREATE TABLE telegram_updates (
    bot_key VARCHAR(36) NOT NULL,
    tenant_id VARCHAR(36),
    update_id BIGINT NOT NULL,
    payload JSON NOT NULL,
    status VARCHAR(20) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (bot_key, update_id)
);

CREATE INDEX ix_telegram_updates_created_at ON telegram_updates (created_at);

CREATE INDEX ix_telegram_updates_tenant_id ON telegram_updates (tenant_id);

CREATE TABLE tenant_members (
    user_id VARCHAR(36) NOT NULL,
    role VARCHAR(20) NOT NULL,
    active BOOLEAN NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    FOREIGN KEY(user_id) REFERENCES platform_users (id),
    UNIQUE (tenant_id, id),
    UNIQUE (tenant_id, user_id)
);

CREATE INDEX ix_tenant_members_created_at ON tenant_members (created_at);

CREATE INDEX ix_tenant_members_tenant_id ON tenant_members (tenant_id);

CREATE INDEX ix_tenant_members_user_id ON tenant_members (user_id);

CREATE TABLE usage_counters (
    key VARCHAR(60) NOT NULL,
    period VARCHAR(20) NOT NULL,
    value BIGINT NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (tenant_id, id),
    UNIQUE (tenant_id, key, period)
);

CREATE INDEX ix_usage_counters_created_at ON usage_counters (created_at);

CREATE INDEX ix_usage_counters_tenant_id ON usage_counters (tenant_id);

CREATE TABLE automation_rules (
    bot_id VARCHAR(36) NOT NULL,
    name VARCHAR(100) NOT NULL,
    trigger VARCHAR(40) NOT NULL,
    action VARCHAR(40) NOT NULL,
    config JSON NOT NULL,
    delay_seconds INTEGER NOT NULL,
    active BOOLEAN NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, bot_id) REFERENCES managed_bots (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_automation_rules_created_at ON automation_rules (created_at);

CREATE INDEX ix_automation_rules_tenant_id ON automation_rules (tenant_id);

CREATE TABLE bot_secrets (
    bot_id VARCHAR(36) NOT NULL,
    token_ciphertext JSON NOT NULL,
    webhook_ciphertext JSON NOT NULL,
    webhook_secret_hash VARCHAR(64) NOT NULL,
    token_version INTEGER NOT NULL,
    token_last_rotated_at BIGINT NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, bot_id) REFERENCES managed_bots (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (bot_id),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_bot_secrets_created_at ON bot_secrets (created_at);

CREATE INDEX ix_bot_secrets_tenant_id ON bot_secrets (tenant_id);

CREATE TABLE bot_settings (
    bot_id VARCHAR(36) NOT NULL,
    description VARCHAR(512) NOT NULL,
    short_description VARCHAR(120) NOT NULL,
    menu_text VARCHAR(32) NOT NULL,
    commands JSON NOT NULL,
    branding JSON NOT NULL,
    policies JSON NOT NULL,
    template VARCHAR(40) NOT NULL,
    support_username VARCHAR(64) NOT NULL,
    remove_expired_members BOOLEAN NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, bot_id) REFERENCES managed_bots (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (bot_id),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_bot_settings_created_at ON bot_settings (created_at);

CREATE INDEX ix_bot_settings_tenant_id ON bot_settings (tenant_id);

CREATE TABLE bot_texts (
    bot_id VARCHAR(36) NOT NULL,
    key VARCHAR(40) NOT NULL,
    locale VARCHAR(8) NOT NULL,
    value VARCHAR(4096) NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, bot_id) REFERENCES managed_bots (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (bot_id, key, locale),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_bot_texts_created_at ON bot_texts (created_at);

CREATE INDEX ix_bot_texts_tenant_id ON bot_texts (tenant_id);

CREATE TABLE campaigns (
    bot_id VARCHAR(36) NOT NULL,
    name VARCHAR(100) NOT NULL,
    text VARCHAR(4096) NOT NULL,
    segment JSON NOT NULL,
    status VARCHAR(20) NOT NULL,
    scheduled_at BIGINT,
    cursor VARCHAR(36),
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, bot_id) REFERENCES managed_bots (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_campaigns_created_at ON campaigns (created_at);

CREATE INDEX ix_campaigns_tenant_id ON campaigns (tenant_id);

CREATE TABLE channels (
    bot_id VARCHAR(36) NOT NULL,
    telegram_chat_id BIGINT NOT NULL,
    title VARCHAR(255) NOT NULL,
    username VARCHAR(64),
    type VARCHAR(20) NOT NULL,
    status VARCHAR(30) NOT NULL,
    permissions JSON NOT NULL,
    connected_at BIGINT,
    access_mode VARCHAR(30) NOT NULL,
    native_invite_link VARCHAR(512),
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, bot_id) REFERENCES managed_bots (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (bot_id, telegram_chat_id),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_channels_created_at ON channels (created_at);

CREATE INDEX ix_channels_tenant_id ON channels (tenant_id);

CREATE TABLE contacts (
    bot_id VARCHAR(36) NOT NULL,
    telegram_user_id BIGINT NOT NULL,
    username VARCHAR(64),
    first_name VARCHAR(128) NOT NULL,
    stage VARCHAR(30) NOT NULL,
    source VARCHAR(64),
    campaign VARCHAR(64),
    referrer VARCHAR(36),
    last_seen_at BIGINT NOT NULL,
    opted_out BOOLEAN NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, bot_id) REFERENCES managed_bots (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (bot_id, telegram_user_id),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_contacts_bot_id ON contacts (bot_id);

CREATE INDEX ix_contacts_created_at ON contacts (created_at);

CREATE INDEX ix_contacts_stage ON contacts (stage);

CREATE INDEX ix_contacts_tenant_id ON contacts (tenant_id);

CREATE TABLE saas_charges (
    charge_id VARCHAR(255) NOT NULL,
    invoice_id VARCHAR(36) NOT NULL,
    amount_xtr BIGINT NOT NULL,
    period_end BIGINT NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(invoice_id) REFERENCES saas_invoices (id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (charge_id),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_saas_charges_created_at ON saas_charges (created_at);

CREATE INDEX ix_saas_charges_tenant_id ON saas_charges (tenant_id);

CREATE TABLE attribution_links (
    bot_id VARCHAR(36) NOT NULL,
    code VARCHAR(32) NOT NULL,
    source VARCHAR(64) NOT NULL,
    campaign VARCHAR(64),
    referrer_id VARCHAR(36),
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, bot_id) REFERENCES managed_bots (tenant_id, id),
    FOREIGN KEY(tenant_id, referrer_id) REFERENCES contacts (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (code),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_attribution_links_created_at ON attribution_links (created_at);

CREATE INDEX ix_attribution_links_tenant_id ON attribution_links (tenant_id);

CREATE TABLE automation_executions (
    rule_id VARCHAR(36) NOT NULL,
    event_id VARCHAR(36) NOT NULL,
    status VARCHAR(20) NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, event_id) REFERENCES events (tenant_id, id),
    FOREIGN KEY(tenant_id, rule_id) REFERENCES automation_rules (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (rule_id, event_id),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_automation_executions_created_at ON automation_executions (created_at);

CREATE INDEX ix_automation_executions_tenant_id ON automation_executions (tenant_id);

CREATE TABLE campaign_recipients (
    campaign_id VARCHAR(36) NOT NULL,
    contact_id VARCHAR(36) NOT NULL,
    status VARCHAR(20) NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, campaign_id) REFERENCES campaigns (tenant_id, id),
    FOREIGN KEY(tenant_id, contact_id) REFERENCES contacts (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (campaign_id, contact_id),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_campaign_recipients_campaign_id ON campaign_recipients (campaign_id);

CREATE INDEX ix_campaign_recipients_created_at ON campaign_recipients (created_at);

CREATE INDEX ix_campaign_recipients_tenant_id ON campaign_recipients (tenant_id);

CREATE TABLE contact_tags (
    contact_id VARCHAR(36) NOT NULL,
    tag_id VARCHAR(36) NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, contact_id) REFERENCES contacts (tenant_id, id),
    FOREIGN KEY(tenant_id, tag_id) REFERENCES tags (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (contact_id, tag_id),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_contact_tags_created_at ON contact_tags (created_at);

CREATE INDEX ix_contact_tags_tenant_id ON contact_tags (tenant_id);

CREATE TABLE conversations (
    bot_id VARCHAR(36) NOT NULL,
    contact_id VARCHAR(36) NOT NULL,
    status VARCHAR(20) NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, bot_id) REFERENCES managed_bots (tenant_id, id),
    FOREIGN KEY(tenant_id, contact_id) REFERENCES contacts (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (contact_id),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_conversations_created_at ON conversations (created_at);

CREATE INDEX ix_conversations_tenant_id ON conversations (tenant_id);

CREATE TABLE crm_tasks (
    contact_id VARCHAR(36) NOT NULL,
    title VARCHAR(200) NOT NULL,
    status VARCHAR(20) NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, contact_id) REFERENCES contacts (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_crm_tasks_created_at ON crm_tasks (created_at);

CREATE INDEX ix_crm_tasks_tenant_id ON crm_tasks (tenant_id);

CREATE TABLE internal_notes (
    contact_id VARCHAR(36) NOT NULL,
    author_id VARCHAR(36) NOT NULL,
    text VARCHAR(2000) NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, contact_id) REFERENCES contacts (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_internal_notes_created_at ON internal_notes (created_at);

CREATE INDEX ix_internal_notes_tenant_id ON internal_notes (tenant_id);

CREATE TABLE plans (
    bot_id VARCHAR(36) NOT NULL,
    channel_id VARCHAR(36),
    name VARCHAR(100) NOT NULL,
    description VARCHAR(1000) NOT NULL,
    benefits JSON NOT NULL,
    duration_days INTEGER NOT NULL,
    active BOOLEAN NOT NULL,
    recurring BOOLEAN NOT NULL,
    sort_order INTEGER NOT NULL,
    product_kind VARCHAR(20) NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    CHECK (duration_days > 0),
    FOREIGN KEY(tenant_id, bot_id) REFERENCES managed_bots (tenant_id, id),
    FOREIGN KEY(tenant_id, channel_id) REFERENCES channels (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_plans_bot_id ON plans (bot_id);

CREATE INDEX ix_plans_created_at ON plans (created_at);

CREATE INDEX ix_plans_tenant_id ON plans (tenant_id);

CREATE TABLE referrals (
    referrer_id VARCHAR(36) NOT NULL,
    referred_id VARCHAR(36) NOT NULL,
    status VARCHAR(20) NOT NULL,
    reward_units INTEGER NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, referred_id) REFERENCES contacts (tenant_id, id),
    FOREIGN KEY(tenant_id, referrer_id) REFERENCES contacts (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (referred_id),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_referrals_created_at ON referrals (created_at);

CREATE INDEX ix_referrals_tenant_id ON referrals (tenant_id);

CREATE TABLE messages (
    conversation_id VARCHAR(36) NOT NULL,
    admin_id VARCHAR(36),
    direction VARCHAR(10) NOT NULL,
    text VARCHAR(4096) NOT NULL,
    telegram_message_id BIGINT,
    status VARCHAR(20) NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, conversation_id) REFERENCES conversations (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_messages_conversation_id ON messages (conversation_id);

CREATE INDEX ix_messages_created_at ON messages (created_at);

CREATE INDEX ix_messages_tenant_id ON messages (tenant_id);

CREATE TABLE payments (
    bot_id VARCHAR(36) NOT NULL,
    contact_id VARCHAR(36) NOT NULL,
    plan_id VARCHAR(36) NOT NULL,
    provider VARCHAR(40) NOT NULL,
    currency VARCHAR(8) NOT NULL,
    amount_minor BIGINT NOT NULL,
    duration_days INTEGER NOT NULL,
    recurring BOOLEAN NOT NULL,
    status VARCHAR(30) NOT NULL,
    idempotency_key VARCHAR(160) NOT NULL,
    invoice_payload VARCHAR(128) NOT NULL,
    checkout_url VARCHAR(1024),
    confirmed_at BIGINT,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    CHECK (amount_minor > 0),
    FOREIGN KEY(tenant_id, bot_id) REFERENCES managed_bots (tenant_id, id),
    FOREIGN KEY(tenant_id, contact_id) REFERENCES contacts (tenant_id, id),
    FOREIGN KEY(tenant_id, plan_id) REFERENCES plans (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (invoice_payload),
    UNIQUE (tenant_id, id),
    UNIQUE (tenant_id, idempotency_key)
);

CREATE INDEX ix_payments_contact_id ON payments (contact_id);

CREATE INDEX ix_payments_created_at ON payments (created_at);

CREATE INDEX ix_payments_status ON payments (status);

CREATE INDEX ix_payments_tenant_id ON payments (tenant_id);

CREATE TABLE plan_prices (
    plan_id VARCHAR(36) NOT NULL,
    provider VARCHAR(40) NOT NULL,
    currency VARCHAR(8) NOT NULL,
    amount_minor BIGINT NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    CHECK (amount_minor > 0),
    FOREIGN KEY(tenant_id, plan_id) REFERENCES plans (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (plan_id, provider, currency),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_plan_prices_created_at ON plan_prices (created_at);

CREATE INDEX ix_plan_prices_tenant_id ON plan_prices (tenant_id);

CREATE TABLE bank_receipts (
    payment_id VARCHAR(36) NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    perceptual_hash VARCHAR(16),
    storage_key VARCHAR(120) NOT NULL,
    media_type VARCHAR(50) NOT NULL,
    status VARCHAR(30) NOT NULL,
    suspicious BOOLEAN NOT NULL,
    duplicate BOOLEAN NOT NULL,
    reviewed_by VARCHAR(36),
    review_note VARCHAR(500) NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, payment_id) REFERENCES payments (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_bank_receipts_created_at ON bank_receipts (created_at);

CREATE INDEX ix_bank_receipts_payment_id ON bank_receipts (payment_id);

CREATE INDEX ix_bank_receipts_sha256 ON bank_receipts (sha256);

CREATE INDEX ix_bank_receipts_tenant_id ON bank_receipts (tenant_id);

CREATE TABLE coupon_redemptions (
    coupon_id VARCHAR(36) NOT NULL,
    contact_id VARCHAR(36) NOT NULL,
    payment_id VARCHAR(36) NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, contact_id) REFERENCES contacts (tenant_id, id),
    FOREIGN KEY(tenant_id, coupon_id) REFERENCES coupons (tenant_id, id),
    FOREIGN KEY(tenant_id, payment_id) REFERENCES payments (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (coupon_id, contact_id),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_coupon_redemptions_created_at ON coupon_redemptions (created_at);

CREATE INDEX ix_coupon_redemptions_tenant_id ON coupon_redemptions (tenant_id);

CREATE TABLE payment_attempts (
    payment_id VARCHAR(36) NOT NULL,
    status VARCHAR(30) NOT NULL,
    code VARCHAR(80) NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, payment_id) REFERENCES payments (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_payment_attempts_created_at ON payment_attempts (created_at);

CREATE INDEX ix_payment_attempts_tenant_id ON payment_attempts (tenant_id);

CREATE TABLE payment_charges (
    payment_id VARCHAR(36) NOT NULL,
    bot_id VARCHAR(36) NOT NULL,
    provider VARCHAR(40) NOT NULL,
    charge_id VARCHAR(255) NOT NULL,
    amount_minor BIGINT NOT NULL,
    currency VARCHAR(8) NOT NULL,
    period_end BIGINT,
    refunded_at BIGINT,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, bot_id) REFERENCES managed_bots (tenant_id, id),
    FOREIGN KEY(tenant_id, payment_id) REFERENCES payments (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (bot_id, provider, charge_id),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_payment_charges_created_at ON payment_charges (created_at);

CREATE INDEX ix_payment_charges_tenant_id ON payment_charges (tenant_id);

CREATE TABLE subscriptions (
    bot_id VARCHAR(36) NOT NULL,
    contact_id VARCHAR(36) NOT NULL,
    plan_id VARCHAR(36) NOT NULL,
    payment_id VARCHAR(36) NOT NULL,
    kind VARCHAR(30) NOT NULL,
    status VARCHAR(30) NOT NULL,
    starts_at BIGINT NOT NULL,
    expires_at BIGINT NOT NULL,
    auto_renew BOOLEAN NOT NULL,
    initial_charge_id VARCHAR(255),
    renewal_status VARCHAR(20) NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, bot_id) REFERENCES managed_bots (tenant_id, id),
    FOREIGN KEY(tenant_id, contact_id) REFERENCES contacts (tenant_id, id),
    FOREIGN KEY(tenant_id, payment_id) REFERENCES payments (tenant_id, id),
    FOREIGN KEY(tenant_id, plan_id) REFERENCES plans (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (payment_id),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_subscriptions_contact_id ON subscriptions (contact_id);

CREATE INDEX ix_subscriptions_created_at ON subscriptions (created_at);

CREATE INDEX ix_subscriptions_expires_at ON subscriptions (expires_at);

CREATE INDEX ix_subscriptions_status ON subscriptions (status);

CREATE INDEX ix_subscriptions_tenant_id ON subscriptions (tenant_id);

CREATE TABLE channel_invites (
    channel_id VARCHAR(36) NOT NULL,
    contact_id VARCHAR(36) NOT NULL,
    subscription_id VARCHAR(36) NOT NULL,
    invite_link VARCHAR(512) NOT NULL,
    expires_at BIGINT NOT NULL,
    used_at BIGINT,
    revoked_at BIGINT,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, channel_id) REFERENCES channels (tenant_id, id),
    FOREIGN KEY(tenant_id, contact_id) REFERENCES contacts (tenant_id, id),
    FOREIGN KEY(tenant_id, subscription_id) REFERENCES subscriptions (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (invite_link),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_channel_invites_created_at ON channel_invites (created_at);

CREATE INDEX ix_channel_invites_tenant_id ON channel_invites (tenant_id);

INSERT INTO alembic_version (version_num) VALUES ('0001') RETURNING alembic_version.version_num;

-- Running upgrade 0001 -> 0002

ALTER TABLE "tenant_members" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "tenant_members" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "tenant_members" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "onboarding" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "onboarding" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "onboarding" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "bot_creation_requests" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "bot_creation_requests" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "bot_creation_requests" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "managed_bots" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "managed_bots" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "managed_bots" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "bot_secrets" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "bot_secrets" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "bot_secrets" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "bot_settings" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "bot_settings" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "bot_settings" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "bot_texts" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "bot_texts" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "bot_texts" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "channels" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "channels" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "channels" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "plans" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "plans" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "plans" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "plan_prices" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "plan_prices" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "plan_prices" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "contacts" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "contacts" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "contacts" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "payments" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "payments" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "payments" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "payment_charges" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "payment_charges" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "payment_charges" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "payment_attempts" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "payment_attempts" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "payment_attempts" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "bank_receipts" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "bank_receipts" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "bank_receipts" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "payment_provider_configs" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "payment_provider_configs" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "payment_provider_configs" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "subscriptions" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "subscriptions" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "subscriptions" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "channel_invites" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "channel_invites" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "channel_invites" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "conversations" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "conversations" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "conversations" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "messages" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "messages" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "messages" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "internal_notes" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "internal_notes" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "internal_notes" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "tags" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "tags" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "tags" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "contact_tags" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "contact_tags" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "contact_tags" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "campaigns" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "campaigns" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "campaigns" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "campaign_recipients" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "campaign_recipients" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "campaign_recipients" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "automation_rules" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "automation_rules" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "automation_rules" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "automation_executions" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "automation_executions" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "automation_executions" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "crm_tasks" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "crm_tasks" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "crm_tasks" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "coupons" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "coupons" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "coupons" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "coupon_redemptions" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "coupon_redemptions" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "coupon_redemptions" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "referrals" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "referrals" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "referrals" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "attribution_links" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "attribution_links" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "attribution_links" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "events" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "events" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "events" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "saas_subscriptions" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "saas_subscriptions" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "saas_subscriptions" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "saas_invoices" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "saas_invoices" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "saas_invoices" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "saas_charges" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "saas_charges" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "saas_charges" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "feature_flags" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "feature_flags" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "feature_flags" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "usage_counters" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "usage_counters" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "usage_counters" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "audit_logs" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "audit_logs" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "audit_logs" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "telegram_updates" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "telegram_updates" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "telegram_updates" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "provider_events" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "provider_events" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "provider_events" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "jobs" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "jobs" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "jobs" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

UPDATE alembic_version SET version_num='0002' WHERE alembic_version.version_num = '0001';

-- Running upgrade 0002 -> 0003

ALTER TABLE bank_receipts ADD COLUMN receipt_ciphertext JSON;

UPDATE alembic_version SET version_num='0003' WHERE alembic_version.version_num = '0002';

-- Running upgrade 0003 -> 0004

CREATE TABLE console_states (
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    bot_key VARCHAR(36) NOT NULL,
    telegram_user_id BIGINT NOT NULL,
    data JSON NOT NULL,
    expires_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (bot_key, telegram_user_id)
);

CREATE INDEX ix_console_states_created_at ON console_states (created_at);

CREATE INDEX ix_console_states_expires_at ON console_states (expires_at);

CREATE TABLE console_buttons (
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    bot_key VARCHAR(36) NOT NULL,
    telegram_user_id BIGINT NOT NULL,
    action VARCHAR(40) NOT NULL,
    data JSON NOT NULL,
    expires_at BIGINT NOT NULL,
    used_at BIGINT,
    PRIMARY KEY (id)
);

CREATE INDEX ix_console_buttons_created_at ON console_buttons (created_at);

CREATE INDEX ix_console_buttons_expires_at ON console_buttons (expires_at);

CREATE TABLE poll_cursors (
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    bot_key VARCHAR(36) NOT NULL,
    next_offset BIGINT NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (bot_key)
);

CREATE INDEX ix_poll_cursors_created_at ON poll_cursors (created_at);

UPDATE alembic_version SET version_num='0004' WHERE alembic_version.version_num = '0003';

-- Running upgrade 0004 -> 0005

CREATE TABLE platform_settings (
    key VARCHAR(80) NOT NULL,
    value JSON NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (key)
);

CREATE INDEX ix_platform_settings_created_at ON platform_settings (created_at);

CREATE TABLE connection_attempts (
    actor_id VARCHAR(36) NOT NULL,
    request_key VARCHAR(160) NOT NULL,
    token_ciphertext JSON,
    candidate JSON NOT NULL,
    replace_bot_id VARCHAR(36),
    status VARCHAR(24) NOT NULL,
    expires_at BIGINT NOT NULL,
    error_code VARCHAR(64),
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(actor_id) REFERENCES platform_users (id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (tenant_id, id),
    UNIQUE (tenant_id, request_key)
);

CREATE INDEX ix_connection_attempts_created_at ON connection_attempts (created_at);

CREATE INDEX ix_connection_attempts_expires_at ON connection_attempts (expires_at);

CREATE INDEX ix_connection_attempts_tenant_id ON connection_attempts (tenant_id);

CREATE TABLE billing_cycles (
    subscription_id VARCHAR(36) NOT NULL,
    plan_id VARCHAR(36) NOT NULL,
    plan_name VARCHAR(40) NOT NULL,
    fixed_usd_minor BIGINT NOT NULL,
    commission_bps INTEGER NOT NULL,
    starts_at BIGINT NOT NULL,
    ends_at BIGINT NOT NULL,
    due_at BIGINT NOT NULL,
    status VARCHAR(24) NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(plan_id) REFERENCES saas_plans (id),
    FOREIGN KEY(tenant_id, subscription_id) REFERENCES saas_subscriptions (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (subscription_id, starts_at),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_billing_cycles_created_at ON billing_cycles (created_at);

CREATE INDEX ix_billing_cycles_tenant_id ON billing_cycles (tenant_id);

CREATE INDEX ix_cycle_close ON billing_cycles (status, ends_at);

CREATE TABLE bot_admins (
    bot_id VARCHAR(36) NOT NULL,
    user_id VARCHAR(36) NOT NULL,
    role VARCHAR(20) NOT NULL,
    permissions JSON NOT NULL,
    active BOOLEAN NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, bot_id) REFERENCES managed_bots (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    FOREIGN KEY(user_id) REFERENCES platform_users (id),
    UNIQUE (bot_id, user_id),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_bot_admins_bot_id ON bot_admins (bot_id);

CREATE INDEX ix_bot_admins_created_at ON bot_admins (created_at);

CREATE INDEX ix_bot_admins_tenant_id ON bot_admins (tenant_id);

CREATE TABLE bot_payment_methods (
    bot_id VARCHAR(36) NOT NULL,
    provider VARCHAR(30) NOT NULL,
    enabled BOOLEAN NOT NULL,
    public_config JSON NOT NULL,
    secrets_ciphertext JSON,
    webhook_key VARCHAR(36) NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, bot_id) REFERENCES managed_bots (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (bot_id, provider),
    UNIQUE (tenant_id, id),
    UNIQUE (webhook_key)
);

CREATE INDEX ix_bot_payment_methods_bot_id ON bot_payment_methods (bot_id);

CREATE INDEX ix_bot_payment_methods_created_at ON bot_payment_methods (created_at);

CREATE INDEX ix_bot_payment_methods_tenant_id ON bot_payment_methods (tenant_id);

CREATE TABLE reports (
    bot_id VARCHAR(36) NOT NULL,
    actor_id VARCHAR(36) NOT NULL,
    starts_at BIGINT NOT NULL,
    ends_at BIGINT NOT NULL,
    status VARCHAR(20) NOT NULL,
    summary JSON NOT NULL,
    content_ciphertext JSON,
    expires_at BIGINT NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, bot_id) REFERENCES managed_bots (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_reports_bot_id ON reports (bot_id);

CREATE INDEX ix_reports_created_at ON reports (created_at);

CREATE INDEX ix_reports_tenant_id ON reports (tenant_id);

CREATE TABLE platform_invoices (
    cycle_id VARCHAR(36) NOT NULL,
    number VARCHAR(60) NOT NULL,
    currency VARCHAR(8) NOT NULL,
    fixed_minor BIGINT NOT NULL,
    commission_minor BIGINT,
    adjustment_minor BIGINT NOT NULL,
    paid_minor BIGINT NOT NULL,
    breakdown JSON NOT NULL,
    due_at BIGINT NOT NULL,
    status VARCHAR(24) NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, cycle_id) REFERENCES billing_cycles (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (cycle_id),
    UNIQUE (number),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_platform_invoice_due ON platform_invoices (status, due_at);

CREATE INDEX ix_platform_invoices_created_at ON platform_invoices (created_at);

CREATE INDEX ix_platform_invoices_tenant_id ON platform_invoices (tenant_id);

CREATE TABLE access_offers (
    bot_id VARCHAR(36) NOT NULL,
    plan_id VARCHAR(36) NOT NULL,
    code_hash VARCHAR(64) NOT NULL,
    code_ciphertext JSON NOT NULL,
    duration_days INTEGER NOT NULL,
    channel_ids JSON NOT NULL,
    max_uses INTEGER NOT NULL,
    uses INTEGER NOT NULL,
    expires_at BIGINT NOT NULL,
    active BOOLEAN NOT NULL,
    actor_id VARCHAR(36) NOT NULL,
    note VARCHAR(500) NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, bot_id) REFERENCES managed_bots (tenant_id, id),
    FOREIGN KEY(tenant_id, plan_id) REFERENCES plans (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (code_hash),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_access_offers_bot_id ON access_offers (bot_id);

CREATE INDEX ix_access_offers_created_at ON access_offers (created_at);

CREATE INDEX ix_access_offers_tenant_id ON access_offers (tenant_id);

CREATE TABLE invoice_adjustments (
    invoice_id VARCHAR(36) NOT NULL,
    amount_minor BIGINT NOT NULL,
    reason VARCHAR(500) NOT NULL,
    actor_id VARCHAR(64) NOT NULL,
    operation_key VARCHAR(160) NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, invoice_id) REFERENCES platform_invoices (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (tenant_id, id),
    UNIQUE (tenant_id, operation_key)
);

CREATE INDEX ix_invoice_adjustments_created_at ON invoice_adjustments (created_at);

CREATE INDEX ix_invoice_adjustments_invoice_id ON invoice_adjustments (invoice_id);

CREATE INDEX ix_invoice_adjustments_tenant_id ON invoice_adjustments (tenant_id);

CREATE TABLE plan_channels (
    plan_id VARCHAR(36) NOT NULL,
    channel_id VARCHAR(36) NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, channel_id) REFERENCES channels (tenant_id, id),
    FOREIGN KEY(tenant_id, plan_id) REFERENCES plans (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (plan_id, channel_id),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_plan_channels_channel_id ON plan_channels (channel_id);

CREATE INDEX ix_plan_channels_created_at ON plan_channels (created_at);

CREATE INDEX ix_plan_channels_plan_id ON plan_channels (plan_id);

CREATE INDEX ix_plan_channels_tenant_id ON plan_channels (tenant_id);

CREATE TABLE platform_settlements (
    invoice_id VARCHAR(36) NOT NULL,
    method VARCHAR(24) NOT NULL,
    reference_hash VARCHAR(64) NOT NULL,
    reference VARCHAR(240) NOT NULL,
    amount_usd_minor BIGINT NOT NULL,
    evidence JSON NOT NULL,
    receipt_ciphertext JSON,
    media_type VARCHAR(50),
    status VARCHAR(24) NOT NULL,
    submitted_by VARCHAR(36) NOT NULL,
    reviewed_by VARCHAR(64),
    reviewed_at BIGINT,
    note VARCHAR(500) NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, invoice_id) REFERENCES platform_invoices (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (reference_hash),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_platform_settlements_created_at ON platform_settlements (created_at);

CREATE INDEX ix_platform_settlements_invoice_id ON platform_settlements (invoice_id);

CREATE INDEX ix_platform_settlements_tenant_id ON platform_settlements (tenant_id);

CREATE TABLE access_redemptions (
    offer_id VARCHAR(36) NOT NULL,
    contact_id VARCHAR(36) NOT NULL,
    subscription_id VARCHAR(36) NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, contact_id) REFERENCES contacts (tenant_id, id),
    FOREIGN KEY(tenant_id, offer_id) REFERENCES access_offers (tenant_id, id),
    FOREIGN KEY(tenant_id, subscription_id) REFERENCES subscriptions (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (offer_id, contact_id),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_access_redemptions_created_at ON access_redemptions (created_at);

CREATE INDEX ix_access_redemptions_offer_id ON access_redemptions (offer_id);

CREATE INDEX ix_access_redemptions_tenant_id ON access_redemptions (tenant_id);

CREATE TABLE commission_entries (
    cycle_id VARCHAR(36),
    charge_id VARCHAR(36) NOT NULL,
    entry_key VARCHAR(160) NOT NULL,
    currency VARCHAR(8) NOT NULL,
    gross_minor BIGINT NOT NULL,
    commission_bps INTEGER NOT NULL,
    usd_rate VARCHAR(60),
    rate_source VARCHAR(100) NOT NULL,
    entry_type VARCHAR(20) NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, charge_id) REFERENCES payment_charges (tenant_id, id),
    FOREIGN KEY(tenant_id, cycle_id) REFERENCES billing_cycles (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (tenant_id, entry_key),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_commission_cycle_currency ON commission_entries (cycle_id, currency);

CREATE INDEX ix_commission_entries_created_at ON commission_entries (created_at);

CREATE INDEX ix_commission_entries_tenant_id ON commission_entries (tenant_id);

CREATE TABLE payment_refunds (
    bot_id VARCHAR(36) NOT NULL,
    charge_id VARCHAR(36) NOT NULL,
    provider VARCHAR(40) NOT NULL,
    reference VARCHAR(255) NOT NULL,
    amount_minor BIGINT NOT NULL,
    currency VARCHAR(8) NOT NULL,
    actor_id VARCHAR(64) NOT NULL,
    reason VARCHAR(500) NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, bot_id) REFERENCES managed_bots (tenant_id, id),
    FOREIGN KEY(tenant_id, charge_id) REFERENCES payment_charges (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (bot_id, provider, reference),
    UNIQUE (tenant_id, id)
);

CREATE INDEX ix_payment_refunds_bot_id ON payment_refunds (bot_id);

CREATE INDEX ix_payment_refunds_charge_id ON payment_refunds (charge_id);

CREATE INDEX ix_payment_refunds_created_at ON payment_refunds (created_at);

CREATE INDEX ix_payment_refunds_tenant_id ON payment_refunds (tenant_id);

CREATE INDEX ix_refund_bot_period ON payment_refunds (bot_id, created_at, currency);

CREATE TABLE subscription_history (
    subscription_id VARCHAR(36) NOT NULL,
    revision BIGINT NOT NULL,
    actor_id VARCHAR(64) NOT NULL,
    action VARCHAR(40) NOT NULL,
    operation_key VARCHAR(200) NOT NULL,
    before JSON NOT NULL,
    after JSON NOT NULL,
    reason VARCHAR(500) NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id, subscription_id) REFERENCES subscriptions (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    UNIQUE (subscription_id, revision),
    UNIQUE (tenant_id, id),
    UNIQUE (tenant_id, operation_key)
);

CREATE INDEX ix_sub_history_timeline ON subscription_history (subscription_id, created_at, revision);

CREATE INDEX ix_subscription_history_created_at ON subscription_history (created_at);

CREATE INDEX ix_subscription_history_subscription_id ON subscription_history (subscription_id);

CREATE INDEX ix_subscription_history_tenant_id ON subscription_history (tenant_id);

ALTER TABLE bank_receipts ADD COLUMN reviewed_at BIGINT;

ALTER TABLE bot_settings ADD COLUMN preferences JSON DEFAULT '{}' NOT NULL;

ALTER TABLE campaigns ADD COLUMN media JSON DEFAULT '{}' NOT NULL;

ALTER TABLE campaigns ADD COLUMN buttons JSON DEFAULT '[]' NOT NULL;

ALTER TABLE campaigns ADD COLUMN actor_id VARCHAR(36);

ALTER TABLE campaigns ADD COLUMN audience_count INTEGER DEFAULT 0 NOT NULL;

ALTER TABLE console_states ADD COLUMN navigation JSON DEFAULT '[]' NOT NULL;

ALTER TABLE console_states ADD COLUMN screen JSON DEFAULT '{}' NOT NULL;

ALTER TABLE contacts ADD COLUMN locale VARCHAR(8) DEFAULT 'es' NOT NULL;

CREATE INDEX ix_contact_bot_created ON contacts (bot_id, created_at);

CREATE INDEX ix_contact_bot_page ON contacts (bot_id, id);

ALTER TABLE jobs ADD COLUMN lane VARCHAR(16) DEFAULT 'background' NOT NULL;

ALTER TABLE jobs ADD COLUMN started_at BIGINT;

ALTER TABLE jobs ADD COLUMN stream_key VARCHAR(100);

ALTER TABLE jobs ADD COLUMN sequence BIGINT DEFAULT 0 NOT NULL;

CREATE INDEX ix_job_lane_due ON jobs (lane, status, run_at, tenant_id);

CREATE INDEX ix_job_stale ON jobs (status, lease_until);

CREATE INDEX ix_job_stream_sequence ON jobs (stream_key, status, sequence);

CREATE INDEX ix_jobs_lane ON jobs (lane);

CREATE INDEX ix_jobs_stream_key ON jobs (stream_key);

ALTER TABLE managed_bots ADD COLUMN connection_kind VARCHAR(20) DEFAULT 'MANAGED' NOT NULL;

ALTER TABLE managed_bots ADD COLUMN disconnected_at BIGINT;

CREATE INDEX ix_charge_bot_period ON payment_charges (bot_id, created_at, currency);

CREATE INDEX ix_charge_payment ON payment_charges (payment_id, created_at);

ALTER TABLE payments ADD COLUMN provider_reference VARCHAR(255);

ALTER TABLE payments ADD COLUMN channel_snapshot JSON DEFAULT '[]' NOT NULL;

CREATE INDEX ix_payment_bot_status ON payments (bot_id, status, created_at);

CREATE INDEX ix_payments_provider_reference ON payments (provider_reference);

ALTER TABLE plans ADD COLUMN visible BOOLEAN DEFAULT true NOT NULL;

ALTER TABLE plans ADD COLUMN archived_at BIGINT;

ALTER TABLE plans ADD COLUMN purchase_message VARCHAR(2000) DEFAULT '' NOT NULL;

ALTER TABLE platform_users ADD COLUMN trial_used_at BIGINT;

ALTER TABLE provider_events ADD COLUMN payload_ciphertext JSON;

ALTER TABLE provider_events ADD COLUMN status VARCHAR(20) DEFAULT 'PENDING' NOT NULL;

ALTER TABLE saas_plans ADD COLUMN fixed_usd_minor BIGINT DEFAULT 0 NOT NULL;

ALTER TABLE saas_plans ADD COLUMN commission_bps INTEGER DEFAULT 800 NOT NULL;

ALTER TABLE saas_subscriptions ADD COLUMN trial_starts_at BIGINT;

ALTER TABLE saas_subscriptions ADD COLUMN cycle_started_at BIGINT;

ALTER TABLE saas_subscriptions ADD COLUMN pending_plan_id VARCHAR(36);

ALTER TABLE saas_subscriptions ADD COLUMN grace_days INTEGER DEFAULT 3 NOT NULL;

ALTER TABLE saas_subscriptions ADD COLUMN cancelled_at BIGINT;

ALTER TABLE saas_subscriptions ADD CONSTRAINT fk_saas_pending_plan FOREIGN KEY(pending_plan_id) REFERENCES saas_plans (id);

ALTER TABLE subscriptions ADD COLUMN origin VARCHAR(24) DEFAULT 'PAYMENT' NOT NULL;

ALTER TABLE subscriptions ADD COLUMN channel_snapshot JSON DEFAULT '[]' NOT NULL;

ALTER TABLE subscriptions ALTER COLUMN payment_id DROP NOT NULL;

CREATE INDEX ix_subscription_bot_status_end ON subscriptions (bot_id, status, expires_at);

CREATE INDEX ix_subscription_contact_status_end ON subscriptions (contact_id, status, expires_at);

ALTER TABLE telegram_updates ADD COLUMN sensitive_ciphertext JSON;

ALTER TABLE tenants ADD COLUMN admin_suspended_at BIGINT;

UPDATE saas_subscriptions SET trial_starts_at=created_at WHERE trial_ends_at>created_at;

UPDATE platform_users SET trial_used_at=(SELECT min(s.created_at) FROM saas_subscriptions s JOIN tenants t ON t.id=s.tenant_id WHERE t.owner_user_id=platform_users.id);

UPDATE saas_plans SET fixed_usd_minor=0, commission_bps=800 WHERE name='STARTER';

UPDATE saas_plans SET fixed_usd_minor=3000, commission_bps=400 WHERE name='PRO';

UPDATE saas_plans SET fixed_usd_minor=8000, commission_bps=100 WHERE name='AGENCY';

UPDATE saas_plans SET features=(features::jsonb || jsonb_build_object('external_payments',true))::json;

INSERT INTO plan_channels(id,created_at,updated_at,tenant_id,plan_id,channel_id) SELECT gen_random_uuid()::text,created_at,updated_at,tenant_id,id,channel_id FROM plans WHERE channel_id IS NOT NULL;

UPDATE payments SET channel_snapshot=(SELECT CASE WHEN p.channel_id IS NULL THEN '[]'::json ELSE json_build_array(p.channel_id) END FROM plans p WHERE p.id=payments.plan_id AND p.tenant_id=payments.tenant_id);

UPDATE subscriptions SET channel_snapshot=(SELECT p.channel_snapshot FROM payments p WHERE p.id=subscriptions.payment_id AND p.tenant_id=subscriptions.tenant_id);

INSERT INTO subscription_history(id,created_at,updated_at,tenant_id,subscription_id,revision,actor_id,action,operation_key,before,after,reason) SELECT gen_random_uuid()::text,extract(epoch from clock_timestamp())::bigint,extract(epoch from clock_timestamp())::bigint,tenant_id,id,1,'migration','MIGRATED','migration:' || id,'{}'::json,json_build_object('status',status,'expires_at',expires_at,'starts_at',starts_at,'origin',origin,'plan_id',plan_id,'channels',channel_snapshot),'Imported from version 0004; previous audit records preserved' FROM subscriptions;

INSERT INTO bot_admins(id,created_at,updated_at,tenant_id,bot_id,user_id,role,permissions,active) SELECT gen_random_uuid()::text,tm.created_at,tm.updated_at,tm.tenant_id,b.id,tm.user_id,CASE tm.role WHEN 'SUPERVISOR' THEN 'ADMIN' WHEN 'PAYMENTS' THEN 'FINANCE' ELSE tm.role END,'[]'::json,tm.active FROM tenant_members tm JOIN managed_bots b ON b.tenant_id=tm.tenant_id;

INSERT INTO bot_payment_methods(id,created_at,updated_at,tenant_id,bot_id,provider,enabled,public_config,secrets_ciphertext,webhook_key) SELECT gen_random_uuid()::text,p.created_at,p.updated_at,p.tenant_id,b.id,p.provider,p.enabled,CASE WHEN p.provider='BANK_TRANSFER' THEN json_build_object('_legacy_provider_id',p.id,'currency',p.public_config->>'currency') ELSE '{}'::json END,p.secrets_ciphertext,gen_random_uuid()::text FROM payment_provider_configs p JOIN managed_bots b ON b.tenant_id=p.tenant_id WHERE p.provider IN ('TELEGRAM_STARS','BANK_TRANSFER');

UPDATE jobs SET lane='interactive' WHERE kind='UPDATE' OR kind='SEND' AND dedup_key LIKE 'console:%';

UPDATE provider_events SET status='DONE';

INSERT INTO commission_entries(id,created_at,updated_at,tenant_id,cycle_id,charge_id,entry_key,currency,gross_minor,commission_bps,usd_rate,rate_source,entry_type) SELECT gen_random_uuid()::text,created_at,updated_at,tenant_id,NULL,id,'sale:' || id,currency,amount_minor,0,CASE WHEN currency='USD' THEN '1' ELSE NULL END,'legacy','TRIAL_OR_LEGACY' FROM payment_charges;

INSERT INTO payment_refunds(id,created_at,updated_at,tenant_id,bot_id,charge_id,provider,reference,amount_minor,currency,actor_id,reason) SELECT gen_random_uuid()::text,refunded_at,refunded_at,tenant_id,bot_id,id,provider,'legacy:' || id,amount_minor,currency,'migration','Existing refund before version 0005' FROM payment_charges WHERE refunded_at IS NOT NULL;

UPDATE campaigns SET status='PAUSED', cursor=CASE WHEN cursor='DONE' THEN 'DONE' ELSE 'SNAPSHOT' END WHERE status IN ('RUNNING','SCHEDULED','PAUSED');

ALTER TABLE "connection_attempts" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "connection_attempts" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON connection_attempts USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "billing_cycles" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "billing_cycles" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON billing_cycles USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "bot_admins" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "bot_admins" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON bot_admins USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "bot_payment_methods" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "bot_payment_methods" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON bot_payment_methods USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "reports" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "reports" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON reports USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "platform_invoices" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "platform_invoices" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON platform_invoices USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "access_offers" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "access_offers" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON access_offers USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "invoice_adjustments" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "invoice_adjustments" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON invoice_adjustments USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "plan_channels" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "plan_channels" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON plan_channels USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "platform_settlements" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "platform_settlements" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON platform_settlements USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "access_redemptions" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "access_redemptions" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON access_redemptions USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "commission_entries" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "commission_entries" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON commission_entries USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "payment_refunds" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "payment_refunds" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON payment_refunds USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

ALTER TABLE "subscription_history" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "subscription_history" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON subscription_history USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

DO $$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname='platform_api') THEN REVOKE ALL ON platform_settings FROM platform_api; END IF; END $$;

UPDATE alembic_version SET version_num='0005' WHERE alembic_version.version_num = '0004';

-- Running upgrade 0005 -> 0006

ALTER TABLE messages ADD COLUMN media JSON DEFAULT '{}' NOT NULL;

ALTER TABLE messages ALTER COLUMN media DROP DEFAULT;

ALTER TABLE payments ADD COLUMN instructions_snapshot JSON DEFAULT '{}' NOT NULL;

ALTER TABLE payments ALTER COLUMN instructions_snapshot DROP DEFAULT;

CREATE TABLE inbox_deliveries (
    id VARCHAR(36) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    bot_id VARCHAR(36) NOT NULL,
    message_id VARCHAR(36) NOT NULL,
    viewer_id BIGINT NOT NULL,
    part VARCHAR(10) NOT NULL,
    telegram_message_id BIGINT,
    status VARCHAR(20) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (tenant_id, id),
    UNIQUE (message_id, viewer_id, part),
    UNIQUE (bot_id, viewer_id, telegram_message_id),
    FOREIGN KEY(tenant_id, bot_id) REFERENCES managed_bots (tenant_id, id),
    FOREIGN KEY(tenant_id, message_id) REFERENCES messages (tenant_id, id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_inbox_deliveries_created_at ON inbox_deliveries (created_at);

CREATE INDEX ix_inbox_deliveries_tenant_id ON inbox_deliveries (tenant_id);

ALTER TABLE inbox_deliveries ENABLE ROW LEVEL SECURITY;

ALTER TABLE inbox_deliveries FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON inbox_deliveries USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), ''));

DO $$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname='platform_api') THEN REVOKE ALL ON inbox_deliveries FROM platform_api; END IF; END $$;

UPDATE alembic_version SET version_num='0006' WHERE alembic_version.version_num = '0005';

COMMIT;

