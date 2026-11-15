"""Family-history-aware insight rules.

Each rule is a pure function ``HealthProfile -> Insight | None``. Rules are
deliberately transparent: every insight lists the exact facts that triggered it
and the published guidance it is based on, so a user (or their clinician) can
check the reasoning. Thresholds are simplified summaries of the cited
guidance; they flag "worth discussing", they do not diagnose.

Clinical content must be reviewed by qualified clinicians and genetic
counselors before any production use, and re-reviewed when guidelines change.
"""
from __future__ import annotations

from typing import Callable, Optional

from ..models import Condition, FamilyMember, HealthProfile, Insight, Level, Reference
from ..terminology import ldl_mg_dl

Rule = Callable[[HealthProfile], Optional[Insight]]

REF_USPSTF_BRCA = Reference(
    title="USPSTF (2019): BRCA-Related Cancer: Risk Assessment, Genetic Counseling, and Genetic Testing",
    url="https://www.uspreventiveservicestaskforce.org/uspstf/recommendation/brca-related-cancer-risk-assessment-genetic-counseling-and-genetic-testing",
)
REF_NCCN = Reference(
    title="NCCN Guidelines: Genetic/Familial High-Risk Assessment (Breast, Ovarian, Pancreatic, Prostate; Colorectal)",
    url="https://www.nccn.org/guidelines/category_2",
)
REF_USMSTF_CRC = Reference(
    title="US Multi-Society Task Force (2017): Colorectal Cancer Screening Recommendations",
    url="https://pubmed.ncbi.nlm.nih.gov/28555630/",
)
REF_USPSTF_CRC = Reference(
    title="USPSTF (2021): Colorectal Cancer Screening",
    url="https://www.uspreventiveservicestaskforce.org/uspstf/recommendation/colorectal-cancer-screening",
)
REF_ACC_AHA_CHOL = Reference(
    title="2018 AHA/ACC Guideline on the Management of Blood Cholesterol",
    url="https://www.ahajournals.org/doi/10.1161/CIR.0000000000000625",
)
REF_ADA = Reference(
    title="ADA Standards of Care in Diabetes: Diagnosis and Classification / Screening",
    url="https://professional.diabetes.org/standards-of-care",
)
REF_ACS_PROSTATE = Reference(
    title="American Cancer Society: Recommendations for Prostate Cancer Early Detection",
    url="https://www.cancer.org/cancer/types/prostate-cancer/detection-diagnosis-staging/acs-recommendations.html",
)
REF_MHAUS = Reference(
    title="Malignant Hyperthermia Association of the United States (MHAUS)",
    url="https://www.mhaus.org/",
)
REF_ACC_AHA_BP = Reference(
    title="2017 ACC/AHA Guideline for High Blood Pressure in Adults",
    url="https://www.ahajournals.org/doi/10.1161/HYP.0000000000000065",
)
REF_SURGEON_GENERAL = Reference(
    title="U.S. Surgeon General's My Family Health Portrait",
    url="https://phgkb.cdc.gov/FHH/html/index.html",
)


def describe(member: FamilyMember, cond: Condition) -> str:
    if cond.onset_age is None:
        age = "age at diagnosis unknown"
    else:
        age = f"diagnosed at {'about ' if cond.age_estimated else ''}{cond.onset_age}"
    return f"{member.label}: {cond.display_name} ({age})"


def describe_self(cond: Condition) -> str:
    age = f", diagnosed at {cond.onset_age}" if cond.onset_age is not None else ""
    return f"You: {cond.display_name}{age}"


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


# --- hereditary breast & ovarian cancer (HBOC) --------------------------------

