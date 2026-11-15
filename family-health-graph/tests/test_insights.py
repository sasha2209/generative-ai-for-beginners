from datetime import date

from fhg.insights import generate_insights, summarize
from fhg.merge import merge_into
from fhg.models import Condition, FamilyMember, HealthProfile, Level, Observation, Relationship, Sex
from fhg.terminology import category_from_text


def rel(relationship, *conds, **kw):
    """rel(Relationship.MOTHER, ("breast cancer", 45))"""
    return FamilyMember(relationship=relationship, conditions=[
        Condition(name=n, category=category_from_text(n), onset_age=a) for n, a in conds
    ], **kw)


def profile(*family, sex=Sex.FEMALE, birth=date(1980, 1, 1), obs=(), conds=()):
    return HealthProfile(
        sex=sex, birth_date=birth, family=list(family),
        observations=[Observation(code=c, value=v, unit=u) for c, v, u in obs],
        conditions=[Condition(name=n, category=category_from_text(n), onset_age=a) for n, a in conds],
    )


def by_rule(p):
    return {i.rule_id: i for i in generate_insights(p).insights}


def test_empty_profile_only_prompts_for_data():
    assert set(by_rule(HealthProfile())) == {"record_gaps"}


# --- HBOC --------------------------------------------------------------------------

def test_hboc_early_breast_cancer():
    i = by_rule(profile(rel(Relationship.MOTHER, ("breast cancer", 45))))["hboc_family_pattern"]
    assert i.level == Level.MODERATE
    assert "Mother: Breast cancer (diagnosed at 45)" in i.evidence


def test_hboc_late_single_breast_cancer_does_not_trigger():
    assert "hboc_family_pattern" not in by_rule(profile(rel(Relationship.MOTHER, ("breast cancer", 68))))


def test_hboc_two_same_side_relatives():
    p = profile(rel(Relationship.PATERNAL_AUNT, ("breast cancer", 62)),
                rel(Relationship.PATERNAL_GRANDMOTHER, ("breast cancer", 70)))
    assert "paternal side" in by_rule(p)["hboc_family_pattern"].summary


def test_hboc_different_sides_do_not_combine():
    p = profile(rel(Relationship.PATERNAL_AUNT, ("breast cancer", 62)),
                rel(Relationship.MATERNAL_GRANDMOTHER, ("breast cancer", 70)))
    assert "hboc_family_pattern" not in by_rule(p)


def test_hboc_male_breast_and_known_variant():
    p = profile(rel(Relationship.UNCLE, ("breast cancer", 70)))
    assert "male breast cancer" in by_rule(p)["hboc_family_pattern"].summary
    p = profile(rel(Relationship.COUSIN, ("BRCA1 mutation", None)))
    assert by_rule(p)["hboc_family_pattern"].level == Level.HIGH


# --- colorectal ------------------------------------------------------------------------

def test_crc_start_age_ten_years_before_youngest():
    p = profile(rel(Relationship.FATHER, ("colon cancer", 47)), birth=date.today().replace(year=date.today().year - 30))
    i = by_rule(p)["colorectal_family_history"]
    assert "around age 37" in i.recommendation
    assert i.level == Level.HIGH  # 47 < 50 also points to possible Lynch syndrome
    assert "Lynch" in i.recommendation


def test_crc_single_older_fdr():
    p = profile(rel(Relationship.MOTHER, ("colon cancer", 66)), birth=date.today().replace(year=date.today().year - 30))
    i = by_rule(p)["colorectal_family_history"]
    assert "age 40 rather than 45" in i.recommendation
    assert i.level == Level.MODERATE


def test_crc_second_degree_late_is_ignored():
    assert "colorectal_family_history" not in by_rule(
        profile(rel(Relationship.PATERNAL_GRANDFATHER, ("colon cancer", 72))))


def test_lynch_pattern_three_relatives():
    p = profile(rel(Relationship.MATERNAL_AUNT, ("uterine cancer", 55)),
                rel(Relationship.MATERNAL_GRANDFATHER, ("stomach cancer", 70)),
                rel(Relationship.MATERNAL_UNCLE, ("colon cancer", 61)))
    assert "Lynch" in by_rule(p)["colorectal_family_history"].recommendation


# --- cardiovascular & metabolic -----------------------------------------------------------

def test_premature_ascvd_sex_specific_thresholds():
    assert "premature_ascvd_family_history" in by_rule(profile(rel(Relationship.FATHER, ("heart attack", 54))))
    assert "premature_ascvd_family_history" not in by_rule(profile(rel(Relationship.FATHER, ("heart attack", 58))))
    assert "premature_ascvd_family_history" in by_rule(profile(rel(Relationship.MOTHER, ("stroke", 60))))


def test_premature_ascvd_escalates_with_high_ldl():
    p = profile(rel(Relationship.BROTHER, ("heart attack", 44)), obs=[("ldl_cholesterol", 4.5, "mmol/L")])
    assert by_rule(p)["premature_ascvd_family_history"].level == Level.HIGH  # 4.5 mmol/L = 174 mg/dL


