"""Consent-gated sharing with partners and de-identified research export.

This is the technical backbone of the partnership strategy
(docs/PARTNERSHIP_STRATEGY.md): every outbound flow is (1) opt-in per partner,
(2) limited to the minimum data categories that partner needs, (3) revocable,
and (4) audited.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .ingest.fhir import to_fhir_bundle
from .insights import generate_insights
from .models import HealthProfile

CONSENT_LLM = "ai_summary"
CONSENT_RESEARCH = "research_deidentified"


def share_scope(partner_id: str) -> str:
    return f"share:{partner_id}"


@dataclass(frozen=True)
class Partner:
    id: str
    name: str
    kind: str
    purpose: str
    categories: frozenset[str] = field(default_factory=frozenset)


# Example partner archetypes. Real partners are onboarded with a contract
# (BAA/DPA), a FHIR endpoint and credentials; see the strategy doc.
PARTNERS: dict[str, Partner] = {
    p.id: p for p in (
        Partner("genetic-counseling", "Genetic counseling network (example)", "genetic_counseling",
                "Book a telehealth genetic counseling visit pre-filled with your family history.",
                frozenset({"family_history", "conditions", "insights"})),
        Partner("primary-care", "Your primary care clinic (example)", "provider",
                "Send your family history and insights into your clinician's EHR before a visit.",
                frozenset({"family_history", "conditions", "observations", "medications", "insights"})),
        Partner("health-plan", "Your health plan (example)", "payer",
                "Let your plan cover and schedule screenings you're eligible for.",
                frozenset({"insights"})),
        Partner("lab-testing", "Lab testing partner (example)", "lab",
                "Order a recommended lab test (e.g. lipid panel, Lp(a), HbA1c).",
                frozenset({"insights", "observations"})),
    )
}


def partner_payload(profile: HealthProfile, partner: Partner) -> dict:
    payload: dict = {"partner": partner.id, "categories": sorted(partner.categories)}
    fhir_cats = partner.categories & {"conditions", "observations", "medications", "family_history"}
    if fhir_cats:
        payload["fhir_bundle"] = to_fhir_bundle(profile, set(fhir_cats))
    if "insights" in partner.categories:
        report = generate_insights(profile)
        payload["insights"] = [
            {"rule_id": i.rule_id, "level": i.level.value, "title": i.title,
             "recommendation": i.recommendation}
            for i in report.insights if i.category != "data_quality"
        ]
    return payload


def _age_bucket(age: int | None) -> int | str | None:
    if age is None:
        return None
    return "90+" if age >= 90 else age


def deidentify(profile: HealthProfile, research_id: str, today: date | None = None) -> dict:
    """HIPAA Safe Harbor-style de-identification of one profile.

    Drops names, free-text fields and exact dates (years only), caps ages at 90+,
    and keys records by a keyed pseudonym. Expert-determination review is still
    recommended before release, because rare family patterns can be identifying.
    """
    age = profile.age(today)
    birth_year = profile.birth_date.year if profile.birth_date and (age or 0) < 90 else None
    return {
        "research_id": research_id,
        "sex": profile.sex.value if profile.sex else None,
        "birth_year": birth_year,
        "age": _age_bucket(age),
        "conditions": [
            {"category": c.category, "onset_age": _age_bucket(c.onset_age)}
            for c in profile.conditions if c.category
        ],
        "observations": [
            {"code": o.code, "value": o.value, "unit": o.unit,
             "year": o.effective_date.year if o.effective_date else None}
            for o in profile.observations
        ],
        "family": [
            {"relationship": m.relationship.value, "degree": m.degree,
             "conditions": [
                 {"category": c.category, "onset_age": _age_bucket(c.onset_age)}
                 for c in m.conditions if c.category
             ]}
            for m in profile.family
        ],
    }
