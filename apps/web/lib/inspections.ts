// apps/web/lib/inspections.ts
export type InspectionStatus =
  | "DRAFT"
  | "IN_FIELD"
  | "PENDING_REVIEW"
  | "PUBLISHED"
  | "DELIVERED"

// Matches the real InspectionTypeEnum from the API.
export const INSPECTION_TYPES = [
  { value: "FULL_INSPECTION", label: "Full Inspection" },
  { value: "WIND_MITIGATION", label: "Wind Mitigation" },
  { value: "FOUR_POINT", label: "4-Point" },
  { value: "MOLD_INSPECTION", label: "Mold Inspection" },
  { value: "TERMITES", label: "Termites" },
  { value: "ROOF_CERTIFICATION", label: "Roof Certification" },
  { value: "OPENING_PROTECTION", label: "Opening Protection" },
  { value: "SEWER_INSPECTION", label: "Sewer Inspection" },
  { value: "LEAD_PAINT_INSPECTION", label: "Lead Paint Inspection" },
  { value: "WATER_QUALITY_TEST", label: "Water Quality Test" },
] as const

export type InspectionType = (typeof INSPECTION_TYPES)[number]["value"]

export const PAYMENT_TIMINGS = [
  { value: "AT_PROPERTY", label: "At Property" },
  { value: "AT_DELIVERY", label: "At Delivery" },
  { value: "AFTER_DELIVERY", label: "After Delivery" },
] as const

export type PaymentTiming = (typeof PAYMENT_TIMINGS)[number]["value"]

export interface NewInspectionPayload {
  propertyAddress: string
  scheduledAt: string
  inspectionTypes: InspectionType[]
  totalFee: number
  paymentTiming: PaymentTiming
  num_bedrooms: number
  num_bathrooms: number
  num_half_bathrooms: number
}

export interface Inspection {
  id: string
  property_address: string
  status: InspectionStatus
  scheduled_at: string // ISO datetime
  inspection_types: InspectionType[]
  total_fee: number
}

export const STATUS_LABELS: Record<InspectionStatus, string> = {
  DRAFT: "Draft",
  IN_FIELD: "In Field",
  PENDING_REVIEW: "Pending Review",
  PUBLISHED: "Published",
  DELIVERED: "Delivered",
}

export const INSPECTION_TYPE_LABELS: Record<InspectionType, string> = {
  FULL_INSPECTION: "Full Inspection",
  WIND_MITIGATION: "Wind Mitigation",
  FOUR_POINT: "4-Point",
  MOLD_INSPECTION: "Mold",
  TERMITES: "Termites",
  ROOF_CERTIFICATION: "Roof Cert",
  OPENING_PROTECTION: "Opening Prot.",
  SEWER_INSPECTION: "Sewer",
  LEAD_PAINT_INSPECTION: "Lead Paint",
  WATER_QUALITY_TEST: "Water Quality",
}

export const ALL_STATUSES: InspectionStatus[] = [
  "DRAFT",
  "IN_FIELD",
  "PENDING_REVIEW",
  "PUBLISHED",
  "DELIVERED",
]

// Mock data kept for hooks/use-inspections.ts (legacy; not used by the live route).
export const MOCK_INSPECTIONS: Inspection[] = [
  {
    id: "insp_001",
    property_address: "1420 Brickell Ave, Miami, FL 33131",
    status: "IN_FIELD",
    scheduled_at: "2026-06-22T13:00:00.000Z",
    inspection_types: ["FULL_INSPECTION", "WIND_MITIGATION"],
    total_fee: 425.0,
  },
  {
    id: "insp_002",
    property_address: "88 Lake Eola Dr, Orlando, FL 32801",
    status: "PENDING_REVIEW",
    scheduled_at: "2026-06-20T15:30:00.000Z",
    inspection_types: ["FOUR_POINT"],
    total_fee: 275.0,
  },
  {
    id: "insp_003",
    property_address: "305 Bayshore Blvd, Tampa, FL 33606",
    status: "PUBLISHED",
    scheduled_at: "2026-06-18T14:00:00.000Z",
    inspection_types: ["FULL_INSPECTION", "ROOF_CERTIFICATION"],
    total_fee: 480.0,
  },
  {
    id: "insp_004",
    property_address: "742 Las Olas Blvd, Fort Lauderdale, FL 33301",
    status: "DELIVERED",
    scheduled_at: "2026-06-15T12:30:00.000Z",
    inspection_types: ["WIND_MITIGATION", "FOUR_POINT"],
    total_fee: 350.0,
  },
  {
    id: "insp_005",
    property_address: "19 Beach Dr NE, St. Petersburg, FL 33701",
    status: "DRAFT",
    scheduled_at: "2026-06-25T17:00:00.000Z",
    inspection_types: ["FULL_INSPECTION"],
    total_fee: 320.0,
  },
  {
    id: "insp_006",
    property_address: "2100 Atlantic Ave, Daytona Beach, FL 32118",
    status: "DELIVERED",
    scheduled_at: "2026-06-12T16:00:00.000Z",
    inspection_types: ["SEWER_INSPECTION", "MOLD_INSPECTION"],
    total_fee: 290.0,
  },
  {
    id: "insp_007",
    property_address: "560 Gulf Shore Blvd, Naples, FL 34102",
    status: "IN_FIELD",
    scheduled_at: "2026-06-23T13:30:00.000Z",
    inspection_types: ["FULL_INSPECTION", "WIND_MITIGATION", "ROOF_CERTIFICATION"],
    total_fee: 500.0,
  },
  {
    id: "insp_008",
    property_address: "311 Clematis St, West Palm Beach, FL 33401",
    status: "PUBLISHED",
    scheduled_at: "2026-06-19T18:00:00.000Z",
    inspection_types: ["FOUR_POINT", "MOLD_INSPECTION"],
    total_fee: 365.0,
  },
]

export function formatScheduledAt(iso: string): string {
  const date = new Date(iso)
  const datePart = date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  })
  const timePart = date.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
  })
  return `${datePart} · ${timePart}`
}

export function formatFee(fee: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(fee)
}
