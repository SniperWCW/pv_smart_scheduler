import { LitElement, html, css } from 'https://unpkg.com/lit?module';

class PVSmartSchedulerCard extends LitElement {
  static get properties() {
    return { hass: { type: Object }, config: { type: Object } };
  }

  static get styles() {
    return css`
      ha-card { padding: 16px; }
      table { width: 100%; border-collapse: collapse; text-align: left; font-size: 14px; }
      th { padding: 8px 4px; color: var(--secondary-text-color); border-bottom: 2px solid var(--divider-color); }
      td { padding: 10px 4px; }
      .row { border-bottom: 1px solid var(--divider-color); }
      .status-pill { padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 12px; display: inline-block; min-width: 80px; text-align: center; }
      .device-info { display: flex; align-items: center; gap: 8px; }
      .kwh { font-size: 10px; color: var(--secondary-text-color); }
    `;
  }

  render() {
    if (!this.hass || !this.config) return html``;
    
    const stateObj = this.hass.states[this.config.entity || 'sensor.pv_smart_scheduler_zentrale'];
    if (!stateObj) return html`<ha-card style="color: red; padding: 16px;">Entität nicht gefunden!</ha-card>`;

    const devices = stateObj.attributes.devices || [];

    return html`
      <ha-card>
        <table>
          <thead>
            <tr><th>Prio</th><th>Gerät</th><th style="text-align:center">Status</th><th style="text-align:right">PV-Deckung</th></tr>
          </thead>
          <tbody>
            ${devices.length === 0 
              ? html`<tr><td colspan="4" style="text-align:center">Keine Geräte konfiguriert</td></tr>`
              : devices.map(d => this._renderDevice(d))}
          </tbody>
        </table>
      </ha-card>
    `;
  }

  _renderDevice(d) {
    const isRunning = d.is_running || d.recommendation === 'läuft';
    const isReady = d.recommendation === 'ja';
    const color = isRunning ? 'var(--info-color)' : (isReady ? 'var(--success-color)' : 'var(--warning-color)');
    
    return html`
      <tr class="row">
        <td>#${d.priority ?? '-'}</td>
        <td>
          <div class="device-info">
            <ha-icon icon="${this._getIcon(d.name)}" style="color: ${color}"></ha-icon>
            ${d.name}
          </div>
        </td>
        <td style="text-align:center">
          <span class="status-pill" style="background: ${color}22; color: ${color};">
            ${isRunning ? 'Läuft' : (d.best_start_mins === 0 ? 'Sofort' : `In ${d.best_start_mins} Min`)}
          </span>
        </td>
        <td style="text-align:right; color: ${color}; font-weight: bold;">
          ${Number(d.pv_coverage || 0).toFixed(1)}%
          <div class="kwh">${Number(d.estimated_kwh || 0).toFixed(2)} kWh</div>
        </td>
      </tr>
    `;
  }

  _getIcon(name) {
    const lower = name.toLowerCase();
    if (lower.includes('wasch')) return 'mdi:washing-machine';
    if (lower.includes('trock')) return 'mdi:tumble-dryer';
    if (lower.includes('spül')) return 'mdi:dishwasher';
    if (lower.includes('pool')) return 'mdi:pool';
    return 'mdi:clock-outline';
  }

  setConfig(config) { this.config = config; }
  getCardSize() { return 3; }
}

customElements.define('pv-smart-scheduler-card', PVSmartSchedulerCard);
