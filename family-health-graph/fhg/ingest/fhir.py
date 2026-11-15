"""Import and export HL7 FHIR R4.

FHIR is how EHRs (via SMART on FHIR / patient access APIs), payers (CMS
Patient Access API), and health-data aggregators hand data over, so it is the
primary integration surface for partners.

Supported resources: Patient, Condition, Observation, MedicationStatement,
MedicationRequest, FamilyMemberHistory.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Iterable, Optional

from ..models import (
    Condition,
    FamilyMember,
    HealthProfile,
    Medication,
    Observation,
    Relationship,
    Sex,
)
from ..terminology import (
    BP_PANEL_CODES,
    LOINC,
    LOINC_TO_OBSERVATION,
    OBSERVATION_TO_LOINC,
    category_from_code,
    category_from_text,
    primary_coding,
)

ROLE_CODE_SYSTEM = "http://terminology.hl7.org/CodeSystem/v3-RoleCode"
GENDER_SYSTEM = "http://hl7.org/fhir/administrative-gender"

ROLE_CODES: dict[str, Relationship] = {
    "MTH": Relationship.MOTHER, "NMTH": Relationship.MOTHER,
    "FTH": Relationship.FATHER, "NFTH": Relationship.FATHER,
    "SIS": Relationship.SISTER, "NSIS": Relationship.SISTER,
    "BRO": Relationship.BROTHER, "NBRO": Relationship.BROTHER,
    "DAU": Relationship.DAUGHTER, "DAUC": Relationship.DAUGHTER,
    "SON": Relationship.SON, "SONC": Relationship.SON,
    "MGRMTH": Relationship.MATERNAL_GRANDMOTHER, "MGRFTH": Relationship.MATERNAL_GRANDFATHER,
    "PGRMTH": Relationship.PATERNAL_GRANDMOTHER, "PGRFTH": Relationship.PATERNAL_GRANDFATHER,
    "GRMTH": Relationship.GRANDMOTHER, "GRFTH": Relationship.GRANDFATHER,
    "MAUNT": Relationship.MATERNAL_AUNT, "MUNCLE": Relationship.MATERNAL_UNCLE,
    "PAUNT": Relationship.PATERNAL_AUNT, "PUNCLE": Relationship.PATERNAL_UNCLE,
    "AUNT": Relationship.AUNT, "UNCLE": Relationship.UNCLE,
    "HSIS": Relationship.HALF_SISTER, "HBRO": Relationship.HALF_BROTHER,
    "NIECE": Relationship.NIECE, "NEPHEW": Relationship.NEPHEW,
    "MCOUSN": Relationship.MATERNAL_COUSIN, "PCOUSN": Relationship.PATERNAL_COUSIN,
    "COUSN": Relationship.COUSIN,
}
RELATIONSHIP_TO_ROLE: dict[Relationship, str] = {
    Relationship.MOTHER: "MTH", Relationship.FATHER: "FTH",
    Relationship.SISTER: "SIS", Relationship.BROTHER: "BRO",
    Relationship.DAUGHTER: "DAUC", Relationship.SON: "SONC",
}
for _code, _rel in ROLE_CODES.items():
    RELATIONSHIP_TO_ROLE.setdefault(_rel, _code)


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _codings(concept: Optional[dict]) -> list[dict]:
    return (concept or {}).get("coding", []) or []


def _concept_text(concept: Optional[dict]) -> str:
    if not concept:
        return ""
    if concept.get("text"):
        return concept["text"]
    for c in _codings(concept):
        if c.get("display"):
            return c["display"]
    return ""


def _category(concept: Optional[dict]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (category, code, system) for a CodeableConcept."""
    first_code = first_system = None
    for coding in _codings(concept):
        code, system = coding.get("code"), coding.get("system")
        first_code = first_code or code
        first_system = first_system or system
        cat = category_from_code(system, code)
        if cat:
            return cat, code, system
    text = _concept_text(concept)
    return (category_from_text(text) if text else None), first_code, first_system


def _age_value(age: Optional[dict]) -> Optional[int]:
    if not age or age.get("value") is None:
        return None
    return int(age["value"])


