# app/modules/agreements/agreement_generator.py
import uuid

import weasyprint
from jinja2 import Environment, select_autoescape
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agent_log.service import log_agent_execution
from app.modules.inspections.service import get_inspection
from app.modules.tenants.service import get_tenant_by_id

_PAYMENT_TIMING_LABELS: dict[str, tuple[str, str]] = {
    # value → (timing_phrase, before_after)
    "AT_PROPERTY": ("at the property", "before"),
    "AT_DELIVERY": ("at delivery of the report", "after"),
    "AFTER_DELIVERY": ("after delivery of the report", "after"),
}

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Home Inspection Agreement — {{ property_address }}</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: Arial, 'Liberation Sans', sans-serif;
  font-size: 10pt;
  color: #000;
  line-height: 1.5;
}

@page {
  size: letter;
  margin: 1in;
}

/* ── Header ─────────────────────────────────────────────────────────────── */
.header-table {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 4pt;
}

.header-left {
  vertical-align: top;
  width: 55%;
}

.header-right {
  vertical-align: top;
  width: 45%;
}

.company-name {
  font-size: 18pt;
  font-weight: 700;
  margin-bottom: 4pt;
}

.header-contact {
  font-size: 9pt;
  line-height: 1.7;
}

.license-box {
  border: 1.5px solid #000;
  padding: 8pt 10pt;
  font-size: 9pt;
  line-height: 1.8;
  margin-left: 12pt;
}

.agreement-subtitle {
  font-size: 8pt;
  color: #333;
  margin-top: 6pt;
  margin-bottom: 4pt;
}

hr {
  border: none;
  border-top: 1.5px solid #000;
  margin: 8pt 0 12pt 0;
}

/* ── Body ───────────────────────────────────────────────────────────────── */
.section-title {
  font-size: 10.5pt;
  font-weight: 700;
  text-decoration: underline;
  margin: 14pt 0 6pt 0;
}

.intro-block {
  margin-bottom: 10pt;
}

p {
  margin-bottom: 7pt;
}

/* ── Numbered clauses ───────────────────────────────────────────────────── */
.clause {
  margin-bottom: 8pt;
  padding-left: 0;
}

.clause-num {
  font-weight: 700;
}

/* ── Limitation lists ───────────────────────────────────────────────────── */
ol.roman-list {
  list-style-type: upper-roman;
  padding-left: 24pt;
  margin-bottom: 8pt;
}

ol.roman-list li {
  margin-bottom: 4pt;
}

ol.alpha-list {
  list-style-type: lower-alpha;
  padding-left: 24pt;
  margin-bottom: 4pt;
}

ol.alpha-list li {
  margin-bottom: 3pt;
}

/* ── Signature block ────────────────────────────────────────────────────── */
.signature-section {
  margin-top: 24pt;
  page-break-inside: avoid;
}

.sig-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 12pt;
}

.sig-cell {
  vertical-align: bottom;
  width: 48%;
}

.sig-spacer { width: 4%; }

.sig-line {
  border-bottom: 1px solid #000;
  height: 28pt;
  margin-bottom: 3pt;
}

.sig-label {
  font-size: 8.5pt;
  font-weight: 700;
}

.sig-date-row {
  margin-top: 10pt;
  font-size: 9pt;
}

.copyright {
  font-size: 7.5pt;
  color: #555;
  margin-top: 16pt;
  text-align: center;
}

.acknowledge {
  margin-top: 16pt;
  font-size: 9pt;
  font-weight: 700;
}
</style>
</head>
<body>

