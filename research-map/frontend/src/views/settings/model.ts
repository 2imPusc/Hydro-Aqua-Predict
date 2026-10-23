/**
 * Pure draft logic for the alert-tier editor: scope merge, editable-field
 * updates, diff and client validation (mirrors C1; the server re-validates).
 * Only `thresholds`, `actions_vi`, `persistence_days` and `scopes` are ever written.
 */
import type { AlertConfig, AlertConfigChange, EditableField, ExposureClass, HazardConfig, HazardOverride, ScopeOverrides } from '../../types/alerts'

export type Scope = { kind: 'default' } | { kind: 'class'; id: ExposureClass } | { kind: 'station'; id: string }
export const EDITABLE: EditableField[] = ['thresholds', 'persistence_days', 'actions_vi']
export const CLASSES: ExposureClass[] = ['sheltered', 'semi', 'exposed']
export const CLASS_LABEL: Record<ExposureClass, string> = { sheltered: 'Kín gió', semi: 'Bán kín', exposed: 'Hở' }
export const FIELD_LABEL: Record<EditableField, string> = { thresholds: 'ngưỡng', persistence_days: 'số ngày liên tục', actions_vi: 'hành động' }

export const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T
const sortTiers = (keys: string[]) => [...keys].sort((a, b) => Number(a) - Number(b))
export const tierKeys = (hazard: HazardConfig) => sortTiers(Object.keys(hazard.thresholds))

export function scopeOverrides(config: AlertConfig, scope: Scope): ScopeOverrides | undefined {
  if (scope.kind === 'class') return config.scopes?.exposure_class?.[scope.id]
  if (scope.kind === 'station') return config.scopes?.station?.[scope.id]
  return undefined
}

/** Base hazard deep-merged with the scope's partial override (station layer is shown over the default). */
export function mergedHazard(config: AlertConfig, scope: Scope, id: string): HazardConfig {
  const base = config.hazards[id]
  const override = scopeOverrides(config, scope)?.[id]
  if (!override) return base
  const merged: HazardConfig = { ...base }
  for (const field of EDITABLE) {
    const part = override[field] as Record<string, unknown> | undefined
    if (part) (merged as Record<string, unknown>)[field] = { ...(base[field] ?? {}), ...part }
  }
  return merged
}

const same = (a: unknown, b: unknown) => (typeof a === 'number' && typeof b === 'number' && Number.isNaN(a) && Number.isNaN(b)) || a === b

/**
 * Set one editable leaf. `undefined` clears it (persistence only). In an override
 * scope, a value equal to the base removes the override key and empty objects are pruned.
 */
export function setLeaf(config: AlertConfig, scope: Scope, id: string, field: EditableField, tier: string, value: number | string | undefined): AlertConfig {
  const next = clone(config)
  // JSON round-trip turns NaN into null; restore the in-progress invalid marker.
  restoreNaN(config, next)
  if (scope.kind === 'default') {
    const hazard = next.hazards[id] as unknown as Record<string, Record<string, unknown> | undefined>
    const dict = { ...(hazard[field] ?? {}) }
    if (value === undefined) delete dict[tier]
    else dict[tier] = value
    if (field === 'persistence_days' && Object.keys(dict).length === 0) delete hazard[field]
    else hazard[field] = dict
    return next
  }
  next.scopes ??= { exposure_class: {}, station: {} }
  const bucket: Record<string, ScopeOverrides> = scope.kind === 'class'
    ? (next.scopes.exposure_class ??= {}) as Record<string, ScopeOverrides>
    : (next.scopes.station ??= {})
  const overrides: ScopeOverrides = bucket[scope.id] ?? {}
  const hazardOverride: HazardOverride = overrides[id] ?? {}
  const dict = { ...((hazardOverride[field] as Record<string, unknown> | undefined) ?? {}) }
  const baseValue = (next.hazards[id][field] as Record<string, unknown> | undefined)?.[tier]
  if (value === undefined || same(value, baseValue)) delete dict[tier]
  else dict[tier] = value
  if (Object.keys(dict).length) (hazardOverride as Record<string, unknown>)[field] = dict
  else delete hazardOverride[field]
  if (Object.keys(hazardOverride).length) overrides[id] = hazardOverride
  else delete overrides[id]
  // Exposure classes keep their (possibly empty) slot like the default file; empty stations are dropped.
  if (Object.keys(overrides).length || scope.kind === 'class') bucket[scope.id] = overrides
  else delete bucket[scope.id]
  return next
}

