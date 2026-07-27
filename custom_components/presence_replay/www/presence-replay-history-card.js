// Presence Replay history card.
//
// Vanilla custom element, no build step: served directly by the
// integration (see frontend.py) and auto-loaded via add_extra_js_url, so
// there is nothing to add under Settings > Dashboards > Resources.
//
// Config:
//   type: custom:presence-replay-history-card
//   entity: sensor.upstairs_events_recorded   # any entity on the device, OR:
//   config_entry_id: 01JXXXXXXXXXXXXXXXXXXXXX  # the entry id directly
//   days: 3                                    # live-log window, default 3
//   title: Upstairs light history               # optional

(() => {
  const CARD_TAG = "presence-replay-history-card";
  const WS_HISTORY = "presence_replay/history";
  const WS_ENTITY_GET = "config/entity_registry/get";
  const REFRESH_MS = 60000;
  const DEFAULT_DAYS = 3;

  // Okabe-Ito qualitative palette -- colorblind-safe, cycles if more lights.
  const PALETTE = [
    "#E69F00",
    "#56B4E9",
    "#009E73",
    "#D55E00",
    "#0072B2",
    "#CC79A7",
    "#F0E442",
    "#000000",
  ];

  const VB_WIDTH = 760;
  const VB_HEIGHT = 220;
  const PAD = { top: 10, right: 12, bottom: 22, left: 34 };
  const PLOT_W = VB_WIDTH - PAD.left - PAD.right;
  const PLOT_H = VB_HEIGHT - PAD.top - PAD.bottom;

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatTick(ts) {
    return new Intl.DateTimeFormat(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(ts * 1000));
  }

  function formatFull(ts) {
    return new Intl.DateTimeFormat(undefined, {
      weekday: "short",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }).format(new Date(ts * 1000));
  }

  function stepPathD(points, xScale, yScale) {
    if (!points.length) return "";
    let d = `M ${xScale(points[0].ts).toFixed(1)} ${yScale(points[0].level).toFixed(1)}`;
    for (let i = 1; i < points.length; i++) {
      d += ` H ${xScale(points[i].ts).toFixed(1)} V ${yScale(points[i].level).toFixed(1)}`;
    }
    return d;
  }

  /** Per-entity {ts,level,replay?} series for the visible window, including
   * a baseline point at `start` (carried from the last event before it) and
   * an extension point at `end` so the line reaches both edges. */
  function buildSeries(rows, entityId, start, end) {
    const forEntity = rows
      .filter((row) => row[1] === entityId)
      .sort((a, b) => a[0] - b[0]);
    const before = forEntity.filter((row) => row[0] <= start);
    const inRange = forEntity.filter((row) => row[0] > start && row[0] <= end);
    if (!before.length && !inRange.length) return null;

    const points = [];
    if (before.length) {
      points.push({ ts: start, level: before[before.length - 1][2] });
    } else {
      points.push({ ts: start, level: inRange[0][2] });
    }
    for (const row of inRange) {
      points.push({ ts: row[0], level: row[2], replay: !!row[3] });
    }
    points.push({ ts: end, level: points[points.length - 1].level });
    return { points, markers: inRange };
  }

  class PresenceReplayHistoryCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._config = null;
      this._hass = null;
      this._configEntryId = null;
      this._resolving = false;
      this._data = null;
      this._error = null;
      this._mode = "live";
      this._refreshTimer = null;
      this._colorByEntity = new Map();
      this._hiddenEntities = new Set();
      this._onPointerMove = this._onPointerMove.bind(this);
      this._onPointerLeave = this._onPointerLeave.bind(this);
    }

    setConfig(config) {
      if (!config || (!config.entity && !config.config_entry_id)) {
        throw new Error(
          "presence-replay-history-card: set either 'entity' (any entity on the Presence Replay device) or 'config_entry_id'"
        );
      }
      this._config = {
        days: DEFAULT_DAYS,
        title: "Presence Replay History",
        ...config,
      };
      this._configEntryId = config.config_entry_id || null;
      this._data = null;
      this._error = null;
      this._colorByEntity = new Map();
      this._hiddenEntities = new Set();
      this._renderShell("Loading…");
      if (this._hass) this._resolveAndLoad();
    }

    static getStubConfig() {
      return { config_entry_id: "" };
    }

    getCardSize() {
      return 6;
    }

    set hass(hass) {
      const first = !this._hass;
      this._hass = hass;
      if (first && this._config) this._resolveAndLoad();
    }

    get hass() {
      return this._hass;
    }

    connectedCallback() {
      this._startPolling();
    }

    disconnectedCallback() {
      this._stopPolling();
    }

    async _resolveAndLoad() {
      if (!this._configEntryId) {
        if (this._resolving) return;
        this._resolving = true;
        try {
          const entry = await this._hass.callWS({
            type: WS_ENTITY_GET,
            entity_id: this._config.entity,
          });
          if (!entry || !entry.config_entry_id) {
            throw new Error(`${this._config.entity} is not attached to a config entry`);
          }
          this._configEntryId = entry.config_entry_id;
        } catch (err) {
          this._resolving = false;
          this._renderError(err.message || String(err));
          return;
        }
        this._resolving = false;
      }
      await this._fetchData();
      this._startPolling();
    }

    async _fetchData() {
      if (!this._hass || !this._configEntryId) return;
      try {
        this._data = await this._hass.callWS({
          type: WS_HISTORY,
          config_entry_id: this._configEntryId,
        });
        this._error = null;
        if (this._mode === "snapshot" && !this._data.snapshot) this._mode = "live";
        this._assignColors();
      } catch (err) {
        this._error = err.message || String(err);
      }
      this._render();
    }

    _assignColors() {
      if (!this._data) return;
      const ids = new Set();
      for (const row of this._data.events) ids.add(row[1]);
      if (this._data.snapshot) {
        for (const row of this._data.snapshot.events) ids.add(row[1]);
      }
      for (const id of Array.from(ids).sort()) {
        if (!this._colorByEntity.has(id)) {
          this._colorByEntity.set(id, PALETTE[this._colorByEntity.size % PALETTE.length]);
        }
      }
    }

    _startPolling() {
      if (this._refreshTimer || !this.isConnected) return;
      this._refreshTimer = window.setInterval(() => this._fetchData(), REFRESH_MS);
    }

    _stopPolling() {
      if (this._refreshTimer) {
        window.clearInterval(this._refreshTimer);
        this._refreshTimer = null;
      }
    }

    _friendlyName(entityId) {
      const state = this._hass?.states?.[entityId];
      return state?.attributes?.friendly_name || entityId;
    }

    _baseStyle() {
      return `
        <style>
          ha-card { padding: 0; }
          .content { padding: 0 16px 16px; }
          .toolbar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            padding: 4px 0 12px;
            flex-wrap: wrap;
          }
          .pills { display: flex; gap: 4px; }
          .pill {
            border: 1px solid var(--divider-color, #ccc);
            background: none;
            color: var(--primary-text-color);
            border-radius: 999px;
            padding: 4px 12px;
            font-size: 0.8rem;
            cursor: pointer;
          }
          .pill.active {
            background: var(--primary-color);
            border-color: var(--primary-color);
            color: var(--text-primary-color, #fff);
          }
          .range { font-size: 0.8rem; color: var(--secondary-text-color); }
          .chart-wrap { position: relative; }
          svg { width: 100%; height: auto; display: block; overflow: visible; }
          .gridline { stroke: var(--divider-color, #e0e0e0); stroke-width: 1; }
          .axis-label {
            fill: var(--secondary-text-color);
            font-size: 9px;
            font-family: var(--paper-font-common-base_-_font-family, inherit);
          }
          .series-path { fill: none; stroke-width: 2; }
          .marker.replay { opacity: 0.6; }
          .crosshair { stroke: var(--secondary-text-color); stroke-width: 1; stroke-dasharray: 3 3; pointer-events: none; }
          .tooltip {
            position: absolute;
            top: 4px;
            pointer-events: none;
            background: var(--card-background-color, #fff);
            border: 1px solid var(--divider-color, #ccc);
            border-radius: 6px;
            padding: 6px 8px;
            font-size: 0.75rem;
            color: var(--primary-text-color);
            box-shadow: var(--ha-card-box-shadow, 0 2px 4px rgba(0,0,0,0.2));
            white-space: nowrap;
            z-index: 2;
          }
          .tooltip .row { display: flex; align-items: center; gap: 6px; }
          .tooltip .swatch { width: 8px; height: 8px; border-radius: 50%; flex: none; }
          .legend { display: flex; flex-wrap: wrap; gap: 10px; padding-top: 10px; }
          .legend-item {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 0.75rem;
            color: var(--primary-text-color);
            cursor: pointer;
            user-select: none;
          }
          .legend-item.hidden { opacity: 0.4; }
          .legend-swatch { width: 10px; height: 10px; border-radius: 50%; flex: none; }
          .note { font-size: 0.7rem; color: var(--secondary-text-color); padding-top: 6px; }
          .empty, .error {
            padding: 24px 0;
            text-align: center;
            color: var(--secondary-text-color);
          }
          .error { color: var(--error-color, #db4437); }
        </style>
      `;
    }

    _renderShell(message) {
      this.shadowRoot.innerHTML = `
        ${this._baseStyle()}
        <ha-card header="${escapeHtml(this._config.title)}">
          <div class="content"><div class="empty">${escapeHtml(message)}</div></div>
        </ha-card>
      `;
    }

    _renderError(message) {
      this._error = message;
      this._render();
    }

    _render() {
      if (!this._config) return;
      if (this._error) {
        this._renderShell(this._error);
        this.shadowRoot.querySelector(".empty").classList.replace("empty", "error");
        return;
      }
      if (!this._data) {
        this._renderShell("Loading…");
        return;
      }

      const hasSnapshot = !!this._data.snapshot;
      let start;
      let end;
      let rows;
      if (this._mode === "snapshot" && hasSnapshot) {
        rows = this._data.snapshot.events;
        end = this._data.snapshot.created;
        start = end - this._data.snapshot.days * 86400;
      } else {
        rows = this._data.events;
        end = Date.now() / 1000;
        start = end - this._config.days * 86400;
      }

      const entityIds = Array.from(new Set(rows.map((row) => row[1]))).sort();
      const xScale = (ts) => PAD.left + ((ts - start) / (end - start || 1)) * PLOT_W;
      const yScale = (level) => PAD.top + (1 - level / 255) * PLOT_H;

      const series = [];
      for (const entityId of entityIds) {
        const built = buildSeries(rows, entityId, start, end);
        if (built) series.push({ entityId, ...built });
      }

      const rangeLabel =
        this._mode === "snapshot"
          ? `snapshot · ${this._data.snapshot.days}d captured ${formatTick(this._data.snapshot.created)}`
          : `last ${this._config.days}d`;

      let bodyHtml;
      if (!series.length) {
        bodyHtml = `<div class="empty">No events recorded in this range yet.</div>`;
      } else {
        bodyHtml = this._renderChart(series, start, end, xScale, yScale);
      }

      this.shadowRoot.innerHTML = `
        ${this._baseStyle()}
        <ha-card header="${escapeHtml(this._config.title)}">
          <div class="content">
            <div class="toolbar">
              ${
                hasSnapshot
                  ? `<div class="pills">
                       <button class="pill ${this._mode === "live" ? "active" : ""}" data-mode="live">Live log</button>
                       <button class="pill ${this._mode === "snapshot" ? "active" : ""}" data-mode="snapshot">Snapshot</button>
                     </div>`
                  : `<div></div>`
              }
              <div class="range">${escapeHtml(rangeLabel)}</div>
            </div>
            ${bodyHtml}
          </div>
        </ha-card>
      `;
      this._attachListeners(series, start, end, xScale, yScale);
    }

    _renderChart(series, start, end, xScale, yScale) {
      const gridFracs = [0, 0.25, 0.5, 0.75, 1];
      const gridlines = gridFracs
        .map((frac) => {
          const y = PAD.top + (1 - frac) * PLOT_H;
          return `
            <line class="gridline" x1="${PAD.left}" x2="${VB_WIDTH - PAD.right}" y1="${y}" y2="${y}" />
            <text class="axis-label" x="2" y="${y + 3}">${Math.round(frac * 100)}%</text>
          `;
        })
        .join("");

      const tickCount = 4;
      const timeTicks = Array.from({ length: tickCount + 1 }, (_, i) => start + ((end - start) * i) / tickCount)
        .map((ts) => {
          const x = xScale(ts);
          return `<text class="axis-label" x="${x}" y="${VB_HEIGHT - 6}" text-anchor="middle">${escapeHtml(formatTick(ts))}</text>`;
        })
        .join("");

      const paths = series
        .filter((s) => !this._hiddenEntities.has(s.entityId))
        .map((s) => {
          const color = this._colorByEntity.get(s.entityId) || "#888";
          const d = stepPathD(s.points, xScale, yScale);
          const markers = s.markers
            .map(
              (row) =>
                `<circle class="marker ${row[3] ? "replay" : ""}" cx="${xScale(row[0]).toFixed(1)}" cy="${yScale(row[2]).toFixed(1)}" r="3" fill="${color}" stroke="var(--card-background-color, #fff)" stroke-width="${row[3] ? 1.5 : 0}" />`
            )
            .join("");
          return `<path class="series-path" d="${d}" stroke="${color}" />${markers}`;
        })
        .join("");

      const anyReplay = series.some((s) => s.markers.some((row) => row[3]));

      return `
        <div class="chart-wrap">
          <svg viewBox="0 0 ${VB_WIDTH} ${VB_HEIGHT}" preserveAspectRatio="none">
            ${gridlines}
            ${timeTicks}
            ${paths}
            <g class="hover-layer"></g>
          </svg>
          <div class="tooltip" hidden></div>
        </div>
        <div class="legend">
          ${series
            .map((s) => {
              const color = this._colorByEntity.get(s.entityId) || "#888";
              const hidden = this._hiddenEntities.has(s.entityId);
              return `
                <div class="legend-item ${hidden ? "hidden" : ""}" data-entity="${escapeHtml(s.entityId)}">
                  <span class="legend-swatch" style="background:${color}"></span>
                  <span>${escapeHtml(this._friendlyName(s.entityId))}</span>
                </div>
              `;
            })
            .join("")}
        </div>
        ${anyReplay ? `<div class="note">Faint ring around a point = written while replay was running.</div>` : ""}
      `;
    }

    _attachListeners(series, start, end, xScale, yScale) {
      const root = this.shadowRoot;
      for (const button of root.querySelectorAll(".pill")) {
        button.addEventListener("click", () => {
          this._mode = button.dataset.mode;
          this._render();
        });
      }
      for (const item of root.querySelectorAll(".legend-item")) {
        item.addEventListener("click", () => {
          const entityId = item.dataset.entity;
          if (this._hiddenEntities.has(entityId)) this._hiddenEntities.delete(entityId);
          else this._hiddenEntities.add(entityId);
          this._render();
        });
      }
      const svg = root.querySelector("svg");
      if (!svg) return;
      this._chartCtx = { series, start, end, xScale, yScale, svg };
      svg.addEventListener("pointermove", this._onPointerMove);
      svg.addEventListener("pointerleave", this._onPointerLeave);
    }

    _onPointerLeave() {
      const tooltip = this.shadowRoot.querySelector(".tooltip");
      const hoverLayer = this.shadowRoot.querySelector(".hover-layer");
      if (tooltip) tooltip.hidden = true;
      if (hoverLayer) hoverLayer.innerHTML = "";
    }

    _onPointerMove(event) {
      const ctx = this._chartCtx;
      if (!ctx) return;
      const rect = ctx.svg.getBoundingClientRect();
      const scale = VB_WIDTH / rect.width;
      const vbX = (event.clientX - rect.left) * scale;
      if (vbX < PAD.left || vbX > VB_WIDTH - PAD.right) {
        this._onPointerLeave();
        return;
      }
      const ts = ctx.start + ((vbX - PAD.left) / PLOT_W) * (ctx.end - ctx.start);

      const rows = [];
      for (const s of ctx.series) {
        if (this._hiddenEntities.has(s.entityId)) continue;
        let level = null;
        for (const p of s.points) {
          if (p.ts <= ts) level = p.level;
          else break;
        }
        if (level !== null) {
          rows.push({ entityId: s.entityId, level, color: this._colorByEntity.get(s.entityId) });
        }
      }

      const hoverLayer = this.shadowRoot.querySelector(".hover-layer");
      if (hoverLayer) {
        hoverLayer.innerHTML = `<line class="crosshair" x1="${vbX.toFixed(1)}" x2="${vbX.toFixed(1)}" y1="${PAD.top}" y2="${VB_HEIGHT - PAD.bottom}" />`;
      }

      const tooltip = this.shadowRoot.querySelector(".tooltip");
      if (!tooltip) return;
      tooltip.hidden = false;
      const pct = (level) => Math.round((level / 255) * 100);
      tooltip.innerHTML = `
        <div><strong>${escapeHtml(formatFull(ts))}</strong></div>
        ${rows
          .map(
            (row) =>
              `<div class="row"><span class="swatch" style="background:${row.color}"></span>${escapeHtml(this._friendlyName(row.entityId))}: ${pct(row.level)}%</div>`
          )
          .join("")}
      `;
      const wrapRect = this.shadowRoot.querySelector(".chart-wrap").getBoundingClientRect();
      let left = (vbX / scale) + 8;
      const maxLeft = wrapRect.width - 160;
      if (left > maxLeft) left = Math.max(0, (vbX / scale) - 168);
      tooltip.style.left = `${left}px`;
    }
  }

  if (!customElements.get(CARD_TAG)) {
    customElements.define(CARD_TAG, PresenceReplayHistoryCard);
  }

  window.customCards = window.customCards || [];
  window.customCards.push({
    type: CARD_TAG,
    name: "Presence Replay History",
    description: "Graphs the recorded light-level log from a Presence Replay entry.",
  });
})();
