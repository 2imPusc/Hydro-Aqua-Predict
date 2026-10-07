import { Layers, Map as MapIcon, Waves, MapPin } from 'lucide-react'
import type { BathymetryManifest, FlowArtifact, Layer, StationNetwork } from '../../types'
import { LABEL } from '../map/MapOverlays'

interface SidebarLeftProps {
  mapDataMode: 'live' | 'mock'
  setMapDataMode: (val: 'live' | 'mock') => void
  mockScenario: string
  setMockScenario: (val: string) => void
  enabled: Record<string, boolean>
  setEnabled: (fn: (current: Record<string, boolean>) => Record<string, boolean>) => void
  stationNetwork: StationNetwork | null
  flowArtifact: FlowArtifact | null
  available: Layer[]
  bathymetry: BathymetryManifest | null
  bathymetryLod: string
}

export function SidebarLeft(props: SidebarLeftProps) {
  const { enabled, setEnabled, available } = props

  const toggleEnvironment = (name: string, checked: boolean) => setEnabled(current => {
    const environmentalLayers = ['rain', 'wave', 'sea_level', 'mixed_layer_depth']
    return { ...current, ...Object.fromEntries(environmentalLayers.map(layer => [layer, layer === name ? checked : false])) }
  })
  
  const toggleWindParticles = (checked: boolean) => setEnabled(current => ({ ...current, wind_particles: checked }))
  
  return (
    <aside className="w-80 bg-white shadow-xl flex flex-col h-full overflow-y-auto z-10 relative">
      <div className="p-5 border-b border-slate-200">
        <h2 className="text-sm font-bold text-slate-800 uppercase tracking-wider flex items-center gap-2 mb-4">
          <Layers size={18} className="text-blue-500" />
          Điều khiển Bản đồ
        </h2>
        
        <div className="bg-slate-50 p-3 rounded-lg border border-slate-200">
          <label className="text-xs font-semibold text-slate-600 mb-2 block">CHẾ ĐỘ DỮ LIỆU</label>
          <div className="flex flex-col gap-2">
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="radio" className="accent-blue-600" checked={props.mapDataMode === 'live'} onChange={() => props.setMapDataMode('live')} /> 
              Live sensor + API
            </label>
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="radio" className="accent-purple-600" checked={props.mapDataMode === 'mock'} onChange={() => props.setMapDataMode('mock')} /> 
              Mock demo
            </label>
          </div>
          {props.mapDataMode === 'mock' && (
            <select className="w-full mt-3 p-2 text-sm border border-slate-300 rounded-md bg-white focus:outline-none focus:border-purple-500" value={props.mockScenario} onChange={e => props.setMockScenario(e.target.value)}>
              <option value="normal">Bình thường (Normal)</option>
              <option value="rain_wind_watch">Mưa + Gió (Watch)</option>
              <option value="nh3_watch">NH3 tăng cao (Watch)</option>
              <option value="temperature_warning">Sốc nhiệt độ (Warning)</option>
              <option value="extreme_hazard">Thảm họa tổng hợp (Warning)</option>
              <option value="oyster_danger_cobia_safe">Lệch pha đối tượng</option>
              <option value="missing_sensor_data">Mất dữ liệu cảm biến</option>
            </select>
          )}
        </div>
      </div>

      <div className="p-5 flex-1 flex flex-col gap-6">
        {/* Network & Domains */}
        <div>
          <h3 className="text-xs font-bold text-slate-500 mb-3 flex items-center gap-2">
            <MapPin size={14} /> MẠNG LƯỚI & PHẠM VI
          </h3>
          <div className="flex flex-col gap-3">
            <label className="flex items-start gap-2 text-sm text-slate-700 cursor-pointer">
              <input type="checkbox" className="mt-1" checked readOnly /> 
              <div>
                <span className="font-medium">HSI historical zones</span>
              </div>
            </label>
            <label className="flex items-start gap-2 text-sm text-slate-700 cursor-pointer">
              <input type="checkbox" className="mt-1" checked={enabled.context_buffer} onChange={e => setEnabled(c => ({...c, context_buffer: e.target.checked}))} /> 
              <div>
                <span className="font-medium">Phạm vi context 5 km</span>
                <p className="text-xs text-slate-500">water-clipped</p>
              </div>
            </label>
            <label className="flex items-start gap-2 text-sm text-slate-700 cursor-pointer">
              <input type="checkbox" className="mt-1" checked={enabled.station_network} onChange={e => setEnabled(c => ({...c, station_network: e.target.checked}))} /> 
              <div>
                <span className="font-medium">Kết nối mặt nước giữa các trạm</span>
                <p className="text-xs text-slate-500">{props.stationNetwork?.network_status === 'building' ? 'đang dựng water-path…' : 'tĩnh · không biểu diễn hướng dòng chảy'}</p>
              </div>
            </label>
          </div>
        </div>

        {/* Environmental Layers */}
        <div>
          <h3 className="text-xs font-bold text-slate-500 mb-3 flex items-center gap-2">
            <MapIcon size={14} /> KHÍ TƯỢNG HẢI VĂN
          </h3>
          <div className="flex flex-col gap-3">
            <label className="flex items-start gap-2 text-sm text-slate-700 cursor-pointer">
              <input type="checkbox" className="mt-1" checked={enabled.flow_streamlines} onChange={e => setEnabled(c => ({...c, flow_streamlines: e.target.checked}))} /> 
              <div>
                <span className="font-medium">Tia dòng chảy</span>
                <p className="text-xs text-slate-500">nội suy + water-clipped · {props.flowArtifact?.ray_count ?? 0} tia</p>
              </div>
            </label>
            <label className="flex items-start gap-2 text-sm text-slate-700 cursor-pointer">
              <input type="checkbox" className="mt-1" checked={enabled.wind_particles} onChange={e => toggleWindParticles(e.target.checked)} /> 
              <div>
                <span className="font-medium">Vệt gió (Wind particles)</span>
                <p className="text-xs text-slate-500">canvas particle (tuỳ chọn)</p>
              </div>
            </label>
            
            {available.map(layer => (
              <label key={layer.layer} className={`flex items-start gap-2 text-sm cursor-pointer ${layer.status === 'unavailable' ? 'opacity-50' : 'text-slate-700'}`}>
                <input type="checkbox" className="mt-1" checked={!!enabled[layer.layer]} disabled={layer.status === 'unavailable'} onChange={e => toggleEnvironment(layer.layer, e.target.checked)} /> 
                <div>
                  <span className="font-medium">{LABEL[layer.layer]}</span>
                  <p className="text-xs text-slate-500">
                    {layer.status === 'unavailable' ? layer.reason_code : layer.layer === 'current' ? `${layer.kind} · streamline + particle` : `${layer.kind} · ${layer.geojson?.features.length ?? 0} ${layer.kind === 'scalar_grid' ? 'ô' : 'vector'}`}
                  </p>
                </div>
              </label>
            ))}
          </div>
        </div>

        {/* Bathymetry */}
        <div>
          <h3 className="text-xs font-bold text-slate-500 mb-3 flex items-center gap-2">
            <Waves size={14} /> ĐỊA HÌNH ĐÁY
          </h3>
          <div className="flex flex-col gap-3">
            <label className={`flex items-start gap-2 text-sm cursor-pointer ${props.bathymetry?.status === 'unavailable' ? 'opacity-50' : 'text-slate-700'}`}>
              <input type="checkbox" className="mt-1" checked={enabled.bathymetry_bands} disabled={props.bathymetry?.status !== 'ready'} onChange={e => setEnabled(c => ({...c, bathymetry_bands: e.target.checked}))} /> 
              <div>
                <span className="font-medium">Dải độ sâu Copernicus</span>
                <p className="text-xs text-slate-500">{props.bathymetry?.status === 'ready' ? `${props.bathymetry.source_resolution} · LOD ${props.bathymetryLod}` : props.bathymetry?.reason_code ?? 'đang dựng artifact…'}</p>
              </div>
            </label>
            <label className={`flex items-start gap-2 text-sm cursor-pointer ${props.bathymetry?.status === 'unavailable' ? 'opacity-50' : 'text-slate-700'}`}>
              <input type="checkbox" className="mt-1" checked={enabled.bathymetry_contours} disabled={props.bathymetry?.status !== 'ready'} onChange={e => setEnabled(c => ({...c, bathymetry_contours: e.target.checked}))} /> 
              <div>
                <span className="font-medium">Đường đồng mức đáy</span>
                <p className="text-xs text-slate-500">0,25 / 0,5 / 0,75 / 1 m; mức sâu hơn khi có</p>
              </div>
            </label>
            <label className={`flex items-start gap-2 text-sm cursor-pointer ${props.bathymetry?.status === 'unavailable' ? 'opacity-50' : 'text-slate-700'}`}>
              <input type="checkbox" className="mt-1" checked={enabled.bathymetry_slope} disabled={props.bathymetry?.status !== 'ready'} onChange={e => setEnabled(c => ({...c, bathymetry_slope: e.target.checked}))} /> 
              <div>
                <span className="font-medium">Độ dốc đáy</span>
                <p className="text-xs text-slate-500">tính từ depth đã qua quality mask</p>
              </div>
            </label>
          </div>
        </div>
      </div>
    </aside>
  )
}
