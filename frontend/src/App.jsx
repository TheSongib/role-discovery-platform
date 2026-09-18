import { useState, useEffect } from 'react'

// ── Company badge colours ────────────────────────────────────────────────────
const COMPANY_STYLES = {
  Affirm:    'bg-emerald-50 text-emerald-700 ring-emerald-200',
  Coinbase:  'bg-blue-50 text-blue-700 ring-blue-200',
  Microsoft: 'bg-sky-50 text-sky-700 ring-sky-200',
  Netflix:   'bg-red-50 text-red-700 ring-red-200',
  Dropbox:   'bg-violet-50 text-violet-700 ring-violet-200',
  Reddit:    'bg-orange-50 text-orange-700 ring-orange-200',
  Airbnb:    'bg-rose-50 text-rose-700 ring-rose-200',
  Stripe:    'bg-purple-50 text-purple-700 ring-purple-200',
  GitLab:      'bg-amber-50 text-amber-700 ring-amber-200',
  CrowdStrike: 'bg-red-50 text-red-700 ring-red-200',
  GitHub:      'bg-gray-50 text-gray-700 ring-gray-200',
  Mozilla:     'bg-orange-50 text-orange-700 ring-orange-200',
  Circle:      'bg-teal-50 text-teal-700 ring-teal-200',
  NerdWallet:  'bg-green-50 text-green-700 ring-green-200',
  Confluent:   'bg-cyan-50 text-cyan-700 ring-cyan-200',
  Zillow:      'bg-blue-50 text-blue-700 ring-blue-200',
  Instacart:   'bg-orange-50 text-orange-700 ring-orange-200',
  Quora:       'bg-red-50 text-red-700 ring-red-200',
  Twilio:      'bg-rose-50 text-rose-700 ring-rose-200',
  Zoom:        'bg-sky-50 text-sky-700 ring-sky-200',
  Zscaler:     'bg-indigo-50 text-indigo-700 ring-indigo-200',
}

function companyStyle(company) {
  return COMPANY_STYLES[company] ?? 'bg-slate-100 text-slate-700 ring-slate-200'
}

// ── Date helpers ─────────────────────────────────────────────────────────────
function relativeDate(dateStr) {
  if (!dateStr) return null
  const hasTime = dateStr.includes('T')
  const d = new Date(hasTime ? dateStr : dateStr + 'T12:00:00')
  const diffMs    = Date.now() - d.getTime()
  const diffMins  = Math.floor(diffMs / 60_000)
  const diffHours = Math.floor(diffMs / 3_600_000)
  const diffDays  = Math.floor(diffMs / 86_400_000)

  if (hasTime) {
    if (diffMins  <  1) return 'Just now'
    if (diffMins  < 60) return `${diffMins}m ago`
    if (diffHours < 24) return `${diffHours}h ago`
  }
  if (diffDays <= 0) return 'Today'
  if (diffDays === 1) return 'Yesterday'
  if (diffDays <= 6)  return `${diffDays}d ago`
  const opts = { month: 'short', day: 'numeric' }
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = 'numeric'
  return d.toLocaleDateString('en-US', opts)
}

function isPostedToday(dateStr) {
  if (!dateStr) return false
  const hasTime = dateStr.includes('T')
  const d = new Date(hasTime ? dateStr : dateStr + 'T12:00:00')
  const diffMs = Date.now() - d.getTime()
  if (hasTime) return diffMs >= 0 && diffMs < 86_400_000
  // date-only: compare in local time
  const now = new Date()
  return d.getFullYear() === now.getFullYear() &&
         d.getMonth()    === now.getMonth()    &&
         d.getDate()     === now.getDate()
}

