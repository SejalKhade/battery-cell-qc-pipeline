"""
Battery Cell Manufacturing QC -- Flask API
Serves pre-aggregated Gold layer tables from DuckDB.
"""
import os

import duckdb
from flask import Flask, jsonify, render_template

app = Flask(__name__)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "battery_qc.db")


def query(sql: str):
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        return con.execute(sql).fetchdf().to_dict(orient="records")
    finally:
        con.close()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/summary")
def summary():
    rows = query("""
        SELECT COUNT(*) AS total_cells,
               SUM(CASE WHEN yield_status='PASS' THEN 1 ELSE 0 END) AS pass_count,
               SUM(CASE WHEN yield_status='FAIL' THEN 1 ELSE 0 END) AS fail_count,
               SUM(CASE WHEN yield_status='REVIEW' THEN 1 ELSE 0 END) AS review_count,
               ROUND(AVG(anomaly_rate_pct), 2) AS avg_anomaly_rate_pct,
               SUM(anomaly_count) AS total_anomalies,
               SUM(total_readings) AS total_readings
        FROM gold_cell_yield
    """)
    return jsonify(rows[0] if rows else {})


@app.route("/api/spc_by_stage")
def spc_by_stage():
    return jsonify(query("""
        SELECT stage, line_id, anomaly_rate_pct, avg_voltage, avg_temperature,
               avg_resistance, avg_capacity, lcl_voltage, ucl_voltage,
               lcl_capacity, ucl_capacity, total_readings, anomaly_count
        FROM gold_spc_summary ORDER BY stage, line_id
    """))


@app.route("/api/anomaly_trend")
def anomaly_trend():
    return jsonify(query("""
        SELECT STRFTIME(DATE_TRUNC('day', timestamp), '%Y-%m-%d') AS day_bucket,
               stage,
               COUNT(*) AS total_readings,
               SUM(is_anomaly) AS anomaly_count,
               ROUND(100.0 * SUM(is_anomaly) / COUNT(*), 2) AS anomaly_rate_pct
        FROM gold_sensor_anomalies
        GROUP BY DATE_TRUNC('day', timestamp), stage
        ORDER BY day_bucket, stage
    """))


@app.route("/api/cell_yield")
def cell_yield():
    return jsonify(query("""
        SELECT cell_id, yield_status, anomaly_rate_pct, ooc_voltage_count,
               ooc_temperature_count, ooc_resistance_count, ooc_capacity_count,
               total_readings, anomaly_count
        FROM gold_cell_yield ORDER BY anomaly_rate_pct DESC LIMIT 100
    """))


@app.route("/api/sensor_distribution")
def sensor_distribution():
    return jsonify(query("""
        SELECT stage,
               ROUND(AVG(voltage), 4) AS avg_voltage,
               ROUND(AVG(temperature_c), 2) AS avg_temperature,
               ROUND(AVG(internal_resistance), 2) AS avg_resistance,
               ROUND(AVG(capacity_ah), 4) AS avg_capacity,
               ROUND(MIN(lcl_voltage), 4) AS lcl_voltage,
               ROUND(MAX(ucl_voltage), 4) AS ucl_voltage,
               ROUND(MIN(lcl_capacity), 4) AS lcl_capacity,
               ROUND(MAX(ucl_capacity), 4) AS ucl_capacity,
               ROUND(MIN(lcl_resistance), 2) AS lcl_resistance,
               ROUND(MAX(ucl_resistance), 2) AS ucl_resistance
        FROM gold_sensor_anomalies GROUP BY stage ORDER BY stage
    """))


if __name__ == "__main__":
    app.run(debug=True, port=5052)
