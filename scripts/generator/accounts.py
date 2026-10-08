"""
AEGIS-Flow Synthetic Generator — Accounts Module
=================================================

Manages synthetic institutions, account pools, and deterministic account generation.
All institutions are synthetic identifiers (e.g. BANK_A, BANK_B, BANK_C, BANK_D).
These do NOT represent real financial institutions or integrations.
"""

from __future__ import annotations

from enum import StrEnum, unique
from typing import Sequence

from contracts.account import AccountReference


# ── Synthetic Banking Institutions ───────────────────────────────────────────
SYNTHETIC_BANKS: list[str] = ["BANK_A", "BANK_B", "BANK_C", "BANK_D"]


@unique
class AccountRole(StrEnum):
    """Synthetic account behavioral role within test scenarios."""

    VICTIM = "victim"
    MULE = "mule"
    AGGREGATOR = "aggregator"
    CHOKEPOINT = "chokepoint"
    EXFILTRATION = "exfiltration"
    MERCHANT = "merchant"
    COMMINGLER = "commingler"
    COLD_START = "cold_start"
    LEGITIMATE = "legitimate"


def create_account(
    account_id: str,
    institution: str = "BANK_A",
    label: str | None = None,
) -> AccountReference:
    """Create a canonical AccountReference adhering to the contracts schema."""
    return AccountReference(
        account_id=account_id,
        institution=institution,
        label=label or account_id,
    )


class AccountPool:
    """Deterministic account directory for synthetic scenario generation."""

    def __init__(self, prefix: str = "acc", default_bank: str = "BANK_A") -> None:
        self.prefix = prefix
        self.default_bank = default_bank
        self._accounts: dict[str, AccountReference] = {}
        self._counter: int = 0

    def new_account(
        self,
        role: AccountRole = AccountRole.LEGITIMATE,
        institution: str | None = None,
        label: str | None = None,
        custom_id: str | None = None,
    ) -> AccountReference:
        """Create and register a new deterministic synthetic account."""
        self._counter += 1
        bank = institution or self.default_bank
        if custom_id is not None:
            acct_id = custom_id
        else:
            acct_id = f"{self.prefix}-{bank.lower()}-{role.value}-{self._counter:04d}"

        display_label = label or f"{bank} {role.value.capitalize()} #{self._counter:04d}"
        acct = create_account(account_id=acct_id, institution=bank, label=display_label)
        self._accounts[acct_id] = acct
        return acct

    def get(self, account_id: str) -> AccountReference | None:
        """Retrieve an account by ID."""
        return self._accounts.get(account_id)

    def all_accounts(self) -> list[AccountReference]:
        """Return all registered accounts."""
        return list(self._accounts.values())
