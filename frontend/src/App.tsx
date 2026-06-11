import { type ReactNode, useCallback, useEffect, useMemo, useState } from 'react'
import { ScanControls, TodoPanel } from './components'
import OpportunityDetailPage from './pages/OpportunityDetailPage'
import {
  buildOpportunityId,
  formatOpportunityDisplayLabel,
  getHashRoute,
  getOpportunityRouteId,
  readOpportunitySnapshot,
  saveOpportunitySnapshot,
  type OpportunitySnapshot,
  type Opportunity,
} from './lib/opportunityRoutes'
import {
  defaultScanParams,
  type ScanParamKey,
  type ScanParams,
} from './config/scanFieldConfig'

type Section =
  | 'Scan Controls'
  | 'Matched Pairs'
  | 'Cross-Platform Opportunities'
//   | 'Traditional Events'
//   | 'Polymarket Markets'
  | 'Candidate Matches'

type ThemeName = 'sepia' | 'terminal' | 'blue' | 'glass' | 'graphite'

const themeOptions: Array<{ value: ThemeName; label: string }> = [
  { value: 'sepia', label: 'Sepia' },
  { value: 'terminal', label: 'Terminal' },
  { value: 'blue', label: 'Blue' },
  { value: 'glass', label: 'Glass' },
  { value: 'graphite', label: 'Graphite' },
]

interface BetfairEventSummary {
  id?: string
  home_team?: string
  away_team?: string
  sport?: string
  description?: string
  commence_time?: string
  category?: string
}

interface PolymarketEventSummary {
  id?: string
  question?: string
  sport_category?: string
}

interface MatchedPair {
  betfair?: BetfairEventSummary
  polymarket?: PolymarketEventSummary
  similarity: number
}

interface DashboardScanResponse {
  matched_pair_count?: number
  opportunity_count?: number
  generated_at?: string
  matched_pairs?: MatchedPair[]
  opportunities?: Opportunity[]
  sample_betfair_events?: BetfairEventSummary[]
  sample_polymarket_markets?: PolymarketEventSummary[]
  unmatched_betfair_count?: number
  unmatched_polymarket_count?: number
}

const sections: Section[] = [
  'Scan Controls',
  'Cross-Platform Opportunities',
  'Matched Pairs',
//   'Traditional Events',
//   'Polymarket Markets',
  'Candidate Matches',
]

function Card({
  title,
  value,
  subtitle,
}: {
  title: string
  value: ReactNode
  subtitle: string
}) {
  return (
    <div className="card metric-card">
      <div className="metric-title">{title}</div>
      <div className="metric-value">{value}</div>
      <div className="metric-subtitle">{subtitle}</div>
    </div>
  )
}

function LoadingDots() {
  return (
    <span className="loading-dots" aria-label="Updating" aria-live="polite">
      <span className="loading-dot">.</span>
      <span className="loading-dot">.</span>
      <span className="loading-dot">.</span>
    </span>
  )
}

function SectionList({ items }: { items: string[] }) {
  return (
    <div className="list">
      {items.map((item) => (
        <div className="list-row" key={item}>
          <span>{item}</span>
          <span className="muted">→</span>
        </div>
      ))}
    </div>
  )
}

function OpportunityList({
  items,
  onOpen,
}: {
  items: Opportunity[]
  onOpen: (item: Opportunity) => void
}) {
  return (
    <div className="list">
      {items.map((item, index) => {
        const id = buildOpportunityId(item)
        const href = `${'#'}${'/opportunity/'}${id}`

        return (
          <a
            className="list-row opportunity-row"
            href={href}
            key={`${id}-${index}`}
            onClick={(event) => {
              event.preventDefault()
              onOpen(item)
            }}
          >
            <span className="opportunity-copy">
              <span className="opportunity-title">{formatOpportunityDisplayLabel(item)}</span>
              <span className="opportunity-meta">
                {(item.profit_percentage ?? 0).toFixed(2)}% profit
              </span>
            </span>
            <span className="list-arrow" aria-hidden="true">
              →
            </span>
          </a>
        )
      })}
    </div>
  )
}

