"""
Silver layer: validate + compute SPC Z-scores and 3-sigma control limits per stage
Gold layer:   Isolation Forest + Z-score anomaly flags, cell-level yield, SPC summary
"""
import os

import duckdb
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "battery_qc.db")
SENSORS = ["voltage", "temperature_c", "internal_resistance", "capacity_ah"]
SHORT = {"voltage": "voltage", "temperature_c": "temperature",
         "internal_resistance": "resistance", "capacity_ah": "capacity"}


def spc_columns():
    """Z-score + UCL/LCL per sensor, partitioned by stage (window functions)."""
    parts = []
    for col, short in SHORT.items():
        mean = f"AVG({col}) OVER (PARTITION BY stage)"
        std = f"STDDEV({col}) OVER (PARTITION BY stage)"
        parts.append(f"({col} - {mean}) / NULLIF({std}, 0) AS z_{short}")
        parts.append(f"{mean} - 3 * {std} AS lcl_{short}")
        parts.append(f"{mean} + 3 * {std} AS ucl_{short}")
    return ",\n        ".join(parts)


def main():
    con = duckdb.connect(DB_PATH)

    # SILVER
    print("Building Silver layer...")
    con.execute("DROP TABLE IF EXISTS silver_sensor_clean")
    con.execute(f"""
        CREATE TABLE silver_sensor_clean AS
        SELECT cell_id, stage, cycle, CAST(timestamp AS TIMESTAMP) AS timestamp,
               line_id, operator_id, voltage, temperature_c, internal_resistance, capacity_ah,
        {spc_columns()}
        FROM bronze_sensor_readings
        WHERE voltage IS NOT NULL AND temperature_c IS NOT NULL
          AND internal_resistance IS NOT NULL AND capacity_ah IS NOT NULL
    """)
    print(f"Silver: {con.execute('SELECT COUNT(*) FROM silver_sensor_clean').fetchone()[0]:,} clean rows")

    # GOLD: anomaly detection
    print("Building Gold layer (Isolation Forest + SPC)...")
    df = con.execute("SELECT * FROM silver_sensor_clean").df()

    X = StandardScaler().fit_transform(df[SENSORS])
    iso = IsolationForest(n_estimators=100, contamination=0.03, random_state=42)
    df["anomaly_if_flag"] = (iso.fit_predict(X) == -1).astype(int)

    z_cols = ["z_voltage", "z_temperature", "z_resistance", "z_capacity"]
    df["anomaly_zscore_flag"] = (df[z_cols].abs() > 3).any(axis=1).astype(int)
    df["is_anomaly"] = ((df["anomaly_if_flag"] == 1) | (df["anomaly_zscore_flag"] == 1)).astype(int)

    for col, short in SHORT.items():
        df[f"ooc_{short}"] = ((df[col] < df[f"lcl_{short}"]) | (df[col] > df[f"ucl_{short}"])).astype(int)

    con.execute("DROP TABLE IF EXISTS gold_sensor_anomalies")
    con.execute("CREATE TABLE gold_sensor_anomalies AS SELECT * FROM df")

    con.execute("DROP TABLE IF EXISTS gold_cell_yield")
    con.execute("""
        CREATE TABLE gold_cell_yield AS
        SELECT cell_id,
               COUNT(*) AS total_readings,
               SUM(is_anomaly) AS anomaly_count,
               ROUND(100.0 * SUM(is_anomaly) / COUNT(*), 2) AS anomaly_rate_pct,
               SUM(ooc_voltage) AS ooc_voltage_count,
               SUM(ooc_temperature) AS ooc_temperature_count,
               SUM(ooc_resistance) AS ooc_resistance_count,
               SUM(ooc_capacity) AS ooc_capacity_count,
               CASE WHEN 100.0 * SUM(is_anomaly) / COUNT(*) > 10 THEN 'FAIL'
                    WHEN 100.0 * SUM(is_anomaly) / COUNT(*) > 5  THEN 'REVIEW'
                    ELSE 'PASS' END AS yield_status
        FROM gold_sensor_anomalies
        GROUP BY cell_id
    """)

    con.execute("DROP TABLE IF EXISTS gold_spc_summary")
    con.execute("""
        CREATE TABLE gold_spc_summary AS
        SELECT stage, line_id,
               COUNT(*) AS total_readings,
               SUM(is_anomaly) AS anomaly_count,
               ROUND(100.0 * SUM(is_anomaly) / COUNT(*), 2) AS anomaly_rate_pct,
               ROUND(AVG(voltage), 4) AS avg_voltage,
               ROUND(AVG(temperature_c), 2) AS avg_temperature,
               ROUND(AVG(internal_resistance), 2) AS avg_resistance,
               ROUND(AVG(capacity_ah), 4) AS avg_capacity,
               ROUND(MIN(lcl_voltage), 4) AS lcl_voltage,
               ROUND(MAX(ucl_voltage), 4) AS ucl_voltage,
               ROUND(MIN(lcl_capacity), 4) AS lcl_capacity,
               ROUND(MAX(ucl_capacity), 4) AS ucl_capacity
        FROM gold_sensor_anomalies
        GROUP BY stage, line_id
        ORDER BY stage, line_id
    """)

    anomalies = con.execute("SELECT SUM(is_anomaly) FROM gold_sensor_anomalies").fetchone()[0]
    status = dict(con.execute("SELECT yield_status, COUNT(*) FROM gold_cell_yield GROUP BY 1").fetchall())
    print(f"Gold: {anomalies:,} anomalies detected")
    print(f"Cell yield: {status}")
    con.close()


if __name__ == "__main__":
    main()
