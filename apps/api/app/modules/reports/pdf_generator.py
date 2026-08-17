# app/modules/reports/pdf_generator.py
import uuid
from collections import defaultdict

import weasyprint
from jinja2 import Environment, select_autoescape
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agent_log.service import log_agent_execution
from app.modules.findings.models import Condition, Section
from app.modules.findings.service import list_findings_by_inspection
from app.modules.inspections.service import get_inspection
from app.modules.tenants.service import get_tenant_by_id

_INSPECTION_TYPE_LABELS: dict[str, str] = {
    "FULL_INSPECTION": "Full Inspection",
    "WIND_MITIGATION": "Wind Mitigation",
    "FOUR_POINT": "4-Point Inspection",
    "MOLD_INSPECTION": "Mold Inspection",
    "TERMITES": "Termite Inspection",
    "ROOF_CERTIFICATION": "Roof Certification",
    "OPENING_PROTECTION": "Opening Protection",
    "SEWER_INSPECTION": "Sewer Inspection",
    "LEAD_PAINT_INSPECTION": "Lead Paint Inspection",
    "WATER_QUALITY_TEST": "Water Quality Test",
}

_SECTION_LABELS: dict[str, str] = {
    "FRONT": "Front / Entrance",
    "EXTERIOR": "Exterior",
    "INSULATION": "Insulation",
    "PLUMBING": "Plumbing",
    "STRUCTURAL": "Structural",
    "ELECTRICAL": "Electrical",
    "ROOF": "Roof",
    "KITCHEN": "Kitchen",
    "INTERIOR": "Interior",
    "AIR_CONDITIONING": "Air Conditioning",
    "COMMENTS": "Comments",
    "COST_ESTIMATION": "Cost Estimation",
    "COUNTY_INFO": "County Information",
    "BEDROOMS": "Bedrooms",
    "BATHROOMS": "Bathrooms",
    "DISCLOSURE": "Disclosure",
}

_CONDITION_COLORS: dict[str | None, str] = {
    Condition.GOOD.value: "#dcfce7",
    Condition.MARGINAL.value: "#fef9c3",
    Condition.DEFECTIVE.value: "#fee2e2",
    "N_A": "#f3f4f6",
    None: "#ffffff",
}

_SECTION_DISCLAIMERS: dict[str, str] = {
    "_DEFAULT": (
        "This is a report made to the best of our ability and professional belief on the "
        "existing conditions of the components inspected. This report is not a guarantee "
        "or warranty of any kind."
    ),
    "FRONT": (
        "This is a report made to the best of our ability and professional belief on the "
        "existing conditions of the front and entrance components. The Inspector has visually "
        "inspected all accessible areas of the front and entrance. This report is not a "
        "guarantee or warranty of any kind."
    ),
    "EXTERIOR": (
        "This is a report made to the best of our ability and professional belief on the "
        "existing conditions of the exterior components. As all exterior areas are not "
        "accessibly visible in some areas due to foliage, plaster or painting, the Inspector "
        "cannot guarantee against hidden defects, structural damage or repairs. This inspection "
        "has been made for such structural defects as would require engineering skill practices."
    ),
    "INSULATION": (
        "This is a report made to the best of our ability and professional belief on the "
        "existing conditions of the insulation components. Insulation levels and types are "
        "visually estimated where accessible. Hidden or covered insulation cannot be evaluated. "
        "This report is not a guarantee or warranty of any kind."
    ),
    "PLUMBING": (
        "This is a report made to the best of our ability and professional belief on the "
        "existing conditions of the plumbing components. Water supply and drain lines within "
        "walls or underground are not inspected. This inspection does not test for water quality "
        "or pressure adequacy. This report is not a guarantee or warranty of any kind."
    ),
    "STRUCTURAL": (
        "This is a report made to the best of our ability and professional belief on the "
        "existing conditions of the structural components. Concealed framing, foundation, and "
        "below-grade structural elements are not inspected. Where structural concerns are noted, "
        "further evaluation by a licensed structural engineer is recommended. This report is "
        "not a guarantee or warranty of any kind."
    ),
    "ELECTRICAL": (
        "This is a report made to the best of our ability and professional belief on the "
        "existing conditions of the electrical components. Concealed wiring, grounding electrode "
        "systems, and load calculations are outside the scope of this inspection. The Inspector "
        "tests accessible outlets, switches, and panels only. This report is not a guarantee "
        "or warranty of any kind."
    ),
    "ROOF": (
        "This is a report made to the best of our ability and professional belief on the "
        "existing conditions of the roof components. The Inspector performs a visual inspection "
        "of accessible roof surfaces. Concealed leaks, underlying deck damage, or damage beneath "
        "roofing material may not be detected. This report is not a guarantee or warranty "
        "of any kind."
    ),
    "KITCHEN": (
        "This is a report made to the best of our ability and professional belief on the "
        "existing conditions of the kitchen components. Built-in appliances are operated through "
        "normal user controls only. Hidden plumbing or electrical defects behind cabinetry are "
        "not within the scope of this inspection. This report is not a guarantee or warranty "
        "of any kind."
    ),
    "INTERIOR": (
        "This is a report made to the best of our ability and professional belief on the "
        "existing conditions of the interior components. Furniture, personal belongings, and "
        "floor coverings obscuring floors or walls are not moved during inspection. Concealed "
        "or cosmetic conditions not affecting habitability may not be noted. This report is "
        "not a guarantee or warranty of any kind."
    ),
    "AIR_CONDITIONING": (
        "This is a report made to the best of our ability and professional belief on the "
        "existing conditions of the air conditioning and heating components. Systems are "
        "operated through normal thermostat controls only. Internal components of equipment "
        "not accessible without disassembly are outside the scope of this inspection. This "
        "report is not a guarantee or warranty of any kind."
    ),
}

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{{ inspection.property_address }} — Inspection Report</title>
<style>
{% if font_import_url %}
@import url('{{ font_import_url }}');
{% endif %}

