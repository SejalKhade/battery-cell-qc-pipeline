"""
Battery Cell QC -- API and pipeline tests.
Runs against the real Gold layer: builds the DuckDB pipeline once if missing,
then checks every endpoint plus manufacturing business invariants.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import app as flask_app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def build_pipeline():
    if not os.path.exists(flask_app.DB_PATH):
        import generate_data
        import build_silver_gold
        generate_data.main()
        build_silver_gold.main()


@pytest.fixture(scope="session")
def client():
    flask_app.app.config["TESTING"] = True
    with flask_app.app.test_client() as c:
        yield c


def get(client, path):
    r = client.get(path)
    assert r.status_code == 200, f"{path} returned {r.status_code}"
    return r.get_json()


# Dashboard
def test_index_200(client):
    assert client.get("/").status_code == 200


# Summary
def test_summary_keys(client):
    d = get(client, "/api/summary")
    for k in ("total_cells", "pass_count", "fail_count", "review_count", "avg_anomaly_rate_pct"):
        assert k in d


def test_summary_500_cells(client):
    assert get(client, "/api/summary")["total_cells"] == 500


def test_summary_yield_adds_up(client):
    d = get(client, "/api/summary")
    assert d["pass_count"] + d["fail_count"] + d["review_count"] == d["total_cells"]


def test_summary_readings_count(client):
    assert get(client, "/api/summary")["total_readings"] == 49500


def test_summary_anomaly_rate_valid(client):
    assert 0 <= get(client, "/api/summary")["avg_anomaly_rate_pct"] <= 100


def test_anomalies_detected(client):
    # 3% injected out-of-spec events must be caught
    assert get(client, "/api/summary")["total_anomalies"] > 0


# SPC by stage and line
def test_spc_covers_all_stages_and_lines(client):
    data = get(client, "/api/spc_by_stage")
    assert {r["stage"] for r in data} == {"formation", "aging", "final_test"}
    assert {r["line_id"] for r in data} == {"LINE_A", "LINE_B", "LINE_C"}


def test_spc_control_limits_ordered(client):
    for r in get(client, "/api/spc_by_stage"):
        assert r["lcl_voltage"] < r["ucl_voltage"]
        assert r["lcl_capacity"] < r["ucl_capacity"]


def test_spc_anomaly_rate_valid(client):
    for r in get(client, "/api/spc_by_stage"):
        assert 0 <= r["anomaly_rate_pct"] <= 100


def test_spc_aging_runs_hotter(client):
    # Aging is an elevated-temperature stress stage
    data = get(client, "/api/spc_by_stage")
    aging = [r["avg_temperature"] for r in data if r["stage"] == "aging"]
    formation = [r["avg_temperature"] for r in data if r["stage"] == "formation"]
    assert min(aging) > max(formation)


# Anomaly trend
def test_trend_fields(client):
    row = get(client, "/api/anomaly_trend")[0]
    for f in ("day_bucket", "stage", "anomaly_count", "anomaly_rate_pct"):
        assert f in row


def test_trend_counts_valid(client):
    for r in get(client, "/api/anomaly_trend"):
        assert 0 <= r["anomaly_count"] <= r["total_readings"]


# Cell yield
def test_yield_status_valid(client):
    for r in get(client, "/api/cell_yield"):
        assert r["yield_status"] in {"PASS", "REVIEW", "FAIL"}


def test_yield_sorted_descending(client):
    rates = [r["anomaly_rate_pct"] for r in get(client, "/api/cell_yield")]
    assert rates == sorted(rates, reverse=True)


def test_yield_status_matches_threshold(client):
    for r in get(client, "/api/cell_yield"):
        if r["anomaly_rate_pct"] > 10:
            assert r["yield_status"] == "FAIL"
        elif r["anomaly_rate_pct"] > 5:
            assert r["yield_status"] == "REVIEW"
        else:
            assert r["yield_status"] == "PASS"


def test_yield_limit_100(client):
    assert len(get(client, "/api/cell_yield")) == 100


# Sensor distribution / control chart
def test_sensor_three_stages(client):
    assert len(get(client, "/api/sensor_distribution")) == 3


def test_sensor_avg_within_limits(client):
    for r in get(client, "/api/sensor_distribution"):
        assert r["lcl_voltage"] < r["avg_voltage"] < r["ucl_voltage"]
        assert r["lcl_capacity"] < r["avg_capacity"] < r["ucl_capacity"]
        assert r["lcl_resistance"] < r["avg_resistance"] < r["ucl_resistance"]


def test_capacity_degrades_across_stages(client):
    caps = {r["stage"]: r["avg_capacity"] for r in get(client, "/api/sensor_distribution")}
    assert caps["formation"] > caps["aging"] > caps["final_test"]


# Defective batch detection
def test_defective_lot_is_caught(client):
    import generate_data
    defective = {f"CELL_{i:04d}" for i in generate_data.DEFECTIVE_CELLS}
    failed = {r["cell_id"] for r in get(client, "/api/cell_yield") if r["yield_status"] == "FAIL"}
    assert len(failed & defective) >= 12   # at least 80% of the bad lot flagged FAIL
    assert not failed - defective          # no healthy cell is failed
