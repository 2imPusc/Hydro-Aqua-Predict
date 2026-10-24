/** Station hazards (Track G) and active storms (Track D). */
import { getJson } from './client'
import type { ActiveStormsResponse, StationHazardsResponse } from '../types/alerts'

type Signal = AbortSignal | undefined

export const getActiveStorms = (signal?: Signal) => getJson<ActiveStormsResponse>('/research/storms/active', signal)
export type HazardSource = 'live' | 'replay'
export const getStationHazards = (signal?: Signal, source: HazardSource = 'live', daysBefore = 1) =>
  getJson<StationHazardsResponse>(source === 'replay' ? `/research/hazards/stations?source=replay&days_before=${daysBefore}` : '/research/hazards/stations', signal)