/** Clear every override of one hazard in a scope. */
export function resetHazardOverride(config: AlertConfig, scope: Scope, id: string): AlertConfig {
  const next = clone(config)
  restoreNaN(config, next)
  const overrides = scopeOverrides(next, scope)
  if (overrides) delete overrides[id]
  if (scope.kind === 'station' && overrides && !Object.keys(overrides).length) delete next.scopes.station[scope.id]
  return next
}

function restoreNaN(source: AlertConfig, target: AlertConfig) {
  for (const [id, hazard] of Object.entries(source.hazards)) {
    for (const [tier, value] of Object.entries(hazard.thresholds)) if (Number.isNaN(value)) target.hazards[id].thresholds[tier] = NaN
  }
  for (const kind of ['exposure_class', 'station'] as const) {
    for (const [scopeId, overrides] of Object.entries((source.scopes?.[kind] ?? {}) as Record<string, ScopeOverrides>)) {
      for (const [id, override] of Object.entries(overrides ?? {})) {
        for (const [tier, value] of Object.entries(override.thresholds ?? {})) {
          if (Number.isNaN(value)) ((target.scopes[kind] as Record<string, ScopeOverrides>)[scopeId][id].thresholds as Record<string, number>)[tier] = NaN
        }
      }
    }
  }
}

/** Is this leaf overridden in the scope (shown as a diff vs the base)? */
export function isOverridden(config: AlertConfig, scope: Scope, id: string, field: EditableField, tier: string): boolean {
  const part = scopeOverrides(config, scope)?.[id]?.[field] as Record<string, unknown> | undefined
  return !!part && tier in part
}

export function countOverrides(overrides: ScopeOverrides | undefined): number {
  let count = 0
  for (const override of Object.values(overrides ?? {})) for (const field of EDITABLE) count += Object.keys((override[field] as object | undefined) ?? {}).length
  return count
}

/* ---------------------------------------------------------------- diff */

function leaves(config: AlertConfig): Map<string, unknown> {
  const out = new Map<string, unknown>()
  const addHazard = (prefix: string, hazard: HazardOverride | undefined) => {
    for (const field of EDITABLE) for (const [tier, value] of Object.entries((hazard?.[field] as Record<string, unknown> | undefined) ?? {})) out.set(`${prefix}.${field}.${tier}`, value)
  }
  for (const [id, hazard] of Object.entries(config.hazards)) addHazard(`hazards.${id}`, hazard)
  for (const kind of ['exposure_class', 'station'] as const) {
    for (const [scopeId, overrides] of Object.entries((config.scopes?.[kind] ?? {}) as Record<string, ScopeOverrides>)) {
      for (const [id, override] of Object.entries(overrides ?? {})) addHazard(`scopes.${kind}.${scopeId}.${id}`, override)
    }
  }
  return out
}

/** Changes restricted to editable leaves, in the server's `{path, old, new}` shape (`null` = absent). */
export function diffConfig(before: AlertConfig, after: AlertConfig): AlertConfigChange[] {
  const a = leaves(before), b = leaves(after)
  const paths = [...new Set([...a.keys(), ...b.keys()])]
  return paths.filter(path => !same(a.get(path), b.get(path))).map(path => ({ path, old: a.get(path) ?? null, new: b.get(path) ?? null }))
}

/** "hazards.storm_wind.thresholds.2" → readable Vietnamese. */
export function describePath(path: string, config: AlertConfig | null, stationName?: (id: string) => string): { scope: string; hazard: string; field: string } {
  const parts = path.split('.')
  let scope = 'Mặc định', rest = parts.slice(1)
  if (parts[0] === 'scopes') {
    scope = parts[1] === 'exposure_class' ? `Lớp ${CLASS_LABEL[parts[2] as ExposureClass] ?? parts[2]}` : `Trạm ${stationName?.(parts[2]) ?? parts[2]}`
    rest = parts.slice(3)
  }
  const [hazardId, field, tier] = rest
  const hazard = config?.hazards[hazardId]?.label_vi ?? hazardId
  return { scope, hazard, field: `${FIELD_LABEL[field as EditableField] ?? field}${tier ? ` bậc ${tier}` : ''}` }
}

/* ---------------------------------------------------------- validation */

export type FieldErrors = Record<string, string>
const leafKey = (field: EditableField, tier: string) => `${field}.${tier}`

