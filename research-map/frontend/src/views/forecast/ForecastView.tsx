import { getForecastBenchmark } from '../../api/research'
import { useLiveData } from '../../app/LiveDataContext'
import { Disclosure, Skeleton, stateMeta, Verdict, type VerdictStatus } from '../../components/ui'
import { horizonLabel } from '../../lib/format'
import type { ForecastBenchmark, LongForecast } from '../../types/research'
import type { PollState } from '../../hooks/usePolling'
import { DirectionPanel, PageScroll, ResearchGate, ResearchHeader, Unavailable, useDirection, useResearch } from '../shared/research'
import { BenchmarkDetails, benchmarkSummary, SkillPanel } from './Benchmark'
import { ledgerMeta, LiveShadow, useLongForecast } from './LiveShadow'

/** One question: can water temperature be forecast 3–12 h ahead? Figures come from the export rows. */
function ForecastVerdict({ benchmark, ledger, headline }: { benchmark: PollState<ForecastBenchmark>; ledger: PollState<LongForecast>; headline?: string }) {
  const data = benchmark.data?.status === 'ready' ? benchmark.data : null
  if (!data) {
    if (benchmark.data || benchmark.error) return <Unavailable envelope={benchmark.data} error={benchmark.error} title="Chưa có bảng benchmark" onRetry={benchmark.refresh} />
    return <Skeleton className="h-32" />
  }
  const s = benchmarkSummary(data)
  const status: VerdictStatus = s.maxPassHorizon != null ? { tone: 'ok', label: 'Đạt kiểm định' } : { tone: 'danger', label: 'Chưa đạt kiểm định' }
  const meta = ledgerMeta(ledger.data)
  const ledgerState = ledger.data ? meta.state : ledger.error ? 'unavailable' : 'loading'
  const ledgerTone = stateMeta(ledgerState).tone
  return (
    <Verdict
      question="Dự báo được nhiệt độ nước bao xa?"
      status={status}
      value={s.maxPassHorizon != null ? horizonLabel(s.maxPassHorizon) : '—'}
      answer={headline}
      facts={[
        { label: 'Cấu hình nhiệt độ đạt kiểm định', value: `${s.tempPassed}/${s.tempTotal}`, hint: 'trên tập kiểm tra giữ riêng' },
        s.phTotal === 0
          ? { label: 'pH 3–12 h', value: '—', status: { tone: 'neutral', label: 'Không có dòng' } }
          : { label: 'pH 3–12 h', value: `${s.phPassed}/${s.phTotal}`, status: s.phPassed * 2 < s.phTotal ? { tone: 'danger', label: 'Không đạt' } : { tone: 'ok', label: 'Đạt' }, hint: 'dữ liệu trước khi đầu dò pH trôi' },
        { label: 'Sổ ghi shadow', value: ledger.data?.items?.length ?? 0, status: { tone: ledgerTone, label: ledger.data ? meta.label : stateMeta(ledgerState).label }, hint: 'bản dự báo đang đọc' },
      ]}
    >
      <Disclosure summary="Chỉ nghiên cứu: nghĩa là gì?">
        <p className="m-0">Dự báo chạy ở chế độ shadow: được ghi lại và chấm điểm, không gửi tới người nuôi và không kích hoạt cảnh báo.</p>
      </Disclosure>
    </Verdict>
  )
}

export default function ForecastView() {
  const { pilotStation } = useLiveData()
  const { direction, poll: overview } = useDirection('H1')
  const benchmark = useResearch(getForecastBenchmark)
  const ledger = useLongForecast(pilotStation)
  return (
    <PageScroll>
      <ResearchHeader code="H1" title="Dự báo ngắn hạn" direction={direction} exportVersion={benchmark.data?.export_version ?? overview.data?.export_version ?? undefined} />
      <ForecastVerdict benchmark={benchmark} ledger={ledger} headline={direction?.headline} />
      <LiveShadow poll={ledger} />
      <ResearchGate poll={benchmark} title="Không có bảng benchmark" skeleton={<Skeleton className="h-72" />}>
        {data => (
          <>
            <SkillPanel data={data} />
            <BenchmarkDetails data={data} />
          </>
        )}
      </ResearchGate>
      <DirectionPanel direction={direction} poll={overview} />
    </PageScroll>
  )
}
