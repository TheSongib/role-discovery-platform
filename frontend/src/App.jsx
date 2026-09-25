import { useState, useEffect } from 'react'

// ── Company badge colours ────────────────────────────────────────────────────
// Brand hues stay in one map so every configured company gets a recognizable
// badge while the shared CSS controls contrast and the neon treatment.
const COMPANY_COLORS = {
  Affirm:              '#4A4AF4',
  Coinbase:            '#0052FF',
  Microsoft:           '#00A4EF',
  Netflix:             '#E50914',
  Dropbox:             '#0061FF',
  Reddit:              '#FF4500',
  Airbnb:              '#FF5A5F',
  Stripe:              '#635BFF',
  GitLab:              '#FC6D26',
  CrowdStrike:         '#E01E2D',
  GitHub:              '#F0F6FC',
  Mozilla:             '#FF7139',
  Circle:              '#2775CA',
  NerdWallet:          '#8CC63F',
  Confluent:           '#00AFBA',
  Zillow:              '#006AFF',
  Instacart:           '#43B02A',
  Quora:               '#B92B27',
  Twilio:              '#F22F46',
  Zoom:                '#2D8CFF',
  Zscaler:             '#0096D6',
  Oura:                '#D6B46C',
  Wiz:                 '#8B5CF6',
  Rubrik:              '#F26322',
  Databricks:          '#FF3621',
  Elastic:             '#00BFB3',
  SailPoint:           '#00B2A9',
  Snowflake:           '#29B5E8',
  Plaid:               '#F5F7FA',
  Brex:                '#FF5A1F',
  Figma:               '#A259FF',
  HubSpot:             '#FF7A59',
  'Abnormal Security': '#8B5CF6',
  'Grafana Labs':      '#F46800',
  Tenable:             '#00B3B8',
  '1Password':         '#0572EC',
  Vanta:               '#8B5CF6',
  Drata:               '#7C5CFC',
  Pinterest:           '#E60023',
  DoorDash:            '#FF3008',
  OpenAI:              '#10A37F',
  Tailscale:           '#F4F4F5',
  MongoDB:             '#00ED64',
  Chime:               '#00D64F',
  Discord:             '#5865F2',
  Samsara:             '#FF5C35',
  Temporal:            '#8B5CF6',
  Mercury:             '#8C6FF7',
  Vercel:              '#FFFFFF',
  ClickHouse:          '#FFCC01',
  LaunchDarkly:        '#405BFF',
  OpenRouter:          '#7C83FF',
  Render:              '#46E3B7',
  WorkOS:              '#6366F1',
  'Modern Treasury':   '#2D6CDF',
  Omni:                '#8B5CF6',
  Centralize:          '#22D3EE',
}

function companyColor(company) {
  return COMPANY_COLORS[company] ?? '#94A3B8'
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
    <div className="surface-card group rounded-2xl px-5 py-4 transition-colors hover:border-white/15">
      <div className="mb-3 h-0.5 w-8 rounded-full bg-gradient-to-r from-violet-400 to-cyan-400 opacity-70 transition-all group-hover:w-12" />
      <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">{label}</p>
      <p className="mt-1.5 text-3xl font-semibold tracking-tight text-slate-100">{value}</p>
    </div>
  )
}

function CompanyBadge({ company }) {
  return (
    <span
      className="company-badge inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-semibold tracking-wide"
      style={{ '--company-color': companyColor(company) }}
    >
      {company}
    </span>
  )
}

function SkeletonRow({ canManage }) {
  return (
    <tr className="animate-pulse border-b border-white/[0.05]">
      {[72, 220, 110, 150, 70, 90, ...(canManage ? [32] : [])].map((w, i) => (
        <td key={i} className="px-5 py-4">
          <div className="h-3.5 rounded bg-slate-800" style={{ width: w }} />
        </td>
      ))}
    </tr>
  )
}

function EmptyState({ canManage, columnCount }) {
  return (
    <tr>
      <td colSpan={columnCount} className="px-6 py-24 text-center">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-white/10 bg-white/[0.04]">
          <svg className="h-7 w-7 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
          </svg>
        </div>
        <p className="text-base font-semibold text-slate-200">No listings yet</p>
        <p className="mt-1 text-sm text-slate-500">
          {canManage
            ? <>Run <code className="rounded bg-white/[0.06] px-1.5 py-0.5 font-mono text-xs text-slate-300">Scan Now</code> to pull jobs</>
            : 'Scheduled scans will populate this dashboard.'}
        </p>
      </td>
    </tr>
  )
}