def hereditary_breast_ovarian(p: HealthProfile) -> Optional[Insight]:
    evidence, reasons = [], []
    level = Level.MODERATE

    for m, c in p.affected({"hboc_variant"}, max_degree=3):
        evidence.append(describe(m, c))
        reasons.append("a relative has a known BRCA1/BRCA2 variant")
        level = Level.HIGH

    for m, c in p.affected({"breast_cancer"}, max_degree=2):
        if c.onset_age is not None and c.onset_age <= 50:
            evidence.append(describe(m, c))
            reasons.append("breast cancer at or before age 50 in a close relative")
        if m.effective_sex == "male":
            evidence.append(describe(m, c))
            reasons.append("male breast cancer in the family")

    for m, c in p.affected({"ovarian_cancer"}, max_degree=2):
        evidence.append(describe(m, c))
        reasons.append("ovarian cancer in a close relative (any age)")

    for m, c in p.affected({"pancreatic_cancer"}, max_degree=2):
        evidence.append(describe(m, c))
        reasons.append("pancreatic cancer in a close relative (any age)")

    for side in ("maternal", "paternal"):
        same_side = {
            m.id: (m, c) for m, c in p.affected({"breast_cancer"}, max_degree=3)
            if side in m.lineage_sides
        }
        if len(same_side) >= 2:
            evidence.extend(describe(m, c) for m, c in same_side.values())
            reasons.append(f"two or more relatives with breast cancer on your {side} side")

    for c in p.own_conditions({"breast_cancer"}):
        if c.onset_age is not None and c.onset_age <= 50:
            evidence.append(describe_self(c))
            reasons.append("your own breast cancer diagnosis at or before 50")
    for c in p.own_conditions({"ovarian_cancer", "pancreatic_cancer"}):
        evidence.append(describe_self(c))
        reasons.append(f"your own {c.display_name.lower()} diagnosis")

    if not reasons:
        return None

    return Insight(
        rule_id="hboc_family_pattern",
        category="hereditary_cancer",
        level=level,
        title="Family pattern worth a hereditary cancer risk assessment",
        summary=(
            "Your family history includes " + "; ".join(_dedupe(reasons)) + ". Patterns like this "
            "are the ones guidelines use to decide who should be offered genetic counseling for "
            "inherited cancer risk (for example BRCA1/BRCA2). It does not mean you have a variant."
        ),
        evidence=_dedupe(evidence),
        recommendation=(
            "Ask your clinician about a formal familial risk assessment and, if appropriate, "
            "referral to a genetic counselor. If a relative has already had genetic testing, "
            "ask for a copy of their result: it makes your own testing far more informative. "
            "This applies to people of any sex; inherited variants also affect prostate, "
            "pancreatic and male breast cancer risk."
        ),
        references=[REF_USPSTF_BRCA, REF_NCCN],
    )


# --- colorectal cancer & Lynch syndrome ---------------------------------------

LYNCH_CANCERS = {"colorectal_cancer", "endometrial_cancer", "ovarian_cancer", "stomach_cancer"}


def colorectal_family_history(p: HealthProfile) -> Optional[Insight]:
    fdr = p.affected({"colorectal_cancer"}, max_degree=1)
    known_lynch = p.affected({"lynch_syndrome"}, max_degree=3)
    early = [
        (m, c) for m, c in p.affected({"colorectal_cancer", "endometrial_cancer"}, max_degree=2)
        if c.onset_age is not None and c.onset_age < 50
    ]
    lynch_relatives = {m.id for m, _ in p.affected(LYNCH_CANCERS, max_degree=2)}

    genetic = bool(known_lynch or early or len(lynch_relatives) >= 3)
    if not fdr and not genetic:
        return None

    evidence = [describe(m, c) for m, c in fdr + known_lynch + early]
    parts, recs = [], []
    level = Level.MODERATE

    if fdr:
        ages = [c.onset_age for _, c in fdr if c.onset_age is not None]
        higher = len({m.id for m, _ in fdr}) >= 2 or any(a < 60 for a in ages)
        start = 40
        if ages and higher:
            start = min(40, min(ages) - 10)
        parts.append("a parent, sibling or child has had colorectal cancer")
        if higher:
            recs.append(
                f"Guidelines for this pattern suggest colonoscopy starting around age {start} "
                "(age 40, or 10 years before the youngest affected relative's diagnosis, whichever "
                "is earlier) and repeating about every 5 years."
            )
        else:
            recs.append(
                "Guidelines for this pattern suggest starting screening at age 40 rather than 45."
            )
        if any(c.onset_age is None for _, c in fdr):
            recs.append(
                "At least one relative's age at diagnosis is unknown; if it was before 60, "
                "screening may need to start earlier and be more frequent."
            )
        age = p.age()
        if age is not None and age >= start:
            level = Level.HIGH
            recs.append(
                f"You are {age}, so if you haven't been screened yet this is worth raising now."
            )

    if genetic:
        level = Level.HIGH
        parts.append(
            "a known Lynch syndrome diagnosis in the family" if known_lynch
            else "a pattern (early-onset or multiple Lynch-associated cancers) that can point to Lynch syndrome"
        )
        evidence.extend(describe(m, c) for m, c in p.affected(LYNCH_CANCERS, max_degree=2))
        recs.append(
            "Ask about genetic counseling for Lynch syndrome, which raises the risk of colorectal, "
            "endometrial and several other cancers and changes screening substantially."
        )

    return Insight(
        rule_id="colorectal_family_history",
        category="hereditary_cancer",
        level=level,
        title="Colorectal cancer in the family may change when screening starts",
        summary="Your record shows " + " and ".join(parts) + ". The general-population "
                "screening start age is 45; family history can move it earlier.",
        evidence=_dedupe(evidence),
        recommendation=" ".join(recs),
        references=[REF_USMSTF_CRC, REF_USPSTF_CRC, REF_NCCN],
    )


