import { useEffect, useRef, useState } from 'react'

const RANGES = [
  { label: '30 days', days: 30 },
  { label: '90 days', days: 90 },
  { label: '1 year', days: 365 },
  { label: 'All time', days: 0 },
]

function formatDay(day, options = { month: 'short', day: 'numeric' }) {
  return new Date(`${day}T12:00:00`).toLocaleDateString(undefined, options)
}

function RolesChart({ series, mode }) {
  const [hovered, setHovered] = useState(null)
  const chartRef = useRef(null)
  const [width, setWidth] = useState(1000)
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(280, Math.round(entry.contentRect.width))))
    observer.observe(chartRef.current)
    return () => observer.disconnect()
  }, [])
  const compact = width < 500
  const height = compact ? 300 : 360
  const left = compact ? 38 : 48
  const right = compact ? 12 : 22
  const top = 24
  const bottom = compact ? 40 : 48
  const plotWidth = width - left - right
  const plotHeight = height - top - bottom
  const value = day => mode === 'average' ? (day.average_7_day ?? day.count) : day.count
  const maxCount = Math.max(1, ...series.map(value))
  const axisMax = Math.max(4, Math.ceil(maxCount / 4) * 4)
  const x = index => left + (series.length === 1 ? plotWidth / 2 : index * plotWidth / (series.length - 1))
  const y = count => top + plotHeight * (1 - count / axisMax)
  const points = series.map((day, index) => `${x(index)},${y(value(day))}`).join(' ')
  const area = `M ${x(0)} ${y(0)} L ${points.replaceAll(' ', ' L ')} L ${x(series.length - 1)} ${y(0)} Z`
  const tickCount = compact ? 3 : 5
  const xTicks = [...new Set(Array.from({ length: tickCount }, (_, step) => Math.round(step * (series.length - 1) / (tickCount - 1))))]

  function onMove(event) {
    const bounds = event.currentTarget.getBoundingClientRect()
    const coordinate = (event.clientX - bounds.left) * width / bounds.width
    const index = Math.round((coordinate - left) * (series.length - 1) / plotWidth)
    setHovered(Math.max(0, Math.min(series.length - 1, index)))
  }

  return (
    <div>
      <div ref={chartRef} className="relative" onMouseMove={onMove} onMouseLeave={() => setHovered(null)}>
        <svg className="w-full" viewBox={`0 0 ${width} ${height}`} role="img"
          aria-label={`Line chart of ${mode === 'average' ? 'seven-day average roles found' : 'daily roles found'} from ${series[0].date} through ${series[series.length - 1].date}`}>
          <defs>
            <linearGradient id={`roles-area-${mode}`} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="#8b5cf6" stopOpacity="0.32" />
              <stop offset="100%" stopColor="#8b5cf6" stopOpacity="0.01" />
            </linearGradient>
            <linearGradient id={`roles-line-${mode}`} x1="0" x2="1">
              <stop offset="0%" stopColor="#a78bfa" />
              <stop offset="100%" stopColor="#67e8f9" />
            </linearGradient>
          </defs>
          {[0, 1, 2, 3, 4].map(step => {
            const count = axisMax * step / 4
            return (
              <g key={step}>
                <line x1={left} x2={width - right} y1={y(count)} y2={y(count)} stroke="rgba(255,255,255,0.09)" />
                <text x={left - 12} y={y(count) + 4} textAnchor="end" fill="#94a3b8" fontSize="12">{count}</text>
              </g>
            )
          })}
          <path d={area} fill={`url(#roles-area-${mode})`} />
          <polyline points={points} fill="none" stroke={`url(#roles-line-${mode})`} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
          {series.length === 1 && <circle cx={x(0)} cy={y(value(series[0]))} r="4" fill="#a78bfa" />}
          {xTicks.map(index => (
            <text key={index} x={x(index)} y={height - 15} textAnchor={index === 0 ? 'start' : index === series.length - 1 ? 'end' : 'middle'} fill="#94a3b8" fontSize="12">
              {formatDay(series[index].date, { month: 'short', day: 'numeric', ...(series.length > 365 ? { year: '2-digit' } : {}) })}
            </text>
          ))}
          {hovered !== null && (
            <g>
              <line x1={x(hovered)} x2={x(hovered)} y1={top} y2={y(0)} stroke="rgba(255,255,255,0.25)" strokeDasharray="4 4" />
              <circle cx={x(hovered)} cy={y(value(series[hovered]))} r="6" fill="#67e8f9" stroke="#111827" strokeWidth="3" />
            </g>
          )}
        </svg>
        {hovered !== null && (
          <div className="pointer-events-none absolute top-3 rounded-lg border border-white/10 bg-[#141a2b] px-3 py-2 text-xs shadow-xl"
            style={{ left: `${Math.max(8, Math.min(80, x(hovered) / width * 100))}%` }}>
            <div className="text-slate-400">{formatDay(series[hovered].date, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })}</div>
            {mode === 'average' ? (
              <>
                <div className="mt-1 font-semibold text-cyan-200">7-day avg: {(series[hovered].average_7_day ?? series[hovered].count).toFixed(1)} roles/day</div>
                <div className="mt-1 text-slate-300">Daily: {series[hovered].count} roles</div>
              </>
            ) : (
              <>
                <div className="mt-1 font-semibold text-cyan-200">{series[hovered].count} roles found</div>
                <div className="mt-1 text-slate-300">7-day avg: {(series[hovered].average_7_day ?? series[hovered].count).toFixed(1)} roles/day</div>
              </>
            )}
          </div>
        )}
      </div>
      {mode === 'daily' && <details className="mt-4 text-xs text-slate-400">
        <summary className="cursor-pointer hover:text-slate-200">View daily counts</summary>
        <div className="mt-3 max-h-48 overflow-auto rounded-lg border border-white/10">
          <table className="w-full text-left">
            <thead className="sticky top-0 bg-[#171c2b] text-slate-300"><tr><th className="px-3 py-2">Date</th><th className="px-3 py-2">Roles found</th><th className="px-3 py-2">7-day avg</th></tr></thead>
            <tbody>{series.map(day => <tr key={day.date} className="border-t border-white/[0.05]"><td className="px-3 py-1.5">{day.date}</td><td className="px-3 py-1.5">{day.count}</td><td className="px-3 py-1.5">{(day.average_7_day ?? day.count).toFixed(1)}</td></tr>)}</tbody>
          </table>
        </div>
      </details>}
    </div>
  )
}

