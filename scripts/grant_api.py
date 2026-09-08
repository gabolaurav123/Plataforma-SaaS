"""Run with migration/system role after migrations; API role cannot alter schemas or bypass RLS."""

from sqlalchemy import text
from platform_app.runtime import Runtime

with Runtime().db.system() as db:
    if db.bind.dialect.name != "postgresql":
        raise SystemExit("PostgreSQL only")
    db.execute(text("GRANT USAGE ON SCHEMA public TO platform_api"))
    db.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO platform_api"))
    db.execute(text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO platform_api"))
    db.execute(text("REVOKE UPDATE, DELETE ON audit_logs FROM platform_api"))
    db.execute(text("REVOKE ALL ON auth_sessions FROM platform_api"))
    db.execute(text("REVOKE ALL ON console_states, console_buttons, poll_cursors FROM platform_api"))
    db.execute(text("REVOKE ALL ON platform_settings FROM platform_api"))
    db.execute(text("REVOKE ALL ON inbox_deliveries FROM platform_api"))
    db.execute(text("REVOKE INSERT, UPDATE, DELETE ON billing_cycles, commission_entries, platform_invoices, platform_settlements, invoice_adjustments, payment_refunds, subscription_history FROM platform_api"))
print("Granted scoped API access; audit logs are append-only for API role.")
