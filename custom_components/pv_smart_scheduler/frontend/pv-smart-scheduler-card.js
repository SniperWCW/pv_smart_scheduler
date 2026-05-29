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
          <style>
            .timeline-container {
              margin-top: 16px;
              padding: 0 4px;
              position: relative;
              height: 40px;
              background: var(--secondary-background-color, #f0f0f0);
              border-radius: 4px;
              display: flex;
              align-items: center;
            }
            .timeline-axis {
              position: absolute;
              top: -18px;
              width: 100%;
              display: flex;
              justify-content: space-between;
              font-size: 10px;
              color: var(--secondary-text-color);
            }
            .device-bar {
              position: absolute;
              height: 20px;
              border-radius: 2px;
              opacity: 0.7;
              font-size: 8px;
              color: white;
              overflow: hidden;
              display: flex;
              align-items: center;
              justify-content: center;
              white-space: nowrap;
            }
          </style>
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
            <div id="timeline-area" style="margin-top: 25px;"></div>
          </div>
        </ha-card>
      `;
      this.content = this.querySelector('#scheduler-tbody');
      this.timelineArea = this.querySelector('#timeline-area');
    }

    let html = '';
    let timelineHtml = `
      <div class="timeline-container">
        <div class="timeline-axis"><span>08:00</span><span>12:00</span><span>16:00</span><span>20:00</span></div>
    `;

    if (devices.length === 0) {
      html = `<tr><td colspan="4" style="padding: 16px; text-align: center; color: var(--secondary-text-color);">Keine Geräte konfiguriert</td></tr>`;
      timelineHtml = '';
    } else {
      devices.forEach((device) => {
        const isReady = device.recommendation === 'ja';
        const currentPower = this.getFirstNumber(device, ['current_power'], 0);
        const isRunning = (device.is_running === true || device.recommendation === 'läuft' || currentPower > 15) && currentPower > 2;
        const startMins = this.getFirstNumber(device, ['best_start_mins'], 0);
        const durationMins = this.getFirstNumber(device, ['duration_mins'], 120);
        const startTimeStr = device.best_start_time;
        const startTimeObj = startTimeStr ? new Date(startTimeStr) : new Date();
        
        let timeLabel = '';
        if (startTimeStr) {
          timeLabel = startTimeObj.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        }

        const pvCoverage = this.getFirstNumber(device, ['pv_coverage'], 0);
        const estimatedKwh = this.getFirstNumber(device, ['estimated_kwh'], 0);

        let bestStartDisplay = timeLabel || 'Warten';
        const statusColor = isRunning ? 'var(--info-color, #2196f3)' : (isReady ? 'var(--success-color, #4caf50)' : 'var(--warning-color, #ff9800)');

        if (isRunning) {
          bestStartDisplay = currentPower > 5 ? `${this.formatNumber(currentPower, 0)} W` : 'Läuft';
        } else if (isReady && startMins === 0) {
          bestStartDisplay = 'Sofort';
        }

        const icon = this.getDeviceIcon(device.name || '');
        const name = this.escapeHtml(device.name || 'Gerät');
        const prio = device.priority !== undefined && device.priority !== null ? device.priority : '-';

        html += `
          <tr style="border-bottom: 1px solid var(--divider-color, rgba(0,0,0,0.1));">
            <td style="padding: 10px 4px; font-weight: bold; color: var(--secondary-text-color);">#${prio}</td>
            <td style="padding: 10px 4px; font-weight: 500;">
              <div style="display: flex; align-items: center; gap: 8px;">
                <ha-icon icon="${icon}" style="color: ${statusColor}; --mdc-icon-size: 18px;"></ha-icon>
                <span>${name}</span>
              </div>
            </td>
            <td style="padding: 10px 4px; text-align: center;">
              <span style="background: ${statusColor}22; color: ${statusColor}; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 12px; display: inline-block; min-width: 80px;">
                ${bestStartDisplay}
              </span>
            </td>
            <td style="padding: 10px 4px; text-align: right; font-weight: bold; color: ${statusColor};">
              ${this.formatNumber(pvCoverage, 1)}%
              <div style="font-size: 10px; font-weight: normal; color: var(--secondary-text-color);">${this.formatNumber(estimatedKwh, 2)} kWh</div>
            </td>
          </tr>
        `;

        // Timeline Logik (08:00 - 20:00 Uhr = 720 Minuten Bereich)
        if (!isRunning && startTimeObj) {
            const dayStart = new Date(startTimeObj);
            dayStart.setHours(8, 0, 0, 0);
            const dayEnd = new Date(startTimeObj);
            dayEnd.setHours(20, 0, 0, 0);

            const startOffset = (startTimeObj - dayStart) / (1000 * 60); // Minuten seit 08:00
            const timelineTotal = 720; // 12 Stunden

            if (startOffset >= 0 && startOffset < timelineTotal) {
                const left = (startOffset / timelineTotal) * 100;
                const width = (durationMins / timelineTotal) * 100;
                timelineHtml += `
                  <div class="device-bar" style="left: ${left}%; width: ${width}%; background: ${statusColor};" title="${name}">
                    ${width > 10 ? name : ''}
                  </div>
                `;
            }
        }
      });
      timelineHtml += '</div>';
    }

    this.content.innerHTML = html;
    this.timelineArea.innerHTML = timelineHtml;
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
