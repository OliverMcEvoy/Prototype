export const defaultScanParams = {
  sport: 'all',
  threshold: '0.35',
  investment: '100',
  gbpUsdRate: '1.27',
  betfairDaysAhead: '7',
  betfairMinHoursAhead: '0',
  polymarketActiveOnly: true,
  polymarketMinVolume: '0',
}

export type ScanParams = typeof defaultScanParams

export type ScanParamKey =
  | 'sport'
  | 'threshold'
  | 'investment'
  | 'gbpUsdRate'
  | 'betfairDaysAhead'
  | 'betfairMinHoursAhead'
  | 'polymarketActiveOnly'
  | 'polymarketMinVolume'

export type ScanSelectField = {
  key: Exclude<ScanParamKey, 'polymarketActiveOnly'>
  label: string
  help: string
  kind: 'select'
  options: Array<{ value: string; label: string }>
}

export type ScanNumberField = {
  key: Exclude<ScanParamKey, 'polymarketActiveOnly'>
  label: string
  help: string
  kind: 'number'
  step?: string
  min?: string
  max?: string
}

export type ScanFieldConfig =
  | ScanSelectField
  | ScanNumberField
  | {
      key: 'polymarketActiveOnly'
      label: string
      help: string
      kind: 'checkbox'
    }

export const scanFieldConfigs: Array<ScanSelectField | ScanNumberField> = [
  {
    key: 'sport',
    label: 'Sport',
    help: 'Limits the scan to one sport family. Use All to scan everything the backend supports.',
    kind: 'select',
    options: [
      { value: 'all', label: 'All' },
      { value: 'soccer', label: 'Football' },
      { value: 'basketball', label: 'Basketball' },
      { value: 'tennis', label: 'Tennis' },
      { value: 'politics', label: 'Politics' },
      { value: 'cricket', label: 'Cricket' },
      { value: 'americanfootball', label: 'American Football' },
      { value: 'baseball', label: 'Baseball' },
      { value: 'icehockey', label: 'Ice Hockey' },
      { value: 'mma', label: 'MMA' },
      { value: 'rugby', label: 'Rugby' },
    ],
  },
  {
    key: 'threshold',
    label: 'Match threshold',
    help: 'Minimum similarity required before the matcher treats two events as a likely cross-platform pair.',
    kind: 'number',
    min: '0',
    max: '1',
    step: '0.01',
  },
  {
    key: 'investment',
    label: 'Investment',
    help: 'The notional stake used when the backend calculates arbitrage sizing and expected profit.',
    kind: 'number',
    min: '0.01',
    step: '0.01',
  },
  {
    key: 'gbpUsdRate',
    label: 'GBP/USD rate',
    help: 'Exchange rate used to normalise returned values between GBP-denominated and USD-denominated markets.',
    kind: 'number',
    min: '0.01',
    step: '0.01',
  },
  {
    key: 'betfairDaysAhead',
    label: 'Betfair days ahead',
    help: 'How far ahead Betfair is scanned for upcoming events.',
    kind: 'number',
    min: '1',
    max: '30',
    step: '1',
  },
  {
    key: 'betfairMinHoursAhead',
    label: 'Betfair minimum hours ahead',
    help: 'Skips events starting sooner than this many hours from now.',
    kind: 'number',
    min: '0',
    max: '72',
    step: '0.5',
  },
  {
    key: 'polymarketMinVolume',
    label: 'Polymarket minimum volume',
    help: 'Filters out thin markets below this volume threshold.',
    kind: 'number',
    min: '0',
    step: '1',
  },
]

export const polymarketActiveOnlyField = {
  key: 'polymarketActiveOnly' as const,
  label: 'Polymarket active only',
  help: 'When enabled, the backend ignores resolved or closed Polymarket markets.',
}
