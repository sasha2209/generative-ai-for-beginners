# Growing Through Partnerships with Existing Companies

**Thesis:** don't compete with the companies that already hold health data, see patients, or
pay for care. Become the **family-history layer** they all lack. They supply the data and act
on the insights. We supply the structured family graph and the reasoning that connects the two.

Family history is valuable to almost everyone in healthcare, yet almost nobody captures it well:
- **Clinicians** need it for risk-based screening but have minutes per visit, and EHR family-history fields are often sparse.
- **Health plans and employers** pay for late-stage cancer and cardiac events that earlier, risk-appropriate screening could catch.
- **Genetic testing and counseling companies** need to find the people who meet testing criteria, most of whom have never been identified.
- **Researchers and life-science companies** need well-phenotyped, consented cohorts.

> Company names below are illustrative examples of each category as of 2026. Ownership and
> product lines in this space change often (acquisitions, bankruptcies), so verify each one
> before outreach.

---

## 1. The partnership map

Partners fall into three roles: they bring **data in**, **act** on insights, or **distribute**
the product.

### A. Data-in partners (cut the user's data-entry burden to near zero)

| Partner type | Examples | What we get | What they get | How (built / to build) |
|---|---|---|---|---|
| EHR vendors and patient portals | Epic, Oracle Health, athenahealth, eClinicalWorks | The patient's own conditions, labs, meds and any recorded family history | An app that improves family-history capture (a known documentation gap); listing in their marketplace | SMART on FHIR patient access (certified EHRs must expose FHIR APIs under the Cures Act). FHIR import ✅ built |
| Consumer health record hubs | Apple Health Records, Android Health Connect | Records the user has already aggregated on their phone | Engagement with their health platform | Native mobile app (to build) |
| Health-data networks and aggregators | Health Gorilla, Particle Health, Metriport, 1upHealth, Zus Health; TEFCA QHINs | Records from many providers at once, through a single integration | Usage-based API revenue | FHIR via aggregator API; TEFCA "individual access services" exchange |
| Health plans | Any plan's CMS-mandated Patient Access API; Medicare Blue Button 2.0 | Claims-based history (diagnoses, procedures such as past colonoscopies) | See "Payers" below | FHIR (CARIN Blue Button profile) |
| Labs | Quest, Labcorp; at-home testing companies | Lipid panels, HbA1c, Lp(a) | Test orders driven by insights | Lab result feeds or FHIR |
| Genetic testing labs | Myriad, Ambry, GeneDx, Labcorp (Invitae), Color | Structured variant results, so a relative's BRCA or Lynch result informs the family | Cascade testing of at-risk relatives, their biggest unmet volume driver | Genetic report ingestion (to build) |

### B. Action partners (turn insights into care, which is where revenue comes from)

| Insight | Partner type | Examples | Flow |
|---|---|---|---|
| Hereditary cancer pattern | Telehealth genetic counseling | Genome Medical, InformedDNA, Color | User consents → we send a pre-filled pedigree and the triggering evidence → counselor visit → testing. ✅ `genetic-counseling` partner archetype built |
| Earlier colonoscopy, mammography, PSA | Health systems' high-risk clinics, GI groups, imaging centers | Local health systems; national imaging networks | Referral with a FHIR bundle attached; the clinician receives a structured family history before the visit. ✅ `primary-care` archetype |
| Premature ASCVD, FH, Lp(a) | Preventive cardiology and lipid clinics; lab ordering | Health-system cardiology; Quest / Labcorp consumer ordering | "Order an Lp(a) test" → result flows back in → insight updates. ✅ `lab-testing` archetype |
| Prediabetes | CDC-recognised Diabetes Prevention Programs, digital DPP providers | Plan- or employer-sponsored DPPs | Eligibility handoff (insight only, minimum necessary) |
| Screening gaps | Health plans / value-based care organisations | MA plans, ACOs | Plan learns which members qualify for earlier screening and covers or schedules it. ✅ `health-plan` archetype receives **insights only**, no records |