def _iter_resources(bundle: dict) -> Iterable[dict]:
    if bundle.get("resourceType") == "Bundle":
        for entry in bundle.get("entry", []) or []:
            res = entry.get("resource")
            if isinstance(res, dict):
                yield res
    elif "resourceType" in bundle:
        yield bundle


def parse_fhir(bundle: dict, source: str = "fhir") -> HealthProfile:
    """Parse a FHIR R4 Bundle (or single resource) into a profile fragment."""
    if not isinstance(bundle, dict) or "resourceType" not in bundle:
        raise ValueError("Expected a FHIR resource or Bundle (missing resourceType)")

    fragment = HealthProfile()
    resources = list(_iter_resources(bundle))

    for res in resources:
        if res.get("resourceType") == "Patient":
            gender = res.get("gender")
            fragment.sex = Sex(gender) if gender in Sex._value2member_map_ else None
            fragment.birth_date = _parse_date(res.get("birthDate"))

    for res in resources:
        rtype = res.get("resourceType")
        if rtype == "Condition":
            fragment.conditions.append(_parse_condition(res, fragment.birth_date, source))
        elif rtype == "Observation":
            fragment.observations.extend(_parse_observation(res, source))
        elif rtype in ("MedicationStatement", "MedicationRequest"):
            name = _concept_text(res.get("medicationCodeableConcept"))
            if name:
                fragment.medications.append(
                    Medication(name=name, status=res.get("status", "active"), source=source)
                )
        elif rtype == "FamilyMemberHistory":
            fragment.family.append(_parse_family_member(res, source))

    return fragment


def _parse_condition(res: dict, birth_date: Optional[date], source: str) -> Condition:
    category, code, system = _category(res.get("code"))
    onset_date = _parse_date(res.get("onsetDateTime"))
    onset_age = _age_value(res.get("onsetAge"))
    if onset_age is None and onset_date and birth_date:
        onset_age = onset_date.year - birth_date.year - (
            (onset_date.month, onset_date.day) < (birth_date.month, birth_date.day)
        )
    status = (_codings(res.get("clinicalStatus")) or [{}])[0].get("code", "unknown")
    return Condition(
        name=_concept_text(res.get("code")) or (code or "Unknown condition"),
        category=category, code=code, code_system=system,
        onset_age=onset_age, onset_date=onset_date, status=status, source=source,
    )


def _parse_observation(res: dict, source: str) -> list[Observation]:
    effective = _parse_date(res.get("effectiveDateTime") or res.get("issued"))
    codes = {c.get("code") for c in _codings(res.get("code")) if c.get("system") in (LOINC, None)}
    out: list[Observation] = []

    if codes & BP_PANEL_CODES:
        for comp in res.get("component", []) or []:
            for c in _codings(comp.get("code")):
                canonical = LOINC_TO_OBSERVATION.get(c.get("code", ""))
                vq = comp.get("valueQuantity") or {}
                if canonical and vq.get("value") is not None:
                    out.append(Observation(code=canonical, value=float(vq["value"]),
                                           unit=vq.get("unit", ""), effective_date=effective,
                                           source=source))
        return out

    vq = res.get("valueQuantity") or {}
    if vq.get("value") is None:
        return out
    for code in codes:
        canonical = LOINC_TO_OBSERVATION.get(code or "")
        if canonical:
            out.append(Observation(code=canonical, value=float(vq["value"]),
                                   unit=vq.get("unit", ""), effective_date=effective,
                                   source=source))
            break
    return out


def _parse_family_member(res: dict, source: str) -> FamilyMember:
    relationship = Relationship.OTHER
    for c in _codings(res.get("relationship")):
        if c.get("code") in ROLE_CODES:
            relationship = ROLE_CODES[c["code"]]
            break
    else:
        from .text import parse_relationship  # local import avoids a cycle

        relationship = parse_relationship(_concept_text(res.get("relationship"))) or Relationship.OTHER

    sex = None
    for c in _codings(res.get("sex")):
        if c.get("code") in Sex._value2member_map_:
            sex = Sex(c["code"])

    deceased = res.get("deceasedBoolean")
    if deceased is None and any(k.startswith("deceased") for k in res):
        deceased = True

    age = _age_value(res.get("ageAge")) or _age_value(res.get("deceasedAge"))
    member = FamilyMember(
        relationship=relationship, name=res.get("name"), sex=sex,
        deceased=deceased, age=age, source=source,
    )
    for cond in res.get("condition", []) or []:
        category, code, system = _category(cond.get("code"))
        member.conditions.append(Condition(
            name=_concept_text(cond.get("code")) or (code or "Unknown condition"),
            category=category, code=code, code_system=system,
            onset_age=_age_value(cond.get("onsetAge")), source=source,
        ))
    return member


