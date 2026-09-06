import json
import threading
from .config import get_settings
from .db import Database
from .security import Vault, LocalKeyring
from .telegram import BotClients, BotClient
from .limiter import RateLimiter
from .cache import PublicConfigCache
from .services.bots import TelegramBotManager, ManagedBotProvisioner
from .services.channels import ChannelService
from .services.payments import PaymentService
from .services.receipts import ReceiptService
from .services.updates import UpdateHandler
from .services.growth import CampaignService, AutomationService
from .services.billing import SaaSBillingService
from .services.billing_ledger import PlatformLedger
from .services.connections import ConnectionService
from .services.business import InvitationService
from .services.reporting import ReportService


class Runtime:
    def __init__(self, settings=None, client_factory=BotClient):
        self.settings = settings or get_settings()
        self.db = Database(self.settings)
        self.bot_config_changed = threading.Event()
        self.claim_lock = threading.Lock()
        self.job_wakeups = []
        self.db.on_jobs = self.notify_jobs
        self.db.on_bots = self.bot_config_changed.set
        keys = json.loads(self.settings.encryption_keys.get_secret_value())
        # No fallback, static development key, or automatic loss of encryption on restart.
        self.vault = Vault(LocalKeyring(keys, self.settings.active_key_version)) if keys else None
        self.clients = BotClients(self.settings, self.vault, client_factory)
        self.limiter = RateLimiter(self.settings)
        self.public_cache = PublicConfigCache(self.limiter.redis)
        self.manager, self.provisioner = TelegramBotManager(self), ManagedBotProvisioner(self)
        self.channels, self.payments = ChannelService(self), PaymentService(self)
        self.receipts, self.updates = ReceiptService(self), UpdateHandler(self)
        self.campaigns, self.automations = CampaignService(), AutomationService()
        self.billing = SaaSBillingService(self)
        self.ledger = PlatformLedger(self)
        self.connections = ConnectionService(self)
        self.invitations = InvitationService(self)
        self.reports = ReportService(self)

    def close(self):
        self.clients.close()
        for provider in self.payments.providers.values():
            if hasattr(provider, "close"):
                provider.close()
        self.db.engine.dispose()
        if self.db.system_engine is not self.db.engine:
            self.db.system_engine.dispose()

    def notify_jobs(self):
        for wake in list(self.job_wakeups):
            wake.set()
