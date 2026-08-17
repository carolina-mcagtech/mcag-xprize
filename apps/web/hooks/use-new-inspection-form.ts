"use client"

import { useCallback, useMemo, useState } from "react"
import type {
  InspectionType,
  NewInspectionPayload,
  PaymentTiming,
} from "@/lib/inspections"

export interface NewInspectionFormState {
  propertyAddress: string
  scheduledAt: string
  inspectionTypes: InspectionType[]
  totalFee: string
  paymentTiming: PaymentTiming | ""
  numBedrooms: string
  numBathrooms: string
  numHalfBathrooms: string
}

const INITIAL_STATE: NewInspectionFormState = {
  propertyAddress: "",
  scheduledAt: "",
  inspectionTypes: [],
  totalFee: "",
  paymentTiming: "",
  numBedrooms: "0",
  numBathrooms: "0",
  numHalfBathrooms: "0",
}

function parseFee(raw: string): number {
  const cleaned = raw.replace(/[^0-9.]/g, "")
  const value = Number.parseFloat(cleaned)
  return Number.isFinite(value) ? value : Number.NaN
}

export function useNewInspectionForm() {
  const [state, setState] = useState<NewInspectionFormState>(INITIAL_STATE)

  const setField = useCallback(
    <K extends keyof NewInspectionFormState>(
      key: K,
      value: NewInspectionFormState[K],
    ) => {
      setState((prev) => ({ ...prev, [key]: value }))
    },
    [],
  )

  const toggleInspectionType = useCallback((type: InspectionType) => {
    setState((prev) => {
      const exists = prev.inspectionTypes.includes(type)
      return {
        ...prev,
        inspectionTypes: exists
          ? prev.inspectionTypes.filter((t) => t !== type)
          : [...prev.inspectionTypes, type],
      }
    })
  }, [])

  const reset = useCallback(() => setState(INITIAL_STATE), [])

  const fee = useMemo(() => parseFee(state.totalFee), [state.totalFee])

  const isValid = useMemo(() => {
    return (
      state.propertyAddress.trim().length > 0 &&
      state.scheduledAt.trim().length > 0 &&
      state.inspectionTypes.length > 0 &&
      Number.isFinite(fee) &&
      fee > 0 &&
      state.paymentTiming !== ""
    )
  }, [state, fee])

  const getPayload = useCallback((): NewInspectionPayload => {
    console.log("payload bedrooms:", state.numBedrooms, parseInt(state.numBedrooms, 10))
    return {
      propertyAddress: state.propertyAddress.trim(),
      scheduledAt: state.scheduledAt,
      inspectionTypes: state.inspectionTypes,
      totalFee: fee,
      paymentTiming: state.paymentTiming as PaymentTiming,
      num_bedrooms: Math.max(0, parseInt(state.numBedrooms, 10) || 0),
      num_bathrooms: Math.max(0, parseInt(state.numBathrooms, 10) || 0),
      num_half_bathrooms: Math.max(0, parseInt(state.numHalfBathrooms, 10) || 0),
    }
  }, [state, fee])

  return {
    state,
    setField,
    toggleInspectionType,
    reset,
    isValid,
    getPayload,
  }
}