/** Errors per leaf for one (merged) hazard: number, guardrails, strict monotonic order, persistence ≥ 1 day. */
export function validateHazard(hazard: HazardConfig): FieldErrors {
  const errors: FieldErrors = {}
  const tiers = tierKeys(hazard)
  const up = hazard.direction === 'ge'
  let previous: { tier: string; value: number } | null = null
  for (const tier of tiers) {
    const value = hazard.thresholds[tier]
    const key = leafKey('thresholds', tier)
    if (typeof value !== 'number' || !Number.isFinite(value)) { errors[key] = 'Nhập một số'; continue }
    const min = hazard.guardrails?.min?.[tier], max = hazard.guardrails?.max?.[tier]
    if (min != null && value < min) errors[key] = `Thấp hơn giới hạn cho phép (${fmt(min)})`
    else if (max != null && value > max) errors[key] = `Cao hơn giới hạn cho phép (${fmt(max)})`
    else if (previous && (up ? value <= previous.value : value >= previous.value)) errors[key] = `Phải ${up ? 'lớn' : 'nhỏ'} hơn bậc ${previous.tier} (${fmt(previous.value)})`
    previous = { tier, value }
  }
  for (const [tier, days] of Object.entries(hazard.persistence_days ?? {})) {
    if (!Number.isInteger(days) || days < 1) errors[leafKey('persistence_days', tier)] = 'Số ngày nguyên ≥ 1'
  }
  for (const tier of tiers) if (!String(hazard.actions_vi?.[tier] ?? '').trim()) errors[leafKey('actions_vi', tier)] = 'Không để trống'
  return errors
}

export type ScopeIssue = { scope: Scope; hazard: string; key: string; message: string }

/** Validates the default hazards and every scope that holds overrides. */
export function validateConfig(config: AlertConfig): ScopeIssue[] {
  const scopes: Scope[] = [{ kind: 'default' }]
  for (const id of Object.keys(config.scopes?.exposure_class ?? {})) if (countOverrides(config.scopes.exposure_class[id as ExposureClass])) scopes.push({ kind: 'class', id: id as ExposureClass })
  for (const id of Object.keys(config.scopes?.station ?? {})) if (countOverrides(config.scopes.station[id])) scopes.push({ kind: 'station', id })
  const issues: ScopeIssue[] = []
  for (const scope of scopes) {
    for (const id of Object.keys(config.hazards)) {
      for (const [key, message] of Object.entries(validateHazard(mergedHazard(config, scope, id)))) issues.push({ scope, hazard: id, key, message })
    }
  }
  return issues
}

export const sameScope = (a: Scope, b: Scope) => a.kind === b.kind && (a.kind === 'default' || (a as { id: string }).id === (b as { id: string }).id)
export const scopeName = (scope: Scope, stationName?: (id: string) => string) =>
  scope.kind === 'default' ? 'Mặc định' : scope.kind === 'class' ? `Lớp ${CLASS_LABEL[scope.id]}` : `Trạm ${stationName?.(scope.id) ?? scope.id}`

export function fmt(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') return Number.isFinite(value) ? value.toLocaleString('vi-VN', { maximumFractionDigits: 3 }) : '—'
  return String(value)
}

/** Copy only editable fields of a saved version onto the current effective config (restore → new draft). */
export function restoreFrom(current: AlertConfig, version: AlertConfig): AlertConfig {
  const next = clone(current)
  for (const [id, hazard] of Object.entries(next.hazards)) {
    const source = version.hazards?.[id]
    if (!source) continue
    hazard.thresholds = { ...source.thresholds }
    hazard.actions_vi = { ...source.actions_vi }
    if (source.persistence_days) hazard.persistence_days = { ...source.persistence_days }
    else delete hazard.persistence_days
  }
  const pick = (overrides: ScopeOverrides | undefined): ScopeOverrides => {
    const out: ScopeOverrides = {}
    for (const [id, override] of Object.entries(overrides ?? {})) {
      if (!next.hazards[id]) continue
      const kept: HazardOverride = {}
      for (const field of EDITABLE) if (override[field]) (kept as Record<string, unknown>)[field] = { ...(override[field] as object) }
      if (Object.keys(kept).length) out[id] = kept
    }
    return out
  }
  const exposure: Partial<Record<ExposureClass, ScopeOverrides>> = {}
  for (const id of CLASSES) exposure[id] = pick(version.scopes?.exposure_class?.[id])
  const station: Record<string, ScopeOverrides> = {}
  for (const [id, overrides] of Object.entries(version.scopes?.station ?? {})) { const kept = pick(overrides); if (Object.keys(kept).length) station[id] = kept }
  next.scopes = { exposure_class: exposure, station }
  return next
}

/** Draft as sent to the server: NaN never leaves the client (validation blocks it anyway). */
export const toPayload = (config: AlertConfig): AlertConfig => clone(config)