# --- premature cardiovascular disease -----------------------------------------

def premature_ascvd(p: HealthProfile) -> Optional[Insight]:
    # Relatives with unknown onset age are surfaced by record_gaps instead.
    premature = []
    for m, c in p.affected({"coronary_artery_disease", "stroke"}, max_degree=1):
        sex = m.effective_sex
        threshold = 55 if sex == "male" else 65 if sex == "female" else None
        if c.onset_age is not None and threshold is not None and c.onset_age < threshold:
            premature.append((m, c))

    if not premature:
        return None

    evidence = [describe(m, c) for m, c in premature]
    level = Level.MODERATE
    ldl = p.latest("ldl_cholesterol")
    extra = ""
    if ldl:
        mg = ldl_mg_dl(ldl.value, ldl.unit)
        evidence.append(f"Your most recent LDL cholesterol: {ldl.value:g} {ldl.unit}".rstrip())
        if mg >= 160:
            level = Level.HIGH
            extra = " Combined with an LDL of 160 mg/dL or higher, this is worth discussing soon."
    if not ldl:
        extra += " There's no cholesterol result in your record yet."

    return Insight(
        rule_id="premature_ascvd_family_history",
        category="cardiovascular",
        level=level,
        title="Early heart disease or stroke in a parent or sibling",
        summary=(
            "A first-degree relative had heart disease or stroke at a young age (men before 55, "
            "women before 65). Cardiology guidelines treat this as a 'risk-enhancing factor' that "
            "can tip decisions about cholesterol treatment." + extra
        ),
        evidence=_dedupe(evidence),
        recommendation=(
            "Ask your clinician to estimate your 10-year cardiovascular risk with this family "
            "history included, check a lipid panel if you haven't recently, and consider measuring "
            "lipoprotein(a) at least once. Lp(a) is largely inherited and isn't part of a standard panel."
        ),
        references=[REF_ACC_AHA_CHOL],
    )


def familial_hypercholesterolemia(p: HealthProfile) -> Optional[Insight]:
    evidence = []
    ldl = p.latest("ldl_cholesterol")
    high_ldl = ldl is not None and ldl_mg_dl(ldl.value, ldl.unit) >= 190
    if high_ldl:
        evidence.append(f"Your most recent LDL cholesterol: {ldl.value:g} {ldl.unit}".rstrip())
    fh_family = p.affected({"familial_hypercholesterolemia"}, max_degree=2)
    evidence.extend(describe(m, c) for m, c in fh_family)
    own_fh = p.own_conditions({"familial_hypercholesterolemia"})

    if not (high_ldl or fh_family) or own_fh:
        return None

    return Insight(
        rule_id="familial_hypercholesterolemia",
        category="cardiovascular",
        level=Level.HIGH,
        title="Possible inherited high cholesterol (familial hypercholesterolemia)",
        summary=(
            "Your record shows "
            + " and ".join(s for s, on in (
                ("an LDL of 190 mg/dL or higher", high_ldl),
                ("a relative diagnosed with familial hypercholesterolemia", bool(fh_family)),
            ) if on)
            + ". Guidelines use this as a signal to look for familial hypercholesterolemia, a "
              "common inherited condition that is very treatable when found early."
        ),
        evidence=evidence,
        recommendation=(
            "Discuss evaluation for familial hypercholesterolemia with your clinician. If it is "
            "confirmed, your parents, siblings and children should also have their cholesterol checked."
        ),
        references=[REF_ACC_AHA_CHOL],
    )


