/** Alert-config admin client (Track B). No auth yet: owner decision 2026-10-23. */
import { getJson } from './client'
import type { AlertConfigResponse, AlertConfigVersion } from '../types/alerts'

type Signal = AbortSignal | undefined

export const getAlertConfig = (signal?: Signal) => getJson<AlertConfigResponse>('/admin/alert-config', signal)
export const getAlertConfigVersions = (signal?: Signal) =>
  getJson<{ status: string; versions: AlertConfigVersion[] }>('/admin/alert-config/versions', signal)
