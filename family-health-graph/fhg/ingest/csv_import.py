"""Import family history from a spreadsheet export (CSV).

Expected columns (header row required, case-insensitive; only the first two
are mandatory)::

    relationship,condition,age_at_diagnosis,sex,deceased,name

One row per relative-condition pair. Rows with the same relationship and name
are grouped into one relative. A row with relationship ``self`` adds a
condition to the user's own record.
"""
from __future__ import annotations

import csv
import io

from ..models import Condition, FamilyMember, HealthProfile, Sex
from ..terminology import category_from_text
from .text import parse_relationship


class CsvImportError(ValueError):
    pass


def _truthy(value: str) -> bool | None:
    v = (value or "").strip().lower()
    if v in ("y", "yes", "true", "1", "deceased"):
        return True
    if v in ("n", "no", "false", "0", "living", "alive"):
        return False
    return None


def parse_family_csv(content: str) -> tuple[HealthProfile, list[str]]:
    """Return the parsed fragment and a list of per-row warnings."""
    reader = csv.DictReader(io.StringIO(content.strip()))
    if not reader.fieldnames:
        raise CsvImportError("CSV is empty")
    fields = {f.strip().lower(): f for f in reader.fieldnames}
    if "relationship" not in fields or "condition" not in fields:
        raise CsvImportError("CSV must have 'relationship' and 'condition' columns")

    def col(row: dict, name: str) -> str:
        key = fields.get(name)
        return (row.get(key) or "").strip() if key else ""

    fragment = HealthProfile()
    members: dict[tuple, FamilyMember] = {}
    warnings: list[str] = []

    for line_no, row in enumerate(reader, start=2):
        rel_text, cond_text = col(row, "relationship"), col(row, "condition")
        if not rel_text:
            warnings.append(f"line {line_no}: missing relationship, skipped")
            continue

        is_self = rel_text.lower() in ("self", "me", "patient")
        relationship = None if is_self else parse_relationship(rel_text)
        if not is_self and relationship is None:
            warnings.append(f"line {line_no}: relationship '{rel_text}' not recognised, skipped")
            continue

        age_text = col(row, "age_at_diagnosis")
        onset_age = int(age_text) if age_text.isdigit() else None
        if age_text and onset_age is None:
            warnings.append(f"line {line_no}: could not read age '{age_text}'")

        condition = None
        if cond_text:
            condition = Condition(name=cond_text, category=category_from_text(cond_text),
                                  onset_age=onset_age, source="csv")
            if condition.category is None:
                warnings.append(f"line {line_no}: condition '{cond_text}' not recognised; stored as text")

        if is_self:
            if condition:
                fragment.conditions.append(condition)
            continue

        name = col(row, "name") or None
        key = (relationship, (name or "").lower())
        member = members.get(key)
        if member is None:
            sex_text = col(row, "sex").lower()
            member = FamilyMember(
                relationship=relationship, name=name,
                sex=Sex(sex_text) if sex_text in Sex._value2member_map_ else None,
                deceased=_truthy(col(row, "deceased")), source="csv",
            )
            members[key] = member
        if condition and not any(
            c.category == condition.category and c.name.lower() == condition.name.lower()
            for c in member.conditions
        ):
            member.conditions.append(condition)

    fragment.family = list(members.values())
    return fragment, warnings