# --- diabetes -------------------------------------------------------------------

def diabetes_risk(p: HealthProfile) -> Optional[Insight]:
    if p.own_conditions({"type_2_diabetes", "type_1_diabetes"}):
        return None
    fdr = p.affected({"type_2_diabetes"}, max_degree=1)
    a1c = p.latest("hba1c")
    bmi = p.latest("bmi")
    age = p.age()

    evidence = [describe(m, c) for m, c in fdr]
    findings, level = [], None

    if a1c:
        evidence.append(f"Your most recent HbA1c: {a1c.value:g}%")
        if a1c.value >= 6.5:
            level = Level.HIGH
            findings.append(
                "your most recent HbA1c is in the diabetes range (6.5% or higher); a diagnosis "
                "needs a confirming test, so please follow up with your clinician"
            )
        elif a1c.value >= 5.7:
            level = Level.MODERATE
            findings.append("your most recent HbA1c is in the prediabetes range (5.7–6.4%)")

    if fdr:
        if bmi:
            evidence.append(f"Your most recent BMI: {bmi.value:g}")
        overweight = bmi is not None and bmi.value >= 25
        if overweight or (age is not None and age >= 35) or level:
            level = level or Level.MODERATE
            findings.append(
                "a parent or sibling has type 2 diabetes"
                + (", and your BMI is 25 or higher" if overweight else "")
            )
        else:
            level = level or Level.INFO
            findings.append("a parent or sibling has type 2 diabetes")

    if not findings:
        return None

    return Insight(
        rule_id="diabetes_risk",
        category="metabolic",
        level=level,
        title="Type 2 diabetes risk",
        summary="Your record shows " + "; ".join(findings) + ".",
        evidence=_dedupe(evidence),
        recommendation=(
            "Ask about diabetes screening (an HbA1c or fasting glucose test). Family history "
            "plus overweight is a standard reason to screen, and prediabetes is often reversible "
            "with structured lifestyle programs such as the National Diabetes Prevention Program."
        ),
        references=[REF_ADA],
    )


# --- prostate cancer ------------------------------------------------------------

def prostate_family_history(p: HealthProfile) -> Optional[Insight]:
    if p.sex is not None and p.sex.value == "female":
        return None
    fdr = p.affected({"prostate_cancer"}, max_degree=1)
    if not fdr:
        return None
    early = [(m, c) for m, c in fdr if c.onset_age is not None and c.onset_age < 65]
    multiple = len({m.id for m, _ in fdr}) >= 2
    if not early and not multiple:
        return None
    start = 40 if (multiple and early) else 45
    return Insight(
        rule_id="prostate_family_history",
        category="hereditary_cancer",
        level=Level.MODERATE,
        title="Prostate cancer in close relatives",
        summary=(
            "A father, brother or son with prostate cancer (especially before 65) puts you in a "
            "higher-risk group for prostate cancer."
            + ("" if p.sex else " This applies if you have a prostate.")
        ),
        evidence=[describe(m, c) for m, c in fdr],
        recommendation=(
            f"The American Cancer Society suggests higher-risk men talk with a clinician about "
            f"PSA screening starting around age {start}, rather than 50."
        ),
        references=[REF_ACS_PROSTATE, REF_NCCN],
    )


# --- safety ---------------------------------------------------------------------

def anesthesia_safety(p: HealthProfile) -> Optional[Insight]:
    hits = p.affected({"malignant_hyperthermia"}, max_degree=99)
    own = p.own_conditions({"malignant_hyperthermia"})
    if not hits and not own:
        return None
    return Insight(
        rule_id="malignant_hyperthermia",
        category="safety",
        level=Level.HIGH,
        title="Tell any surgical or anesthesia team about this family history",
        summary=(
            "Malignant hyperthermia is an inherited, potentially life-threatening reaction to some "
            "anesthesia drugs. Blood relatives of someone who had it may carry the same risk."
        ),
        evidence=[describe(m, c) for m, c in hits] + [describe_self(c) for c in own],
        recommendation=(
            "Before any procedure that involves anesthesia (including dental surgery), tell the "
            "team about this history so they can use safe alternatives. Ask your clinician whether "
            "genetic testing or a medical alert ID is appropriate."
        ),
        references=[REF_MHAUS],
    )


