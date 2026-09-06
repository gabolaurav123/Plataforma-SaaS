from typing import Protocol, Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class ImportRecord:
    kind: str
    source_id: str
    data: dict


class LegacyImporter(Protocol):
    """Future offline contract. No production DB connector or migration runner is included."""

    def validate(self, records: Iterable[ImportRecord]) -> list[str]: ...
    def dry_run(self, tenant_id: str, records: Iterable[ImportRecord]) -> dict: ...
    def import_batch(self, tenant_id: str, records: Iterable[ImportRecord], idempotency_key: str) -> dict: ...