### C. Distribution partners (reach users cheaply and with trust)

| Channel | Why it works |
|---|---|
| **Health plans and employers** as payers | Offer us as a benefit. One contract reaches thousands of members, and the buyer is not the user, so the product can be free to the user. |
| **Health systems** | "Complete your family history before your visit" link in the portal and pre-visit intake. They get better documentation; we get trusted distribution. |
| **Pre-visit intake platforms** | Embed our family-history capture in the forms patients already fill in. |
| **Patient advocacy organisations** | FORCE (hereditary cancer), the Family Heart Foundation (FH), Lynch syndrome groups. Highly motivated communities and credible co-branding. |
| **Public health campaigns** | The U.S. Surgeon General's *National Family History Day* is Thanksgiving: a built-in annual moment when families are together. On 2026-11-15 that is 11 days away, a good pilot campaign. |

---

## 2. The growth engine: families, not individuals

The strongest growth loop is built into the product itself: **every user's insights improve when
their relatives join**.

1. A user adds their history and sees "Questions to ask your family" (the `record_gaps` insight is already built).
2. They invite their mother, siblings or cousins to fill in their own branch, with consent controls on what each person sees.
3. Each new relative's data enriches everyone's pedigree, and each relative gets their own insights.
4. A **positive genetic result in one relative** triggers consented cascade notifications to at-risk blood relatives, the single highest-yield intervention in hereditary-risk care.

This is a real network effect, and it doubles as the moat: a family graph is hard to copy and
gets more valuable with each member. Partners amplify it. Genetic labs want cascade testing,
and plans want covered family members screened.

---

## 3. Business models (in order of priority)

| Model | Who pays | Notes |
|---|---|---|
| **B2B2C per-member pricing** | Health plans, employers, value-based providers | Primary model. Priced on screening-gap closure and avoided late-stage events, so outcomes data matters from day one. |
| **Enterprise SaaS / integration** | Health systems | Family-history capture with EHR write-back plus a clinician view. |
| **Platform fees from action partners** | Genetic counseling, labs, DPPs | Use flat platform or subscription fees, **not per-referral fees**: per-referral payments tied to federally reimbursed services can raise Anti-Kickback Statute issues. Get healthcare regulatory counsel on every structure. |
| **Consented research partnerships** | Academic medical centers, life-science companies | De-identified and opt-in only (✅ `research_deidentified` export built). Strong use cases: finding undiagnosed FH and hereditary cancer families for trials. Users should see what research their data supports. |
| **Consumer premium** (later) | Individuals | Optional. Never put safety-relevant insights behind a paywall. |

### Lines we will not cross (published as a public trust pledge)
- **No sale of identifiable data, ever.**
- **No sharing with life, disability or long-term-care insurers, or with employers, for underwriting or employment decisions.** GINA protects against genetic discrimination in health insurance and employment, but **not** in life, disability or long-term-care insurance. Users must know we will never be the leak.
- No advertising based on health data.
- Every share is opt-in, specific to a partner, limited to the minimum necessary, revocable and logged (✅ enforced in code).

Trust is the product. One breach of these lines would destroy the family network effect,
because people won't invite relatives into something they don't trust.

---

## 4. Phased plan

| Phase | Timeline | Goals | Partnerships | Exit criteria |
|---|---|---|---|---|
| **0. Clinical and trust foundation** | Months 0–6 | Clinician and genetic-counselor review of the rules; validate against real pedigrees; security audit; regulatory positioning | Clinical advisory board; 1 academic medical center for validation | Rules sensitivity at or above established screening tools; SOC 2 Type I underway |
| **1. Data-in and pilot** | Months 3–9 | Consumer launch; SMART on FHIR connection to the top EHRs; family invitations | 1 aggregator or network; 1–2 advocacy organisations; Family History Day campaign | Median user has ≥8 relatives with ages; ≥30% invite a relative |
| **2. Action loop** | Months 6–12 | Close the loop from insight to care | 1 telehealth genetic counseling partner; lab ordering; 1 health system | ≥25% of "high" insights lead to a completed counseling visit or screening |
| **3. Payer and employer contracts** | Months 12–24 | Paid distribution, with outcomes evidence from phase 2 | 1–2 regional plans or MA plans; 1 large self-insured employer | Gap-closure lift versus control; signed per-member contract |
| **4. Research and scale** | Months 18+ | Consented research programs; additional conditions (e.g. hereditary cardiomyopathy, hemochromatosis) | AMC research consortium; life-science partners | IRB-approved studies; user-visible research dashboard |

