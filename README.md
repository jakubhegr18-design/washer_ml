# Washer ML

Home Assistant custom integration (HACS compatible) that detects washing
machine cycle phases from a smart plug power sensor — **fully locally**, no
cloud APIs, no internet needed for detection.

Works on a Raspberry Pi 4B next to Home Assistant Core without heavy ML
frameworks (pure-Python decision tree + threshold heuristics).

## Features

- `sensor.<name>_stav` — current phase: `Spuštěno`, `Ohřívání`, `Prání`,
  `Máchání`, `Odstřeďování`, `Skončilo`, `Vypnuto`, `Nejisté`
  - attributes: `confidence`, `current_power`, `elapsed_minutes`,
    `estimated_remaining_minutes`, `detected_program`, `cycle_count_learned`
- `sensor.<name>_confidence` — model confidence 0-100 %
- Calibration buttons to label cycles for training
- `switch.<name>_test_mode` — debug output, raw prediction scores + active model layer
- Sidebar panel at `/washer-ml` with live status, calibration and retrain buttons
- Services: `import_history`, `retrain`, `reset_calibration`
- SQLite storage (`config/washer_ml/<entry_id>/history.db`), model saved as JSON
- Two-layer detection: heuristic (works immediately) → decision tree trained
  from labelled cycles (auto-retrain every `retrain_interval_cycles`)

## Installation (HACS)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jakubhegr18-design&repository=washer_ml&category=integration)

1. Click the button above (or add the repository manually: HACS → ⋯ → Custom repositories → `https://github.com/jakubhegr18-design/washer_ml` with category **Integration**).
2. Download → restart Home Assistant.
3. Settings → Devices & Services → Add Integration → **Washer ML** → select the
   power sensor of your smart plug (e.g. `sensor.professor_89712_5_vykon`).

## Manual calibration

Use the calibration buttons (`Spuštěno`, `Ohřívání`, ...) during a real wash
cycle to label it. Press **Skončilo** when the machine finishes — the cycle is
stored and used for retraining. After at least `retrain_interval_cycles` (5)
labelled cycles the decision tree trains itself automatically.

## Importing historical data

`washer_ml.import_history` with `csv_path` or `csv_content` (HA history export
format: `entity_id,state,last_changed`). Imported cycles are auto-labelled by
the heuristics and bootstrap the model.

## Services

| Service | Parameters |
|---|---|
| `washer_ml.import_history` | `entry_id`, `csv_path` **or** `csv_content` |
| `washer_ml.retrain` | `entry_id` |
| `washer_ml.reset_calibration` | `entry_id` |

## Requirements

- Home Assistant 2024.6+
- Python 3.12+ (HA default)
- Only dependency: `aiosqlite` (already part of HA core)

> Set `codeowners` / `issue_tracker` / `documentation` in `manifest.json` before
> publishing.