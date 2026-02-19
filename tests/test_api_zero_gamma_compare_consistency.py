# tests/test_api_zero_gamma_compare_consistency.py
from fastapi.testclient import TestClient

from apps.api.main import app

client = TestClient(app)


def _as_float(x):
    return None if x is None else float(x)


def test_compare_level_diff_matches_levels_when_both_found():
    r = client.get(
        "/synthetic/zero-gamma/compare",
        params={
            "bracket_pct": 0.40,
            "tilt": 3,
            "oi_base": 20000,
            "oi_width": 0.10,
            "tol_rel": 1e-8,  # make it tighter so both modes usually converge cleanly
        },
    )
    assert r.status_code == 200
    j = r.json()

    # Schema locks
    assert "netted" in j and "raw" in j and "delta" in j
    assert "result" in j["netted"] and "result" in j["raw"]
    assert "both_found" in j["delta"]
    assert "level_diff" in j["delta"]

    net = j["netted"]["result"]
    raw = j["raw"]["result"]
    both_found = bool(j["delta"]["both_found"])

    # If both found, level_diff must equal net.level - raw.level (within tight tolerance)
    if both_found:
        assert net["found"] is True
        assert raw["found"] is True

        net_level = float(net["level"])
        raw_level = float(raw["level"])
        expected = net_level - raw_level

        got = float(j["delta"]["level_diff"])
        assert abs(got - expected) < 1e-12

    # If not both_found, level_diff must be None
    else:
        assert j["delta"]["level_diff"] is None


def test_compare_reports_tolerance_controls_target_for_both():
    r = client.get(
        "/synthetic/zero-gamma/compare",
        params={
            "bracket_pct": 0.40,
            "tilt": 3,
            "oi_base": 20000,
            "oi_width": 0.10,
            "tol_rel": 1e-6,
        },
    )
    assert r.status_code == 200
    j = r.json()

    # tol_rel echo is part of the API contract now
    assert float(j["tol_rel"]) == 1e-6

    net = j["netted"]["result"]
    raw = j["raw"]["result"]

    # targets must be present and positive (scale * tol_rel)
    assert "target" in net and "target" in raw
    assert float(net["target"]) > 0.0
    assert float(raw["target"]) > 0.0

    # If converged, |gex_level| must be <= target (strong guarantee)
    if net.get("converged") and net.get("found"):
        assert abs(float(net["gex_level"])) <= float(net["target"]) + 1e-12
    if raw.get("converged") and raw.get("found"):
        assert abs(float(raw["gex_level"])) <= float(raw["target"]) + 1e-12