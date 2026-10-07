import { Activity, Clock } from 'lucide-react'
import type { Snapshot } from '../../types'

export function Header({ snapshot, mapDataMode }: { snapshot: Snapshot | null, mapDataMode: 'live' | 'mock' }) {
  return (
    <header className="bg-slate-900 text-white shadow-md flex justify-between items-center px-6 py-4 z-10 relative">
      <div>
        <h1 className="text-xl font-bold flex items-center gap-2">
          <Activity className="text-blue-400" size={24} />
          Dashboard Quan Trắc & Cảnh Báo
        </h1>
        <p className="text-slate-400 text-sm mt-1">Context môi trường & cảnh báo rủi ro nuôi trồng</p>
      </div>
      <div className="flex items-center gap-4">
        {mapDataMode === 'mock' && (
          <span className="bg-purple-600 text-white px-3 py-1 rounded-full text-xs font-semibold animate-pulse">
            MOCK MODE
          </span>
        )}
        <div className={`px-4 py-1.5 rounded-full text-sm font-semibold flex items-center gap-2 ${
          !snapshot ? 'bg-red-500/20 text-red-400' :
          snapshot.status === 'fresh' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-amber-500/20 text-amber-400'
        }`}>
          <Clock size={16} />
          {snapshot ? `${snapshot.status.toUpperCase()} · ${new Date(snapshot.retrieved_at).toLocaleTimeString()}` : 'MẤT KẾT NỐI'}
        </div>
      </div>
    </header>
  )
}
