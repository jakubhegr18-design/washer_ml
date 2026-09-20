"""Constants for the Washer ML integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "washer_ml"
DOMAIN_TITLE = "Washer ML"

PLATFORMS = [Platform.SENSOR, Platform.BUTTON, Platform.SWITCH]

# Configuration keys
CONF_POWER_SENSOR = "power_sensor"
CONF_NAME = "name"
CONF_MODEL_TYPE = "model_type"
CONF_CONFIDENCE_THRESHOLD = "confidence_threshold"
CONF_RETRAIN_INTERVAL = "retrain_interval_cycles"
CONF_MAX_STORED_CYCLES = "max_stored_cycles"
CONF_IDLE_THRESHOLD = "idle_threshold_w"
CONF_SPIN_THRESHOLD = "spin_threshold_w"
CONF_ENTITY_SLUG = "entity_slug"

# Defaults
DEFAULT_NAME = "Pračka"
DEFAULT_MODEL_TYPE = "simple_threshold"
DEFAULT_CONFIDENCE_THRESHOLD = 70.0
DEFAULT_RETRAIN_INTERVAL = 5
DEFAULT_MAX_STORED_CYCLES = 100
DEFAULT_IDLE_THRESHOLD = 20.0
DEFAULT_SPIN_THRESHOLD = 800.0

# Model types
MODEL_SIMPLE_THRESHOLD = "simple_threshold"
MODEL_DECISION_TREE = "decision_tree"
MODEL_TFLITE = "tflite"

# Active model layer names (test mode / diagnostics)
MODEL_LAYER_HEURISTIC = "heuristic"
MODEL_LAYER_LEARNED = "learned"

# Washing cycle states (Czech, as shown to the user)
STATE_RUNNING = "Spuštěno"
STATE_HEATING = "Ohřívání"
STATE_WASHING = "Prání"
STATE_RINSING = "Máchání"
STATE_SPINNING = "Odstřeďování"
STATE_FINISHED = "Skončilo"
STATE_OFF = "Vypnuto"
STATE_UNKNOWN = "Nejisté"

WASHER_STATES = (
    STATE_RUNNING,
    STATE_HEATING,
    STATE_WASHING,
    STATE_RINSING,
    STATE_SPINNING,
    STATE_FINISHED,
    STATE_OFF,
    STATE_UNKNOWN,
)

PHASE_SLUGS = {
    STATE_RUNNING: "spusteno",
    STATE_HEATING: "ohrivani",
    STATE_WASHING: "prani",
    STATE_RINSING: "machani",
    STATE_SPINNING: "odstredovani",
    STATE_FINISHED: "skonceno",
}

PHASE_ICONS = {
    STATE_RUNNING: "mdi:play-circle-outline",
    STATE_HEATING: "mdi:water-boiler",
    STATE_WASHING: "mdi:water",
    STATE_RINSING: "mdi:water-outline",
    STATE_SPINNING: "mdi:rotate-right",
    STATE_FINISHED: "mdi:check-circle-outline",
    STATE_OFF: "mdi:power-plug-off",
    STATE_UNKNOWN: "mdi:help-circle-outline",
}

# Sensor attributes
ATTR_CONFIDENCE = "confidence"
ATTR_CURRENT_POWER = "current_power"
ATTR_ELAPSED_MINUTES = "elapsed_minutes"
ATTR_ESTIMATED_REMAINING = "estimated_remaining_minutes"
ATTR_DETECTED_PROGRAM = "detected_program"
ATTR_CYCLE_COUNT_LEARNED = "cycle_count_learned"
ATTR_CYCLE_ID = "cycle_id"
ATTR_RAW_PREDICTION_SCORES = "raw_prediction_scores"
ATTR_ACTIVE_MODEL_LAYER = "active_model_layer"
ATTR_SAMPLES_IN_CURRENT_CYCLE = "samples_in_current_cycle"

# Services
SERVICE_IMPORT_HISTORY = "import_history"
SERVICE_RETRAIN = "retrain"
SERVICE_RESET_CALIBRATION = "reset_calibration"

# Detection timing
ACTIVATION_SAMPLES = 3
FINISHED_IDLE_SECONDS = 120
OFF_AFTER_FINISHED_SECONDS = 600
DB_FLUSH_INTERVAL_SECONDS = 45

# hass.data keys
DATA_COORDINATOR = "coordinator"
DATA_DATASTORE = "data_store"
PANEL_STATIC_KEY = "static_registered"
PANEL_LINK_KEY = "panel_url"
PANEL_REGISTERED_KEY = "panel_registered"