---

## 5. What each partner integration needs (checklist)

- **Contract**: BAA (when the partner is a HIPAA covered entity, or we act on their behalf) and/or a data processing agreement, data-use limits, breach terms, and a ban on re-identification and onward sale.
- **Consent scope** registered in `fhg/sharing.py`, with the minimum data categories that partner needs.
- **Technical**: FHIR endpoint and authentication (SMART Backend Services / OAuth 2.0 client credentials), sandbox testing, and monitoring.
- **Clinical**: agreement on how the partner acts on the insight, and a feedback path so outcomes (visit completed, test result) flow back and improve the user's record.
- **Metrics**: insight-to-action conversion, time to action, user satisfaction, and safety events.

---

## 6. Regulatory landscape (summary; get counsel)

| Area | Why it matters |
|---|---|
| **HIPAA** | Direct-to-consumer apps are usually *not* covered entities, but when we work on behalf of a plan or provider we are a **business associate** and must comply fully. Design to HIPAA standards everywhere. |
| **FTC Act §5 and Health Breach Notification Rule** | The FTC applies these to non-HIPAA health apps (updated rule in 2024) and has acted against apps that shared health data for advertising. |
| **State health-privacy laws** | Washington's My Health My Data Act (with a private right of action), similar laws in Nevada and Connecticut, CCPA/CPRA, and state genetic-privacy laws. |
| **FDA (software as a medical device / clinical decision support)** | Patient-specific recommendations can make software a device. Keep the logic transparent and guideline-based, keep a clinician in the loop, and get a regulatory strategy early (including a clinician-facing version designed around the non-device CDS criteria). |
| **GINA and genetic privacy** | Health insurance and employment protections only; this drives the trust pledge above. |
| **Anti-Kickback Statute / Stark** | Shapes how money flows with providers and labs (see business models). |
| **Information blocking (Cures Act)** | Works in our favour: it requires providers and EHRs to release patients' data to apps the patient chooses. |

---

## 7. Key risks and mitigations

| Risk | Mitigation |
|---|---|
| False reassurance ("no insight = low risk") | Explicit disclaimer (in code), `record_gaps` prompts, and a "completeness score" before showing an "all clear" |
| Incorrect or outdated clinical logic | Clinical governance, versioned rules with citations, guideline-change monitoring, and regression tests on reference pedigrees |
| Dependence on EHR or aggregator access | Several data-in partners, plus user-entered text and CSV that work without any partner |
| Privacy breach or loss of trust | Encryption, minimum-necessary sharing, audits, the public trust pledge, and no data sale |
| Partners wanting more data than needed | Partner archetypes enforce category limits in code; contracts mirror them |
| Health equity (adoptees, estranged families, limited records) | Allow "unknown" as a first-class answer; support genetic test results as an alternative input; multilingual text parsing |

---

## 8. First five conversations to have

1. **A telehealth genetic counseling provider**: fastest path to a closed loop and an early revenue partner.
2. **A health-data aggregator or network**: removes most manual data entry for users.
3. **A hereditary-cancer or FH advocacy organisation**: credibility plus an engaged launch community.
4. **One regional health system's cancer genetics or preventive cardiology program**: clinical validation partner and first enterprise customer.
5. **One regional or Medicare Advantage health plan's quality team**: screening-gap closure pilot, the bridge to per-member revenue.