def test_fh_from_ldl():
    i = by_rule(profile(obs=[("ldl_cholesterol", 205, "mg/dL")]))["familial_hypercholesterolemia"]
    assert i.level == Level.HIGH and "190" in i.summary


def test_diabetes_levels():
    assert by_rule(profile(obs=[("hba1c", 6.8, "%")]))["diabetes_risk"].level == Level.HIGH
    assert by_rule(profile(obs=[("hba1c", 6.0, "%")]))["diabetes_risk"].level == Level.MODERATE
    p = profile(rel(Relationship.MOTHER, ("type 2 diabetes", 50)), obs=[("bmi", 29, "")])
    assert "BMI is 25 or higher" in by_rule(p)["diabetes_risk"].summary
    p = profile(rel(Relationship.MOTHER, ("type 2 diabetes", 50)), conds=[("type 2 diabetes", 40)])
    assert "diabetes_risk" not in by_rule(p)


def test_prostate_only_for_non_female():
    fam = rel(Relationship.FATHER, ("prostate cancer", 60))
    assert "prostate_family_history" in by_rule(profile(fam, sex=Sex.MALE))
    assert "prostate_family_history" not in by_rule(profile(fam, sex=Sex.FEMALE))


def test_blood_pressure_bands():
    assert by_rule(profile(obs=[("systolic_bp", 185, "mmHg"), ("diastolic_bp", 100, "mmHg")]))["blood_pressure"].level == Level.HIGH
    assert by_rule(profile(obs=[("systolic_bp", 142, "mmHg"), ("diastolic_bp", 85, "mmHg")]))["blood_pressure"].level == Level.MODERATE
    assert "blood_pressure" not in by_rule(profile(obs=[("systolic_bp", 118, "mmHg"), ("diastolic_bp", 76, "mmHg")]))


def test_malignant_hyperthermia_any_relative_is_high():
    i = by_rule(profile(rel(Relationship.COUSIN, ("bad reaction to anesthesia", None))))["malignant_hyperthermia"]
    assert i.level == Level.HIGH


# --- report-level behaviour -------------------------------------------------------------------

def test_report_sorted_and_evidence_has_no_names():
    p = profile(rel(Relationship.MATERNAL_AUNT, ("ovarian cancer", 50), name="Ruth"),
                rel(Relationship.COUSIN, ("malignant hyperthermia", None), name="Bob"),
                obs=[("systolic_bp", 132, "mmHg"), ("diastolic_bp", 70, "mmHg")])
    report = generate_insights(p)
    order = {"high": 0, "moderate": 1, "info": 2}
    levels = [order[i.level.value] for i in report.insights]
    assert levels == sorted(levels)
    blob = " ".join(e for i in report.insights for e in i.evidence)
    assert "Ruth" not in blob and "Bob" not in blob


def test_every_clinical_insight_cites_a_reference():
    p = profile(rel(Relationship.MOTHER, ("breast cancer", 40), ("colon cancer", 45), ("stroke", 50)),
                rel(Relationship.FATHER, ("prostate cancer", 55), ("type 2 diabetes", 50)),
                sex=Sex.MALE, obs=[("ldl_cholesterol", 200, "mg/dL"), ("hba1c", 6.1, "%")])
    for i in generate_insights(p).insights:
        assert i.references, i.rule_id


def test_template_summary_without_llm():
    out = summarize(generate_insights(profile(rel(Relationship.MOTHER, ("breast cancer", 45)))), allow_llm=False)
    assert out["generated_by"] == "template" and "hereditary cancer" in out["text"]


def test_llm_summary_uses_client_and_only_derived_data():
    class Block:
        type, text = "text", "Plain summary."

    class FakeMessages:
        def create(self, **kw):
            self.kw = kw
            return type("R", (), {"content": [Block()]})()

    client = type("C", (), {"messages": FakeMessages()})()
    p = profile(rel(Relationship.MOTHER, ("breast cancer", 45), name="Jane Doe"))
    out = summarize(generate_insights(p), allow_llm=True, client=client)
    assert out["text"] == "Plain summary."
    sent = client.messages.kw["messages"][0]["content"]
    assert "Jane" not in sent and "1980" not in sent


# --- merge ---------------------------------------------------------------------------------

def test_merge_deduplicates_and_fills_ages():
    base = profile(rel(Relationship.MOTHER, ("breast cancer", None)))
    merge_into(base, profile(rel(Relationship.MOTHER, ("breast cancer", 44), ("hypertension", 60))))
    mother = base.family[0]
    assert len(base.family) == 1
    assert {c.category: c.onset_age for c in mother.conditions} == {"breast_cancer": 44, "hypertension": 60}


def test_merge_keeps_unnamed_distinct_siblings():
    base = profile(rel(Relationship.SISTER, ("melanoma", 30)))
    stats = merge_into(base, profile(rel(Relationship.SISTER, ("asthma", 10))))
    assert stats["relatives_added"] == 1 and len(base.family) == 2
