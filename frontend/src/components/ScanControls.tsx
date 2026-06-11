import {
  scanFieldConfigs,
  polymarketActiveOnlyField,
  type ScanParamKey,
  type ScanParams,
} from '../config/scanFieldConfig'

function ScanFieldLabel({ label, help }: { label: string; help: string }) {
  return (
    <span className="scan-field-label" title={help}>
      {label}
    </span>
  )
}

export function ScanControls({
  scanParams,
  loading,
  onChange,
  onSubmit,
}: {
  scanParams: ScanParams
  loading: boolean
  onChange: (key: ScanParamKey, value: string | boolean) => void
  onSubmit: () => void
}) {
  return (
    <div className="scan-controls">
      <div className="scan-grid">
        {scanFieldConfigs.map((field) => {
          if (field.kind === 'select') {
            const value = scanParams[field.key]

            return (
              <label className="scan-field" key={field.key}>
                <ScanFieldLabel label={field.label} help={field.help} />
                <select
                  value={value}
                  onChange={(event) => onChange(field.key, event.target.value)}
                >
                  {field.options.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
            )
          }

          const value = scanParams[field.key]

          return (
            <label className="scan-field" key={field.key}>
              <ScanFieldLabel label={field.label} help={field.help} />
              <input
                type="number"
                min={field.min}
                max={field.max}
                step={field.step}
                value={value}
                onChange={(event) => onChange(field.key, event.target.value)}
              />
            </label>
          )
        })}
      </div>

      <label className="scan-term scan-field-checkbox">
        <span className="scan-checkbox-copy">
          <ScanFieldLabel
            label={polymarketActiveOnlyField.label}
            help={polymarketActiveOnlyField.help}
          />
          <span className="scan-field-hint">{polymarketActiveOnlyField.help}</span>
        </span>
        <input
          type="checkbox"
          checked={scanParams.polymarketActiveOnly}
          onChange={(event) => onChange('polymarketActiveOnly', event.target.checked)}
        />
      </label>

      <div className="scan-actions">
        <button className="scan-update-button" onClick={onSubmit} disabled={loading}>
          {loading ? 'Updating…' : 'Update'}
        </button>
      </div>
    </div>
  )
}
