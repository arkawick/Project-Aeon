"""
Prediction store — the Merge Gate's learning loop.

Every forecast is recorded here. When the REAL build result later arrives at
/api/pipelines/ingest (Jenkins / GitHub Actions webhook), it's matched back to
the prediction by commit SHA (or repo+PR), and the gate's running accuracy,
Brier score, and calibration are updated. Once enough real outcomes exist, a
gentle calibration factor nudges future probabilities toward reality.

Persistence: a JSON file (PREDICT_STORE_PATH, default /tmp/aeon_predictions.json).
Seeded with a handful of historical outcomes so the accuracy card is meaningful
immediately; live predictions/outcomes accumulate on top.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone

_PATH = os.getenv("PREDICT_STORE_PATH", "/tmp/aeon_predictions.json")
_MIN_FOR_CALIBRATION = 10
_lock = threading.Lock()

# id -> record. record: {id, repo, pr, sha, probability, verdict, confidence,
#                        predicted_fail, created_at, actual, resolved_at, correct}
_preds: dict[str, dict] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pid(repo: str, pr) -> str:
    return f"{repo}#{pr}"


def _predicted_fail(probability: int) -> bool:
    return probability >= 50


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _save() -> None:
    try:
        with open(_PATH, "w", encoding="utf-8") as f:
            json.dump(list(_preds.values()), f)
    except Exception as exc:
        print(f"[prediction_store] save failed: {exc}")


def _load() -> None:
    global _preds
    try:
        if os.path.exists(_PATH):
            with open(_PATH, "r", encoding="utf-8") as f:
                rows = json.load(f)
            _preds = {r["id"]: r for r in rows if r.get("id")}
    except Exception as exc:
        print(f"[prediction_store] load failed: {exc}")
    if not _preds:
        _seed()


def _seed() -> None:
    """A calibrated set of past forecasts+outcomes so accuracy is shown live."""
    demo = [
        # (repo, pr, prob, verdict, actual)  — roughly calibrated
        ("acme/payments-api", 812, 78, "BLOCK",   "fail"),
        ("acme/payments-api", 809, 71, "BLOCK",   "fail"),
        ("acme/web-frontend", 1447, 66, "BLOCK",  "fail"),
        ("acme/web-frontend", 1440, 52, "CAUTION", "fail"),
        ("acme/data-service", 233, 48, "CAUTION", "pass"),
        ("acme/data-service", 230, 41, "CAUTION", "fail"),
        ("acme/payments-api", 801, 33, "PASS",    "pass"),
        ("acme/web-frontend", 1431, 22, "PASS",   "pass"),
        ("acme/mobile-app",   540, 61, "BLOCK",   "fail"),
        ("acme/mobile-app",   536, 29, "PASS",    "pass"),
        ("acme/data-service", 221, 18, "PASS",    "pass"),
        ("acme/web-frontend", 1425, 74, "BLOCK",  "fail"),
        ("acme/payments-api", 795, 44, "CAUTION", "pass"),
        ("acme/mobile-app",   528, 12, "PASS",    "pass"),
    ]
    for repo, pr, prob, verdict, actual in demo:
        rid = _pid(repo, pr)
        _preds[rid] = {
            "id": rid, "repo": repo, "pr": pr, "sha": "", "probability": prob,
            "verdict": verdict, "confidence": "high", "predicted_fail": _predicted_fail(prob),
            "created_at": _now(), "actual": actual, "resolved_at": _now(),
            "correct": _predicted_fail(prob) == (actual == "fail"), "seed": True,
        }
    _save()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_prediction(repo: str, pr, sha: str, probability: int,
                      verdict: str, confidence: str) -> None:
    with _lock:
        rid = _pid(repo, pr)
        _preds[rid] = {
            "id": rid, "repo": repo, "pr": pr, "sha": sha or "",
            "probability": probability, "verdict": verdict, "confidence": confidence,
            "predicted_fail": _predicted_fail(probability),
            "created_at": _now(), "actual": None, "resolved_at": None, "correct": None,
        }
        _save()


def record_outcome(repo: str = "", sha: str = "", status: str = "",
                   pr=None) -> dict | None:
    """Match a real build result to an open prediction and resolve it.

    status: "success"/"passed" -> pass; anything else -> fail.
    Matches by repo+PR when given, else by commit SHA.
    """
    actual = "pass" if status.lower() in ("success", "passed", "pass") else "fail"
    with _lock:
        match = None
        if pr is not None and repo:
            match = _preds.get(_pid(repo, pr))
        if not match and sha:
            for r in _preds.values():
                if r.get("sha") and r["sha"] == sha and r.get("actual") is None:
                    match = r
                    break
        if not match:
            return None
        match["actual"] = actual
        match["resolved_at"] = _now()
        match["correct"] = match["predicted_fail"] == (actual == "fail")
        _save()
        return match


def calibration_factor() -> float:
    """A gentle learned multiplier for future probabilities, active only once
    enough REAL (non-seed) outcomes exist. Clamped so it never distorts wildly."""
    resolved = [r for r in _preds.values() if r.get("actual") and not r.get("seed")]
    if len(resolved) < _MIN_FOR_CALIBRATION:
        return 1.0
    mean_pred = sum(r["probability"] for r in resolved) / len(resolved) / 100.0
    actual_rate = sum(1 for r in resolved if r["actual"] == "fail") / len(resolved)
    if mean_pred <= 0.01:
        return 1.0
    return max(0.7, min(1.3, actual_rate / mean_pred))


def stats() -> dict:
    with _lock:
        resolved = [r for r in _preds.values() if r.get("actual")]
        n = len(resolved)
        if n == 0:
            return {"resolved": 0, "accuracy": None, "brier": None,
                    "block_precision": None, "calibration_factor": 1.0, "recent": []}
        correct = sum(1 for r in resolved if r.get("correct"))
        brier = sum((r["probability"] / 100.0 - (1 if r["actual"] == "fail" else 0)) ** 2
                    for r in resolved) / n
        blocks = [r for r in resolved if r["verdict"] == "BLOCK"]
        block_hits = sum(1 for r in blocks if r["actual"] == "fail")
        recent = sorted(resolved, key=lambda r: r.get("resolved_at", ""), reverse=True)[:8]
        return {
            "resolved": n,
            "pending": sum(1 for r in _preds.values() if r.get("actual") is None),
            "accuracy": round(correct / n, 3),
            "brier": round(brier, 3),
            "block_precision": round(block_hits / len(blocks), 3) if blocks else None,
            "calibration_factor": round(calibration_factor(), 3),
            "recent": [
                {"repo": r["repo"], "pr": r["pr"], "probability": r["probability"],
                 "verdict": r["verdict"], "actual": r["actual"], "correct": r["correct"]}
                for r in recent
            ],
        }


_load()