export default function AnalyticsPage({ refreshKey }) {
  const [range, setRange] = useState(90)
  const [series, setSeries] = useState([])
  const [baselineDate, setBaselineDate] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    fetch(`/api/analytics/roles?days=${range}`, { cache: 'no-store', signal: controller.signal })
      .then(response => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return response.json()
      })
      .then(data => { setSeries(data.series); setBaselineDate(data.baseline_date) })
      .catch(reason => { if (reason.name !== 'AbortError') setError(reason.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [range, refreshKey])

  const total = series.reduce((sum, day) => sum + day.count, 0)
  const activeDays = series.filter(day => day.count > 0).length
  const peak = Math.max(0, ...series.map(day => day.count))

  return (
    <section className="space-y-6" aria-labelledby="analytics-title">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-violet-300/70">Hiring trends</p>
          <h2 id="analytics-title" className="text-2xl font-semibold text-white">Roles found over time</h2>
          <p className="mt-2 text-sm text-slate-400">New roles when they first appear in the tracker, grouped by Eastern date.</p>
        </div>
        <div className="flex flex-wrap gap-1 rounded-xl border border-white/10 bg-white/[0.03] p-1" aria-label="Chart date range">
          {RANGES.map(option => (
            <button key={option.days} type="button" onClick={() => setRange(option.days)}
              aria-pressed={range === option.days}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${range === option.days ? 'bg-violet-500/25 text-violet-100' : 'text-slate-400 hover:bg-white/[0.06] hover:text-white'}`}>
              {option.label}
            </button>
          ))}
        </div>
      </div>

      {!loading && !error && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          {[
            ['Roles found', total],
            ['Days with new roles', activeDays],
            ['Peak in one day', peak],
          ].map(([label, value]) => (
            <div key={label} className="surface-card rounded-2xl px-5 py-4">
              <p className="text-xs text-slate-400">{label}</p>
              <p className="mt-2 text-2xl font-semibold text-white">{value}</p>
            </div>
          ))}
        </div>
      )}

      {loading || error || !series.length ? (
        <div className="surface-card rounded-2xl px-4 py-5 sm:px-6">
          {loading ? <p className="py-24 text-center text-sm text-slate-400">Loading trends…</p>
            : error ? <p className="py-24 text-center text-sm text-red-300">Could not load trends: {error}</p>
            : <p className="py-24 text-center text-sm text-slate-400">No scan history is available yet.</p>}
        </div>
      ) : (
        <>
          <div className="surface-card rounded-2xl px-4 py-5 sm:px-6">
            <h3 className="text-base font-semibold text-white">7-day rolling average</h3>
            <p className="mt-1 text-xs text-slate-400">Roles found per day, averaged over the previous 7 days. Weekend discoveries are included.</p>
            <div className="mt-4"><RolesChart series={series} mode="average" /></div>
          </div>
          <div className="surface-card rounded-2xl px-4 py-5 sm:px-6">
            <h3 className="text-base font-semibold text-white">Daily roles found</h3>
            <p className="mt-1 text-xs text-slate-400">Exact counts for each day, including weekends.</p>
            <div className="mt-4"><RolesChart series={series} mode="daily" /></div>
          </div>
        </>
      )}
      <p className="text-xs text-slate-500">Counts use the tracker’s first discovery of each role, including roles since removed from the live feed. Earlier history is available where scan records were retained.{baselineDate && ` The initial inventory on ${formatDay(baselineDate, { month: 'long', day: 'numeric', year: 'numeric' })} is excluded; date ranges start no earlier than the following day.`}</p>
    </section>
  )
}
