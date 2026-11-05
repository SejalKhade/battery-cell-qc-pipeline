# Battery Cell Manufacturing QC Pipeline

End-to-end quality control pipeline for simulated lithium-ion cell production. Sensor readings flow through a Bronze/Silver/Gold DuckDB pipeline, get scored by Statistical Process Control (SPC) limits and an Isolation Forest model, and land in a Flask API and D3.js dashboard that flags cells as PASS, REVIEW, or FAIL.

## Problem

Cell production lines generate thousands of sensor readings per shift across formation, aging, and final test. A drifting cell that slips past QC means a scrapped pack later, or a field failure. Engineers need two things fast: which cells are out of control, and which stage or line is causing it.

## Architecture

```
generate_data.py      Bronze  bronze_sensor_readings   49,500 raw readings (500 cells x 3 stages x 33 cycles)
        |
build_silver_gold.py  Silver  silver_sensor_clean      null checks, Z-scores, 3-sigma UCL/LCL per stage (window functions)
        |             Gold    gold_sensor_anomalies    Isolation Forest + Z-score flags, out-of-control flags per sensor
        |                     gold_cell_yield          per-cell anomaly rate and PASS / REVIEW / FAIL status
        |                     gold_spc_summary         anomaly rate and control limits per stage and line
        |
app.py                Flask API (5 JSON endpoints)  ->  templates/index.html  D3.js dashboard
```

## Why this stack

| Choice | Reason |
|---|---|
| DuckDB | Columnar, in-process, fast window functions; no server to run |
| Medallion layers | Raw data is kept untouched; every Gold number can be traced back |
| SPC (3-sigma) | Standard manufacturing control method engineers already trust |
| Isolation Forest | Catches multi-sensor anomalies that single-sensor limits miss |
| Flask + D3.js | Light API, custom charts (control limits, grouped bars) |
| pytest + GitHub Actions | Every push rebuilds the pipeline and checks business rules |

## Data model

- Sensors: `voltage` (V), `temperature_c` (C), `internal_resistance` (mOhm), `capacity_ah` (Ah)
- Context: `cell_id`, `stage`, `cycle`, `timestamp`, `line_id`, `operator_id`
- 3% of readings are injected out-of-spec events (3.5 to 5 sigma) to test detection
- Yield rule: anomaly rate above 10% is FAIL, above 5% is REVIEW, otherwise PASS

## Setup

```bash
pip install -r requirements.txt
python scripts/generate_data.py
python scripts/build_silver_gold.py
python app.py            # http://localhost:5052
```

## API endpoints

| Endpoint | Returns |
|---|---|
| `/api/summary` | total cells, pass / review / fail counts, average anomaly rate |
| `/api/spc_by_stage` | anomaly rate, averages, and control limits per stage and line |
| `/api/anomaly_trend` | daily anomaly rate per stage |
| `/api/cell_yield` | top 100 cells by anomaly rate with out-of-control counts |
| `/api/sensor_distribution` | stage averages against UCL / LCL |

## Tests

```bash
pytest tests/ -v --cov=app
```

Tests run against the real Gold layer and check business rules, not just status codes: yield counts add up to 500 cells, every reading is accounted for, control limits are ordered, statuses match thresholds, aging runs hotter than formation, and capacity drops across stages.

## What's next

- Stream readings with Kafka instead of batch generation
- Move storage to S3 + Athena or Snowflake for multi-line scale
- Add a root-cause view linking anomalies to operator and line
- Schedule the pipeline with Airflow and alert on FAIL spikes
