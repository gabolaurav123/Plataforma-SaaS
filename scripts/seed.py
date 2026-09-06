from platform_app.runtime import Runtime
from platform_app.services.tenants import seed_saas_plans

with Runtime().db.system() as session:
    seed_saas_plans(session)
print("Seeded configurable SaaS plans. No creators, customers or Telegram connections created.")