# --- export ------------------------------------------------------------------

def _coded(category: Optional[str], name: str, code: Optional[str], system: Optional[str]) -> dict:
    codings = []
    if code and system:
        codings.append({"system": system, "code": code})
    elif category and (pc := primary_coding(category)):
        codings.append({"system": pc[0], "code": pc[1]})
    concept: dict[str, Any] = {"text": name}
    if codings:
        concept["coding"] = codings
    return concept


def _age(value: int) -> dict:
    return {"value": value, "unit": "a", "system": "http://unitsofmeasure.org", "code": "a"}


def to_fhir_bundle(profile: HealthProfile, categories: Optional[set[str]] = None) -> dict:
    """Export a profile as a FHIR R4 collection Bundle.

    ``categories`` limits the export (minimum-necessary sharing): any of
    ``conditions``, ``observations``, ``medications``, ``family_history``.
    """
    categories = categories or {"conditions", "observations", "medications", "family_history"}
    patient_ref = "urn:uuid:patient"
    entries: list[dict] = []

    patient: dict[str, Any] = {"resourceType": "Patient"}
    if profile.sex:
        patient["gender"] = profile.sex.value
    if profile.birth_date:
        patient["birthDate"] = profile.birth_date.isoformat()
    entries.append({"fullUrl": patient_ref, "resource": patient})
    subject = {"reference": patient_ref}

    if "conditions" in categories:
        for c in profile.conditions:
            res: dict[str, Any] = {
                "resourceType": "Condition", "subject": subject,
                "code": _coded(c.category, c.name, c.code, c.code_system),
            }
            if c.onset_date:
                res["onsetDateTime"] = c.onset_date.isoformat()
            elif c.onset_age is not None:
                res["onsetAge"] = _age(c.onset_age)
            entries.append({"resource": res})

    if "observations" in categories:
        for o in profile.observations:
            loinc = OBSERVATION_TO_LOINC.get(o.code)
            if not loinc:
                continue
            res = {
                "resourceType": "Observation", "status": "final", "subject": subject,
                "code": {"coding": [{"system": LOINC, "code": loinc[0], "display": loinc[1]}]},
                "valueQuantity": {"value": o.value, "unit": o.unit},
            }
            if o.effective_date:
                res["effectiveDateTime"] = o.effective_date.isoformat()
            entries.append({"resource": res})

    if "medications" in categories:
        for m in profile.medications:
            entries.append({"resource": {
                "resourceType": "MedicationStatement", "status": m.status, "subject": subject,
                "medicationCodeableConcept": {"text": m.name},
            }})

    if "family_history" in categories:
        for fm in profile.family:
            role = RELATIONSHIP_TO_ROLE.get(fm.relationship)
            res = {
                "resourceType": "FamilyMemberHistory", "status": "completed", "patient": subject,
                "relationship": (
                    {"coding": [{"system": ROLE_CODE_SYSTEM, "code": role}], "text": fm.label}
                    if role else {"text": fm.label}
                ),
            }
            if fm.sex:
                res["sex"] = {"coding": [{"system": GENDER_SYSTEM, "code": fm.sex.value}]}
            if fm.deceased is not None:
                res["deceasedBoolean"] = fm.deceased
            if fm.age is not None and not fm.deceased:
                res["ageAge"] = _age(fm.age)
            conds = []
            for c in fm.conditions:
                entry: dict[str, Any] = {"code": _coded(c.category, c.name, c.code, c.code_system)}
                if c.onset_age is not None:
                    entry["onsetAge"] = _age(c.onset_age)
                conds.append(entry)
            if conds:
                res["condition"] = conds
            entries.append({"resource": res})

    return {
        "resourceType": "Bundle", "type": "collection",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "entry": entries,
    }
