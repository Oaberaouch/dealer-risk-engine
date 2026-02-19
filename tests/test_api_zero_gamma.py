# tests/test_api_zero_gamma.py
import math

from fastapi.testclient import TestClient

from apps.api.main import app

client = TestClient(app)


def _is_finite_number(x) -> bool:
    try:
        xf = float(x)
    except Exception:
        return False
    return math.isfinite(xf)


def _assert_zero_gamma_result_contract(res: dict) -> None:
    """
    Contract for the solver payload returned under j["result"].

    We DON'T lock exact numeric values (too brittle), we lock:
    - schema keys exist
    - target ~= tol_rel * scale
    - if found=True => converged=True and |gex_level| <= target
    """
    for k in (
        "found",
        "mode",
        "level",
        "gex_level",
        "gex_lo",
        "gex_hi",
        "bracket_final",
        "gex_lo_final",
        "gex_hi_final",
        "iters",
        "scale",
        "target",
        "reason",
        "converged",
    ):
        assert k in res, f"Missing key in result: {k}"

    assert isinstance(res["mode"], str)
    assert res["mode"] in ("netted", "raw")

    # Diagnostics must be numeric and finite
    assert _is_finite_number(res["scale"])
    assert float(res["scale"]) > 0.0
    assert _is_finite_number(res["target"])
    assert float(res["target"]) > 0.0
    assert isinstance(res["iters"], int)
    assert res["iters"] >= 0

    assert isinstance(res["bracket_final"], (list, tuple))
    assert len(res["bracket_final"]) == 2
    assert _is_finite_number(res["bracket_final"][0])
    assert _is_finite_number(res["bracket_final"][1])

    # gex_lo / gex_hi should always be present + finite (endpoint evaluations)
    assert _is_finite_number(res["gex_lo"])
    assert _is_finite_number(res["gex_hi"])
    assert _is_finite_number(res["gex_lo_final"])
    assert _is_finite_number(res["gex_hi_final"])

    # If found=False, level and gex_level should be None
    if not res["found"]:
        assert res["level"] is None
        assert res["gex_level"] is None
        # reason should explain failure mode
        assert isinstance(res["reason"], str)
        assert res["converged"] is False
        return

    # If found=True
    assert _is_finite_number(res["level"])
    assert _is_finite_number(res["gex_level"])
    assert res["converged"] is True
    assert res["reason"] == "converged"

    # Strong guarantee: |gex_level| <= target (within tiny numeric slack)
    g = abs(float(res["gex_level"]))
    target = float(res["target"])
    assert g <= target * (1.0 + 1e-9) + 1e-12


def test_zero_gamma_defaults_are_exposed_and_result_has_contract():
    r = client.get(
        "/synthetic/zero-gamma",
        params={
            "bracket_pct": 0.40,
            "tilt": 3,
            "oi_base": 20000,
            "oi_width": 0.10,
        },
    )
    assert r.status_code == 200
    j = r.json()

    # API surface locks (you explicitly wanted these defaults)
    assert j["mode"] == "netted"
    assert j["tol_rel"] == 1e-6
    assert j["max_iter"] == 140

    assert "result" in j
    _assert_zero_gamma_result_contract(j["result"])

    # target ~= tol_rel * scale
    scale = float(j["result"]["scale"])
    target = float(j["result"]["target"])
    assert math.isclose(target, float(j["tol_rel"]) * scale, rel_tol=1e-12, abs_tol=1e-12)


def test_zero_gamma_tighter_tol_rel_produces_tighter_target_and_respects_contract():
    base_params = {
        "bracket_pct": 0.40,
        "tilt": 3,
        "oi_base": 20000,
        "oi_width": 0.10,
        "mode": "netted",
    }

    r1 = client.get("/synthetic/zero-gamma", params={**base_params, "tol_rel": 1e-6})
    r2 = client.get("/synthetic/zero-gamma", params={**base_params, "tol_rel": 1e-8})

    assert r1.status_code == 200 and r2.status_code == 200
    j1, j2 = r1.json(), r2.json()

    _assert_zero_gamma_result_contract(j1["result"])
    _assert_zero_gamma_result_contract(j2["result"])

    # Lock mathematical relationship for each call
    scale1 = float(j1["result"]["scale"])
    scale2 = float(j2["result"]["scale"])
    target1 = float(j1["result"]["target"])
    target2 = float(j2["result"]["target"])

    assert math.isclose(target1, float(j1["tol_rel"]) * scale1, rel_tol=1e-12, abs_tol=1e-12)
    assert math.isclose(target2, float(j2["tol_rel"]) * scale2, rel_tol=1e-12, abs_tol=1e-12)

    # tighter tol_rel => smaller target, regardless of scale (scale should usually match, but don't assume)
    assert target2 < target1

    # if both found=True, tighter tol_rel should not produce larger |gex_level| by much
    if j1["result"]["found"] and j2["result"]["found"]:
        g1 = abs(float(j1["result"]["gex_level"]))
        g2 = abs(float(j2["result"]["gex_level"]))
        assert g2 <= g1 * (1.0 + 1e-6) + 1e-9


def test_zero_gamma_compare_respects_tol_rel_and_returns_two_contract_results():
    r = client.get(
        "/synthetic/zero-gamma/compare",
        params={
            "bracket_pct": 0.40,
            "tilt": 3,
            "oi_base": 20000,
            "oi_width": 0.10,
            "tol_rel": 1e-8,
        },
    )
    assert r.status_code == 200
    j = r.json()

    assert j["tol_rel"] == 1e-8
    assert "netted" in j and "raw" in j
    assert "result" in j["netted"]
    assert "result" in j["raw"]

    _assert_zero_gamma_result_contract(j["netted"]["result"])
    _assert_zero_gamma_result_contract(j["raw"]["result"])

    # Targets must be positive, and satisfy target ~= tol_rel * scale in each mode
    net_scale = float(j["netted"]["result"]["scale"])
    raw_scale = float(j["raw"]["result"]["scale"])
    net_target = float(j["netted"]["result"]["target"])
    raw_target = float(j["raw"]["result"]["target"])

    assert net_target > 0.0 and raw_target > 0.0
    assert math.isclose(net_target, float(j["tol_rel"]) * net_scale, rel_tol=1e-12, abs_tol=1e-12)
    assert math.isclose(raw_target, float(j["tol_rel"]) * raw_scale, rel_tol=1e-12, abs_tol=1e-12)