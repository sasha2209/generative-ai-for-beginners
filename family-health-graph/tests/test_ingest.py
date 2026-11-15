import json
from pathlib import Path

import pytest

from fhg.ingest import (
    CsvImportError,
    parse_family_csv,
    parse_family_history_text,
    parse_fhir,
    parse_relationship,
    to_fhir_bundle,
)
from fhg.models import Relationship
from fhg.terminology import ICD10, SNOMED, category_from_code, category_from_text

SAMPLES = Path(__file__).parent.parent / "fhg" / "sample_data"


def rels(profile):
    return {m.relationship: m for m in profile.family}


# --- terminology -----------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Breast Cancer", "breast_cancer"),
    ("colon cancer", "colorectal_cancer"),
    ("heart attack", "coronary_artery_disease"),
    ("Type 1 diabetes", "type_1_diabetes"),
    ("diabetes", "type_2_diabetes"),
    ("congenital heart disease", "congenital_heart_disease"),
    ("BRCA2 mutation", "hboc_variant"),
    ("some cancer", "cancer_unspecified"),
    ("asthma", None),
])
def test_category_from_text(text, expected):
    assert category_from_text(text) == expected


def test_icd10_longest_prefix_wins():
    assert category_from_code(ICD10, "E78.01") == "familial_hypercholesterolemia"
    assert category_from_code(ICD10, "E78.00") == "hyperlipidemia"
    assert category_from_code(ICD10, "c50.911") == "breast_cancer"
    assert category_from_code(SNOMED, "22298006") == "coronary_artery_disease"
    assert category_from_code(SNOMED, "000") is None


# --- free text -------------------------------------------------------------------

def test_text_sample():
    p = parse_family_history_text((SAMPLES / "family_history.txt").read_text())
    r = rels(p)
    assert r[Relationship.MOTHER].conditions[0].category == "breast_cancer"
    assert r[Relationship.MOTHER].conditions[0].onset_age == 46
    aunt = r[Relationship.MATERNAL_AUNT].conditions[0]
    assert (aunt.category, aunt.onset_age, aunt.age_estimated) == ("ovarian_cancer", 58, True)
    dad = {c.category: c for c in r[Relationship.FATHER].conditions}
    assert dad["coronary_artery_disease"].onset_age == 51
    assert dad["type_2_diabetes"].onset_age is None
    grandpa = r[Relationship.PATERNAL_GRANDFATHER]
    assert grandpa.deceased and grandpa.conditions[0].onset_age == 72
    assert r[Relationship.MATERNAL_GRANDMOTHER].conditions[0].category == "cancer_unspecified"
    assert [c.category for c in p.conditions] == ["hyperlipidemia"]


def test_text_multiple_relatives_and_shared_noun():
    p = parse_family_history_text("My mother and sister both had breast and ovarian cancer.")
    r = rels(p)
    for rel in (Relationship.MOTHER, Relationship.SISTER):
        assert {c.category for c in r[rel].conditions} == {"breast_cancer", "ovarian_cancer"}


def test_text_side_phrase_and_distinct_siblings():
    p = parse_family_history_text(
        "My aunt on my dad's side had colon cancer at 44. "
        "My sister had melanoma. My other sister had breast cancer at 39."
    )
    assert any(m.relationship == Relationship.PATERNAL_AUNT for m in p.family)
    assert Relationship.FATHER not in rels(p)  # "dad's side" is not the father
    sisters = [m for m in p.family if m.relationship == Relationship.SISTER]
    assert len(sisters) == 2


def test_text_ignores_sentences_without_relatives():
    p = parse_family_history_text("Cancer runs in families. We had a picnic.")
    assert not p.family and not p.conditions


@pytest.mark.parametrize("label,expected", [
    ("Maternal Aunt", Relationship.MATERNAL_AUNT),
    ("mom's mom", Relationship.MATERNAL_GRANDMOTHER),
    ("Dad's brother", Relationship.PATERNAL_UNCLE),
    ("half-brother", Relationship.HALF_BROTHER),
    ("uncle on my mother's side", Relationship.MATERNAL_UNCLE),
    ("neighbour", None),
])
def test_parse_relationship(label, expected):
    assert parse_relationship(label) == expected


# --- FHIR -------------------------------------------------------------------------

def test_fhir_sample():
    p = parse_fhir(json.loads((SAMPLES / "fhir_bundle.json").read_text()))
    assert p.sex.value == "female" and p.birth_date.isoformat() == "1984-05-02"
    assert p.conditions[0].category == "hyperlipidemia"
    assert p.conditions[0].onset_age == 38  # derived from onsetDateTime and birthDate
    codes = {o.code: o.value for o in p.observations}
    assert codes == {"ldl_cholesterol": 172, "hba1c": 5.9, "bmi": 27.4,
                     "systolic_bp": 134, "diastolic_bp": 86}
    r = rels(p)
    assert r[Relationship.MATERNAL_AUNT].conditions[0].category == "ovarian_cancer"  # text-only code
    assert r[Relationship.PATERNAL_GRANDFATHER].deceased is True
    assert r[Relationship.SISTER].age == 39


def test_fhir_rejects_non_fhir():
    with pytest.raises(ValueError):
        parse_fhir({"hello": "world"})


def test_fhir_round_trip():
    original = parse_fhir(json.loads((SAMPLES / "fhir_bundle.json").read_text()))
    again = parse_fhir(to_fhir_bundle(original))
    assert again.sex == original.sex and again.birth_date == original.birth_date
    assert [(c.category, c.onset_age) for c in again.conditions] == \
           [(c.category, c.onset_age) for c in original.conditions]
    assert sorted((o.code, o.value) for o in again.observations) == \
           sorted((o.code, o.value) for o in original.observations)
    summarize = lambda p: sorted(
        (m.relationship.value, tuple((c.category, c.onset_age) for c in m.conditions)) for m in p.family
    )
    assert summarize(again) == summarize(original)


def test_fhir_export_respects_categories():
    p = parse_fhir(json.loads((SAMPLES / "fhir_bundle.json").read_text()))
    types = {e["resource"]["resourceType"] for e in to_fhir_bundle(p, {"family_history"})["entry"]}
    assert types == {"Patient", "FamilyMemberHistory"}


# --- CSV --------------------------------------------------------------------------

def test_csv_sample():
    p, warnings = parse_family_csv((SAMPLES / "family.csv").read_text())
    assert warnings == []
    r = rels(p)
    assert len(r[Relationship.FATHER].conditions) == 2
    assert r[Relationship.MATERNAL_AUNT].name == "Ruth" and r[Relationship.MATERNAL_AUNT].deceased
    assert r[Relationship.BROTHER].conditions == []


def test_csv_warnings_and_errors():
    p, warnings = parse_family_csv(
        "relationship,condition,age_at_diagnosis\nneighbour,flu,\nmother,weird thing,abc\nself,diabetes,40\n"
    )
    assert len(warnings) == 3
    assert p.conditions[0].category == "type_2_diabetes"
    with pytest.raises(CsvImportError):
        parse_family_csv("name,age\nx,1\n")
