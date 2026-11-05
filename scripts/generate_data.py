"""
Battery Cell Manufacturing QC -- Data Generator
Simulates sensor readings from a lithium-ion cell production line.
Each cell goes through: Formation -> Aging -> Final Test stages.
Sensors: voltage (V), temperature (C), internal resistance (mOhm), capacity (Ah)
49,500 rows across 500 cells x 3 stages x 33 cycles each
"""
import os
import random
from datetime import datetime, timedelta

import duckdb
import numpy as np
import pandas as pd

random.seed(42)
np.random.seed(42)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "battery_qc.db")

# Specification targets per stage
SPECS = {
    "formation": {
        "voltage":             {"mean": 3.65, "std": 0.04},
        "temperature_c":       {"mean": 25.0, "std": 1.5},
        "internal_resistance": {"mean": 28.0, "std": 2.0},
        "capacity_ah":         {"mean": 4.85, "std": 0.08},
    },
    "aging": {
        "voltage":             {"mean": 3.60, "std": 0.05},
        "temperature_c":       {"mean": 40.0, "std": 2.0},
        "internal_resistance": {"mean": 30.0, "std": 2.5},
        "capacity_ah":         {"mean": 4.75, "std": 0.10},
    },
    "final_test": {
        "voltage":             {"mean": 3.58, "std": 0.04},
        "temperature_c":       {"mean": 23.0, "std": 1.0},
        "internal_resistance": {"mean": 32.0, "std": 2.0},
        "capacity_ah":         {"mean": 4.70, "std": 0.09},
    },
}

STAGES = ["formation", "aging", "final_test"]
LINES = ["LINE_A", "LINE_B", "LINE_C"]
OPERATORS = ["OP_01", "OP_02", "OP_03", "OP_04", "OP_05"]
N_CELLS = 500
N_CYCLES = 33
ANOMALY_RATE = 0.03  # 3% of readings are injected out-of-spec events


def generate_reading(stage, cell_id, cycle, ts, inject_anomaly=False):
    row = {
        "cell_id": f"CELL_{cell_id:04d}",
        "stage": stage,
        "cycle": cycle,
        "timestamp": ts,
        "line_id": random.choice(LINES),
        "operator_id": random.choice(OPERATORS),
    }
    for sensor, cfg in SPECS[stage].items():
        val = np.random.normal(cfg["mean"], cfg["std"])
        if inject_anomaly:
            direction = random.choice([-1, 1])
            val = cfg["mean"] + direction * cfg["std"] * random.uniform(3.5, 5.0)
        row[sensor] = round(float(val), 4)
    return row


def main():
    rows = []
    ts = datetime(2024, 1, 1, 6, 0, 0)
    for cell_id in range(1, N_CELLS + 1):
        for stage in STAGES:
            for cycle in range(1, N_CYCLES + 1):
                inject = random.random() < ANOMALY_RATE
                rows.append(generate_reading(stage, cell_id, cycle, ts, inject))
                ts += timedelta(minutes=random.randint(2, 6))

    df = pd.DataFrame(rows)
    print(f"Generated {len(df):,} sensor readings across {N_CELLS} cells")

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = duckdb.connect(DB_PATH)
    con.execute("DROP TABLE IF EXISTS bronze_sensor_readings")
    con.execute("""
        CREATE TABLE bronze_sensor_readings AS
        SELECT *, CURRENT_TIMESTAMP AS ingested_at FROM df
    """)
    count = con.execute("SELECT COUNT(*) FROM bronze_sensor_readings").fetchone()[0]
    print(f"Bronze layer: {count:,} rows loaded into {DB_PATH}")
    con.close()


if __name__ == "__main__":
    main()