def blood_pressure(p: HealthProfile) -> Optional[Insight]:
    sbp, dbp = p.latest("systolic_bp"), p.latest("diastolic_bp")
    if not sbp and not dbp:
        return None
    s = sbp.value if sbp else 0
    d = dbp.value if dbp else 0
    reading = f"{s:g}/{d:g} mmHg" if sbp and dbp else (f"systolic {s:g}" if sbp else f"diastolic {d:g}")
    family_htn = p.affected({"hypertension"}, max_degree=1)
    evidence = [f"Your most recent blood pressure: {reading}"] + [describe(m, c) for m, c in family_htn]

    if s >= 180 or d >= 120:
        level, band = Level.HIGH, "severely elevated"
        rec = ("Contact a clinician promptly to recheck it. If you have chest pain, shortness of "
               "breath, severe headache, weakness, or vision or speech changes, seek emergency care.")
    elif s >= 140 or d >= 90:
        level, band = Level.MODERATE, "in the stage 2 high blood pressure range"
        rec = "Ask your clinician about confirming this with repeat or home readings."
    elif s >= 130 or d >= 80:
        level, band = Level.INFO, "in the stage 1 high blood pressure range"
        rec = "One reading isn't a diagnosis; home monitoring over a few weeks gives a clearer picture."
    else:
        return None

    return Insight(
        rule_id="blood_pressure",
        category="cardiovascular",
        level=level,
        title="Blood pressure reading above target",
        summary=f"Your most recent reading ({reading}) is {band} under the 2017 ACC/AHA definitions.",
        evidence=evidence,
        recommendation=rec,
        references=[REF_ACC_AHA_BP],
    )


# --- data completeness ------------------------------------------------------------

AGE_SENSITIVE = {
    "breast_cancer", "colorectal_cancer", "endometrial_cancer", "prostate_cancer",
    "coronary_artery_disease", "stroke",
}


def record_gaps(p: HealthProfile) -> Optional[Insight]:
    questions = []
    for m in p.family:
        for c in m.conditions:
            if c.category == "cancer_unspecified":
                questions.append(f"What type of cancer did your {m.label.lower()} have, and at what age?")
            elif c.category in AGE_SENSITIVE and c.onset_age is None:
                questions.append(
                    f"How old was your {m.label.lower()} when diagnosed with "
                    f"{c.display_name.lower()}? Age changes the guidance."
                )
            elif c.category is None:
                questions.append(f"Can you find out more about your {m.label.lower()}'s '{c.name}'?")

    rels = {m.relationship.value for m in p.family}
    if "mother" not in rels:
        questions.append("Add your mother's health history (even 'no known conditions' helps).")
    if "father" not in rels:
        questions.append("Add your father's health history (even 'no known conditions' helps).")
    if not any(r.startswith("maternal_grand") for r in rels) and not any(
        r.startswith("paternal_grand") for r in rels
    ):
        questions.append("Add what you know about your grandparents on both sides.")
    if not p.birth_date or not p.sex:
        questions.append("Add your date of birth and sex so age- and sex-specific guidance can apply.")

    if not questions:
        return None
    return Insight(
        rule_id="record_gaps",
        category="data_quality",
        level=Level.INFO,
        title="Questions to ask your family",
        summary=(
            "A few missing details could change your insights. Family gatherings are a good time "
            "to ask; relatives can also be invited to add their own history."
        ),
        evidence=_dedupe(questions)[:10],
        recommendation="Fill in what you can; your insights update automatically.",
        references=[REF_SURGEON_GENERAL],
    )


ALL_RULES: list[Rule] = [
    anesthesia_safety,
    hereditary_breast_ovarian,
    colorectal_family_history,
    familial_hypercholesterolemia,
    premature_ascvd,
    diabetes_risk,
    prostate_family_history,
    blood_pressure,
    record_gaps,
]
