/** Station hazards (Track G) and active storms (Track D). */
import { getJson } from './client'
import type { ActiveStormsResponse, StationHazardsResponse } from '../types/alerts'

type Signal = AbortSignal | undefined

export const getActiveStorms = (signal?: Signal) => getJson<ActiveStormsResponse>('/research/storms/active', signal)
export const getStationHazards = (signal?: Signal) => getJson<StationHazardsResponse>('/research/hazards/stations', signal)
