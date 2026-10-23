import { getForecastBenchmark } from '../../api/research'
import { useLiveData } from '../../app/LiveDataContext'
import { Skeleton } from '../../components/ui'
import { DirectionPanel, PageScroll, ResearchGate, ResearchHeader, useDirection, useResearch } from '../shared/research'
import { Benchmark } from './Benchmark'
import { LiveShadow } from './LiveShadow'

export default function ForecastView() {
  const { pilotStation } = useLiveData()
  const { direction, poll: overview } = useDirection('H1')
  const benchmark = useResearch(getForecastBenchmark)
  return (
    <PageScroll>
      <ResearchHeader code="H1" title="Dự báo ngắn hạn" direction={direction} exportVersion={benchmark.data?.export_version ?? overview.data?.export_version ?? undefined} />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <LiveShadow station={pilotStation} />
        <DirectionPanel direction={direction} poll={overview} />
      </div>
      <ResearchGate poll={benchmark} title="Không có bảng benchmark" skeleton={<div className="grid gap-4 xl:grid-cols-2"><Skeleton className="h-64" /><Skeleton className="h-64" /></div>}>
        {data => <Benchmark data={data} />}
      </ResearchGate>
    </PageScroll>
  )
}
