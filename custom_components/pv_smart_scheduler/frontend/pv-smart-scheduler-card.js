class PVSmartSchedulerCard extends HTMLElement {
  set hass(hass) {
    const entityId = (this.config && this.config.entity) || 'sensor.pv_smart_scheduler_zentrale';
    const stateObj = hass.states[entityId];

    if (!stateObj) {
      this.innerHTML = `<ha-card style="padding: 16px; color: red;">Entität ${entityId} nicht gefunden!</ha-card>`;
      return;
    }

    const devices = stateObj.attributes.devices || [];

    if (!this.content) {
      this.innerHTML = `
        <ha-card>
          <div style="padding: 16px;">
            <table style="width: 100%; border-collapse: collapse; text-align: left; font-size: 14px;">
              <thead>
                <tr style="border-bottom: 2px solid var(--divider-color, #e0e0e0); color: var(--secondary-text-color);">
                  <th style="padding: 8px 4px; width: 40px;">Prio</th>
                  <th style="padding: 8px 4px;">Gerät</th>
                  <th style="padding: 8px 4px; text-align: center;">Startzeit</th>
                  <th style="padding: 8px 4px; text-align: right;">PV-Deckung</th>
                </tr>
              </thead>
              <tbody id="scheduler-tbody"></tbody>
            </table>
          </div>
        </ha-card>
      `;
      this.content = this.querySelector('#scheduler-tbody');
    }

    let html = '';
    if (devices.length === 0) {
      html = `<tr><td colspan="4" style="padding: 16px; text-align: center; color: var(--secondary-text-color);">Keine Geräte konfiguriert</td></tr>`;
    } else {
      devices.forEach((device) => {
        const isReady = device.recommendation === 'ja';
        const startMins = this.getFirstNumber(
          device,
          ['best_start_mins', 'best_start_minutes', 'start_in_mins'],
          0
        );
        const pvCoverage = this.getFirstNumber(
          device,
          ['pv_coverage', 'coverage_percent', 'pvDeckung'],
          0
        );
        const estimatedKwh = this.getFirstNumber(
          device,
          ['estimated_kwh', 'total_kwh', 'estimatedKwh'],
          0
        );

        const bestStartDisplay =
          isReady && startMins === 0
            ? 'Sofort'
            : startMins > 0
              ? `In ${startMins} Min`
              : 'Warten';
        const statusColor = isReady ? '#4caf50' : '#ff9800';
        const icon = this.getDeviceIcon(device.name || '');
        const name = this.escapeHtml(device.name || 'Gerät');
        const prio = device.priority !== undefined && device.priority !== null ? device.priority : '-';

        html += `
          <tr style="border-bottom: 1px solid var(--divider-color, rgba(0,0,0,0.1));">
            <td style="padding: 10px 4px; font-weight: bold; color: var(--secondary-text-color);">#${prio}</td>
            <td style="padding: 10px 4px; font-weight: 500;">
              <div style="display: flex; align-items: center; gap: 8px;">
                <ha-icon icon="${icon}" style="color: ${isReady ? 'var(--success-color, #4caf50)' : 'var(--primary-text-color)'}; --mdc-icon-size: 18px;"></ha-icon>
                <span>${name}</span>
              </div>
            </td>
            <td style="padding: 10px 4px; text-align: center;">
              <span style="background: ${statusColor}22; color: ${statusColor}; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 12px; display: inline-block; min-width: 80px;">
                ${bestStartDisplay}
              </span>
            </td>
            <td style="padding: 10px 4px; text-align: right; font-weight: bold; color: ${isReady ? 'var(--success-color, #4caf50)' : 'var(--primary-text-color)'};">
              ${this.formatNumber(pvCoverage, 1)}%
              <div style="font-size: 10px; font-weight: normal; color: var(--secondary-text-color);">${this.formatNumber(estimatedKwh, 2)} kWh</div>
            </td>
          </tr>
        `;
      });
    }

    this.content.innerHTML = html;
  }

  getFirstNumber(source, keys, fallback = 0) {
    for (const key of keys) {
      const value = Number(source[key]);
      if (Number.isFinite(value)) {
        return value;
      }
    }
    return fallback;
  }

  formatNumber(value, fractionDigits) {
    return Number(value).toLocaleString(undefined, {
      minimumFractionDigits: fractionDigits,
      maximumFractionDigits: fractionDigits,
    });
  }

  escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (char) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#039;',
    }[char]));
  }

  getDeviceIcon(name) {
    const lower = name.toLowerCase();
    if (lower.includes('wasch') || lower.includes('wash')) return 'mdi:washing-machine';
    if (lower.includes('trock') || lower.includes('dryer')) return 'mdi:tumble-dryer';
    if (lower.includes('spül') || lower.includes('dish')) return 'mdi:dishwasher';
    if (lower.includes('pool')) return 'mdi:pool';
    return 'mdi:clock-outline';
  }

  setConfig(config) {
    this.config = config;
  }

  getCardSize() {
    return 3;
  }
}

customElements.define('pv-smart-scheduler-card', PVSmartSchedulerCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'pv-smart-scheduler-card',
  name: 'PV Smart Scheduler Karte',
  description: 'Zeigt die priorisierte Startreihenfolge deiner Haushaltsgeräte basierend auf PV-Überschuss.',
  preview: false,
});
