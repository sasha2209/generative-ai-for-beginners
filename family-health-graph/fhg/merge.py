"""Merge an ingested fragment into a user's longitudinal profile.

Records arrive from many sources (EHR exports, the user typing, a relative's
spreadsheet). Merging is additive and de-duplicating; it never deletes.
"""
from __future__ import annotations

from .models import (
    SINGULAR_RELATIONSHIPS,
    Condition,
    FamilyMember,
    HealthProfile,
)


def _condition_key(c: Condition) -> str:
    return c.category or c.name.strip().lower()


def _merge_conditions(existing: list[Condition], incoming: list[Condition]) -> int:
    added = 0
    by_key = {_condition_key(c): c for c in existing}
    for new in incoming:
        old = by_key.get(_condition_key(new))
        if old is None:
            existing.append(new)
            by_key[_condition_key(new)] = new
            added += 1
            continue
        # Prefer known, exact, earlier onset information.
        if new.onset_age is not None and (
            old.onset_age is None
            or (old.age_estimated and not new.age_estimated)
            or (new.age_estimated == old.age_estimated and new.onset_age < old.onset_age)
        ):
            old.onset_age, old.age_estimated = new.onset_age, new.age_estimated
        old.onset_date = old.onset_date or new.onset_date
        old.code = old.code or new.code
        old.code_system = old.code_system or new.code_system
        if new.status != "unknown":
            old.status = new.status
    return added


def _find_match(family: list[FamilyMember], new: FamilyMember) -> FamilyMember | None:
    same_rel = [m for m in family if m.relationship == new.relationship]
    if not same_rel:
        return None
    if new.relationship in SINGULAR_RELATIONSHIPS:
        return same_rel[0]
    if new.name:
        for m in same_rel:
            if m.name and m.name.strip().lower() == new.name.strip().lower():
                return m
        return None
    # Unnamed sibling/aunt/etc.: only merge when it is clearly the same person,
    # i.e. an unnamed relative of that type who shares a condition.
    new_keys = {_condition_key(c) for c in new.conditions}
    for m in same_rel:
        if not m.name and new_keys & {_condition_key(c) for c in m.conditions}:
            return m
    return None


def merge_into(profile: HealthProfile, fragment: HealthProfile) -> dict:
    stats = {"conditions": 0, "observations": 0, "medications": 0,
             "relatives_added": 0, "relative_conditions": 0}

    if fragment.sex and not profile.sex:
        profile.sex = fragment.sex
    if fragment.birth_date and not profile.birth_date:
        profile.birth_date = fragment.birth_date

    stats["conditions"] = _merge_conditions(profile.conditions, fragment.conditions)

    seen_obs = {(o.code, o.value, o.effective_date) for o in profile.observations}
    for o in fragment.observations:
        if (o.code, o.value, o.effective_date) not in seen_obs:
            profile.observations.append(o)
            seen_obs.add((o.code, o.value, o.effective_date))
            stats["observations"] += 1

    seen_meds = {m.name.strip().lower() for m in profile.medications}
    for m in fragment.medications:
        if m.name.strip().lower() not in seen_meds:
            profile.medications.append(m)
            seen_meds.add(m.name.strip().lower())
            stats["medications"] += 1

    for new in fragment.family:
        match = _find_match(profile.family, new)
        if match is None:
            profile.family.append(new)
            stats["relatives_added"] += 1
            stats["relative_conditions"] += len(new.conditions)
            continue
        match.name = match.name or new.name
        match.sex = match.sex or new.sex
        match.deceased = match.deceased if match.deceased is not None else new.deceased
        match.age = match.age if match.age is not None else new.age
        stats["relative_conditions"] += _merge_conditions(match.conditions, new.conditions)

    profile.touch()
    return stats
