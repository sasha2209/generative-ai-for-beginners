"""Run all rules over a profile and assemble a report."""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone

from ..models import LEVEL_ORDER, HealthProfile, InsightReport
from .rules import ALL_RULES, Rule

log = logging.getLogger(__name__)

DISCLAIMER = (
    "These insights are educational and based on simplified summaries of published "
    "guidelines. They are not a diagnosis and do not replace advice from a clinician "
    "or genetic counselor who knows your full history. The absence of an insight does "
    "not mean your risk is low; it may mean information is missing."
)


def pedigree_summary(profile: HealthProfile) -> dict:
    by_side: Counter = Counter()
    by_condition: Counter = Counter()
    for m in profile.family:
        by_side[m.side or ("immediate" if m.degree == 1 else "unspecified")] += 1
        for c in m.conditions:
            by_condition[c.display_name] += 1
    return {
        "relatives": len(profile.family),
        "relatives_with_conditions": sum(1 for m in profile.family if m.conditions),
        "by_side": dict(by_side),
        "conditions_in_family": dict(by_condition.most_common()),
    }


def generate_insights(profile: HealthProfile, rules: list[Rule] | None = None) -> InsightReport:
    insights = []
    for rule in rules or ALL_RULES:
        try:
            result = rule(profile)
        except Exception:  # one bad rule must never take down the report
            log.exception("insight rule %s failed", getattr(rule, "__name__", rule))
            continue
        if result:
            insights.append(result)
    insights.sort(key=lambda i: LEVEL_ORDER[i.level])
    return InsightReport(
        generated_at=datetime.now(timezone.utc),
        insights=insights,
        pedigree=pedigree_summary(profile),
        disclaimer=DISCLAIMER,
    )