:root {
  --primary: {{ primary_color }};
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: {{ font_family }}, 'Liberation Sans', Arial, sans-serif;
  font-size: 10pt;
  color: #1a1a1a;
}

@page {
  size: letter;
  margin: 0.75in 0.75in 1in 0.75in;
  @bottom-left {
    content: "{{ brand_name }}{% if license_number %} | Lic. {{ license_number }}{% endif %}";
    font-size: 7.5pt;
    color: #666;
    border-top: 1.5px solid var(--primary);
    padding-top: 4pt;
    width: 70%;
    white-space: nowrap;
    overflow: hidden;
  }
  @bottom-right {
    content: "Page " counter(page) " of " counter(pages);
    font-size: 7.5pt;
    color: #666;
    border-top: 1.5px solid var(--primary);
    padding-top: 4pt;
    width: 30%;
    text-align: right;
    white-space: nowrap;
  }
}

@page :first {
  @top-left { content: none; }
  @top-right { content: none; }
}

@page :not(:first) {
  @top-left {
    content: "{{ brand_name }}  |  Inspection #{{ report_number }}  |  {{ inspection.scheduled_at | datefmt }}\\A Tel: {{ phone or '' }}{% if email %}  |  {{ email }}{% endif %}  |  License #{{ license_number or '' }}";
    white-space: pre;
    font-size: 7.5pt;
    color: #666;
    padding-bottom: 4pt;
    border-bottom: 1px solid #e5e7eb;
    width: 100%;
  }
  @top-right { content: none; }
}

/* ── Cover page ──────────────────────────────────────────────────────────── */
.cover { page-break-after: always; }

.header-band {
  background: var(--primary);
  height: 8px;
  margin: -0.75in -0.75in 32pt -0.75in;
  width: calc(100% + 1.5in);
}

.cover-logo {
  text-align: center;
  margin: 24pt 0 16pt;
}

.cover-logo img { max-height: 80px; max-width: 280px; }

.cover-brand-name {
  font-size: 26pt;
  font-weight: 700;
  color: var(--primary);
  text-align: center;
  margin-bottom: 4pt;
}

.cover-company-info {
  text-align: center;
  font-size: 9pt;
  color: #555;
  line-height: 1.7;
  margin-bottom: 20pt;
}

.cover-divider {
  border: none;
  border-top: 2px solid var(--primary);
  margin: 16pt 0;
}

.cover-report-title {
  text-align: center;
  font-size: 18pt;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #1a1a1a;
  margin-bottom: 24pt;
}

.cover-info-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 8pt;
}

.cover-info-table td {
  padding: 6pt 10pt;
  font-size: 10pt;
  border-bottom: 1px solid #e5e7eb;
  vertical-align: top;
}

.cover-info-table td:first-child {
  font-weight: 600;
  color: #555;
  width: 38%;
  white-space: nowrap;
}

/* ── Section header band ─────────────────────────────────────────────────── */
.section-header {
  background: var(--primary);
  color: #fff;
  font-size: 13pt;
  font-weight: 700;
  padding: 8pt 12pt;
  margin: 0 -0.1in 14pt -0.1in;
  letter-spacing: 0.04em;
}