function ErrorState({ message, columnCount }) {
  return (
    <tr>
      <td colSpan={columnCount} className="px-6 py-24 text-center">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-red-400/15 bg-red-400/10">
          <svg className="h-7 w-7 text-red-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
          </svg>
        </div>
        <p className="text-base font-semibold text-slate-200">Could not load jobs</p>
        <p className="mt-1 text-sm text-slate-500">{message} — is the API running?</p>
        <p className="mt-2 font-mono text-xs text-slate-600">uvicorn api:app --reload</p>
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
          <span key={i} className="inline-flex items-center gap-1 rounded-full bg-violet-400/10 px-2.5 py-1 text-xs font-medium text-violet-200 ring-1 ring-inset ring-violet-400/20">
            {kw}
            <button
              onClick={() => onRemove(i)}
              className="ml-0.5 rounded-full text-violet-300/60 transition-colors hover:text-violet-100"
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
          className="flex-1 rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-xs text-slate-200 outline-none placeholder:text-slate-600 focus:border-violet-400/50 focus:ring-2 focus:ring-violet-500/15"
        />
        <button
          onClick={onAdd}
          className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-medium text-slate-300 transition-colors hover:border-white/20 hover:bg-white/[0.07] hover:text-white"
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
      <div className="absolute inset-0 bg-[#03050a]/80 backdrop-blur-md" onClick={onClose} />

      {/* Modal */}
      <div className="relative mx-4 w-full max-w-lg overflow-hidden rounded-3xl border border-white/10 bg-[#0d111d]/95 shadow-2xl shadow-black/60 ring-1 ring-black/30">
        <div className="h-px bg-gradient-to-r from-transparent via-violet-400/60 to-transparent" />
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/[0.07] px-6 py-5">
          <div>
            <h2 className="text-sm font-semibold tracking-wide text-slate-100">Keyword Filters</h2>
            <p className="mt-1 text-xs text-slate-500">Changes take effect on the next scan</p>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-500 transition-colors hover:bg-white/[0.06] hover:text-slate-200">
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="space-y-5 px-6 py-5">
          <div>
            <p className="mb-2.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Include — title must contain at least one</p>
            <TagList
              items={includeKws}
              onRemove={i => removeKeyword(setIncludeKws, i)}
              input={includeInput}
              setInput={setIncludeInput}
              onAdd={() => addKeyword(includeKws, setIncludeKws, includeInput, setIncludeInput)}
              placeholder="e.g. software engineer"
            />
          </div>

          <div className="border-t border-white/[0.07] pt-4">
            <p className="mb-2.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Exclude — title must not contain any</p>
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
        <div className="flex items-center justify-between border-t border-white/[0.07] bg-black/10 px-6 py-4">
          <div className="h-5">
            {saveResult === 'ok' && (
              <span className="text-xs font-medium text-emerald-300">Saved successfully</span>
            )}
            {saveResult === 'error' && (
              <span className="text-xs font-medium text-red-300">Save failed — try again</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button onClick={onClose} className="rounded-xl border border-white/10 px-3 py-2 text-xs font-medium text-slate-400 transition-colors hover:border-white/20 hover:text-slate-200">
              Close
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="rounded-xl bg-gradient-to-r from-violet-500 to-indigo-500 px-4 py-2 text-xs font-semibold text-white shadow-lg shadow-violet-950/30 transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60"
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
      <div className="surface-card flex items-center gap-3 rounded-2xl px-5 py-4 text-sm text-slate-500">
        <span className="h-2 w-2 rounded-full bg-slate-600" />
        No scans have been recorded yet
      </div>
    )
  }

  const failed = (scan.companies ?? []).filter(company => company.status === 'failed')
  const completed = (scan.companies ?? []).length
  const isRunning = scan.status === 'running'
  const statusStyle = {
    success: 'bg-emerald-400/10 text-emerald-300 ring-emerald-400/20',
    partial: 'bg-amber-400/10 text-amber-300 ring-amber-400/20',
    failed: 'bg-red-400/10 text-red-300 ring-red-400/20',
    running: 'bg-cyan-400/10 text-cyan-300 ring-cyan-400/20',
  }[scan.status] ?? 'bg-slate-400/10 text-slate-300 ring-slate-400/20'

  const summary = isRunning
    ? `${completed} of ${scan.total_companies} companies completed`
    : scan.status === 'success'
      ? `All ${scan.total_companies} companies returned successfully`
      : `${scan.successful_companies} of ${scan.total_companies} companies returned successfully`

  return (
    <div className="surface-card overflow-hidden rounded-2xl">
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
        <div className="flex min-w-0 items-center gap-3">
          <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] ring-1 ring-inset ${statusStyle}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${isRunning ? 'animate-pulse bg-cyan-300' : 'bg-current'}`} />
            {scan.status}
          </span>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-slate-200">{summary}</p>
            <p className="mt-0.5 text-xs text-slate-500">
              {scan.trigger} scan · {relativeDate(scan.finished_at ?? scan.started_at)}
            </p>
            <p className="mt-1 text-xs text-slate-400">
              {scan.total_found} jobs found · {scan.keyword_filtered} removed by keywords · {scan.not_remote} not remote · {scan.total_seen} matching
            </p>
          </div>
        </div>
        <button
          onClick={() => setExpanded(value => !value)}
          className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-1.5 text-xs font-medium text-slate-400 transition-colors hover:border-white/20 hover:bg-white/[0.06] hover:text-slate-200"
        >
          {expanded ? 'Hide details' : 'View details'}
        </button>
      </div>

      {failed.length > 0 && !expanded && (
        <div className="border-t border-amber-400/10 bg-amber-400/[0.06] px-5 py-3 text-xs text-amber-300">
          Failed: {failed.map(company => company.company).join(', ')}
        </div>
      )}

      {expanded && (
        <div className="max-h-80 overflow-y-auto border-t border-white/[0.07] bg-black/10">
          {(scan.companies ?? []).map(company => (
            <div key={company.company} className="flex items-start justify-between gap-4 border-b border-white/[0.05] px-5 py-3 last:border-0 hover:bg-white/[0.02]">
              <div className="min-w-0">
                <p className="text-sm font-medium text-slate-300">
                  {company.company}
                  <span className="ml-2 text-xs font-normal text-slate-600">{company.ats}</span>
                </p>
                {company.error && (
                  <p className="mt-1 break-words text-xs text-red-300">{company.error}</p>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-3 text-xs">
                {company.status === 'success' && (
                  <span className="text-slate-500">
                    {company.jobs_found} found · {company.keyword_filtered} removed by keywords · {company.not_remote} not remote · {company.jobs_seen} matching
                  </span>
                )}
                <span className={company.status === 'success' ? 'font-medium text-emerald-300' : 'font-medium text-red-300'}>
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
  const [auth, setAuth]             = useState({ enabled: false, authenticated: false, can_manage: false, username: null })
  const [authLoaded, setAuthLoaded] = useState(false)

  const AGE_OPTIONS = [
    { label: '24 hours', value: 1 },
    { label: '3 days',   value: 3 },
    { label: '1 week',   value: 7 },
    { label: 'All time', value: 0 },
  ]

  function loadAuth() {
    return fetch('/api/auth/status', { cache: 'no-store' })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(data => {
        setAuth(data)
        if (!data.can_manage) setShowHidden(false)
      })
      .catch(() => setAuth({ enabled: false, authenticated: false, can_manage: false, username: null }))
      .finally(() => setAuthLoaded(true))
  }

  function loadJobs(age, canManage = auth.can_manage) {
    setLoading(true)
    setError(null)
    fetch(`/api/jobs?show_hidden=${canManage}&max_age_days=${age}`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(data => { setJobs(data); setLoading(false) })
      .catch(e  => { setError(e.message); setLoading(false) })
  }

  useEffect(() => { loadAuth() }, [])

  useEffect(() => {
    if (authLoaded) loadJobs(maxAge, auth.can_manage)
  }, [maxAge, auth.can_manage, authLoaded])

  function loadLatestScan() {
    return fetch('/api/scans/latest', { cache: 'no-store' })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(data => setLatestScan(data))
      .catch(() => {})
  }

  useEffect(() => {
    loadLatestScan()
    const scanIsActive = scanning || scanResult?.status === 'accepted' || latestScan?.status === 'running'
    const interval = setInterval(loadLatestScan, scanIsActive ? 1_000 : 60_000)
    return () => clearInterval(interval)
  }, [scanning, scanResult?.status, latestScan?.status])

  useEffect(() => {
    if (scanResult?.status !== 'accepted' || !latestScan?.started_at) return
    const isRequestedScan = new Date(latestScan.started_at) >= new Date(scanResult.accepted_at)
    if (isRequestedScan && latestScan.status !== 'running') {
      setScanResult(latestScan)
      loadJobs(maxAge)
    }
  }, [latestScan?.status, latestScan?.started_at, scanResult?.status])

  async function startScan() {
    setScanning(true)
    setScanResult(null)
    try {
      const r = await fetch('/api/scan', { method: 'POST' })
      if (r.status === 401 || r.status === 403) {
        await loadAuth()
        throw new Error('Admin session expired')
      }
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const result = await r.json()
      setScanResult(result)
      loadLatestScan()
    } catch (error) {
      setScanResult({ error: error.message || 'Scan failed' })
      loadLatestScan()
      setScanning(false)
    } finally {
      setScanning(false)
    }
  }

  async function toggleHidden(job) {
    const nextHidden = !job.hidden
    // Optimistic update
    setJobs(prev => prev.map(j => j.id === job.id ? { ...j, hidden: nextHidden ? 1 : 0 } : j))
    try {
      const response = await fetch(`/api/jobs/${job.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ hidden: nextHidden }),
      })
      if (response.status === 401 || response.status === 403) await loadAuth()
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
    } catch {
      loadJobs(maxAge)
    }
  }

  const visible   = jobs.filter(j => !j.hidden)
  const hidden    = jobs.filter(j =>  j.hidden)
  const companies = [...new Set(visible.map(j => j.company))]
  const lastScan  = latestScan?.finished_at ?? latestScan?.started_at ?? ''
  const tableColumns = auth.can_manage ? 7 : 6
  const scanPending = scanning || scanResult?.status === 'accepted'

  return (
    <div className="app-shell min-h-screen font-sans text-slate-100">

      {showSettings && auth.can_manage && <KeywordsModal onClose={() => setShowSettings(false)} />}

      {/* ── Header ── */}
      <header className="sticky top-0 z-10 border-b border-white/[0.07] bg-[#080b14]/80 shadow-lg shadow-black/10 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 to-cyan-400 shadow-lg shadow-violet-950/40 ring-1 ring-white/20">
              <svg className="h-4.5 w-4.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m4 6h.01M5 20h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
            </div>
            <div>
              <h1 className="text-sm font-semibold leading-none tracking-wide text-white">JobTracker</h1>
              <p className="mt-1 text-[11px] tracking-wide text-slate-500">Remote US · Engineering &amp; Security</p>
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-end gap-2.5">
            {!loading && !error && (
              <span className="mr-1 text-xs text-slate-500">
                <span className="font-semibold text-slate-200">{visible.length}</span> listings
              </span>
            )}

            {/* Age filter dropdown */}
            <select
              value={maxAge}
              onChange={e => setMaxAge(Number(e.target.value))}
              aria-label="Job age"
              className="control-dark rounded-xl px-3 py-2 text-xs font-medium text-slate-300 outline-none focus:border-violet-400/50 focus:ring-2 focus:ring-violet-500/15"
            >
              {AGE_OPTIONS.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>

            {/* Scan result flash */}
            {scanResult && !scanPending && (
              <span className={`rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${
                scanResult.error || scanResult.status === 'failed'
                  ? 'bg-red-400/10 text-red-300 ring-red-400/20'
                  : scanResult.status === 'partial' || scanResult.status === 'already_running'
                    ? 'bg-amber-400/10 text-amber-300 ring-amber-400/20'
                  : scanResult.new_jobs > 0
                    ? 'bg-emerald-400/10 text-emerald-300 ring-emerald-400/20'
                    : 'bg-slate-400/10 text-slate-400 ring-slate-400/20'
              }`}>
                {scanResult.error || scanResult.status === 'failed'
                  ? (typeof scanResult.error === 'string' ? scanResult.error : 'Scan failed')
                  : scanResult.status === 'already_running'
                    ? 'Scan already running'
                  : scanResult.status === 'partial'
                    ? `${scanResult.failed_companies} failed`
                  : scanResult.new_jobs > 0
                    ? `+${scanResult.new_jobs} new`
                    : 'No new jobs'}
              </span>
            )}

            {auth.can_manage ? (
              <>
                <button
                  onClick={() => setShowSettings(s => !s)}
                  title="Keyword filters"
                  className="control-dark rounded-xl p-2 text-slate-400 transition-colors hover:border-white/20 hover:bg-white/[0.07] hover:text-slate-100"
                >
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                      d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  </svg>
                </button>

                <button
                  onClick={() => setShowHidden(h => !h)}
                  className={`flex items-center gap-1.5 rounded-xl border px-3 py-2 text-xs font-medium transition-colors ${
                    showHidden
                      ? 'border-violet-400/30 bg-violet-400/10 text-violet-200'
                      : 'border-white/10 bg-white/[0.035] text-slate-400 hover:border-white/20 hover:bg-white/[0.06] hover:text-slate-200'
                  }`}
                >
                  {showHidden ? <EyeIcon /> : <EyeSlashIcon />}
                  {showHidden ? `Showing hidden (${hidden.length})` : `Hidden (${hidden.length})`}
                </button>

                <button
                  onClick={startScan}
                  disabled={scanPending}
                  className="flex items-center gap-1.5 rounded-xl bg-gradient-to-r from-violet-500 to-indigo-500 px-3.5 py-2 text-xs font-semibold text-white shadow-lg shadow-violet-950/30 transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {scanPending ? (
                    <>
                      <svg className="h-3.5 w-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                      {scanning ? 'Starting…' : 'Scan queued…'}
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

                {auth.enabled && (
                  <a href="/api/auth/logout" className="ml-1 text-xs font-medium text-slate-500 transition-colors hover:text-slate-200">
                    Sign out{auth.username ? ` (${auth.username})` : ''}
                  </a>
                )}
              </>
            ) : authLoaded && auth.enabled ? (
              <a
                href="/api/auth/login"
                className="control-dark rounded-xl px-3.5 py-2 text-xs font-semibold text-slate-300 transition-colors hover:border-violet-400/40 hover:bg-violet-400/10 hover:text-violet-200"
              >
                Admin login
              </a>
            ) : null}
          </div>
        </div>
      </header>

      <main className="relative mx-auto max-w-7xl space-y-6 px-6 py-8 sm:py-10">

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
        <div className="surface-card overflow-hidden rounded-2xl">
          <div className="flex items-center justify-between border-b border-white/[0.07] px-6 py-4">
            <div>
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-violet-300/70">Opportunity feed</p>
              <h2 className="text-sm font-semibold text-slate-200">
                {showHidden ? 'Hidden Listings' : 'Active Listings'}
              </h2>
            </div>
            {!loading && !error && jobs.length > 0 && (
              <span className="rounded-full bg-white/[0.05] px-2.5 py-1 text-xs font-medium text-slate-400 ring-1 ring-inset ring-white/[0.08]">
                {showHidden ? hidden.length : visible.length} roles
              </span>
            )}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/[0.07] bg-white/[0.025]">
                  {['Company', 'Title', 'Department', 'Location', 'Posted', 'Date Found', ...(auth.can_manage ? [''] : [])].map((col, i) => (
                    <th key={i}
                      className="px-5 py-3.5 text-left text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-600">
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>

              <tbody>
                {loading ? (
                  Array.from({ length: 10 }).map((_, i) => <SkeletonRow key={i} canManage={auth.can_manage} />)
                ) : error ? (
                  <ErrorState message={error} columnCount={tableColumns} />
                ) : (showHidden ? hidden : visible).length === 0 ? (
                  <EmptyState canManage={auth.can_manage} columnCount={tableColumns} />
                ) : (
                  (showHidden ? hidden : visible).map((job, idx) => (
                    <tr
                      key={job.id}
                      className={`group border-b border-white/[0.045] transition-colors hover:bg-violet-400/[0.045] ${
                        job.hidden ? 'opacity-50' : idx % 2 === 1 ? 'bg-white/[0.012]' : ''
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
                            className="font-medium text-slate-200 decoration-violet-400/50 underline-offset-4 transition-colors hover:text-violet-300 hover:underline">
                            {job.title}
                          </a>
                        ) : (
                          <span className="font-medium text-slate-200">{job.title}</span>
                        )}
                      </td>

                      {/* Department */}
                      <td className="whitespace-nowrap px-5 py-3.5 text-slate-500">
                        {job.department || <span className="text-slate-700">—</span>}
                      </td>

                      {/* Location */}
                      <td className="px-5 py-3.5">
                        <span className="block max-w-[200px] truncate text-slate-500" title={job.location}>
                          {job.location || <span className="text-slate-700">—</span>}
                        </span>
                      </td>

                      {/* Posted */}
                      <td className="whitespace-nowrap px-5 py-3.5">
                        <span className="font-medium text-slate-300">
                          {relativeDate(job.date_posted ?? job.date_found)}
                        </span>
                      </td>

                      {/* Date Found */}
                      <td className="whitespace-nowrap px-5 py-3.5 text-slate-600">
                        {shortDate(job.date_found)}
                      </td>

                      {auth.can_manage && (
                        <td className="whitespace-nowrap px-4 py-3.5">
                          <button
                            onClick={() => toggleHidden(job)}
                            title={job.hidden ? 'Unhide this job' : 'Hide this job'}
                            className={`rounded-md p-1.5 transition-colors ${
                              job.hidden
                                ? 'text-violet-300 hover:bg-violet-400/10 hover:text-violet-200'
                                : 'text-slate-600 opacity-0 group-hover:opacity-100 hover:bg-white/[0.06] hover:text-slate-300'
                            }`}
                          >
                            {job.hidden ? <EyeIcon /> : <EyeSlashIcon />}
                          </button>
                        </td>
                      )}
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
