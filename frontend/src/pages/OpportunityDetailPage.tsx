import { type Opportunity, type OpportunitySnapshot, OPPORTUNITY_ROUTE_PREFIX, formatOpportunityDisplayLabel, formatSportDisplayLabel } from '../lib/opportunityRoutes'

function formatCurrency(value?: number) {
  if (value === undefined || Number.isNaN(value)) {
    return '—'
  }

  return value.toFixed(2)
}

function formatDateTime(value?: string) {
  if (!value) {
    return 'Unavailable'
  }

  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

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

function formatPercent(value?: number) {
  if (value === undefined || Number.isNaN(value)) {
    return '—'
  }

  return `${value.toFixed(2)}%`
}

function formatStake(value?: number) {
  if (value === undefined || Number.isNaN(value)) {
    return '—'
  }

  return value.toFixed(2)
}

function formatSignedMoney(value?: number) {
  if (value === undefined || Number.isNaN(value)) {
    return '—'
  }

  const prefix = value > 0 ? '+' : ''
  return `${prefix}${value.toFixed(2)}`
}

function getPerOutcomeResults(opportunity: Opportunity) {
  const bestOutcomes = opportunity.best_outcomes ?? []
  const stakeEntries = Object.entries(opportunity.stake_distribution ?? {})

  return bestOutcomes.map((outcome, index) => {
    const stake = stakeEntries[index]?.[1] ?? 0
    const payout = stake * (outcome.price ?? 0)
    const netResult = payout - (opportunity.total_stake ?? 0)

    return {
      outcome,
      stake,
      payout,
      netResult,
    }
  })
}

function getStakeDistribution(opportunity: Opportunity) {
  const distribution = opportunity.stake_distribution ?? {}

  return Object.entries(distribution)
    .map(([bookmaker, amount]) => ({ bookmaker, amount }))
    .sort((left, right) => right.amount - left.amount)
}

function formatDetailHeaderLabel(opportunity: Opportunity) {
  const rawLabel = opportunity.event?.description || formatOpportunityDisplayLabel(opportunity)

  return rawLabel
    .replace(/^\[[^\]]+\]\s*/i, '')
    .replace(/^\d+(?:\.\d+)?%\s*match:\s*/i, '')
    .replace(/\s+—\s+Moneyline.*$/i, '')
    .replace(/\s+\/\s+Polymarket:.*$/i, '')
    .replace(/^(?:American Football|Football|Soccer|Basketball|Tennis|Baseball|Ice Hockey|Cricket|MMA|Rugby|Politics):\s*/i, '')
    .trim()
}

