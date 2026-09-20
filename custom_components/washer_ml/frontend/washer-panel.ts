/**
 * Washer ML - sidebar panel (TypeScript source).
 *
 * Compiled output: washer-panel.js
 *
 * NOTE: this panel intentionally uses vanilla Web Components with NO external
 * imports so it renders fully offline (no dependency on a CDN / internet).
 * The shipped washer-panel.js is the compiled/bundled version of this file.
 *
 * Compile with:
 *   tsc washer-panel.ts --target ES2020 --module ES2020 --lib DOM,ES2020 --outFile washer-panel.js
 */

/// <reference lib="dom" />
/// <reference lib="es2020" />

interface HassState {
  entity_id: string;
  state: string;
  attributes: Record<string, unknown>;
}

interface Hass {
  states: Record<string, HassState>;
  callService(domain: string, service: string, data?: Record<string, unknown>): Promise<unknown>;
}

interface WasherPanelConfig {
  name: string;
  entry_id: string;
  state_entity: string;
  confidence_entity: string;
  test_mode_entity: string;
  retrain_interval: number;
  buttons: Record<string, string>;
}

interface WasherPanelPanel {
  config: WasherPanelConfig;
}

const PHASES = [
  "Spuštěno",
  "Ohřívání",
  "Prání",
  "Máchání",
  "Odstřeďování",
  "Skončilo",
  "Vypnuto",
  "Nejisté",
];

function esc(value: unknown): string {
  const str = String(value == null ? "" : value);
  return str.replace(/[&<>"']/g, (c) =>
    ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[c])
  );
}

function fmt(value: unknown, unit: string): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  return String(value) + unit;
}

const STYLES = [
  ":host { display: block; }",
  ".card { background: var(--card-background-color); color: var(--primary-text-color); border-radius: 12px; padding: 20px; margin: 16px auto; max-width: 720px; box-shadow: var(--shadow-elevation-2, 0 2px 4px rgba(0,0,0,.2)); box-sizing: border-box; }",
  "h2 { margin: 0 0 14px; font-size: 1.4rem; display: flex; align-items: center; gap: 10px; }",
  ".row { display: flex; justify-content: space-between; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--divider-color, rgba(0,0,0,.08)); }",
  ".row:last-child { border-bottom: none; }",
  ".label { color: var(--secondary-text-color); }",
  ".value { font-weight: 600; text-align: right; }",
  ".chip { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: .85em; background: var(--primary-color, #2980b9); color: var(--text-primary-color, #fff); margin-left: 6px; }",
  ".section { margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--divider-color, rgba(0,0,0,.08)); }",
  ".btn { width: 100%; padding: 10px; margin: 4px 0; border-radius: 8px; border: 1px solid var(--divider-color, rgba(0,0,0,.15)); background: var(--card-background-color); color: var(--primary-text-color); font-size: 1rem; cursor: pointer; }",
  ".btn:hover { border-color: var(--primary-color); }",
  ".btn-primary { background: var(--primary-color, #2980b9); color: var(--text-primary-color, #fff); border-color: transparent; }",
  ".calib-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 8px; }",
  ".calib-grid .btn { margin: 0; }",
  ".scores { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: .9rem; }",
  ".scores td { padding: 3px 6px; }",
  ".scores .bar { background: var(--primary-color, #2980b9); height: 8px; border-radius: 4px; min-width: 2px; }",
  ".muted { color: var(--secondary-text-color); font-size: .85rem; }",
  ".link { display: inline-block; margin-top: 10px; color: var(--primary-color); }",
].join("\n");

