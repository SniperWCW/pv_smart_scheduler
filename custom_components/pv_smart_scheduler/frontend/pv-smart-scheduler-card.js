const CARD_VERSION = '0.2.6';

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
          <div id="card-header-info" style="padding: 12px 16px 0 16px; font-size: 12px; display: flex; justify-content: space-between; align-items: center;">
            <div id="battery-status"></div>
            <div style="display: flex; align-items: center; gap: 10px;">
              <div id="forecast-status"></div>
              <div id="card-version" style="color: var(--secondary-text-color); opacity: 0.8;"></div>
            </div>
          </div>
          <style>
            .timeline-wrapper {
              margin-top: 16px;
              padding: 20px 4px 4px 4px;
              position: relative;
              border-top: 1px solid var(--divider-color);
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
            .timeline-lane {
              position: relative;
              height: 24px;
              background: var(--secondary-background-color, rgba(0,0,0,0.05));
              margin-bottom: 6px;
              border-radius: 3px;
              width: 100%;
            }
            .device-bar {
              position: absolute;
              height: 100%;
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
      this.headerBattery = this.querySelector('#battery-status');
      this.headerForecast = this.querySelector('#forecast-status');
      this.headerVersion = this.querySelector('#card-version');
    }

    let html = '';
    let timelineRowsHtml = '';
    const timelineStartTime = (this.config && this.config.timeline_start) || stateObj.attributes.schedule_start_time || '05:00';
    const timelineEndTime = (this.config && this.config.timeline_end) || stateObj.attributes.schedule_end_time || '23:00';
    const timelineStartMins = this.parseTimeToMinutes(timelineStartTime, '05:00');
    let timelineEndMins = this.parseTimeToMinutes(timelineEndTime, '23:00');
    if (timelineEndMins <= timelineStartMins) {
      timelineEndMins += 1440;
    }
    const timelineTotal = timelineEndMins - timelineStartMins;
    const timelineAxis = this.buildTimelineAxis(timelineStartMins, timelineEndMins);

    // Header Infos aktualisieren
    const batSoc = stateObj.attributes.battery_soc;
    const batWarn = stateObj.attributes.battery_night_warning;
    if (batSoc !== undefined) {
      this.headerBattery.innerHTML = `
        <div style="display: flex; align-items: center; gap: 4px; color: ${batWarn ? 'var(--error-color, #f44336)' : 'var(--secondary-text-color)'};">
          <ha-icon icon="${batWarn ? 'mdi:battery-alert' : 'mdi:battery-check'}" style="--mdc-icon-size: 16px;"></ha-icon>
          <span>Akku: ${batSoc}% ${batWarn ? '(Knapp für Nacht)' : ''}</span>
        </div>
      `;
    }
    const avgPower = stateObj.attributes.forecast_average_power;
    this.headerForecast.innerHTML = avgPower ? `<span style="color: var(--secondary-text-color);">Ø Prognose: ${avgPower} W</span>` : '';
    this.headerVersion.textContent = `Card ${CARD_VERSION}`;

    if (devices.length === 0) {
      html = `<tr><td colspan="4" style="padding: 16px; text-align: center; color: var(--secondary-text-color);">Keine Geräte konfiguriert</td></tr>`;
      timelineRowsHtml = '';
    } else {
      devices.forEach((device) => {
        const isReady = device.recommendation === 'ja';
        const currentPower = this.getFirstNumber(device, ['current_power'], 0);
        const isRunning = device.is_running !== undefined
          ? device.is_running === true
          : ((device.recommendation === 'läuft' || currentPower > 15) && currentPower > 2);
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
          bestStartDisplay = 'Läuft';
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
                ${bestStartDisplay} ${!isRunning && pvCoverage < (device.target_coverage || 80) ? '⚠️' : ''}
              </span>
            </td>
            <td style="padding: 10px 4px; text-align: right; font-weight: bold; color: ${statusColor};">
              ${this.formatNumber(pvCoverage, 1)}%
              <div style="font-size: 10px; font-weight: normal; color: var(--secondary-text-color);">${this.formatNumber(estimatedKwh, 2)} kWh</div>
            </td>
          </tr>
        `;

        if (!isRunning && startTimeStr && !Number.isNaN(startTimeObj.getTime())) {
          const startOffset = this.dateToTimelineMinutes(
            startTimeObj,
            timelineStartMins,
            timelineEndMins
          ) - timelineStartMins;

          if (startOffset >= 0 && startOffset < timelineTotal) {
            const visibleDurationMins = Math.max(1, Math.min(durationMins, timelineTotal - startOffset));
            const left = (startOffset / timelineTotal) * 100;
            const width = (visibleDurationMins / timelineTotal) * 100;

            timelineRowsHtml += `
              <div style="display: flex; align-items: center; margin-bottom: 4px;">
                <div style="width: 70px; font-size: 9px; color: var(--secondary-text-color); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding-right: 4px;">
                  ${name}
                </div>
                <div class="timeline-lane">
                  <div class="device-bar" style="left: ${left}%; width: ${width}%; background: ${statusColor};" title="${name}: ${timeLabel}">
                    ${width > 15 ? name : ''}
                  </div>
                </div>
              </div>
            `;
          }
        }
      });
    }

    this.content.innerHTML = html;
    this.timelineArea.innerHTML = timelineRowsHtml ? `<div class="timeline-wrapper">${timelineAxis}${timelineRowsHtml}</div>` : '';
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

  parseTimeToMinutes(value, fallback) {
    const source = String(value || fallback);
    const match = source.match(/^(\d{1,2}):(\d{2})/);
    if (!match) {
      return this.parseTimeToMinutes(fallback, '05:00');
    }

    const hours = Math.max(0, Math.min(23, Number(match[1])));
    const minutes = Math.max(0, Math.min(59, Number(match[2])));
    return (hours * 60) + minutes;
  }

  formatTimeLabel(totalMinutes) {
    const minutesOfDay = ((totalMinutes % 1440) + 1440) % 1440;
    const hours = Math.floor(minutesOfDay / 60);
    const minutes = minutesOfDay % 60;
    return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;
  }

  buildTimelineAxis(startMins, endMins) {
    const total = endMins - startMins;
    const step = total <= 480 ? 120 : (total <= 720 ? 180 : 240);
    const ticks = [startMins];
    let nextTick = Math.ceil(startMins / step) * step;

    while (nextTick < endMins) {
      if (nextTick !== startMins) {
        ticks.push(nextTick);
      }
      nextTick += step;
    }

    if (ticks[ticks.length - 1] !== endMins) {
      ticks.push(endMins);
    }

    return `<div class="timeline-axis">${ticks.map((tick) => `<span>${this.formatTimeLabel(tick)}</span>`).join('')}</div>`;
  }

  dateToTimelineMinutes(date, startMins, endMins) {
    let minutes = (date.getHours() * 60) + date.getMinutes();
    while (minutes < startMins) {
      minutes += 1440;
    }
    while (minutes > endMins && minutes - 1440 >= startMins) {
      minutes -= 1440;
    }
    return minutes;
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