export default function OpportunityDetailPage({
  snapshot,
  onBack,
}: {
  snapshot: OpportunitySnapshot
  onBack: () => void
}) {
  const opportunity: Opportunity = snapshot.opportunity
  const event = opportunity.event
  const stakeDistribution = getStakeDistribution(opportunity)
  const perOutcomeResults = getPerOutcomeResults(opportunity)
  const totalStake = opportunity.total_stake
  const guaranteedProfit = opportunity.profit
  const guaranteedReturn =
    totalStake !== undefined && guaranteedProfit !== undefined
      ? totalStake + guaranteedProfit
      : undefined
  const eventLabel = formatDetailHeaderLabel(opportunity)
  const eventSubtitleParts = [
    formatSportDisplayLabel(event?.sport),
    event?.commence_time ? formatDateTime(event.commence_time) : '',
  ].filter(Boolean)

  return (
    <div className="detail-layout">
      <header className="hero card detail-hero">
        <button
          className="detail-back-arrow"
          onClick={onBack}
          aria-label="Back to dashboard"
          title="Back to dashboard"
          type="button"
        >
          ←
        </button>
        <div>
          <div className="eyebrow">Opportunity details</div>
          <h1>{eventLabel}</h1>
          <p>
            {eventSubtitleParts.join(' · ')}
          </p>

        </div>
      </header>

      <section className="metrics detail-metrics">
        <Card title="ROI" value={formatPercent(opportunity.roi)} subtitle="Reported by the backend" />
        <Card
          title="Event date"
          value={event?.commence_time ? formatDateTime(event.commence_time) : 'Unavailable'}
          subtitle="Scheduled start"
        />
        <Card
          title="Saved"
          value={new Date(snapshot.saved_at).toLocaleDateString()}
          subtitle={formatDateTime(snapshot.generated_at)}
        />
      </section>

      <main className="grid detail-grid">
        <section className="card panel">
          <h2>Summary</h2>
          <p className="muted">A quick view of the stake split and guaranteed return.</p>

          <div className="detail-blocks">
            <div className="detail-block">
              <span className="detail-label">Total stake</span>
              <strong>{formatStake(totalStake)}</strong>
            </div>
            <div className="detail-block">
              <span className="detail-label"> profit</span>
              <strong>{formatStake(guaranteedProfit)}</strong>
            </div>
            <div className="detail-block">
              <span className="detail-label">Expected return</span>
              <strong>{formatStake(guaranteedReturn)}</strong>
            </div>
          </div>

          <h3 className="detail-heading">Stake split</h3>
          <div className="list">
            {stakeDistribution.length > 0 ? (
              stakeDistribution.map(({ bookmaker, amount }) => (
                <div className="list-row detail-outcome" key={bookmaker}>
                  <span>
                    <span className="opportunity-title">{bookmaker}</span>
                    <span className="opportunity-meta"> Place {formatStake(amount)} on this leg</span>
                  </span>
                  <span className="muted">
                    {totalStake ? `${((amount / totalStake) * 100).toFixed(1)}%` : '—'}
                  </span>
                </div>
              ))
            ) : (
              <div className="list-row">
                <span>No stake split was returned for this opportunity.</span>
                <span className="muted">—</span>
              </div>
            )}
          </div>

          <h3 className="detail-heading">Event context</h3>
          <div className="detail-blocks">
            <div className="detail-block">
              <span className="detail-label">Event</span>
              <strong>{eventLabel}</strong>
            </div>
            <div className="detail-block">
              <span className="detail-label">Source event id</span>
              <strong>{event?.id ?? 'Unavailable'}</strong>
            </div>
            <div className="detail-block">
              <span className="detail-label">Market timing</span>
              <strong>{event?.commence_time ? formatDateTime(event.commence_time) : 'Unavailable'}</strong>
            </div>
          </div>

          <h3 className="detail-heading">Possible outcomes</h3>
          <div className="list">
            {perOutcomeResults.length > 0 ? (
              perOutcomeResults.map(({ outcome, stake, payout, netResult }, index) => (
                <div className="list-row detail-outcome" key={`${outcome.bookmaker ?? ' bookmaker'}-${index}`}>
                  <span>
                    <span className="opportunity-title">{outcome.name ?? 'Outcome'}</span>
                    <span className="opportunity-meta">
                      {' '}
                      {outcome.bookmaker ?? 'Unknown bookmaker'} · stake {formatStake(stake)} · odds {formatCurrency(outcome.price)}
                    </span>
                  </span>
                  <span className={netResult >= 0 ? 'profit-value' : 'loss-value'}>
                    {formatSignedMoney(netResult)}
                    <span className="result-subtitle">
                      payout {formatStake(payout)}
                    </span>
                  </span>
                </div>
              ))
            ) : (
              <div className="list-row">
                <span>No outcome breakdown returned for this opportunity.</span>
                <span className="muted">—</span>
              </div>
            )}
          </div>
        </section>

        <aside className="card panel sidebar">
          <h2>Permalink</h2>
          <p className="muted">Open this same link later to return to the stored snapshot in this browser.</p>
          <div className="permalink-box">{OPPORTUNITY_ROUTE_PREFIX}{snapshot.id}</div>
          <h2>Snapshot info</h2>
          <ul className="todo-preview">
            <li>Generated at: {snapshot.generated_at ? formatDateTime(snapshot.generated_at) : 'Unavailable'}</li>
            <li>Saved locally: {formatDateTime(snapshot.saved_at)}</li>
            <li>Permalink persists without a backend route change</li>
          </ul>
        </aside>
      </main>
    </div>
  )
}