function template(hass: Hass | null, panel: WasherPanelPanel | null): string {
  const cfg = panel && panel.config;
  if (!cfg) {
    return '<div class="card"><h2>&#129531; Pračka</h2><p class="muted">Načítám...</p></div>';
  }

  const stateEntity = hass && hass.states[cfg.state_entity];
  const confEntity = hass && hass.states[cfg.confidence_entity];
  const testEntity = hass && hass.states[cfg.test_mode_entity];

  const attrs = (stateEntity && stateEntity.attributes) || {};
  let phase: string | null = stateEntity ? stateEntity.state : null;
  if (phase === "unavailable" || phase === "unknown") phase = null;

  const confidence = confEntity ? confEntity.state : null;
  const layer = String(attrs.active_model_layer || "heuristic");
  const layerLabel = layer === "learned" ? "naučený model" : "heuristika";
  const testOn = testEntity ? testEntity.state === "on" : false;

  const learned = attrs.cycle_count_learned;
  const interval = cfg.retrain_interval || 10;
  const learnedLabel =
    learned === null || learned === undefined ? "—" : `${learned}/${interval}`;

  let scoresRows = "";
  if (testOn && attrs.raw_prediction_scores) {
    const scores = attrs.raw_prediction_scores as Record<string, number>;
    for (const p of PHASES) {
      const prob = scores[p] != null ? Math.round(scores[p] * 100) : 0;
      scoresRows +=
        `<tr><td>${esc(p)}</td>` +
        `<td class="value" style="width:300px"><div class="bar" style="width:${prob}%"></div></td>` +
        `<td>${prob}%</td></tr>`;
    }
  }

  const buttons = cfg.buttons || {};
  const calibDefs: Array<[string, string]> = [
    ["running", "Spuštěno"],
    ["heating", "Ohřívání"],
    ["washing", "Prání"],
    ["rinsing", "Máchání"],
    ["finished", "Skončilo"],
  ];
  let calibration = "";
  for (const def of calibDefs) {
    calibration +=
      `<button class="btn calib" data-entity="${esc(buttons[def[0]] || "")}">${esc(def[1])}</button>`;
  }

  const settingsUrl =
    "/config/integrations/integration/" + encodeURIComponent(cfg.entry_id);

  return (
    '<div class="card">' +
    `<h2>&#129531; ${esc(cfg.name || "Pračka")}</h2>` +
    `<div class="row"><span class="label">Stav</span><span class="value">${esc(phase || "—")}</span></div>` +
    `<div class="row"><span class="label">Jistota</span><span class="value">${esc(fmt(confidence, " %"))}<span class="chip">${esc(layerLabel)}</span></span></div>` +
    `<div class="row"><span class="label">Aktuální výkon</span><span class="value">${esc(fmt(attrs.current_power, " W"))}</span></div>` +
    `<div class="row"><span class="label">Uplynulo</span><span class="value">${esc(fmt(attrs.elapsed_minutes, " min"))}</span></div>` +
    `<div class="row"><span class="label">Zbývá</span><span class="value">${esc(fmt(attrs.estimated_remaining_minutes, " min"))}</span></div>` +
    `<div class="row"><span class="label">Program</span><span class="value">${esc(attrs.detected_program || "neznámý")}</span></div>` +
    `<div class="row"><span class="label">Naučeno cyklů</span><span class="value">${esc(learnedLabel)}</span></div>` +
    '<div class="section">' +
    `<button class="btn" data-action="toggle-test">Test mode: ${testOn ? "ZAPNUTO (vypnout)" : "VYPNUTO (zapnout)"}</button>` +
    (testOn && scoresRows ? `<table class="scores">${scoresRows}</table>` : "") +
    "</div>" +
    '<div class="section"><div class="label">Kalibrace (trénink)</div>' +
    `<div class="calib-grid">${calibration}</div></div>` +
    '<div class="section">' +
    '<button class="btn btn-primary" data-action="retrain">Retrénovat nyní</button>' +
    `<a class="link" href="${settingsUrl}">&#9881; Upravit nastavení</a>` +
    "</div>" +
    "</div>"
  );
}

class WasherPanelElement extends HTMLElement {
  private _connected = false;
  private _hass: Hass | null = null;
  private _panel: WasherPanelPanel | null = null;
  private _narrow = false;

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  public set hass(value: Hass) {
    this._hass = value;
    if (this._connected) this._render();
  }

  public get hass(): Hass | null {
    return this._hass;
  }

  public set panel(value: WasherPanelPanel) {
    this._panel = value;
    if (this._connected) this._render();
  }

  public get panel(): WasherPanelPanel | null {
    return this._panel;
  }

  public set narrow(value: boolean) {
    this._narrow = value;
  }

  public get narrow(): boolean {
    return this._narrow;
  }

  private connectedCallback(): void {
    this._connected = true;
    this._render();
  }

  private disconnectedCallback(): void {
    this._connected = false;
  }

  private _render(): void {
    const root = this.shadowRoot;
    if (!root) return;
    root.innerHTML = `<style>${STYLES}</style>${template(this._hass, this._panel)}`;
    this._bind(root);
  }

  private _bind(root: ShadowRoot): void {
    const hass = this._hass;
    const cfg = this._panel && this._panel.config;
    if (!hass || !cfg) return;
    for (const el of Array.from(root.querySelectorAll<HTMLElement>("[data-entity]"))) {
      el.addEventListener("click", () => {
        const entityId = el.getAttribute("data-entity");
        if (entityId) {
          void hass.callService("button", "press", { entity_id: entityId });
        }
      });
    }
    for (const el of Array.from(root.querySelectorAll<HTMLElement>("[data-action]"))) {
      el.addEventListener("click", () => {
        const action = el.getAttribute("data-action");
        if (action === "toggle-test") {
          void hass.callService("switch", "toggle", {
            entity_id: cfg.test_mode_entity,
          });
        } else if (action === "retrain") {
          void hass.callService("washer_ml", "retrain", {
            entry_id: cfg.entry_id,
          });
        }
      });
    }
  }
}

customElements.define("washer-panel", WasherPanelElement);