// apps/web/app/api/inspections/route.ts
import { cookies } from "next/headers"
import { NextRequest, NextResponse } from "next/server"

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

export async function POST(req: NextRequest) {
  const token = cookies().get("id_token")?.value
  if (!token) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  let body: {
    propertyAddress: string
    scheduledAt: string
    inspectionTypes: string[]
    totalFee: number
    paymentTiming: string
    numBedrooms?: number
    numBathrooms?: number
    numHalfBathrooms?: number
    num_bedrooms?: number
    num_bathrooms?: number
    num_half_bathrooms?: number
  }
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ error: "Invalid request body" }, { status: 400 })
  }

  const apiBody = {
    property_address: body.propertyAddress,
    scheduled_at: body.scheduledAt,
    inspection_types: body.inspectionTypes,
    total_fee: String(body.totalFee),
    payment_timing: body.paymentTiming,
    num_bedrooms: body.num_bedrooms ?? body.numBedrooms ?? 0,
    num_bathrooms: body.num_bathrooms ?? body.numBathrooms ?? 0,
    num_half_bathrooms: body.num_half_bathrooms ?? body.numHalfBathrooms ?? 0,
  }

  const res = await fetch(`${API_BASE}/inspections`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(apiBody),
  })

  const data = await res.json().catch(() => null)
  return NextResponse.json(data, { status: res.status })
}