function shortDate(isoStr) {
  if (!isoStr) return '—'
  const d = new Date(isoStr.slice(0, 10) + 'T12:00:00')
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

// ── Small components ─────────────────────────────────────────────────────────
function StatCard({ label, value }) {
  return (
    <div className="bg-white rounded-xl px-5 py-4 shadow-sm ring-1 ring-slate-100">
      <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">{label}</p>
      <p className="mt-1 text-3xl font-bold text-slate-900">{value}</p>
    </div>
  )
}

function CompanyBadge({ company }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${companyStyle(company)}`}>
      {company}
    </span>
  )
}

function SkeletonRow() {
  return (
    <tr className="animate-pulse border-b border-slate-50">
      {[72, 220, 110, 150, 70, 90].map((w, i) => (
        <td key={i} className="px-5 py-4">
          <div className="h-3.5 rounded bg-slate-100" style={{ width: w }} />
        </td>
      ))}
    </tr>
  )
}

function EmptyState() {
  return (
    <tr>
      <td colSpan={7} className="px-6 py-24 text-center">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-slate-100">
          <svg className="h-7 w-7 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
          </svg>
        </div>
        <p className="text-base font-semibold text-slate-700">No listings yet</p>
        <p className="mt-1 text-sm text-slate-400">
          Run <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-600">Scan Now</code> to pull jobs
        </p>
      </td>
    </tr>
  )
}

function ErrorState({ message }) {
  return (
    <tr>
      <td colSpan={7} className="px-6 py-24 text-center">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-red-50">
          <svg className="h-7 w-7 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
          </svg>
        </div>
        <p className="text-base font-semibold text-slate-700">Could not load jobs</p>
        <p className="mt-1 text-sm text-slate-400">{message} — is the API running?</p>
        <p className="mt-2 font-mono text-xs text-slate-400">uvicorn api:app --reload</p>
      </td>
    </tr>
  )
}

// ── Keywords settings modal ──────────────────────────────────────────────────
function TagList({ items, onRemove, input, setInput, onAdd, placeholder }) {
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5 min-h-[2.5rem]">
        {items.map((kw, i) => (
          <span key={i} className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700">
            {kw}
            <button
              onClick={() => onRemove(i)}
              className="ml-0.5 rounded-full text-slate-400 hover:text-slate-700 transition-colors"
              aria-label={`Remove ${kw}`}
            >
              <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </span>
        ))}
      </div>
      <div className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && onAdd()}
          placeholder={placeholder}
          className="flex-1 rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-700 placeholder-slate-400 focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
        />
        <button
          onClick={onAdd}
          className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:border-slate-300 hover:text-slate-800 transition-colors"
        >
          Add
        </button>
      </div>
    </div>
  )
}

function KeywordsModal({ onClose }) {
  const [includeKws, setIncludeKws] = useState([])
  const [excludeKws, setExcludeKws] = useState([])
  const [includeInput, setIncludeInput] = useState('')
  const [excludeInput, setExcludeInput] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveResult, setSaveResult] = useState(null) // 'ok' | 'error'

  useEffect(() => {
    fetch('/api/config/keywords')
      .then(r => r.json())
      .then(data => {
        setIncludeKws(data.title_keywords ?? [])
        setExcludeKws(data.title_exclude_keywords ?? [])
      })
  }, [])

  function addKeyword(list, setList, inputVal, setInput) {
    const trimmed = inputVal.trim()
    if (!trimmed || list.map(k => k.toLowerCase()).includes(trimmed.toLowerCase())) return
    setList(prev => [...prev, trimmed])
    setInput('')
  }

  function removeKeyword(setList, idx) {
    setList(prev => prev.filter((_, i) => i !== idx))
  }

  async function handleSave() {
    setSaving(true)
    setSaveResult(null)
    try {
      const r = await fetch('/api/config/keywords', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title_keywords: includeKws,
          title_exclude_keywords: excludeKws,
        }),
      })
      setSaveResult(r.ok ? 'ok' : 'error')
    } catch {
      setSaveResult('error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/30 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <div className="relative w-full max-w-lg rounded-2xl bg-white shadow-xl ring-1 ring-slate-200 mx-4">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">Keyword Filters</h2>
            <p className="mt-0.5 text-xs text-slate-500">Changes take effect on the next scan</p>
          </div>
          <button onClick={onClose} className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors">
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="space-y-5 px-6 py-5">
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Include — title must contain at least one</p>
            <TagList
              items={includeKws}
              onRemove={i => removeKeyword(setIncludeKws, i)}
              input={includeInput}
              setInput={setIncludeInput}
              onAdd={() => addKeyword(includeKws, setIncludeKws, includeInput, setIncludeInput)}
              placeholder="e.g. software engineer"
            />
          </div>

          <div className="border-t border-slate-100 pt-4">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Exclude — title must not contain any</p>
            <TagList
              items={excludeKws}
              onRemove={i => removeKeyword(setExcludeKws, i)}
              input={excludeInput}
              setInput={setExcludeInput}
              onAdd={() => addKeyword(excludeKws, setExcludeKws, excludeInput, setExcludeInput)}
              placeholder="e.g. senior"
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-slate-100 px-6 py-4">
          <div className="h-5">
            {saveResult === 'ok' && (
              <span className="text-xs font-medium text-emerald-600">Saved successfully</span>
            )}
            {saveResult === 'error' && (
              <span className="text-xs font-medium text-red-500">Save failed — try again</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button onClick={onClose} className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:border-slate-300 transition-colors">
              Close
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-indigo-700 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Icons ────────────────────────────────────────────────────────────────────
function EyeSlashIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
        d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
    </svg>
  )
}

function EyeIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
        d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
        d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
    </svg>
  )
}

function ScanStatusPanel({ scan }) {
  const [expanded, setExpanded] = useState(false)

  if (!scan) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white px-5 py-4 text-sm text-slate-500 shadow-sm">
        No scans have been recorded yet.
      </div>
    )
  }

  const failed = (scan.companies ?? []).filter(company => company.status === 'failed')
  const completed = (scan.companies ?? []).length
  const isRunning = scan.status === 'running'
  const statusStyle = {
    success: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
    partial: 'bg-amber-50 text-amber-700 ring-amber-200',
    failed: 'bg-red-50 text-red-700 ring-red-200',
    running: 'bg-blue-50 text-blue-700 ring-blue-200',
  }[scan.status] ?? 'bg-slate-100 text-slate-700 ring-slate-200'

  const summary = isRunning
    ? `${completed} of ${scan.total_companies} companies completed`
    : scan.status === 'success'
      ? `All ${scan.total_companies} companies returned successfully`
      : `${scan.successful_companies} of ${scan.total_companies} companies returned successfully`

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
        <div className="flex min-w-0 items-center gap-3">
          <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold capitalize ring-1 ring-inset ${statusStyle}`}>
            {scan.status}
          </span>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-slate-800">{summary}</p>
            <p className="mt-0.5 text-xs text-slate-400">
              {scan.trigger} scan · {relativeDate(scan.finished_at ?? scan.started_at)}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              {scan.total_found} jobs found · {scan.keyword_filtered} removed by keywords · {scan.not_remote} not remote · {scan.total_seen} matching
            </p>
          </div>
        </div>
        <button
          onClick={() => setExpanded(value => !value)}
          className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:border-slate-300 hover:text-slate-800"
        >
          {expanded ? 'Hide details' : 'View details'}
        </button>
      </div>

      {failed.length > 0 && !expanded && (
        <div className="border-t border-amber-100 bg-amber-50/60 px-5 py-3 text-xs text-amber-800">
          Failed: {failed.map(company => company.company).join(', ')}
        </div>
      )}

      {expanded && (
        <div className="max-h-80 overflow-y-auto border-t border-slate-100">
          {(scan.companies ?? []).map(company => (
            <div key={company.company} className="flex items-start justify-between gap-4 border-b border-slate-50 px-5 py-3 last:border-0">
              <div className="min-w-0">
                <p className="text-sm font-medium text-slate-700">
                  {company.company}
                  <span className="ml-2 text-xs font-normal text-slate-400">{company.ats}</span>
                </p>
                {company.error && (
                  <p className="mt-1 break-words text-xs text-red-600">{company.error}</p>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-3 text-xs">
                {company.status === 'success' && (
                  <span className="text-slate-400">
                    {company.jobs_found} found · {company.keyword_filtered} removed by keywords · {company.not_remote} not remote · {company.jobs_seen} matching
                  </span>
                )}
                <span className={company.status === 'success' ? 'font-medium text-emerald-600' : 'font-medium text-red-600'}>
                  {company.status}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Main app ─────────────────────────────────────────────────────────────────
export default function App() {
  const [jobs, setJobs]             = useState([])
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState(null)
  const [showHidden, setShowHidden] = useState(false)
  const [scanning, setScanning]     = useState(false)
  const [scanResult, setScanResult] = useState(null) // { new_jobs, total_seen }
  const [maxAge, setMaxAge]         = useState(3)
  const [showSettings, setShowSettings] = useState(false)
  const [latestScan, setLatestScan] = useState(null)

  const AGE_OPTIONS = [
    { label: '24 hours', value: 1 },
    { label: '3 days',   value: 3 },
    { label: '1 week',   value: 7 },
    { label: 'All time', value: 0 },
  ]

  function loadJobs(age) {
    setLoading(true)
    setError(null)
    fetch(`/api/jobs?show_hidden=true&max_age_days=${age}`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(data => { setJobs(data); setLoading(false) })
      .catch(e  => { setError(e.message); setLoading(false) })
  }

  useEffect(() => { loadJobs(maxAge) }, [maxAge])

  function loadLatestScan() {
    return fetch('/api/scans/latest', { cache: 'no-store' })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(data => setLatestScan(data))
      .catch(() => {})
  }

  useEffect(() => {
    loadLatestScan()
    const scanIsActive = scanning || latestScan?.status === 'running'
    const interval = setInterval(loadLatestScan, scanIsActive ? 1_000 : 60_000)
    return () => clearInterval(interval)
  }, [scanning, latestScan?.status])

  async function startScan() {
    setScanning(true)
    setScanResult(null)
    try {
      const r = await fetch('/api/scan', { method: 'POST' })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const result = await r.json()
      setScanResult(result)
      loadJobs(maxAge)
      loadLatestScan()
    } catch {
      setScanResult({ error: true })
      loadLatestScan()
    } finally {
      setScanning(false)
    }
  }

  function toggleHidden(job) {
    const nextHidden = !job.hidden
    // Optimistic update
    setJobs(prev => prev.map(j => j.id === job.id ? { ...j, hidden: nextHidden ? 1 : 0 } : j))
    fetch(`/api/jobs/${job.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hidden: nextHidden }),
    }).catch(() => loadJobs(maxAge)) // revert on error
  }

  const visible   = jobs.filter(j => !j.hidden)
  const hidden    = jobs.filter(j =>  j.hidden)
  const companies = [...new Set(visible.map(j => j.company))]
  const lastScan  = latestScan?.finished_at ?? latestScan?.started_at ?? ''

  return (
    <div className="min-h-screen bg-slate-50 font-sans text-slate-900">

      {showSettings && <KeywordsModal onClose={() => setShowSettings(false)} />}

      {/* ── Header ── */}
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/90 backdrop-blur-sm">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3.5">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 shadow-sm">
              <svg className="h-4.5 w-4.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m4 6h.01M5 20h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
            </div>
            <div>
              <h1 className="text-sm font-bold leading-none text-slate-900">JobTracker</h1>
              <p className="mt-0.5 text-xs text-slate-400">Remote US · Engineering &amp; Security</p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {!loading && !error && (
              <span className="text-sm text-slate-500">
                <span className="font-semibold text-slate-800">{visible.length}</span> listings
              </span>
            )}

            {/* Age filter dropdown */}
            <select
              value={maxAge}
              onChange={e => setMaxAge(Number(e.target.value))}
              className="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-600 shadow-sm transition-colors hover:border-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
            >
              {AGE_OPTIONS.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>

            {/* Scan result flash */}
            {scanResult && !scanning && (
              <span className={`text-xs font-medium px-2.5 py-1 rounded-full ${
                scanResult.error || scanResult.status === 'failed'
                  ? 'bg-red-50 text-red-600'
                  : scanResult.status === 'partial' || scanResult.status === 'already_running'
                    ? 'bg-amber-50 text-amber-700'
                  : scanResult.new_jobs > 0
                    ? 'bg-emerald-50 text-emerald-700'
                    : 'bg-slate-100 text-slate-500'
              }`}>
                {scanResult.error || scanResult.status === 'failed'
                  ? 'Scan failed'
                  : scanResult.status === 'already_running'
                    ? 'Scan already running'
                  : scanResult.status === 'partial'
                    ? `${scanResult.failed_companies} failed`
                  : scanResult.new_jobs > 0
                    ? `+${scanResult.new_jobs} new`
                    : 'No new jobs'}
              </span>
            )}

            {/* Settings button */}
            <button
              onClick={() => setShowSettings(s => !s)}
              title="Keyword filters"
              className="rounded-lg border border-slate-200 bg-white p-1.5 text-slate-500 shadow-sm transition-colors hover:border-slate-300 hover:text-slate-700"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            </button>

            {/* Show hidden toggle */}
            <button
              onClick={() => setShowHidden(h => !h)}
              className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                showHidden
                  ? 'border-indigo-200 bg-indigo-50 text-indigo-700'
                  : 'border-slate-200 bg-white text-slate-500 hover:border-slate-300 hover:text-slate-700'
              }`}
            >
              {showHidden ? <EyeIcon /> : <EyeSlashIcon />}
              {showHidden ? `Showing hidden (${hidden.length})` : `Hidden (${hidden.length})`}
            </button>

            {/* Scan button */}
            <button
              onClick={startScan}
              disabled={scanning}
              className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {scanning ? (
                <>
                  <svg className="h-3.5 w-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Scanning…
                </>
              ) : (
                <>
                  <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                      d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                  </svg>
                  Scan Now
                </>
              )}
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-6 px-6 py-8">

        <ScanStatusPanel scan={latestScan} />

        {/* ── Stat cards ── */}
        {!loading && !error && (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatCard label="Total Roles"  value={visible.length} />
            <StatCard label="Companies"    value={companies.length} />
            <StatCard label="Last Scan"    value={lastScan ? relativeDate(lastScan) : '—'} />
            <StatCard label="Posted Today" value={visible.filter(j => isPostedToday(j.date_posted)).length} />
          </div>
        )}

        {/* ── Table card ── */}
        <div className="overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-slate-100">
          <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
            <h2 className="text-sm font-semibold text-slate-700">
              {showHidden ? 'Hidden Listings' : 'Active Listings'}
            </h2>
            {!loading && !error && jobs.length > 0 && (
              <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600">
                {showHidden ? hidden.length : visible.length} roles
              </span>
            )}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50/60">
                  {['Company', 'Title', 'Department', 'Location', 'Posted', 'Date Found', ''].map((col, i) => (
                    <th key={i}
                      className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-400">
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>

              <tbody>
                {loading ? (
                  Array.from({ length: 10 }).map((_, i) => <SkeletonRow key={i} />)
                ) : error ? (
                  <ErrorState message={error} />
                ) : (showHidden ? hidden : visible).length === 0 ? (
                  <EmptyState />
                ) : (
                  (showHidden ? hidden : visible).map((job, idx) => (
                    <tr
                      key={job.id}
                      className={`group border-b border-slate-50 transition-colors hover:bg-indigo-50/40 ${
                        job.hidden ? 'opacity-60' : idx % 2 === 1 ? 'bg-slate-50/30' : ''
                      }`}
                    >
                      {/* Company */}
                      <td className="whitespace-nowrap px-5 py-3.5">
                        <CompanyBadge company={job.company} />
                      </td>

                      {/* Title */}
                      <td className="px-5 py-3.5">
                        {job.url ? (
                          <a href={job.url} target="_blank" rel="noopener noreferrer"
                            className="font-medium text-slate-800 underline-offset-2 hover:text-indigo-600 hover:underline">
                            {job.title}
                          </a>
                        ) : (
                          <span className="font-medium text-slate-800">{job.title}</span>
                        )}
                      </td>

                      {/* Department */}
                      <td className="whitespace-nowrap px-5 py-3.5 text-slate-500">
                        {job.department || <span className="text-slate-300">—</span>}
                      </td>

                      {/* Location */}
                      <td className="px-5 py-3.5">
                        <span className="block max-w-[200px] truncate text-slate-500" title={job.location}>
                          {job.location || <span className="text-slate-300">—</span>}
                        </span>
                      </td>

                      {/* Posted */}
                      <td className="whitespace-nowrap px-5 py-3.5">
                        <span className="font-medium text-slate-700">
                          {relativeDate(job.date_posted ?? job.date_found)}
                        </span>
                      </td>

                      {/* Date Found */}
                      <td className="whitespace-nowrap px-5 py-3.5 text-slate-400">
                        {shortDate(job.date_found)}
                      </td>

                      {/* Hide / Unhide */}
                      <td className="whitespace-nowrap px-4 py-3.5">
                        <button
                          onClick={() => toggleHidden(job)}
                          title={job.hidden ? 'Unhide this job' : 'Hide this job'}
                          className={`rounded-md p-1.5 transition-colors ${
                            job.hidden
                              ? 'text-indigo-400 hover:bg-indigo-50 hover:text-indigo-600'
                              : 'text-slate-300 opacity-0 group-hover:opacity-100 hover:bg-slate-100 hover:text-slate-600'
                          }`}
                        >
                          {job.hidden ? <EyeIcon /> : <EyeSlashIcon />}
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </main>
    </div>
  )
}
