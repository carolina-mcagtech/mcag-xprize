"use client"

import { Dialog } from "@base-ui/react/dialog"
import { Select } from "@base-ui/react/select"
import { Check, ChevronsUpDown, X } from "lucide-react"
import { useState } from "react"

import { AddressAutocomplete } from "@/components/ui/address-autocomplete"
import { Button } from "@/components/ui/button"
import { useNewInspectionForm } from "@/hooks/use-new-inspection-form"
import {
  INSPECTION_TYPES,
  PAYMENT_TIMINGS,
  type NewInspectionPayload,
} from "@/lib/inspections"
import { cn } from "@/lib/utils"

interface NewInspectionModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSubmit?: (payload: NewInspectionPayload) => Promise<void>
}

const labelClass = "text-sm font-medium text-foreground"
const inputClass =
  "h-9 w-full rounded-lg border border-input bg-background px-3 text-sm text-foreground shadow-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40"

export function NewInspectionModal({
  open,
  onOpenChange,
  onSubmit,
}: NewInspectionModalProps) {
  const form = useNewInspectionForm()
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function handleOpenChange(next: boolean) {
    if (submitting) return
    if (!next) {
      form.reset()
      setError(null)
    }
    onOpenChange(next)
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!form.isValid || submitting) return
    setError(null)
    setSubmitting(true)
    try {
      await onSubmit?.(form.getPayload())
      form.reset()
      onOpenChange(false)
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Something went wrong creating the inspection. Please try again.",
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={handleOpenChange}>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 z-50 bg-foreground/40 backdrop-blur-sm transition-opacity data-[ending-style]:opacity-0 data-[starting-style]:opacity-0" />
        <Dialog.Popup className="fixed left-1/2 top-1/2 z-50 flex max-h-[92vh] w-[calc(100vw-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-xl border border-border bg-card text-card-foreground shadow-2xl transition-all data-[ending-style]:scale-95 data-[ending-style]:opacity-0 data-[starting-style]:scale-95 data-[starting-style]:opacity-0">
          <header className="flex items-start justify-between gap-4 border-b border-border px-6 py-4">
            <div className="space-y-1">
              <Dialog.Title className="text-lg font-semibold text-foreground">
                New Inspection
              </Dialog.Title>
              <Dialog.Description className="text-sm text-muted-foreground">
                Schedule a new property inspection and its services.
              </Dialog.Description>
            </div>
            <Dialog.Close
              aria-label="Close"
              className="-mr-2 -mt-1 inline-flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/40 focus-visible:outline-none"
            >
              <X className="size-4" />
            </Dialog.Close>
          </header>

          <form
            onSubmit={handleSubmit}
            className="flex min-h-0 flex-1 flex-col"
          >
            <div className="flex flex-col gap-5 overflow-y-auto px-6 py-5">
              {/* Property Address */}
              <div className="flex flex-col gap-1.5">
                <label htmlFor="propertyAddress" className={labelClass}>
                  Property Address <span className="text-destructive">*</span>
                </label>
                <AddressAutocomplete
                  value={form.state.propertyAddress}
                  onChange={(v) => form.setField("propertyAddress", v)}
                  placeholder="123 Main St, Miami, FL 33101"
                  className={inputClass}
                />
              </div>

              {/* Scheduled At */}
              <div className="flex flex-col gap-1.5">
                <label htmlFor="scheduledAt" className={labelClass}>
                  Scheduled At <span className="text-destructive">*</span>
                </label>
                <input
                  id="scheduledAt"
                  type="datetime-local"
                  required
                  className={cn(inputClass, "max-w-full")}
                  style={{ colorScheme: "light" }}
                  value={form.state.scheduledAt}
                  onChange={(e) => form.setField("scheduledAt", e.target.value)}
                />
              </div>

              {/* Inspection Types */}
              <div className="flex flex-col gap-2">
                <span className={labelClass}>
                  Inspection Types <span className="text-destructive">*</span>
                </span>
                <div className="flex flex-wrap gap-2">
                  {INSPECTION_TYPES.map((type) => {
                    const selected = form.state.inspectionTypes.includes(
                      type.value,
                    )
                    return (
                      <button
                        key={type.value}
                        type="button"
                        aria-pressed={selected}
                        onClick={() => form.toggleInspectionType(type.value)}
                        className={cn(
                          "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors focus-visible:ring-3 focus-visible:ring-ring/40 focus-visible:outline-none",
                          selected
                            ? "border-primary bg-primary text-primary-foreground"
                            : "border-border bg-background text-foreground hover:bg-muted",
                        )}
                      >
                        {selected && <Check className="size-3" />}
                        {type.label}
                      </button>
                    )
                  })}
                </div>
              </div>

              {/* Total Fee */}
              <div className="flex flex-col gap-1.5">
                <label htmlFor="totalFee" className={labelClass}>
                  Total Fee <span className="text-destructive">*</span>
                </label>
                <div className="relative">
                  <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">
                    $
                  </span>
                  <input
                    id="totalFee"
                    type="text"
                    inputMode="decimal"
                    required
                    placeholder="425.00"
                    className={cn(inputClass, "pl-7")}
                    value={form.state.totalFee}
                    onChange={(e) => form.setField("totalFee", e.target.value)}
                    onBlur={(e) => {
                      const val = parseFloat(e.target.value.replace(/[^0-9.]/g, ""))
                      if (!isNaN(val)) form.setField("totalFee", val.toFixed(2))
                    }}
                  />
                </div>
              </div>

              {/* Payment Timing */}
              <div className="flex flex-col gap-1.5">
                <span className={labelClass}>
                  Payment Timing <span className="text-destructive">*</span>
                </span>
                <Select.Root
                  items={PAYMENT_TIMINGS}
                  value={form.state.paymentTiming || undefined}
                  onValueChange={(value) =>
                    form.setField("paymentTiming", (value ?? "") as never)
                  }
                >
                  <Select.Trigger
                    className={cn(
                      inputClass,
                      "flex items-center justify-between gap-2 text-left data-[popup-open]:border-ring",
                    )}
                  >
                    <Select.Value
                      className="data-[empty]:text-muted-foreground"
                      placeholder="Select payment timing"
                    />
                    <Select.Icon>
                      <ChevronsUpDown className="size-4 text-muted-foreground" />
                    </Select.Icon>
                  </Select.Trigger>
                  <Select.Portal>
                    <Select.Positioner
                      sideOffset={6}
                      className="z-[60] outline-none"
                    >
                      <Select.Popup className="max-h-[--available-height] min-w-[var(--anchor-width)] overflow-y-auto rounded-lg border border-border bg-popover p-1 text-popover-foreground shadow-lg transition-all data-[ending-style]:opacity-0 data-[starting-style]:opacity-0">
                        {PAYMENT_TIMINGS.map((option) => (
                          <Select.Item
                            key={option.value}
                            value={option.value}
                            className="flex cursor-default items-center justify-between gap-2 rounded-md px-3 py-1.5 text-sm outline-none select-none data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground"
                          >
                            <Select.ItemText>{option.label}</Select.ItemText>
                            <Select.ItemIndicator>
                              <Check className="size-4 text-primary" />
                            </Select.ItemIndicator>
                          </Select.Item>
                        ))}
                      </Select.Popup>
                    </Select.Positioner>
                  </Select.Portal>
                </Select.Root>
              </div>
              {/* Bedrooms & Bathrooms */}
              <div className="grid grid-cols-3 gap-4">
                <div className="flex flex-col gap-1.5">
                  <label htmlFor="numBedrooms" className={labelClass}>
                    Bedrooms
                  </label>
                  <input
                    id="numBedrooms"
                    type="number"
                    min={0}
                    max={10}
                    className={inputClass}
                    value={form.state.numBedrooms}
                    onChange={(e) => form.setField("numBedrooms", e.target.value)}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <label htmlFor="numBathrooms" className={labelClass}>
                    Bathrooms
                  </label>
                  <input
                    id="numBathrooms"
                    type="number"
                    min={0}
                    max={10}
                    className={inputClass}
                    value={form.state.numBathrooms}
                    onChange={(e) => form.setField("numBathrooms", e.target.value)}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <label htmlFor="numHalfBathrooms" className={labelClass}>
                    Half Baths
                  </label>
                  <input
                    id="numHalfBathrooms"
                    type="number"
                    min={0}
                    max={9}
                    className={inputClass}
                    value={form.state.numHalfBathrooms}
                    onChange={(e) => form.setField("numHalfBathrooms", e.target.value)}
                  />
                </div>
              </div>
            </div>

            <footer className="flex flex-col gap-3 border-t border-border px-6 py-4">
              {error && (
                <p
                  role="alert"
                  className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
                >
                  {error}
                </p>
              )}
              <div className="flex items-center justify-end gap-2">
                <Dialog.Close
                  render={
                    <Button type="button" variant="outline" disabled={submitting}>
                      Cancel
                    </Button>
                  }
                />
                <Button type="submit" disabled={!form.isValid || submitting}>
                  {submitting ? "Creating…" : "Create Inspection"}
                </Button>
              </div>
            </footer>
          </form>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