export default function App() {
  const [route, setRoute] = useState(getHashRoute)
  const [activeSection, setActiveSection] = useState<Section>('Scan Controls')
  const [scanData, setScanData] = useState<DashboardScanResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [scanParams, setScanParams] = useState<ScanParams>(defaultScanParams)
  const [todoDetached, setTodoDetached] = useState(false)
  const [themeName, setThemeName] = useState<ThemeName>(() => {
    if (typeof window === 'undefined') {
      return 'sepia'
    }

    const savedTheme = window.localStorage.getItem('prototype:theme')
    return savedTheme === 'terminal' || savedTheme === 'blue' || savedTheme === 'glass' || savedTheme === 'graphite' || savedTheme === 'sepia'
      ? savedTheme
      : 'sepia'
  })

  const loadScan = useCallback(async (params: ScanParams) => {
    setLoading(true)
    setError('')

    try {
      const query = new URLSearchParams({
        sport: params.sport,
        threshold: params.threshold,
        investment: params.investment,
        gbp_usd_rate: params.gbpUsdRate,
        betfair_days_ahead: params.betfairDaysAhead,
        betfair_min_hours_ahead: params.betfairMinHoursAhead,
        polymarket_active_only: String(params.polymarketActiveOnly),
        polymarket_min_volume: params.polymarketMinVolume,
      })
      const response = await fetch(`/api/dashboard/scan?${query.toString()}`)
      if (!response.ok) {
        const message = await response.text()
        throw new Error(message || `Request failed with status ${response.status}`)
      }

      const payload = (await response.json()) as DashboardScanResponse
      setScanData(payload)
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadScan(defaultScanParams)
  }, [loadScan])

  useEffect(() => {
    document.body.dataset.theme = themeName
    window.localStorage.setItem('prototype:theme', themeName)

    return () => {
      delete document.body.dataset.theme
    }
  }, [themeName])

  useEffect(() => {
    const handleHashChange = () => {
      setRoute(getHashRoute())
    }

    window.addEventListener('hashchange', handleHashChange)

    return () => {
      window.removeEventListener('hashchange', handleHashChange)
    }
  }, [])

  const summary = useMemo(
    () => [
      {
        title: 'Matched pairs',
        value: loading ? <LoadingDots /> : String(scanData?.matched_pair_count ?? 0),
        subtitle: 'From the latest scan',
      },
      {
        title: 'Opportunities',
        value: loading ? <LoadingDots /> : String(scanData?.opportunity_count ?? 0),
        subtitle: 'Above threshold',
      },
      {
        title: 'Last update',
        value: loading ? 'Updating' : 'Live',
        subtitle: scanData?.generated_at
          ? new Date(scanData.generated_at).toLocaleString()
          : 'Backend response timestamp',
      },
    ],
    [loading, scanData],
  )

  const matchedPairs = scanData?.matched_pairs ?? []
  const opportunities = scanData?.opportunities ?? []
  const opportunityRouteId = getOpportunityRouteId(route)

  const opportunitySnapshot = useMemo(() => {
    if (!opportunityRouteId) {
      return null
    }

    const cachedSnapshot = readOpportunitySnapshot(opportunityRouteId)
    if (cachedSnapshot) {
      return cachedSnapshot
    }

    const liveOpportunity = opportunities.find(
      (item) => buildOpportunityId(item) === opportunityRouteId,
    )

    if (!liveOpportunity) {
      return null
    }

    return {
      id: opportunityRouteId,
      opportunity: liveOpportunity,
      generated_at: scanData?.generated_at,
      saved_at: scanData?.generated_at ?? new Date().toISOString(),
    } as OpportunitySnapshot
  }, [opportunities, opportunityRouteId, scanData?.generated_at])

  const formatEvent = (item: MatchedPair) => {
    const bf =
      item.betfair?.description ||
      `${item.betfair?.home_team ?? 'Unknown'} vs ${item.betfair?.away_team ?? 'Unknown'}`
    const pm = item.polymarket?.question || 'Unknown market'
    return `${bf} · ${pm} · ${(item.similarity * 100).toFixed(1)}%`
  }

  const openOpportunityPage = useCallback(
    (item: Opportunity) => {
      const id = buildOpportunityId(item)

      saveOpportunitySnapshot({
        id,
        opportunity: item,
        generated_at: scanData?.generated_at,
        saved_at: new Date().toISOString(),
      })

      window.location.hash = `#/opportunity/${id}`
    },
    [scanData?.generated_at],
  )

  const returnToDashboard = useCallback(() => {
    window.location.hash = '#/'
  }, [])

  const updateScanParam = useCallback(
    (key: ScanParamKey, value: string | boolean) => {
      setScanParams((current) => ({
        ...current,
        [key]: value,
      }))
    },
    [],
  )

  const submitScanRequest = useCallback(() => {
    void loadScan(scanParams)
  }, [loadScan, scanParams])

  const updateTheme = useCallback((event: React.ChangeEvent<HTMLSelectElement>) => {
    setThemeName(event.target.value as ThemeName)
  }, [])

  if (opportunityRouteId) {
    return opportunitySnapshot ? (
      <div className="app-shell">
        <OpportunityDetailPage snapshot={opportunitySnapshot} onBack={returnToDashboard} />
        <div className="theme-switcher" aria-label="Theme selector">
          <select id="theme-select-detail" value={themeName} onChange={updateTheme}>
            {themeOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>
    ) : (
      <div className="app-shell">
        <header className="hero card detail-hero">
          <div>
            <div className="eyebrow">Opportunity page</div>
            <h1>Loading saved opportunity</h1>
            <p>
              This permalink is valid, but the snapshot is not cached yet. Refresh the dashboard or wait for the latest scan.
            </p>
          </div>
          <div className="hero-actions">
            <button className="button primary" onClick={returnToDashboard}>
              Back to dashboard
            </button>
          </div>
        </header>
        <div className="theme-switcher" aria-label="Theme selector">
          <select
            id="theme-select-detail-loading"
            value={themeName}
            onChange={updateTheme}
          >
            {themeOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>
    )
  }

  return (
    <div className="app-shell">
      <header className="hero card">
        <div>
          <div className="eyebrow">React frontend demo</div>
          <h1>Arbitage Dashboard</h1>
          <p>A frontend dashboard for the Polymarket arbitrage scanner.</p>
        </div>
      </header>

      {error ? <div className="card panel error-box">Backend error: {error}</div> : null}

      <section className="metrics">
        {summary.map((item) => (
          <Card key={item.title} {...item} />
        ))}
      </section>

      <nav className="tabs card">
        {sections.map((section) => (
          <button
            key={section}
            className={section === activeSection ? 'tab active' : 'tab'}
            onClick={() => setActiveSection(section)}
          >
            {section}
          </button>
        ))}
      </nav>

      <main className={todoDetached ? 'grid grid-expanded' : 'grid'}>
        <section className="card panel">
          <h2>{activeSection}</h2>
          <p className="muted">
            {loading && 'Loading live backend data…'}
            {activeSection === 'Scan Controls' &&
              'Adjust the backend scan parameters, then request an updated data set.'}
            {activeSection === 'Cross-Platform Opportunities' &&
              'Profitable back-back and lay-back candidates.'}
            {activeSection === 'Matched Pairs' &&
              'Pairs detected by the matching engine.'}
            {/* {activeSection === 'Traditional Events' &&
              'Betfair events awaiting Polymarket alignment.'}
            {activeSection === 'Polymarket Markets' &&
              'Polymarket markets awaiting Betfair alignment.'} */}
            {activeSection === 'Candidate Matches' &&
              'Near-miss binary markets and election-style matches.'}
          </p>

          {activeSection === 'Scan Controls' && (
            <ScanControls
              loading={loading}
              scanParams={scanParams}
              onChange={updateScanParam}
              onSubmit={submitScanRequest}
            />
          )}

          {activeSection === 'Matched Pairs' && (
            <SectionList items={matchedPairs.map(formatEvent)} />
          )}
          {activeSection === 'Cross-Platform Opportunities' && (
            <OpportunityList items={opportunities} onOpen={openOpportunityPage} />
          )}
          {activeSection === 'Candidate Matches' && (
            <SectionList
              items={
                scanData?.unmatched_betfair_count !== undefined
                  ? [
                      `Unmatched Betfair events: ${scanData.unmatched_betfair_count}`,
                      `Unmatched Polymarket events: ${scanData.unmatched_polymarket_count}`,
                    ]
                  : ['Run a live scan to view candidate matches.']
              }
            />
          )}
        </section>

        <TodoPanel onDetachedChange={setTodoDetached} />
      </main>

      <div className="theme-switcher" aria-label="Theme selector">
        <select id="theme-select" value={themeName} onChange={updateTheme}>
          {themeOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

    </div>
  )
}
