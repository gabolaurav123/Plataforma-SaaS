"""Read-only helper for the operator to identify their own registered Telegram account."""
from sqlalchemy import select
from platform_app.runtime import Runtime
from platform_app.models import PlatformUser

with Runtime().db.system() as session:
    for user in session.scalars(select(PlatformUser).order_by(PlatformUser.created_at.desc()).limit(20)):
        print(user.telegram_user_id, user.first_name, "@" + user.username if user.username else "")
