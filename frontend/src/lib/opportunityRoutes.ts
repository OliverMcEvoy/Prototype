export interface OpportunityOutcome {
  name?: string
  price?: number
  bookmaker?: string
  last_update?: string
  volume?: number
}

export interface OpportunityEvent {
  id?: string
  sport?: string
  commence_time?: string
  home_team?: string
  away_team?: string
  description?: string
  category?: string
}

export interface Opportunity {
  event?: OpportunityEvent
  best_outcomes?: OpportunityOutcome[]
  total_stake?: number
  stake_distribution?: Record<string, number>
  profit?: number
  profit_percentage?: number
  roi?: number
}

export interface OpportunitySnapshot {
  id: string
  opportunity: Opportunity
  generated_at?: string
  saved_at: string
}

export const OPPORTUNITY_ROUTE_PREFIX = '#/opportunity/'
export const OPPORTUNITY_STORAGE_PREFIX = 'prototype:opportunity:'

function slugify(value: string) {
  return (
    value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '') || 'opportunity'
  )
}

function hashString(value: string) {
  let hash = 2166136261

  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }

  return (hash >>> 0).toString(36)
}

export function formatOpportunityLabel(item: Opportunity) {
  return (
    item.event?.description ||
    `${item.event?.home_team ?? 'Unknown'} vs ${item.event?.away_team ?? 'Unknown'}`
  )
}

export function buildOpportunityId(item: Opportunity) {
  const label = formatOpportunityLabel(item)
  const fingerprint = JSON.stringify({
    label,
    sport: item.event?.sport ?? '',
    commence_time: item.event?.commence_time ?? '',
    profit_percentage: item.profit_percentage ?? 0,
    profit: item.profit ?? 0,
    roi: item.roi ?? 0,
    best_outcomes: (item.best_outcomes ?? []).map((outcome) => [
      outcome.name ?? '',
      outcome.price ?? 0,
      outcome.bookmaker ?? '',
    ]),
  })

  return `${slugify(label)}-${hashString(fingerprint)}`
}

export function readOpportunitySnapshot(id: string) {
  if (typeof window === 'undefined') {
    return null
  }

  const raw = window.localStorage.getItem(`${OPPORTUNITY_STORAGE_PREFIX}${id}`)
  if (!raw) {
    return null
  }

  try {
    return JSON.parse(raw) as OpportunitySnapshot
  } catch {
    return null
  }
}

export function saveOpportunitySnapshot(snapshot: OpportunitySnapshot) {
  if (typeof window === 'undefined') {
    return
  }

  window.localStorage.setItem(
    `${OPPORTUNITY_STORAGE_PREFIX}${snapshot.id}`,
    JSON.stringify(snapshot),
  )
}

export function getHashRoute() {
  return typeof window === 'undefined' ? '#/' : window.location.hash || '#/'
}

export function getOpportunityRouteId(route: string) {
  return route.startsWith(OPPORTUNITY_ROUTE_PREFIX)
    ? decodeURIComponent(route.slice(OPPORTUNITY_ROUTE_PREFIX.length))
    : ''
}