.page-section { page-break-after: always; }
.page-section:last-child { page-break-after: avoid; }

/* ── Executive summary ───────────────────────────────────────────────────── */
.summary-counts {
  display: flex;
  gap: 24pt;
  margin: 16pt 0;
}

.count-block { text-align: center; }

.count-number {
  font-size: 36pt;
  font-weight: 700;
  line-height: 1;
}

.count-label { font-size: 9pt; color: #555; margin-top: 3pt; }
.count-defective { color: #dc2626; }

.summary-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 14pt;
  font-size: 9.5pt;
}

.summary-table th {
  background: var(--primary);
  color: #fff;
  padding: 6pt 10pt;
  text-align: left;
  font-weight: 600;
}

.summary-table td {
  padding: 5pt 10pt;
  border-bottom: 1px solid #e5e7eb;
}

.summary-table tr:nth-child(even) td { background: #f8fafc; }

.defective-list {
  margin-top: 16pt;
}

.defective-list h3 {
  font-size: 10.5pt;
  font-weight: 700;
  color: #dc2626;
  margin-bottom: 8pt;
}

.defective-list ul {
  padding-left: 16pt;
  line-height: 1.8;
  font-size: 9.5pt;
}

/* ── Findings table ──────────────────────────────────────────────────────── */
.disclaimer {
  font-size: 8.5pt;
  color: #666;
  line-height: 1.5;
  margin-bottom: 12pt;
  font-style: italic;
}

.findings-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 9pt;
}

.findings-table th {
  background: #f1f5f9;
  color: #334155;
  font-weight: 600;
  padding: 6pt 8pt;
  text-align: left;
  border-bottom: 2px solid #cbd5e1;
}

.findings-table td {
  padding: 5pt 8pt;
  border-bottom: 1px solid #e5e7eb;
  vertical-align: top;
}

.findings-table tr:nth-child(even) td { background: #f8fafc; }

.col-num  { width: 4%; text-align: center; color: #888; }
.col-item { width: 26%; font-weight: 500; }
.col-cond { width: 14%; text-align: center; }
.col-obs  { width: 56%; }

.cond-badge {
  display: inline-block;
  padding: 2pt 6pt;
  border-radius: 3pt;
  font-size: 8pt;
  font-weight: 600;
}

/* ── Property details page ───────────────────────────────────────────────── */
.subsection-title {
  font-size: 10.5pt;
  font-weight: 700;
  color: var(--primary);
  border-bottom: 1.5px solid var(--primary);
  padding-bottom: 3pt;
  margin: 14pt 0 8pt 0;
}

.detail-table {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 4pt;
  font-size: 9pt;
}

.detail-table td {
  padding: 4pt 8pt;
  border-bottom: 1px solid #e5e7eb;
  vertical-align: top;
}

.detail-table td:first-child {
  font-weight: 600;
  color: #555;
  width: 40%;
  white-space: nowrap;
}

/* ── Section certification block ─────────────────────────────────────────── */
.certification {
  margin-top: 20pt;
  font-size: 8pt;
  color: #555;
  border-top: 1px solid #e5e7eb;
  padding-top: 12pt;
}

.signature-line {
  margin-top: 12pt;
  font-weight: 600;
}

/* ── Component observations ──────────────────────────────────────────────── */
.obs-metadata { margin-bottom: 10pt; }
.obs-subtitle {
  font-size: 9pt; font-weight: 700; color: var(--primary);
  margin-bottom: 5pt; border-bottom: 1px solid var(--primary);
  padding-bottom: 2pt;
}
.obs-meta-table { width: 100%; font-size: 8.5pt; }
.obs-meta-label { font-weight: 600; color: #555; width: 35%; padding: 2pt 6pt 2pt 0; }
.obs-meta-value { padding: 2pt 0; }
.obs-conditions { margin-bottom: 10pt; }
.obs-items-table { width: 100%; border-collapse: collapse; font-size: 8.5pt; }
.obs-items-table th {
  background: #f1f5f9; color: #334155; font-weight: 600;
  padding: 4pt 6pt; text-align: left; border-bottom: 1px solid #cbd5e1;
}
.obs-items-table td { padding: 3pt 6pt; border-bottom: 1px solid #f0f0f0; }
.obs-col-item { width: 30%; }
.obs-col-cond { width: 15%; text-align: center; }
.obs-col-notes { width: 55%; }
.obs-divider { border: none; border-top: 1px solid #e5e7eb; margin: 8pt 0; }
</style>
</head>
<body>

{# ── COVER PAGE ─────────────────────────────────────────────────────────── #}
<div class="cover">
  <div class="header-band"></div>

  <div class="cover-logo">
    {% if logo_url %}
      <img src="{{ logo_url }}" alt="{{ brand_name }}">
    {% else %}
      <div class="cover-brand-name">{{ brand_name }}</div>
    {% endif %}
  </div>

  <div class="cover-company-info">
    {% if logo_url %}<div class="cover-brand-name">{{ brand_name }}</div>{% endif %}
    <div>
      {% if phone %}Tel: {{ phone }}{% endif %}
      {% if phone and email %} | {% endif %}
      {% if email %}Email: {{ email }}{% endif %}
      {% if (phone or email) and website %} | {% endif %}
      {% if website %}Web: {{ website }}{% endif %}
    </div>
    {% if license_number %}<div>License #{{ license_number }}</div>{% endif %}
    {% if mold_license %}<div>Mold Inspector: {{ mold_license }}</div>{% endif %}
    {% if nachi_license %}<div>NACHI License: {{ nachi_license }}</div>{% endif %}
    {% if inspector_name %}<div>Inspector: {{ inspector_name }}</div>{% endif %}
  </div>

  <hr class="cover-divider">

  <div class="cover-report-title">Full Inspection Report</div>

  <table class="cover-info-table">
    <tr>
      <td>Prepared For:</td>
      <td>{{ inspection.owner_buyer_name or inspection.realtor_name or "Client" }}</td>
    </tr>
    {% if inspection.realtor_name %}
    <tr>
      <td>Realtor:</td>
      <td>{{ inspection.realtor_name }}</td>
    </tr>
    {% endif %}
    <tr>
      <td>Property:</td>
      <td>{{ inspection.property_address }}</td>
    </tr>
    <tr>
      <td>Date of Inspection:</td>
      <td>{{ inspection.scheduled_at | datefmt }}</td>
    </tr>
    <tr>
      <td>Inspection Fee:</td>
      <td>${{ inspection.total_fee }}</td>
    </tr>
    <tr>
      <td>Report #:</td>
      <td>{{ report_number }}</td>
    </tr>
    <tr>
      <td>Inspection Types:</td>
      <td>{{ inspection_type_labels | join(", ") }}</td>
    </tr>
  </table>
</div>

{# ── PROPERTY DETAILS ───────────────────────────────────────────────────── #}
{% if has_property_details %}
<div class="page-section">
  <div class="section-header">Property Details</div>

  {% if inspection.year_built or inspection.adj_sqft or inspection.gate_code or inspection.lockbox or inspection.num_bedrooms or inspection.num_bathrooms %}
  <h3 class="subsection-title">Property Information</h3>
  <table class="detail-table">
    {% if inspection.year_built %}<tr><td>Year Built:</td><td>{{ inspection.year_built }}</td></tr>{% endif %}
    {% if inspection.adj_sqft %}<tr><td>Adjusted Sq Ft:</td><td>{{ inspection.adj_sqft }}</td></tr>{% endif %}
    {% if inspection.num_bedrooms %}<tr><td>Bedrooms:</td><td>{{ inspection.num_bedrooms }}</td></tr>{% endif %}
    {% if inspection.num_bathrooms or inspection.num_half_bathrooms %}<tr><td>Bathrooms:</td><td>{{ bathrooms_display }}</td></tr>{% endif %}
    {% if inspection.gate_code %}<tr><td>Gate Code:</td><td>{{ inspection.gate_code }}</td></tr>{% endif %}
    {% if inspection.lockbox %}<tr><td>Lockbox:</td><td>{{ inspection.lockbox }}</td></tr>{% endif %}
  </table>
  {% endif %}

  {% if has_roof_data %}
  <h3 class="subsection-title">Roof</h3>
  <table class="detail-table">
    {% if inspection.roof_permit_number %}<tr><td>Roof Permit #:</td><td>{{ inspection.roof_permit_number }}</td></tr>{% endif %}
    {% if inspection.roof_date %}<tr><td>Roof Date:</td><td>{{ inspection.roof_date.year }}</td></tr>{% endif %}
    {% if inspection.roof_style %}<tr><td>Roof Style:</td><td>{{ inspection.roof_style }}</td></tr>{% endif %}
    {% if inspection.roof_type %}<tr><td>Roof Type:</td><td>{{ inspection.roof_type }}</td></tr>{% endif %}
  </table>
  {% endif %}

  {% if has_water_heater_data %}
  <h3 class="subsection-title">Water Heater</h3>
  <table class="detail-table">
    {% if inspection.water_heater_type %}<tr><td>Type:</td><td>{{ inspection.water_heater_type }}</td></tr>{% endif %}
    {% if inspection.water_heater_location %}<tr><td>Location:</td><td>{{ inspection.water_heater_location }}</td></tr>{% endif %}
    {% if inspection.water_heater_capacity %}<tr><td>Capacity/Year:</td><td>{{ inspection.water_heater_capacity }}</td></tr>{% endif %}
  </table>
  {% endif %}

  {% if has_electrical_data %}
  <h3 class="subsection-title">Electrical</h3>
  <table class="detail-table">
    {% if inspection.electrical_brand %}<tr><td>Brand:</td><td>{{ inspection.electrical_brand }}</td></tr>{% endif %}
    {% if inspection.electrical_amps %}<tr><td>Amperage:</td><td>{{ inspection.electrical_amps }}</td></tr>{% endif %}
    {% if inspection.electrical_location %}<tr><td>Location:</td><td>{{ inspection.electrical_location }}</td></tr>{% endif %}
  </table>
  {% endif %}

  {% if has_hvac_data %}
  <h3 class="subsection-title">HVAC</h3>
  <table class="detail-table">
    {% if inspection.hvac_brand %}<tr><td>Brand:</td><td>{{ inspection.hvac_brand }}</td></tr>{% endif %}
    {% if inspection.hvac_age %}<tr><td>Age:</td><td>{{ inspection.hvac_age }} years</td></tr>{% endif %}
    {% if inspection.hvac_model %}<tr><td>Model:</td><td>{{ inspection.hvac_model }}</td></tr>{% endif %}
    {% if inspection.hvac_series %}<tr><td>Series:</td><td>{{ inspection.hvac_series }}</td></tr>{% endif %}
  </table>
  {% endif %}

  {% if wind_mit_inspection %}
  <h3 class="subsection-title">Wind Mitigation</h3>
  <table class="detail-table">
    <tr><td>Doors Protected:</td><td>{{ "Yes" if inspection.doors_protected else "No" }}</td></tr>
    <tr><td>Windows Protected:</td><td>{{ "Yes" if inspection.windows_protected else "No" }}</td></tr>
  </table>
  {% endif %}

  {% if inspection.additional_notes %}
  <h3 class="subsection-title">Additional Notes</h3>
  <p style="font-size: 9pt; line-height: 1.6; margin-top: 4pt;">{{ inspection.additional_notes }}</p>
  {% endif %}

</div>
{% endif %}

{# ── EXECUTIVE SUMMARY ──────────────────────────────────────────────────── #}
<div class="page-section">
  <div class="section-header">Executive Summary</div>

  <div class="summary-counts">
    <div class="count-block">
      <div class="count-number">{{ total_count }}</div>
      <div class="count-label">Total Findings</div>
    </div>
    <div class="count-block">
      <div class="count-number count-defective">{{ defective_count }}</div>
      <div class="count-label">Defective Items</div>
    </div>
  </div>

  {% if sections_with_findings %}
  <table class="summary-table">
    <thead>
      <tr>
        <th>Section</th>
        <th>Total</th>
        <th>Defective</th>
        <th>Items Requiring Attention</th>
      </tr>
    </thead>
    <tbody>
      {% for row in summary_rows %}
      <tr>
        <td>{{ row.label }}</td>
        <td>{{ row.total }}</td>
        <td style="color: {% if row.defective > 0 %}#dc2626{% else %}#666{% endif %}; font-weight: {% if row.defective > 0 %}700{% else %}400{% endif %}">{{ row.defective }}</td>
        <td>{{ row.attention_items | join(", ") }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% endif %}

  {% if defective_items %}
  <div class="defective-list">
    <h3>Items Requiring Immediate Attention</h3>
    <ul>
      {% for item in defective_items %}
      <li>{{ item }}</li>
      {% endfor %}
    </ul>
  </div>
  {% endif %}
</div>

{# ── PER-SECTION PAGES ──────────────────────────────────────────────────── #}
{% for section_key, section_findings in sections.items() %}
{% if section_findings %}
{% set disclaimer = section_disclaimers[section_key] if section_key in section_disclaimers else section_disclaimers['_DEFAULT'] %}
<div class="page-section">
  <div class="section-header">{{ section_labels[section_key] }}</div>

  <p class="disclaimer">{{ disclaimer }}</p>

  {# ── SECTION METADATA (material/type selections) ──────────────────── #}
  {% set obs_data = section_observations.get(section_key) %}
  {% if obs_data and obs_data.metadata %}
  <div class="obs-metadata">
    <h4 class="obs-subtitle">Section Details</h4>
    <table class="obs-meta-table">
      {% for field_key, field_def in obs_data.catalog.metadata_fields.items() %}
      {% set field_val = obs_data.metadata.get(field_key) %}
      {% if field_val %}
      <tr>
        <td class="obs-meta-label">{{ field_def.label }}:</td>
        <td class="obs-meta-value">
          {% if field_val is iterable and field_val is not string %}
            {{ field_val | join(", ") }}
          {% else %}
            {{ field_val }}
          {% endif %}
        </td>
      </tr>
      {% endif %}
      {% endfor %}
    </table>
  </div>
  {% endif %}

  {# ── COMPONENT CONDITIONS (condition items) ────────────────────────── #}
  {% if obs_data and obs_data.observations %}
  <div class="obs-conditions">
    <h4 class="obs-subtitle">Component Conditions</h4>
    <table class="obs-items-table">
      <thead>
        <tr>
          <th class="obs-col-item">Component</th>
          <th class="obs-col-cond">Condition</th>
          <th class="obs-col-notes">Notes</th>
        </tr>
      </thead>
      <tbody>
        {% for obs in obs_data.observations %}
        <tr>
          <td class="obs-col-item">
            {% if obs.room_label %}{{ obs.room_label }} — {% endif %}
            {{ obs.item_label }}
          </td>
          <td class="obs-col-cond">
            <span class="cond-badge" style="background: {{ condition_colors.get(obs.condition, '#ffffff') }}">
              {{ obs.condition | replace("N_A", "N/A") }}
            </span>
          </td>
          <td class="obs-col-notes">{{ obs.observations or "" }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}

  {% if obs_data and (obs_data.metadata or obs_data.observations) %}
  <hr class="obs-divider">
  {% endif %}

  <table class="findings-table">
    <thead>
      <tr>
        <th class="col-num">#</th>
        <th class="col-item">Item</th>
        <th class="col-cond">Condition</th>
        <th class="col-obs">Observations</th>
      </tr>
    </thead>
    <tbody>
      {% for f in section_findings %}
      <tr>
        <td class="col-num">{{ loop.index }}</td>
        <td class="col-item">{{ f.item }}</td>
        <td class="col-cond">
          {% if f.condition %}
          <span class="cond-badge" style="background: {{ condition_colors[f.condition.value] }}">
            {{ f.condition.value | replace("N_A", "N/A") }}
          </span>
          {% endif %}
        </td>
        <td class="col-obs">{{ f.observations or "" }}</td>
      </tr>
      {% set f_photos = finding_photos.get(f.id | string, []) %}
      {% if f_photos %}
      <tr style="border-bottom: 1px solid #e5e7eb;">
        <td></td>
        <td colspan="3" style="padding: 4pt 8pt 8pt 0;">
          <table style="border-collapse: collapse; width: 100%;"><tr>
            <td style="width: 76pt; padding-right: 6pt; vertical-align: top;">{% if f_photos|length > 0 %}<img src="{{ f_photos[0].view_url }}" style="width: 70pt; height: 100pt; display: block;">{% endif %}</td>
            <td style="width: 76pt; padding-right: 6pt; vertical-align: top;">{% if f_photos|length > 1 %}<img src="{{ f_photos[1].view_url }}" style="width: 70pt; height: 100pt; display: block;">{% endif %}</td>
            <td style="width: 76pt; vertical-align: top;">{% if f_photos|length > 2 %}<img src="{{ f_photos[2].view_url }}" style="width: 70pt; height: 100pt; display: block;">{% endif %}</td>
            <td style="vertical-align: top;"></td>
          </tr></table>
        </td>
      </tr>
      {% endif %}
      {% endfor %}
    </tbody>
  </table>

  <div class="certification">
    <p>I certify that I am authorized to sign this inspection on behalf of
    {{ brand_name }} and that, by the signature hereinafter made, {{ brand_name }}
    is duly bound by the terms and conditions of the certification. This report
    expresses no guarantee on the {{ section_labels[section_key] }} components. I further certify
    that I have no interest, present or prospective, in the property, buyer, seller,
    broker, mortgage or other party involved in the transaction. Only the condition
    of the system as of this date is warranted by this inspection.</p>
    <div class="signature-line">
      <span>Signature of Inspector: {{ inspector_name or "________________" }}</span>
    </div>
  </div>
</div>
{% endif %}
{% endfor %}

</body>
</html>
"""

_jinja_env = Environment(autoescape=select_autoescape(["html"]))


def _datefmt(value: object) -> str:
    from datetime import datetime
    if isinstance(value, datetime):
        return value.strftime("%B %d, %Y")
    return str(value)


def _format_bathrooms(num_bathrooms: int, num_half_bathrooms: int) -> str:
    if num_half_bathrooms > 0:
        total = num_bathrooms + num_half_bathrooms * 0.5
        return f"{total:g} Baths"
    return f"{num_bathrooms} Baths"


_jinja_env.filters["datefmt"] = _datefmt


async def _build_inspection_html(
    inspection_id: uuid.UUID,
    session: AsyncSession,
) -> tuple[str, dict]:
    inspection = await get_inspection(inspection_id, session)
    if inspection is None:
        raise ValueError(f"inspection {inspection_id} not found")

    findings = await list_findings_by_inspection(inspection_id, session)
    tenant = await get_tenant_by_id(session)

    theme: dict = tenant.theme_config if tenant and tenant.theme_config else {}
    brand_name: str = theme.get("brand_name") or (tenant.name if tenant else "Home Inspections")
    logo_url: str | None = theme.get("logo_url")
    primary_color: str = theme.get("primary_color") or "#2d5fa3"
    inspector_name: str | None = theme.get("inspector_name")
    license_number: str | None = theme.get("license_number")
    phone: str | None = theme.get("phone")
    website: str | None = theme.get("website")
    email: str | None = theme.get("email")
    mold_license: str | None = theme.get("mold_license")
    nachi_license: str | None = theme.get("nachi_license")
    font_family_raw: str | None = theme.get("font_family")
    font_family = font_family_raw or "sans-serif"
    font_import_url: str | None = None
    if font_family_raw:
        encoded = font_family_raw.replace(" ", "+")
        font_import_url = f"https://fonts.googleapis.com/css2?family={encoded}&display=swap"

    # Build refreshed presigned URLs without mutating ORM objects.
    finding_photos: dict[str, list] = {}
    try:
        from app.modules.media.s3 import generate_view_url
        for f in findings:
            if f.photos:
                finding_photos[str(f.id)] = [
                    {"key": p["key"], "view_url": generate_view_url(p["key"])}
                    for p in f.photos
                ]
    except Exception:
        pass  # S3 not configured; photos will not appear in PDF

    from app.modules.observations.service import get_section_observations
    from app.modules.observations.catalog import SECTION_CATALOG

    _FINDINGS_TO_CATALOG = {
        "FRONT": "FRONT", "EXTERIOR": "EXTERIOR", "INSULATION": "INSULATION_VENTILATION",
        "PLUMBING": "PLUMBING", "STRUCTURAL": "STRUCTURAL", "ELECTRICAL": "ELECTRICAL",
        "ROOF": "ROOF", "KITCHEN": "INTERIOR_KITCHEN_DINING", "INTERIOR": None,
        "AIR_CONDITIONING": "AIR_CONDITIONING", "COMMENTS": None,
        "COST_ESTIMATION": None, "COUNTY_INFO": None, "DISCLOSURE": None,
        "BEDROOMS": "BEDROOMS", "BATHROOMS": "BATHROOMS",
    }

    section_observations: dict = {}
    section_metadata_data: dict = {}
    try:
        for findings_key, catalog_key in _FINDINGS_TO_CATALOG.items():
            if catalog_key and catalog_key in SECTION_CATALOG:
                obs_data = await get_section_observations(
                    inspection_id, catalog_key, session
                )
                section_observations[findings_key] = obs_data
                section_metadata_data[findings_key] = obs_data.metadata
    except Exception:
        pass  # observations not available

    sections: dict[str, list] = defaultdict(list)
    for f in findings:
        key = f.section.value if hasattr(f.section, "value") else str(f.section)
        sections[key].append(f)

    ordered_section_keys = [
        s.value for s in Section
        if s.value in sections and sections[s.value]
    ]
    ordered_sections = {k: sections[k] for k in ordered_section_keys}

    total_count = len(findings)
    defective_count = sum(
        1 for f in findings
        if f.condition is not None and f.condition == Condition.DEFECTIVE
    )

    summary_rows = []
    defective_items: list[str] = []
    for key in ordered_section_keys:
        sec_findings = sections[key]
        sec_total = len(sec_findings)
        sec_defective = sum(
            1 for f in sec_findings
            if f.condition is not None and f.condition == Condition.DEFECTIVE
        )
        attention = [
            f.item for f in sec_findings
            if f.condition is not None and f.condition == Condition.DEFECTIVE
        ]
        defective_items.extend(
            f"{_SECTION_LABELS.get(key, key)}: {f.item}"
            for f in sec_findings
            if f.condition is not None and f.condition == Condition.DEFECTIVE
        )
        summary_rows.append({
            "label": _SECTION_LABELS.get(key, key),
            "total": sec_total,
            "defective": sec_defective,
            "attention_items": attention,
        })

    report_number = (
        inspection.full_report_number
        or str(inspection.id)[:8].upper()
    )
    inspection_type_labels = [
        _INSPECTION_TYPE_LABELS.get(t.value if hasattr(t, "value") else str(t), str(t))
        for t in inspection.inspection_types
    ]

    has_roof_data = any([
        inspection.roof_permit_number, inspection.roof_date,
        inspection.roof_style, inspection.roof_type,
    ])
    has_water_heater_data = any([
        inspection.water_heater_type, inspection.water_heater_location,
        inspection.water_heater_capacity,
    ])
    has_electrical_data = any([
        inspection.electrical_brand, inspection.electrical_amps,
        inspection.electrical_location,
    ])
    has_hvac_data = any([
        inspection.hvac_brand, inspection.hvac_age,
        inspection.hvac_model, inspection.hvac_series,
    ])
    bathrooms_display = _format_bathrooms(
        inspection.num_bathrooms, inspection.num_half_bathrooms
    )
    has_property_details = any([
        inspection.year_built, inspection.adj_sqft,
        inspection.gate_code, inspection.lockbox,
        inspection.num_bedrooms, inspection.num_bathrooms,
        has_roof_data, has_water_heater_data,
        has_electrical_data, has_hvac_data,
        inspection.additional_notes,
    ])
    wind_mit_inspection = any(
        (t.value if hasattr(t, "value") else str(t)) == "WIND_MITIGATION"
        for t in inspection.inspection_types
    )

    template = _jinja_env.from_string(_HTML_TEMPLATE)
    html = template.render(
        inspection=inspection,
        brand_name=brand_name,
        logo_url=logo_url,
        primary_color=primary_color,
        inspector_name=inspector_name,
        license_number=license_number,
        phone=phone,
        website=website,
        email=email,
        mold_license=mold_license,
        nachi_license=nachi_license,
        font_family=font_family,
        font_import_url=font_import_url,
        report_number=report_number,
        inspection_type_labels=inspection_type_labels,
        sections=ordered_sections,
        section_labels=_SECTION_LABELS,
        section_disclaimers=_SECTION_DISCLAIMERS,
        condition_colors=_CONDITION_COLORS,
        total_count=total_count,
        defective_count=defective_count,
        summary_rows=summary_rows,
        defective_items=defective_items,
        finding_photos=finding_photos,
        section_observations=section_observations,
        section_metadata_data=section_metadata_data,
        sections_with_findings=bool(ordered_sections),
        has_roof_data=has_roof_data,
        has_water_heater_data=has_water_heater_data,
        has_electrical_data=has_electrical_data,
        has_hvac_data=has_hvac_data,
        has_property_details=has_property_details,
        wind_mit_inspection=wind_mit_inspection,
        bathrooms_display=bathrooms_display,
    )

    section_meta = {
        "section_count": len(ordered_section_keys),
        "sections_included": [_SECTION_LABELS.get(k, k) for k in ordered_section_keys],
    }
    return html, section_meta


async def generate_full_inspection_pdf(
    inspection_id: uuid.UUID,
    session: AsyncSession,
) -> bytes:
    async with log_agent_execution(
        session,
        agent_name="report_generator",
        trigger_type="user_request",
        trigger_ref=str(inspection_id),
        input_summary={"inspection_id": str(inspection_id), "template": "FULL"},
    ) as entry:
        html, section_meta = await _build_inspection_html(inspection_id, session)
        entry.input_summary["section_count"] = section_meta["section_count"]
        pdf_bytes = weasyprint.HTML(string=html).write_pdf()
        entry.decision = "report_generated"
        entry.output_summary = {
            "pdf_size_bytes": len(pdf_bytes),
            "sections_included": section_meta["sections_included"],
        }
    return pdf_bytes


async def generate_full_inspection_html(
    inspection_id: uuid.UUID,
    session: AsyncSession,
) -> str:
    """Return raw HTML before WeasyPrint conversion (debug only)."""
    html, _ = await _build_inspection_html(inspection_id, session)
    return html
