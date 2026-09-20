/*
 * Washer ML - sidebar panel.
 *
 * Vanilla JS ES module with NO external imports so the page renders fully
 * offline (no internet dependency at runtime). Home Assistant pushes the live
 * `hass` object into the element on every state change, so the panel updates
 * on its own without polling.
 */
(function () {
  "use strict";

  var PHASES = [
    "Spuštěno",
    "Ohřívání",
    "Prání",
    "Máchání",
    "Odstřeďování",
    "Skončilo",
    "Vypnuto",
    "Nejisté",
  ];

  function esc(value) {
    var s = String(value == null ? "" : value);
    return s.replace(/[&<>"']/g, function (c) {
      return {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      }[c];
    });
  }

  function fmt(value, unit) {
    if (value === null || value === undefined || value === "") {
      return "—";
    }
    return String(value) + (unit || "");
  }

  var STYLES = [
    ":host { display: block; }",
    ".card { background: var(--card-background-color); color: var(--primary-text-color); border-radius: 12px; padding: 20px; margin: 16px auto; max-width: 720px; box-shadow: var(--shadow-elevation-2, 0 2px 4px rgba(0,0,0,.2)); box-sizing: border-box; }",
    "h2 { margin: 0 0 14px; font-size: 1.4rem; display: flex; align-items: center; gap: 10px; }",
    ".row { display: flex; justify-content: space-between; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--divider-color, rgba(0,0,0,.08)); }",
    ".row:last-child { border-bottom: none; }",
    ".label { color: var(--secondary-text-color); }",
    ".value { font-weight: 600; text-align: right; }",
    ".chip { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: .85em; background: var(--primary-color, #2980b9); color: var(--text-primary-color, #fff); margin-left: 6px; }",
    ".chip-idle { background: var(--disabled-text-color, #888); }",
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

  var TEMPLATE = function (hass, panel) {
    var cfg = panel && panel.config;
    if (!cfg) {
      return (
        '<div class="card"><h2>&#129531; ' + esc("Pračka") + "</h2>" +
        '<p class="muted">Načítám...</p></div>'
      );
    }
    var stateEntity = hass && hass.states[cfg.state_entity];
    var confEntity = hass && hass.states[cfg.confidence_entity];
    var testEntity = hass && hass.states[cfg.test_mode_entity];

    var attrs = stateEntity ? stateEntity.attributes || {} : {};
    var phase = stateEntity ? stateEntity.state : null;
    if (phase === "unavailable" || phase === "unknown") phase = null;

    var confidence = confEntity ? confEntity.state : null;
    var layer = attrs.active_model_layer || "heuristic";
    var layerLabel = layer === "learned" ? "naučený model" : "heuristika";
    var testOn = testEntity ? testEntity.state === "on" : false;

    var learned = attrs.cycle_count_learned;
    var interval = cfg.retrain_interval || 10;
    var learnedLabel =
      learned === null || learned === undefined ? "—" : learned + "/" + interval;

    var scoresRows = "";
    if (testOn && attrs.raw_prediction_scores) {
      var scores = attrs.raw_prediction_scores;
      PHASES.forEach(function (p) {
        var prob = scores[p] != null ? Math.round(scores[p] * 100) : 0;
        scoresRows +=
          "<tr><td>" + esc(p) + '</td><td class="value" style="width:300px">' +
          '<div class="bar" style="width:' + prob + '%"></div></td>' +
          "<td>" + prob + "%</td></tr>";
      });
    }

    var calibration = "";
    var buttons = cfg.buttons || {};
    var calibDefs = [
      ["running", "Spuštěno"],
      ["heating", "Ohřívání"],
      ["washing", "Prání"],
      ["rinsing", "Máchání"],
      ["spinning", "Odstřeďování"],
      ["finished", "Skončilo"],
    ];
    calibDefs.forEach(function (def) {
      calibration +=
        '<button class="btn calib" data-entity="' +
        esc(buttons[def[0]] || "") +
        '">' +
        esc(def[1]) +
        "</button>";
    });

    var settingsUrl =
      "/config/integrations/integration/" + encodeURIComponent(cfg.entry_id);

    return (
      '<div class="card">' +
      "<h2>&#129531; " + esc(cfg.name || "Pračka") + "</h2>" +

      '<div class="row"><span class="label">Stav</span><span class="value">' +
      esc(phase || "—") + "</span></div>" +
      '<div class="row"><span class="label">Jistota</span><span class="value">' +
      esc(fmt(confidence, " %")) + '<span class="chip">' + esc(layerLabel) +
      "</span></span></div>" +
      '<div class="row"><span class="label">Aktuální výkon</span><span class="value">' +
      esc(fmt(attrs.current_power, " W")) + "</span></div>" +
      '<div class="row"><span class="label">Uplynulo</span><span class="value">' +
      esc(fmt(attrs.elapsed_minutes, " min")) + "</span></div>" +
      '<div class="row"><span class="label">Zbývá</span><span class="value">' +
      esc(fmt(attrs.estimated_remaining_minutes, " min")) + "</span></div>" +
      '<div class="row"><span class="label">Program</span><span class="value">' +
      esc(attrs.detected_program || "neznámý") + "</span></div>" +
      '<div class="row"><span class="label">Naučeno cyklů</span><span class="value">' +
      esc(learnedLabel) + "</span></div>" +

      '<div class="section">' +
      '<button class="btn" data-action="toggle-test">Test mode: ' +
      (testOn ? "ZAPNUTO (vypnout)" : "VYPNUTO (zapnout)") + "</button>" +
      (testOn && scoresRows ? '<table class="scores">' + scoresRows + "</table>" : "") +
      "</div>" +

      '<div class="section"><div class="label">Kalibrace (trénink)</div>' +
      '<div class="calib-grid">' + calibration + "</div></div>" +

      '<div class="section">' +
      '<button class="btn btn-primary" data-action="retrain">Retrénovat nyní</button>' +
      '<a class="link" href="' + settingsUrl + '">&#9881; Upravit nastavení</a>' +
      "</div>" +

      "</div>"
    );
  };

  customElements.define(
    "washer-panel",
    (function (HTMLElement) {
      function WasherPanel() {
        HTMLElement.call(this);
        this._connected = false;
        this._hass = null;
        this._panel = null;
        this.attachShadow({ mode: "open" });
      }
      WasherPanel.prototype = Object.create(HTMLElement.prototype);
      WasherPanel.prototype.constructor = WasherPanel;

      Object.defineProperty(WasherPanel.prototype, "hass", {
        get: function () {
          return this._hass;
        },
        set: function (value) {
          this._hass = value;
          if (this._connected) this._render();
        },
      });
      Object.defineProperty(WasherPanel.prototype, "panel", {
        get: function () {
          return this._panel;
        },
        set: function (value) {
          this._panel = value;
          if (this._connected) this._render();
        },
      });
      Object.defineProperty(WasherPanel.prototype, "narrow", {
        get: function () {
          return this._narrow;
        },
        set: function (value) {
          this._narrow = value;
        },
      });

      WasherPanel.prototype.connectedCallback = function () {
        this._connected = true;
        this._render();
      };
      WasherPanel.prototype.disconnectedCallback = function () {
        this._connected = false;
      };

      WasherPanel.prototype._render = function () {
        var root = this.shadowRoot;
        var html = "<style>" + STYLES + "</style>" +
          TEMPLATE(this._hass, this._panel);
        root.innerHTML = html;
        this._bind(root);
      };

      WasherPanel.prototype._bind = function (root) {
        var self = this;
        var hass = this._hass;
        var cfg = this._panel && this._panel.config;
        if (!hass || !cfg) return;
        Array.prototype.forEach.call(root.querySelectorAll("[data-entity]"), function (el) {
          el.addEventListener("click", function () {
            var entityId = el.getAttribute("data-entity");
            if (entityId) {
              void hass.callService("button", "press", { entity_id: entityId });
            }
          });
        });
        Array.prototype.forEach.call(root.querySelectorAll("[data-action]"), function (el) {
          el.addEventListener("click", function () {
            var action = el.getAttribute("data-action");
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
        });
      };

      return WasherPanel;
    })(HTMLElement)
  );
})();