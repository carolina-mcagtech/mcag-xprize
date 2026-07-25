# InspectIQ — Home Inspection SaaS

> Production-grade multi-tenant SaaS for licensed Florida home inspectors.  
> Built by MCAG Technologies LLC · [mcag-h0.vercel.app](https://mcag-h0.vercel.app)

[![Built for H0 Hackathon](https://img.shields.io/badge/H0%20Hackathon-AWS%20%2B%20Vercel-orange)](https://devpost.com)
[![Live on Vercel](https://img.shields.io/badge/Vercel-Live-black)](https://mcag-h0.vercel.app)
[![Backend on App Runner](https://img.shields.io/badge/AWS-App%20Runner-FF9900)](https://aws.amazon.com/apprunner/)

---

## Live Demo

| | |
|---|---|
| **URL** | https://mcag-h0.vercel.app |
| **Email** | `demo@inspectiq.app` |
| **Password** | `InspectIQDemo2026!` |

> Built for the H0: Hack the Zero Stack hackathon — Vercel + AWS Databases. #H0Hackathon

---

## What is InspectIQ?

InspectIQ replaces paper forms and legacy software for licensed Florida home inspectors. It covers the full inspection workflow:

1. **Schedule** — create inspection with property details, inspection types, and fees
2. **Capture in the field** — document findings, component conditions, and photos from a mobile phone
3. **Generate report** — professional PDF with tenant branding delivered on demand
4. **Deliver** — mark inspection as delivered, report is write-locked

---

## Stack

| Layer | Technology |
|---|---|
| **Frontend** | Next.js 14 (App Router) · TypeScript · Tailwind · Vercel |
| **Backend** | FastAPI · SQLAlchemy 2.0 async · Python 3.12 · AWS App Runner |
| **Database** | Aurora PostgreSQL Serverless v2 · Row Level Security |
| **Auth** | AWS Cognito (JWT + custom `tenant_id` claim) |
| **Storage** | AWS S3 (presigned PUT URLs — photos never touch the backend) |
| **PDF** | WeasyPrint · Jinja2 templates |
| **IaC** | Terraform (`mcag-h0-infra` repo) |
| **CI/CD** | Docker · AWS ECR · App Runner auto-deploy |

---

## Architecture

### Multi-tenant RLS

Every table has Row Level Security enforced at the database layer. Tenant context flows from the JWT through a FastAPI middleware into every SQL query via `SET LOCAL app.current_tenant_id`. No application-level filtering. If the RLS policy is missing, the query returns nothing — not the wrong tenant's data.

### Inspector Identity

`inspector_id` is resolved from the JWT `sub` on the backend via `inspector_profiles.cognito_sub`. The frontend never sends database IDs — only business data.

### Photo Pipeline

```
Inspector phone → presigned PUT URL → S3
                                        ↓
                              Aurora (key + view URL)
                                        ↓
                              WeasyPrint PDF (presigned GET 24h)
```

### Inspection FSM

```
DRAFT → IN_FIELD → PENDING_REVIEW → PUBLISHED → DELIVERED
```

Write-locked at PUBLISHED and DELIVERED. Amendments require a new revision.

---

## Repo Structure

```
apps/
  api/     → FastAPI application
             modules: inspections, findings, observations,
             reports, tenants, inspectors, media, agreements
  web/     → Next.js 14 application
             App Router, Server + Client Components
docs/      → Architecture decisions
docker-compose.yml
```

---

## Inspection Schema

| Sections | Data Model |
|---|---|
| Structural, Exterior, Roof, Electrical, Plumbing, Air Conditioning, Insulation & Ventilation | Metadata + Component Conditions |
| Kitchen/Dining, Appliances, Laundry/Misc | Component Conditions |
| Bedrooms, Bathrooms | Dynamic room arrays (N rooms x condition items) |
| Front, Interior, Comments, Cost Estimation, County Info, Disclosure | Free-form findings |

---

## Key Engineering Decisions

- **RLS over application-level filtering** — security enforced at the database, not the ORM
- **Presigned PUT URLs** — S3 uploads bypass the backend entirely; bandwidth and latency stay low in the field
- **Server Components + debounced autosave** — Next.js App Router fetches data server-side; findings autosave 800ms after last keystroke without full page reloads
- **WeasyPrint for PDF** — server-side HTML to PDF with tenant branding; no headless Chrome dependency
- **Modular monolith** — single FastAPI app with module boundaries; no microservices until scale requires it

---

## Business

| | |
|---|---|
| **Company** | MCAG Technologies LLC · Florida |
| **Customer #1** | REBS Property Specialist LLC · $99/month · July 2026 |
| **Channel** | REBS inspection school · 30-60 graduates/year · near-zero CAC |
| **MRR targets** | $500 month 1 · $5,000 month 6 · $30,000 month 18 |

---

## Local Development

```bash
# Backend
cd apps/api
pip install -r requirements.txt
uvicorn app.main:app --reload

# Frontend
cd apps/web
npm install
npm run dev
```

Requires: AWS credentials (SSO), Aurora connection, Cognito user pool.

---

Built for H0: Hack the Zero Stack with Vercel v0 and AWS Databases · June 2026

\#H0Hackathon

## Pre-existing work disclosure

Per the hackathon rules ("You may reuse pre-existing templates, 
frameworks, boilerplates, or code, but you must clearly explain how 
your project utilizes any pre-existing work"), this repository was 
initialized from code developed prior to and during other hackathon 
efforts: the InspectIQ application core (FastAPI backend, Next.js 
frontend, multi-tenant PostgreSQL schema) and the InspectIQ agent 
pipeline (Google ADK, Vertex AI). The imported state is tagged 
`pre-existing-baseline`. Everything after that tag — the AI 
business-operations layer (support, onboarding, billing 
communications, and marketing agents with a unified agent execution 
log), the Google Cloud production deployment (Cloud Run, Cloud SQL, 
Secret Manager), Stripe billing integration, and the live business 
operation itself (real customers, real revenue) — was created during 
the Build with Gemini XPRIZE submission period. The diff between 
`pre-existing-baseline` and `HEAD` constitutes the work performed 
during the window.
