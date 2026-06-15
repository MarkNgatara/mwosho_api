"""
Central plan / entitlements engine — the single source of truth for pricing,
limits and feature gating.

Before this module, tier logic was duplicated across upload.py, chat.py,
payments.py, orchestrator.py and helpers.py (21 hardcoded checks). To add a
tier, change a price, or move a feature between tiers, edit ONLY this file.

Feature gating is done with entitled(tier, "<feature>"). Features are
cumulative: each tier inherits every feature of the tiers below it.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.models.user import SubscriptionTier


@dataclass(frozen=True)
class Plan:
    tier: SubscriptionTier
    name: str
    usd_monthly: int
    usd_yearly: int          # = 10 x monthly (2 months free)
    kes_monthly: int
    kes_yearly: int
    jobs_per_month: int
    max_file_mb: int
    chat_per_hour: int
    features: frozenset       # cumulative effective feature flags

    @property
    def key(self) -> str:
        return self.tier.value


# Tier ladder, lowest → highest. Order defines feature inheritance.
_TIER_ORDER = [
    SubscriptionTier.FREE,
    SubscriptionTier.STARTER,
    SubscriptionTier.PROFESSIONAL,
    SubscriptionTier.BUSINESS,
    SubscriptionTier.GROWTH,
    SubscriptionTier.ENTERPRISE,
]

# Features UNLOCKED AT each tier (additive). Names are referenced directly by
# entitled(tier, "<feature>") in the backend — keep them stable.
_FEATURES_ADDED: dict[SubscriptionTier, set[str]] = {
    SubscriptionTier.FREE:         set(),  # basic cleaning only (always available)
    SubscriptionTier.STARTER:      {"xlsx", "validation", "quality_score", "history"},
    SubscriptionTier.PROFESSIONAL: {"fuzzy_dedup", "ai_reports", "json_export", "bulk", "priority"},
    SubscriptionTier.BUSINESS:     {"team", "merge", "scheduled", "api", "webhooks", "profiling"},
    SubscriptionTier.GROWTH:       {"analytics", "predictive", "db_sources", "powerbi", "custom_rules", "audit_logs"},
    SubscriptionTier.ENTERPRISE:   {"governance", "sso", "sla", "dedicated_workers"},
}


def _cumulative(up_to: SubscriptionTier) -> frozenset:
    acc: set[str] = set()
    for t in _TIER_ORDER:
        acc |= _FEATURES_ADDED[t]
        if t == up_to:
            break
    return frozenset(acc)


# Pricing & limits.
#   usd_yearly = 10 x monthly (2 months free).  KES ≈ FX at ~130/USD.
#   Enterprise "unlimited" is a 5,000/mo fair-use cap so per-job AI cost stays bounded.
_NAMES = {
    SubscriptionTier.FREE: "Free",
    SubscriptionTier.STARTER: "Starter",
    SubscriptionTier.PROFESSIONAL: "Professional",
    SubscriptionTier.BUSINESS: "Business",
    SubscriptionTier.GROWTH: "Growth",
    SubscriptionTier.ENTERPRISE: "Enterprise",
}

#                              usd_m  usd_y  kes_m   kes_y    jobs   mb     chat
_SPEC: dict[SubscriptionTier, tuple] = {
    SubscriptionTier.FREE:         (0,     0,     0,      0,       5,     18,    5),
    SubscriptionTier.STARTER:      (9,     90,    1200,   12000,   50,    100,   20),
    SubscriptionTier.PROFESSIONAL: (19,    190,   2500,   25000,   150,   250,   50),
    SubscriptionTier.BUSINESS:     (29,    290,   3800,   38000,   500,   500,   80),
    SubscriptionTier.GROWTH:       (59,    590,   7700,   77000,   2000,  1024,  150),
    SubscriptionTier.ENTERPRISE:   (99,    990,   12900,  129000,  5000,  2048,  300),
}

PLANS: dict[SubscriptionTier, Plan] = {
    t: Plan(
        tier=t,
        name=_NAMES[t],
        usd_monthly=v[0], usd_yearly=v[1],
        kes_monthly=v[2], kes_yearly=v[3],
        jobs_per_month=v[4], max_file_mb=v[5], chat_per_hour=v[6],
        features=_cumulative(t),
    )
    for t, v in _SPEC.items()
}

# Every tier except Free — the ones that can be purchased.
PAID_TIERS: list[SubscriptionTier] = [t for t in _TIER_ORDER if t != SubscriptionTier.FREE]


# ── Lookups ────────────────────────────────────────────────────────────────

def plan_for(tier: SubscriptionTier) -> Plan:
    """Return the Plan for a tier, falling back to Free for unknown values."""
    return PLANS.get(tier, PLANS[SubscriptionTier.FREE])


def entitled(tier: SubscriptionTier, feature: str) -> bool:
    """True if this tier (or any below the feature's gate) unlocks `feature`."""
    return feature in plan_for(tier).features


def chat_limit(tier: SubscriptionTier) -> int:
    return plan_for(tier).chat_per_hour


def allowed_extensions(tier: SubscriptionTier) -> set[str]:
    """File types a tier may upload, derived from its features."""
    f = plan_for(tier).features
    exts = {".csv", ".tsv"}                       # Free
    if "xlsx" in f:                               # Starter+
        exts |= {".xlsx", ".xls"}
    if "json_export" in f:                        # Professional+
        exts |= {".json", ".jsonl"}
    if "db_sources" in f:                         # Growth+
        exts |= {".parquet", ".gz"}
    return exts


def tier_for_key(key: str) -> SubscriptionTier | None:
    try:
        return SubscriptionTier(key)
    except ValueError:
        return None


def is_valid_plan_key(key: str) -> bool:
    """True only for purchasable tier keys (excludes 'free')."""
    t = tier_for_key(key)
    return t is not None and t in PAID_TIERS
