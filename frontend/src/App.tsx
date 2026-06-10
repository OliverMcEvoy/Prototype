import { useCallback, useEffect, useMemo, useState } from 'react'

type Section =
  | 'Overview'
  | 'Matched Pairs'
  | 'Cross-Platform Opportunities'
//   | 'Traditional Events'
//   | 'Polymarket Markets'
  | 'Candidate Matches'

interface BetfairEventSummary {
  home_team?: string
  away_team?: string
  sport?: string
  description?: string
}

interface PolymarketEventSummary {
  question?: string
  sport_category?: string
}

interface MatchedPair {
  betfair?: BetfairEventSummary
  polymarket?: PolymarketEventSummary
  similarity: number
}

interface Opportunity {
  event?: {
    home_team?: string
    away_team?: string
    description?: string
  }
  profit_percentage?: number
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
  'Overview',
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
  value: string
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

export default function App() {
  const [activeSection, setActiveSection] = useState<Section>('Overview')
  const [scanData, setScanData] = useState<DashboardScanResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadScan = useCallback(async () => {
    setLoading(true)
    setError('')

    try {
      const response = await fetch('/api/dashboard/scan?sport=all')
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
    loadScan()
  }, [loadScan])

  const summary = useMemo(
    () => [
      {
        title: 'Matched pairs',
        value: loading ? '…' : String(scanData?.matched_pair_count ?? 0),
        subtitle: 'From the latest scan',
      },
      {
        title: 'Opportunities',
        value: loading ? '…' : String(scanData?.opportunity_count ?? 0),
        subtitle: 'Above threshold',
      },
      {
        title: 'Last update',
        value: loading ? 'Loading' : 'Live',
        subtitle: scanData?.generated_at
          ? new Date(scanData.generated_at).toLocaleString()
          : 'Backend response timestamp',
      },
    ],
    [loading, scanData],
  )

  const matchedPairs = scanData?.matched_pairs ?? []
  const opportunities = scanData?.opportunities ?? []
  const tradEvents = scanData?.sample_betfair_events ?? []
  const polyMarkets = scanData?.sample_polymarket_markets ?? []

  const formatEvent = (item: MatchedPair) => {
    const bf =
      item.betfair?.description ||
      `${item.betfair?.home_team ?? 'Unknown'} vs ${item.betfair?.away_team ?? 'Unknown'}`
    const pm = item.polymarket?.question || 'Unknown market'
    return `${bf} · ${pm} · ${(item.similarity * 100).toFixed(1)}%`
  }

  const formatOpportunity = (item: Opportunity) => {
    const event =
      item.event?.description ||
      `${item.event?.home_team ?? 'Unknown'} vs ${item.event?.away_team ?? 'Unknown'}`
    return `${event} · ${(item.profit_percentage ?? 0).toFixed(2)}% profit`
  }

  const formatBetfairEvent = (item: BetfairEventSummary) =>
    `${item.sport ?? 'Sport'} · ${item.description || `${item.home_team ?? 'Unknown'} vs ${item.away_team ?? 'Unknown'}`}`

  const formatPolymarketEvent = (item: PolymarketEventSummary) =>
    `${item.sport_category || 'sports'} · ${item.question || 'Unknown question'}`

  return (
    <div className="app-shell">
      <header className="hero card">
        <div>
          <div className="eyebrow">Arbitrage dashboard</div>
          <h1>React frontend demo</h1>
          <p>
            A frontend dashbaord for the polymarket arbitrage TBD name.
          </p>
        </div>
        <div className="hero-actions">
          <button className="button primary" onClick={loadScan}>
            Refresh
          </button>
          <button className="button">Export</button>
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

      <main className="grid">
        <section className="card panel">
          <h2>{activeSection}</h2>
          <p className="muted">
            {loading && 'Loading live backend data…'}
            {activeSection === 'Overview' &&
              'A simple landing area for the rebuilt dashboard.'}
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

          {activeSection === 'Matched Pairs' && (
            <SectionList items={matchedPairs.map(formatEvent)} />
          )}
          {activeSection === 'Cross-Platform Opportunities' && (
            <SectionList items={opportunities.map(formatOpportunity)} />
          )}
          {/* {activeSection === 'Traditional Events' && (
            <SectionList items={tradEvents.map(formatBetfairEvent)} />
          )}
          {activeSection === 'Polymarket Markets' && (
            <SectionList items={polyMarkets.map(formatPolymarketEvent)} />
          )} */}
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

        <aside className="card panel sidebar">
          <h2>Next steps</h2>
          <ul className="todo-preview">
            <li>Implement configuration options for the frontend</li>
            <li>Implemment periodic refresh</li>
            <li>Dockerise</li>
          </ul>
        </aside>
      </main>
    </div>
  )
}
