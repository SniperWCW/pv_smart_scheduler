class PVSmartSchedulerCard extends HTMLElement {
  set hass(hass) {
    const entityId = this.config.entity || 'sensor.pv_smart_scheduler_zentrale';
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
              <tbody id="scheduler-tbody">
              </tbody>
            </table>
          </div>
        </ha-card>
      `;
      this.content = this.querySelector('#scheduler-tbody');
    }

    // Tabelle neu aufbauen bei Datenänderung
    let html = '';
    if (devices.length === 0) {
      html = `<tr><td colspan="4" style="padding: 16px; text-align: center; color: var(--secondary-text-color);">Keine Geräte konfiguriert</td></tr>`;
    } else {
      devices.forEach(device => {
        // Mapping der neuen Attribut-Namen
        const isReady = device.recommendation === 'ja';
        const startMins =
          device.best_start_mins ?? 0;

        const bestStartDisplay =
          startMins === 0
            ? 'Sofort'
            : `In ${startMins} Min`;

        const pvCoverage =
          Number(device.pv_coverage ?? 0).toFixed(1);

        const pvCoverageDisplay =
          `${pvCoverage}%`;

        const prio =
          device.priority ?? '-';

        const estimatedKwh =
          Number(device.estimated_kwh ?? 0).toFixed(2);
        const statusColor = isReady ? '#4caf50' : '#ff9800';
        const icon = this.getDeviceIcon(device.name || '');

        html += `
          <tr style="border-bottom: 1px solid var(--divider-color, rgba(0,0,0,0.1));">
            <td style="padding: 10px 4px; font-weight: bold; color: var(--secondary-text-color);">#${prio}</td>
            <td style="padding: 10px 4px; font-weight: 500;">
              <div style="display: flex; align-items: center; gap: 8px;">
                <ha-icon icon="${icon}" style="color: ${isReady ? 'var(--success-color, #4caf50)' : 'var(--primary-text-color)'}; --mdc-icon-size: 18px;"></ha-icon>
                <span>${device.name || 'Gerät'}</span>
              </div>
            </td>
            <td style="padding: 10px 4px; text-align: center;">
              <span style="background: ${statusColor}22; color: ${statusColor}; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 12px; display: inline-block; min-width: 80px;">
                ${bestStartDisplay}
              </span>
            </td>
            <td style="padding: 10px 4px; text-align: right; font-weight: bold; color: ${isReady ? 'var(--success-color, #4caf50)' : 'var(--primary-text-color)'};">
              ${pvCoverageDisplay}
              <div style="font-size: 10px; font-weight: normal; color: var(--secondary-text-color);">${estimatedKwh} kWh</div>
            </td>
          </tr>
        `;
      });
    }

    this.content.innerHTML = html;
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
  type: "pv-smart-scheduler-card",
  name: "PV Smart Scheduler Karte",
  description: "Zeigt die priorisierte Startreihenfolge deiner Haushaltsgeräte basierend auf PV-Überschuss.",
  preview: false
});