{# ── HEADER ──────────────────────────────────────────────────────────────── #}
<table class="header-table">
  <tr>
    <td class="header-left">
      <div class="company-name">{{ brand_name }}</div>
      <div class="header-contact">
        {% if email %}<div>{{ email }}</div>{% endif %}
        {% if phone %}<div>Cell: {{ phone }}</div>{% endif %}
      </div>
    </td>
    <td class="header-right">
      <div class="license-box">
        {% if license_number %}<div>Florida Licensed Home Inspector, # {{ license_number }}</div>{% endif %}
        {% if mold_license %}<div>Florida Licensed Mold Assessor, # {{ mold_license }}</div>{% endif %}
        {% if nachi_license %}<div>INTERNACHI {{ nachi_license }}</div>{% endif %}
        {% if not license_number and not mold_license and not nachi_license %}
        <div>Licensed Home Inspector</div>
        {% endif %}
      </div>
    </td>
  </tr>
</table>

<div class="agreement-subtitle">InterNACHI® Home Inspection Agreement &nbsp;&nbsp; Revised February 2019</div>
<hr>

{# ── INTRO ────────────────────────────────────────────────────────────────── #}
<div class="intro-block">
  <p>This is an Agreement between <strong>{{ brand_name }}</strong>, the undersigned Client, and us, the Inspector,
  pertaining to our inspection of the Property at: <strong>{{ property_address }}</strong></p>

  <p>This AGREEMENT made this {{ scheduled_day }} day of {{ scheduled_month }},
  {{ scheduled_year }}, by and between <strong>{{ brand_name }}</strong>
  (Hereinafter "INSPECTOR") and the undersigned {{ inspection.owner_buyer_name or "_______________" }}</p>

  <p>The terms below govern this Agreement.</p>
</div>

{# ── LIMITATIONS, EXCEPTIONS & EXCLUSIONS ─────────────────────────────────── #}
<div class="section-title">Limitations, Exceptions &amp; Exclusions</div>

<p>The inspection and report are performed and prepared for the sole, confidential and exclusive use and
possession of the Client. The inspection is a non-invasive, visual examination of the accessible areas of
a residential property, performed for a fee, which is designed to identify defects within specific systems
and components defined by the InterNACHI Standards of Practice that are both observed and deemed material
by the inspector.</p>

<p><strong>The inspection is not technically exhaustive and is not required to:</strong></p>

<ol class="roman-list">
  <li>Move or disturb furniture, floor coverings, personal property, or any items or materials that may
  obstruct access or visibility.</li>
  <li>Perform any destructive testing or dismantling.</li>
  <li>Enter under-floor crawlspaces or attics that are not readily accessible or that have less than 24 inches
  of vertical clearance.</li>
  <li>Walk on roof surfaces that appear unsafe or that could be damaged by walking on them.</li>
  <li>Inspect or operate equipment that is in storage or is shut down.</li>
  <li>Inspect swimming pools, spas, fountains, ponds, hot tubs, saunas, steam baths, or similar equipment.</li>
  <li>Inspect elevators or lifts.</li>
  <li>Inspect any system or component that is underground, concealed, or inaccessible.</li>
  <li>Inspect private water or sewer systems.</li>
  <li>Inspect systems or components that are not installed.</li>
</ol>

<p><strong>3.2 The inspector is not required to determine:</strong></p>

<ol class="roman-list">
  <li>The condition of systems or components that are not readily accessible.</li>
  <li>The remaining life expectancy of any system or component.</li>
  <li>The strength, adequacy, effectiveness, or efficiency of any system or component.</li>
  <li>The causes of any condition or deficiency.</li>
  <li>The methods, materials, and costs of corrections.</li>
  <li>The suitability of the property for any specialized use.</li>
  <li>Compliance with regulatory requirements (codes, regulations, laws, ordinances, etc.).</li>
  <li>The market value of the property or its marketability.</li>
  <li>The advisability of the purchase of the property.</li>
  <li>The presence or absence of pests such as wood damaging organisms, rodents, or insects.</li>
  <li>Cosmetic items, underground items, or items not permanently installed.</li>
</ol>

{# ── NUMBERED CLAUSES ─────────────────────────────────────────────────────── #}
<p class="clause">
  <span class="clause-num">1. </span>The fee for our inspection is <strong>${{ total_fee }}</strong>, payable
  <strong>{{ payment_timing_phrase }}</strong>, in full at a time {{ payment_before_after }} the appointment.
</p>

<p class="clause">
  <span class="clause-num">2. </span>We will prepare a written report for you identifying the defects that we
  both observed and deemed material during our inspection. We may also include in that report, at our
  professional discretion, items that we deem to be of a safety concern or of a minor deficiency, that we
  recommend be repaired or evaluated by a specialist. If you have not already done so before executing this
  Agreement, we recommend that you read the seller's disclosure statement as well as any other documents
  pertaining to the property, if applicable.
</p>

<p class="clause">
  <span class="clause-num">3. </span>Our inspection and report are performed and prepared in compliance with the
  current Standards of Practice of the International Association of Certified Home Inspectors (InterNACHI)
  (www.nachi.org/standards.htm). We agree to comply with InterNACHI's Code of Ethics. You acknowledge that
  you have read the Standards of Practice prior to signing this Agreement. Our report is not a substitute
  for any seller's disclosure.
</p>

<p class="clause">
  <span class="clause-num">4. </span>The inspection and report do not address or include: (1) the presence or
  absence of radon gas; (2) lead paint; (3) asbestos; (4) urea formaldehyde; (5) toxic or flammable chemicals;
  (6) water or air quality; (7) environmental hazards; (8) mold, mildew or any other fungi; (9) odors;
  (10) noise; (11) fire-safety; (12) code compliance; (13) permits; (14) any items not permanently installed
  or not in the scope of inspection; (15) any underground or concealed items or areas; (16) any items not
  inspected. You should contact a specialist if you desire information regarding any of these items.
  These are separate services that are not included in this standard home inspection unless we both
  specifically agree in writing otherwise.
</p>

<p class="clause">
  <span class="clause-num">5. </span>The Report is provided for the exclusive use of the Client named above.
  No other person or entity may rely upon the Report. In the event that any person, not a party to this
  Agreement, makes any claim against {{ brand_name }} or its employees, agents, or subcontractors, arising
  out of the services provided by {{ brand_name }} pursuant to this Agreement, the Client agrees to indemnify,
  defend, and hold harmless {{ brand_name }} from any such claim or suit, including payment of all legal fees,
  unless such claim or suit is based upon the negligent or intentional act of {{ brand_name }}.
</p>

<p class="clause">
  <span class="clause-num">6. </span><strong>LIMITATION ON LIABILITY AND DAMAGES: </strong>
  THE PARTIES AGREE THAT THE INSPECTOR AND COMPANY'S LIABILITY FOR CLAIMS OR DAMAGES, COSTS OF DEFENSE OR
  SUIT, ATTORNEY'S FEES AND EXPENSES ARISING OUT OF, OR RELATED TO, THE INSPECTOR'S OR COMPANY'S NEGLIGENCE
  OR BREACH OF ANY DUTY IMPOSED BY LAW, BREACH OF CONTRACT, VIOLATION OF ANY CONSUMER PROTECTION LAW, OR
  ANY ACTION AGAINST THE INSPECTOR OR COMPANY BY A THIRD PARTY, AND SHALL BE LIMITED TO A SUM EQUAL TO THE
  FEE PAID FOR THE INSPECTION, EXCEPT FOR BODILY INJURY. IN STATES WHERE LIMITATIONS ON LIABILITY ARE NOT
  PERMITTED, THE ABOVE LIMITATION SHALL APPLY TO THE FULLEST EXTENT ALLOWED BY LAW. THE PARTIES
  ACKNOWLEDGE THAT THIS LIMITATION OF LIABILITY HAS BEEN BARGAINED FOR BETWEEN THE PARTIES AND FORMS THE
  BASIS OF THE CONSIDERATION OF SERVICES HEREIN.
</p>

<p class="clause">
  <span class="clause-num">7. </span>The inspector is not required to, and will not, perform any engineering,
  architectural, plumbing, or any other job function requiring an occupational license in the jurisdiction
  where the inspection is taking place, unless the inspector holds a valid occupational license, in which
  case he/she may inform the Client that he/she holds such license and is therefore qualified to go beyond
  this scope of the inspection. Any services the inspector provides outside the scope of this home
  inspection are not covered by this Agreement.
</p>

<p class="clause">
  <span class="clause-num">8. </span>The Client shall have seven (7) days from the date of the inspection
  to notify the Inspector in writing of any perceived claim arising from the inspection or report. No claim
  by the Client arising from the Inspector's performance or non-performance of services shall be valid unless
  written notification is delivered to the Inspector within this time period. Notification shall be sent to
  {{ brand_name }}{% if email %}, {{ email }}{% endif %}{% if phone %}, {{ phone }}{% endif %}.
</p>

<p class="clause">
  <span class="clause-num">9. </span>In the event of a dispute, claim, or controversy arising from this
  Agreement or the Inspector's performance or non-performance of services, the venue shall be in Boulder
  County, Colorado, USA. This Agreement shall be construed in accordance with the laws of the state
  wherein the inspection took place.
</p>

<p class="clause">
  <span class="clause-num">10. </span>This Agreement constitutes the entire integrated agreement between
  the parties pertaining to the subject matter hereof and supersedes all prior agreements, representations,
  negotiations, and understandings of the parties, whether oral or written. No supplement, modification, or
  amendment of this Agreement shall be binding unless executed in writing by all parties.
</p>

<p class="clause">
  <span class="clause-num">11. </span>Fees that are past due shall bear interest at the rate of eight percent
  (8%) per annum from the date of the inspection until paid. In the event that any legal action is necessary
  to recover fees due, the prevailing party shall be entitled to recover court costs, as well as reasonable
  attorney's fees, incurred in connection with such collection efforts.
</p>

<p class="clause">
  <span class="clause-num">12. </span>Re-inspections are subject to the terms and conditions of this
  Agreement. Additional fees may apply.
</p>

<p class="clause">
  <span class="clause-num">13. </span>This Agreement is non-assignable. Any assignment or transfer of the
  rights and obligations under this Agreement, without the prior written consent of the Inspector, shall be
  null and void.
</p>

<p class="clause">
  <span class="clause-num">14. </span>In the event of any ambiguity or dispute with respect to any term of
  this Agreement, such ambiguity shall not be construed for or against any party based on the drafting of
  such language.
</p>

<p class="clause">
  <span class="clause-num">15. </span>Where multiple clients exist, the client signing this Agreement
  represents that he/she has the authority to sign and agree to this Agreement on behalf of all
  inspecting clients.
</p>

<p class="clause">
  <span class="clause-num">16. </span>This Agreement is available in large print upon request by email to
  {% if email %}{{ email }}{% else %}{{ brand_name }}{% endif %}.
</p>

<p class="clause">
  <span class="clause-num">17. </span><strong>InspectNACHI Buy-Back Guarantee Program: </strong>
  InterNACHI will buy back your home if our member inspector misses anything during his/her inspection of
  the home. The terms and conditions of InterNACHI's Certified Inspector Buy-Back Program apply and are
  available at www.nachi.org/buy-back-guarantee-program.htm. InterNACHI's Buy-Back Guarantee is made
  solely by InterNACHI and not by {{ brand_name }}.
</p>

{# ── SIGNATURE BLOCK ──────────────────────────────────────────────────────── #}
<div class="signature-section">
  <p class="acknowledge">I HAVE CAREFULLY READ THIS AGREEMENT. I AGREE TO IT AND ACKNOWLEDGE RECEIVING A COPY OF IT.</p>
  <p class="acknowledge">CLIENT HAS CAREFULLY READ THE FOREGOING, AGREES TO IT, AND ACKNOWLEDGES RECEIPT OF A COPY OF THIS AGREEMENT.</p>

  <table class="sig-table">
    <tr>
      <td class="sig-cell">
        <div class="sig-line"></div>
        <div class="sig-label">Inspector: {{ inspector_name or brand_name }}</div>
        <div class="sig-date-row">Date: _______________</div>
      </td>
      <td class="sig-spacer"></td>
      <td class="sig-cell">
        <div class="sig-line"></div>
        <div class="sig-label">CLIENT OR REPRESENTATIVE</div>
        <div class="sig-date-row">Date: _______________</div>
      </td>
    </tr>
  </table>
</div>

<div class="copyright">Copyright © 2019 International Association of Certified Home Inspectors</div>

</body>
</html>
"""

_jinja_env = Environment(autoescape=select_autoescape(["html"]))


async def generate_agreement_pdf(
    inspection_id: uuid.UUID,
    session: AsyncSession,
) -> bytes:
    async with log_agent_execution(
        session,
        agent_name="agreement_generator",
        trigger_type="user_request",
        trigger_ref=str(inspection_id),
        input_summary={
            "inspection_id": str(inspection_id),
            "template": "PRE_INSPECTION_AGREEMENT",
        },
    ) as entry:
        inspection = await get_inspection(inspection_id, session)
        if inspection is None:
            raise ValueError(f"inspection {inspection_id} not found")

        tenant = await get_tenant_by_id(session)
        theme: dict = tenant.theme_config if tenant and tenant.theme_config else {}

        brand_name: str = theme.get("brand_name") or (tenant.name if tenant else "Home Inspections")
        inspector_name: str | None = theme.get("inspector_name")
        license_number: str | None = theme.get("license_number")
        email: str | None = theme.get("email")
        phone: str | None = theme.get("phone")
        mold_license: str | None = theme.get("mold_license")
        nachi_license: str | None = theme.get("nachi_license")

        raw_timing = (
            inspection.payment_timing.value
            if hasattr(inspection.payment_timing, "value")
            else str(inspection.payment_timing or "")
        )
        timing_phrase, before_after = _PAYMENT_TIMING_LABELS.get(
            raw_timing, ("at the property", "before")
        )

        from datetime import timezone
        scheduled_dt = inspection.scheduled_at
        if scheduled_dt.tzinfo is None:
            scheduled_dt = scheduled_dt.replace(tzinfo=timezone.utc)
        scheduled_day = scheduled_dt.strftime("%-d")
        scheduled_month = scheduled_dt.strftime("%B")
        scheduled_year = scheduled_dt.strftime("%Y")

        template = _jinja_env.from_string(_HTML_TEMPLATE)
        html = template.render(
            inspection=inspection,
            property_address=inspection.property_address,
            total_fee=inspection.total_fee,
            scheduled_day=scheduled_day,
            scheduled_month=scheduled_month,
            scheduled_year=scheduled_year,
            payment_timing_phrase=timing_phrase,
            payment_before_after=before_after,
            brand_name=brand_name,
            inspector_name=inspector_name,
            license_number=license_number,
            email=email,
            phone=phone,
            mold_license=mold_license,
            nachi_license=nachi_license,
        )

        pdf_bytes: bytes = weasyprint.HTML(string=html).write_pdf()
        entry.decision = "agreement_generated"
        entry.output_summary = {"pdf_size_bytes": len(pdf_bytes)}

    return pdf_bytes
