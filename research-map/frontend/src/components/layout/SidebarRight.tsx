import { useMemo } from 'react'
import { AlertTriangle, Info, Radio, MapPin } from 'lucide-react'
import type { AquacultureMap, BathymetrySample, Layer, SensorLatest, Snapshot, Stations } from '../../types'
import { FlowLegend, RainLegend, WindLegend } from '../map/MapOverlays'

interface SidebarRightProps {
  snapshot: Snapshot | null
  sensorLatest: SensorLatest | null
  stations: Stations | null
  pilotStation: string
  aquacultureMap: AquacultureMap | null
  bathymetrySample: BathymetrySample | null
  enabled: Record<string, boolean>
  available: Layer[]
  mapDataMode: 'live' | 'mock'
}

export function SidebarRight(props: SidebarRightProps) {
  const { snapshot, sensorLatest, pilotStation, stations, aquacultureMap, bathymetrySample, enabled, available, mapDataMode } = props
  const advisories = useMemo(() => new Map(
    (aquacultureMap?.features ?? []).map(feature => [String(feature.properties?.station_serial ?? ''), feature.properties ?? {}]),
  ), [aquacultureMap])

  return (
    <aside className="w-80 flex flex-col gap-4 h-full overflow-y-auto p-4 z-10 pointer-events-none">

      {/* Stations Panel */}
      <div className="p-4 rounded-xl shadow-lg pointer-events-auto backdrop-blur-sm bg-white/95 border border-slate-200">
        <h3 className="font-bold text-slate-800 flex items-center justify-between mb-3 text-sm">
          <div className="flex items-center gap-2">
            <Radio size={16} className="text-emerald-500" />
            Theo dõi các trạm
          </div>
          <div className={`text-[9px] px-1.5 py-0.5 rounded uppercase tracking-wide ${aquacultureMap?.mode === 'mock' ? 'bg-purple-100 text-purple-700' : 'bg-slate-100 text-slate-500'}`}>
            {aquacultureMap?.status ?? 'loading...'} · {aquacultureMap?.mode ?? mapDataMode}
          </div>
        </h3>
        
        {aquacultureMap?.disclaimer && (
          <p className="text-[10px] text-slate-500 italic mb-3 leading-relaxed border-b border-slate-100 pb-2">
            {aquacultureMap.disclaimer}
          </p>
        )}
        
        {stations?.features?.length ? (
          <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
            {stations.features.map((station, idx) => {
              const stationProps = station.properties || {}
              const regional = aquacultureMap?.mode === 'mock' && aquacultureMap.features.length
                ? aquacultureMap.features[idx % aquacultureMap.features.length]?.properties
                : aquacultureMap?.features[0]?.properties
              const props = advisories.get(String(stationProps.station ?? '')) || regional || {}
              const isWatch = props.severity === 'WATCH'
              const isWarning = props.severity === 'WARNING'
              const isUnknown = props.severity === 'UNKNOWN' || !props.severity
              
              let borderColor = 'border-slate-200 bg-slate-50'
              if (isWarning) borderColor = 'border-red-200 bg-red-50'
              else if (isWatch) borderColor = 'border-orange-200 bg-orange-50'
              else if (isUnknown) borderColor = 'border-slate-300 bg-slate-100'
              
              let dotClass = 'bg-emerald-500'
              if (isWarning) dotClass = 'bg-red-600 animate-ping'
              else if (isWatch) dotClass = 'bg-orange-500 animate-pulse'
              else if (isUnknown) dotClass = 'bg-slate-400'
              
              let badgeClass = 'bg-emerald-100 text-emerald-700'
              if (isWarning) badgeClass = 'bg-red-100 text-red-700 font-bold'
              else if (isWatch) badgeClass = 'bg-orange-100 text-orange-700'
              else if (isUnknown) badgeClass = 'bg-slate-200 text-slate-700'
              
              let badgeLabel = 'BÌNH THƯỜNG'
              if (isWarning) badgeLabel = 'CẢNH BÁO'
              else if (isWatch) badgeLabel = 'CẦN THEO DÕI'
              else if (isUnknown) badgeLabel = 'KHÔNG RÕ'
              
              return (
                <details key={idx} className={`rounded-lg border overflow-hidden ${borderColor}`}>
                  <summary className="p-2 cursor-pointer flex justify-between items-center text-sm font-semibold select-none outline-none">
                    <span className="flex items-center gap-1.5">
                      <div className={`w-2 h-2 rounded-full ${dotClass}`} />
                      <span title={String(stationProps.name ?? '')}>Trạm {stationProps.station ?? '?'}</span>
                    </span>
                    <span className={`text-[10px] uppercase px-1.5 py-0.5 rounded ${badgeClass}`}>
                      {badgeLabel}
                    </span>
                  </summary>
                  <div className="p-2 pt-0 text-xs text-slate-600 border-t border-slate-200/50">
                    <p className="mt-1.5"><b>Khu vực:</b> {stationProps.name ?? 'Chưa có tên'}</p>
                    {Object.keys(props).length > 0 && <>
                      <p className="mt-1.5 flex justify-between">
                        <span><b>Áp dụng:</b> {props.species_applied}</span>
                        <span><b>Dữ liệu:</b> {props.data_status ?? 'unknown'}</span>
                      </p>
                      {props.pilot_reference && (
                         <p className="mt-1.5"><b>Nguồn (Pilot):</b> {props.pilot_reference?.source_station_serial}</p>
                      )}
                      <div className="grid grid-cols-2 gap-1 mt-1.5 mb-1.5">
                        <div className="bg-white/60 p-1.5 rounded flex justify-between"><span>NH3:</span> <b>{props.nh3_derived_mg_l ?? '-'}</b></div>
                        <div className="bg-white/60 p-1.5 rounded flex justify-between"><span>Temp:</span> <b>{props.metrics?.Temperature ?? '-'}</b></div>
                        <div className="bg-white/60 p-1.5 rounded flex justify-between"><span>Mưa:</span> <b>{props.weather?.rain_6h_mm ?? '-'}</b></div>
                        <div className="bg-white/60 p-1.5 rounded flex justify-between"><span>Gió:</span> <b>{props.weather?.wind_6h_kmh ?? '-'}</b></div>
                      </div>
                    </>}
                    {props.drivers?.length > 0 && (
                      <div className="mt-1 p-1.5 bg-white/60 rounded text-[10px]">
                        <b className="text-orange-700">Nguyên nhân cảnh báo:</b>
                        <ul className="list-disc pl-3 mt-0.5 text-orange-700">
                          {props.drivers.map((d: any, i: number) => (
                            <li key={i}>{d.metric}: {d.value} {d.unit}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                </details>
              )
            })}
          </div>
        ) : (
          <p className="text-xs text-slate-500 italic">Chưa tải được danh sách trạm</p>
        )}
      </div>

      {/* Legends Panel (Conditional) */}
      {(enabled.rain || enabled.flow_streamlines || enabled.wind_particles) && (
        <div className="p-4 rounded-xl shadow-lg pointer-events-auto bg-white/95 border border-slate-200 backdrop-blur-sm">
          <h3 className="font-bold text-slate-800 flex items-center gap-2 mb-2 text-sm">
            <Info size={14} /> Chú giải (Legends)
          </h3>
          <div className="space-y-3">
            {enabled.rain && available.find(layer => layer.layer === 'rain') && <RainLegend layer={available.find(layer => layer.layer === 'rain')!} />}
            {enabled.flow_streamlines && <FlowLegend />}
            {enabled.wind_particles && <WindLegend />}
          </div>
        </div>
      )}

      {/* Bathymetry Sample Details */}
      {bathymetrySample && (
        <div className="p-4 rounded-xl shadow-lg pointer-events-auto bg-white/95 border border-slate-200 backdrop-blur-sm">
          <h3 className="font-bold text-slate-800 flex items-center gap-2 mb-2 text-sm">
            <MapPin size={14} /> Điểm đo độ sâu
          </h3>
          <div className="text-sm text-slate-700">
            {bathymetrySample.status === 'available' ? (
              <>
                <p><span className="font-semibold">{bathymetrySample.copernicus_depth_m} m</span> · dốc {bathymetrySample.slope_degrees ?? '—'}°</p>
                <p className="text-xs text-slate-500 mt-1">Q={bathymetrySample.quality_indicator} · SDB={bathymetrySample.sdb_type}</p>
              </>
            ) : (
              <p>{bathymetrySample.reason_code}</p>
            )}
          </div>
        </div>
      )}

    </aside>
  )
}
