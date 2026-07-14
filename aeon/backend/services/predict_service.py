"""
Predictive Merge Gate
=====================
Given a PR *before* it builds, forecast whether CI is likely to fail — by fusing
signals Aeon already computes, rather than actually building anything.

Signals (each 0..1, blended by weight):
  1. memory   — do the changed files resemble PAST failed incidents?   (Blast Radius recall)
  2. hanging  — targeted co-change: did the PR touch a file but omit a   (per-file git history)
                partner it historically changes WITH?  (strongest pre-build tell)
  3. shape    — PR-shape risk: source w/o tests, big diff, dep/lockfile  (from the PR files)
  4. risk     — how many changed files are HIGH-risk classes             (Blast classifier)

Ground-truth prior: the PR head commit's existing CI check-runs. A check already
FAILING forces BLOCK (high confidence); all-green dampens the estimate.

Confidence reflects how much evidence actually fired — a 45% from one weak match
reads differently than 45% from three converging signals.

This is a risk forecast grounded in the repo's own history + current CI state —
not a guarantee, and it won't catch a novel error it has never seen.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any, AsyncIterator

import httpx

from services.blast_radius_service import (
    _gh_get, _classify_file, _infer_service, _search_incident_memory,
)

# Hanging-point thresholds (targeted co-change)
HANGING_MIN_SCORE = 0.5
HANGING_MIN_CO = 3
FOCUS_FILE_CAP = 8          # changed files we mine history for
PATH_COMMITS = 20           # commits fetched per changed file
CO_COMMIT_CAP = 60          # unique commits we pull details for

# Blended fail-score weights (sum to 1.0)
W_MEMORY = 0.30
W_HANGING = 0.25
W_SHAPE = 0.25
W_RISK = 0.20

HIGH_RISK_CATEGORIES = {"Dependencies", "Config", "Infrastructure", "Service"}
VERDICT_COLOR = {"BLOCK": "#ef4444", "CAUTION": "#f59e0b", "PASS": "#22c55e"}
CI_FAIL_CONCLUSIONS = {"failure", "cancelled", "timed_out", "startup_failure", "action_required"}


def _verdict(prob: int) -> str:
    if prob >= 60:
        return "BLOCK"
    if prob >= 35:
        return "CAUTION"
    return "PASS"


# ---------------------------------------------------------------------------
# Signal 2: targeted co-change → hanging points on THIS PR's files
# ---------------------------------------------------------------------------

async def _targeted_hanging(client, owner: str, repo_name: str,
                            changed_files: list[tuple], changed_set: set) -> list[dict]:
    """Mine each changed file's OWN commit history for what co-changes with it,
    then flag partners the PR left untouched. Targeted (not a global window) so
    it actually fires on the PR's files."""
    focus = [fp for fp, cat, *_ in changed_files if cat != "Docs"][:FOCUS_FILE_CAP]
    if not focus:
        return []

    # 1. commits that touched each focus file
    sha_set: dict[str, bool] = {}
    for fp in focus:
        commits = await _gh_get(client, f"/repos/{owner}/{repo_name}/commits", path=fp, per_page=PATH_COMMITS)
        for c in (commits or []):
            sha_set[c["sha"]] = True
    shas = list(sha_set)[:CO_COMMIT_CAP]
    if not shas:
        return []

    # 2. file lists for those commits (parallel), skipping merges
    sem = asyncio.Semaphore(10)

    async def _files_for(sha: str):
        async with sem:
            try:
                d = await _gh_get(client, f"/repos/{owner}/{repo_name}/commits/{sha}")
            except Exception:
                return [], 2
            if not d:
                return [], 2
            files = [f.get("filename", "") for f in (d.get("files") or [])]
            return [f for f in files if f], len(d.get("parents") or [])

    results = await asyncio.gather(*[_files_for(s) for s in shas])

    file_counts: Counter = Counter()
    pair_counts: Counter = Counter()
    focus_set = set(focus)
    for files, parents in results:
        if not files or parents > 1 or len(files) > 40:
            continue
        fs = sorted(set(files))
        for f in fs:
            file_counts[f] += 1
        for i in range(len(fs)):
            for j in range(i + 1, len(fs)):
                a, b = fs[i], fs[j]
                if a in focus_set or b in focus_set:      # only pairs involving a changed file
                    pair_counts[(a, b)] += 1

    # 3. strongest untouched partner per focus file
    hanging: list[dict] = []
    seen_missing: set[tuple] = set()
    for (a, b), co in pair_counts.items():
        changed, partner = (a, b) if a in focus_set else (b, a)
        if partner in changed_set or partner in focus_set:
            continue
        denom = min(file_counts[changed], file_counts[partner]) or 1
        score = co / denom
        if co < HANGING_MIN_CO or score < HANGING_MIN_SCORE:
            continue
        key = (changed, partner)
        if key in seen_missing:
            continue
        seen_missing.add(key)
        hanging.append({"changed": changed, "missing": partner, "co_count": co, "score": round(score, 3)})

    hanging.sort(key=lambda h: (h["co_count"], h["score"]), reverse=True)
    return hanging[:8]


# ---------------------------------------------------------------------------
# Signal 3: PR-shape heuristics (always available)
# ---------------------------------------------------------------------------

def _pr_shape(changed_files: list[tuple], risk_counts: dict) -> tuple[float, list[str]]:
    cats = [c for _, c, *_ in changed_files]
    total_lines = sum(add + rem for _, _, _, add, rem in changed_files)
    has_source = "Service" in cats
    has_tests = "Test" in cats

    score = 0.0
    reasons: list[str] = []
    if has_source and not has_tests:
        score += 0.40
        reasons.append("source code changed but no tests updated")
    if total_lines > 800:
        score += 0.35
        reasons.append(f"large diff ({total_lines} lines)")
    elif total_lines > 300:
        score += 0.20
        reasons.append(f"sizable diff ({total_lines} lines)")
    if risk_counts.get("Dependencies"):
        score += 0.20
        reasons.append("dependency manifest changed")
    if risk_counts.get("Infrastructure") or risk_counts.get("Config"):
        score += 0.15
        reasons.append("infra/config changed")
    return min(1.0, score), reasons


# ---------------------------------------------------------------------------
# Ground-truth prior: existing CI check-runs on the PR head commit
# ---------------------------------------------------------------------------

async def _ci_prior(client, owner: str, repo_name: str, head_sha: str) -> dict:
    if not head_sha:
        return {"state": "none", "detail": ""}
    try:
        data = await _gh_get(client, f"/repos/{owner}/{repo_name}/commits/{head_sha}/check-runs")
    except Exception:
        return {"state": "none", "detail": ""}
    runs = (data or {}).get("check_runs") or []
    if not runs:
        return {"state": "none", "detail": ""}

    completed = [r for r in runs if r.get("status") == "completed"]
    pending = [r for r in runs if r.get("status") in ("queued", "in_progress")]
    failed = [r for r in completed if r.get("conclusion") in CI_FAIL_CONCLUSIONS]

    if failed:
        names = ", ".join(r.get("name", "?") for r in failed[:3])
        return {"state": "failed", "detail": f"{len(failed)} CI check(s) already failing: {names}"}
    if completed and not pending and not failed:
        return {"state": "passed", "detail": f"all {len(completed)} CI check(s) currently green"}
    if pending:
        return {"state": "pending", "detail": f"{len(pending)} CI check(s) still running"}
    return {"state": "none", "detail": ""}


# ---------------------------------------------------------------------------
# Narrative
# ---------------------------------------------------------------------------

async def _narrate(repo: str, pr_title: str, prob: int, verdict: str, memory_matches: list,
                   hanging: list, shape_reasons: list, risk_counts: dict, ci: dict) -> dict:
    from core import llm

    mem_str = "\n".join(
        f"  - {m['incident_id']} (similarity {m['similarity']:.0%}"
        + (f", shares files: {', '.join(m['matched_files'])}" if m.get("matched_files") else "")
        + f") — {m.get('root_cause','')[:140]}"
        for m in memory_matches
    ) or "  none"
    hang_str = "\n".join(
        f"  - changed {h['changed']} but NOT its coupled {h['missing']} "
        f"(together {h['co_count']}x, {h['score']:.0%})"
        for h in hanging
    ) or "  none"
    shape_str = "; ".join(shape_reasons) or "nothing notable"
    risk_str = ", ".join(f"{k}: {v}" for k, v in risk_counts.items()) or "none"
    ci_str = ci.get("detail") or "no CI signal yet"

    if not llm.llm_available():
        bits = []
        if ci.get("state") == "failed":
            bits.append(ci["detail"])
        if memory_matches:
            bits.append(f"resembles {memory_matches[0]['incident_id']}")
        if hanging:
            bits.append(f"{len(hanging)} coupled file(s) left unchanged")
        if shape_reasons:
            bits.append(shape_reasons[0])
        narrative = (f"{prob}% predicted failure — " + "; ".join(bits) + ".") if bits else \
                    f"{prob}% predicted failure — no strong historical risk signals found."
        must = [f"Verify {h['missing']} still passes after changing {h['changed']}" for h in hanging[:2]]
        if memory_matches and not must:
            must = [f"Re-run the suite that caught {memory_matches[0]['incident_id']}"]
        if "no tests updated" in shape_str:
            must.append("Add/adjust tests covering the changed source before merge")
        return {"narrative": narrative, "must_test": must or ["Run the full CI pipeline before merge."]}

    prompt = f"""You are a CI/CD risk analyst predicting whether a pull request will FAIL its build,
BEFORE it runs, using only historical + current signals from this repo.

Repository: {repo}
PR: {pr_title}
Computed failure probability: {prob}% -> verdict {verdict}

Signal 1 - resemblance to PAST FAILED incidents (vector memory):
{mem_str}

Signal 2 - HANGING POINTS (changed a file but omitted its historically co-changed partner):
{hang_str}

Signal 3 - PR shape risk: {shape_str}
Signal 4 - high-risk changed file classes: {risk_str}
Ground truth - current CI check state: {ci_str}

Respond ONLY with JSON (no markdown):
{{
  "narrative": "2-3 sentences: will it likely fail and WHY, citing the specific files/incidents/CI above",
  "must_test": ["specific thing to run/verify before merge", "another"]
}}"""
    text = await llm.complete(system="", user=prompt, max_tokens=500)
    if text:
        import json, re
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                out = json.loads(m.group())
                out.setdefault("narrative", "")
                out.setdefault("must_test", [])
                return out
            except Exception:
                pass
    return {"narrative": text or "", "must_test": []}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def predict_build(repo: str, pr_number: int, max_commits: int = 60) -> AsyncIterator[dict[str, Any]]:
    owner_repo = repo.strip("/").replace("https://github.com/", "")
    parts = owner_repo.split("/")
    if len(parts) < 2:
        yield {"type": "error", "message": f"Invalid repo '{repo}'. Use owner/repo format."}
        return
    owner, repo_name = parts[0], parts[1]

    async with httpx.AsyncClient() as client:
        # ── PR + changed files ────────────────────────────────────────────
        yield {"type": "step", "message": f"Fetching PR #{pr_number} from {owner}/{repo_name}…"}
        pr = await _gh_get(client, f"/repos/{owner}/{repo_name}/pulls/{pr_number}")
        if not pr:
            yield {"type": "error", "message": f"PR #{pr_number} not found in {owner}/{repo_name}."}
            return
        head_sha = (pr.get("head") or {}).get("sha", "")

        files_data: list[dict] = []
        for page in range(1, 6):
            batch = await _gh_get(client, f"/repos/{owner}/{repo_name}/pulls/{pr_number}/files",
                                  per_page=100, page=page)
            if not batch:
                break
            files_data.extend(batch)
            if len(batch) < 100:
                break
        if not files_data:
            yield {"type": "error", "message": "Could not fetch PR files."}
            return

        changed_files: list[tuple] = []
        risk_counts: dict[str, int] = {}
        services: set[str] = set()
        for f in files_data[:60]:
            fp = f.get("filename", "")
            cat, risk = _classify_file(fp)
            changed_files.append((fp, cat, risk, f.get("additions", 0), f.get("deletions", 0)))
            if cat in HIGH_RISK_CATEGORIES:
                risk_counts[cat] = risk_counts.get(cat, 0) + 1
            if cat == "Service":
                services.add(_infer_service(fp))
        changed_set = {fp for fp, *_ in changed_files}
        yield {"type": "step", "message": f"Analyzed {len(changed_files)} changed files."}

        # ── Signal 1: incident memory ─────────────────────────────────────
        yield {"type": "step", "message": "Checking incident memory for past failures like this…"}
        memory_matches = await _search_incident_memory(pr.get("title", ""), changed_files, services)

        # ── Signal 2: targeted co-change hanging points ───────────────────
        yield {"type": "step", "message": "Mining each changed file's history for hanging points…"}
        try:
            hanging = await _targeted_hanging(client, owner, repo_name, changed_files, changed_set)
        except Exception as exc:
            hanging = []
            yield {"type": "step", "message": f"Co-change unavailable ({exc}); scoring without it."}

        # ── Signal 3: PR shape ────────────────────────────────────────────
        shape_signal, shape_reasons = _pr_shape(changed_files, risk_counts)

        # ── Ground truth: CI check-runs ───────────────────────────────────
        yield {"type": "step", "message": "Reading current CI check state…"}
        ci = await _ci_prior(client, owner, repo_name, head_sha)

    # ── Blended fail score ────────────────────────────────────────────────
    mem_signal = max((m["similarity"] for m in memory_matches), default=0.0)
    if any(m.get("matched_files") for m in memory_matches):
        mem_signal = min(1.0, mem_signal + 0.15)
    hang_signal = min(1.0, len(hanging) / 3.0)
    risk_signal = min(1.0, sum(risk_counts.values()) / max(len(changed_files), 1))

    from services import prediction_store
    cal = prediction_store.calibration_factor()   # learned from past predicted-vs-actual
    base = W_MEMORY * mem_signal + W_HANGING * hang_signal + W_SHAPE * shape_signal + W_RISK * risk_signal
    prob = int(round(min(1.0, base * cal) * 100))

    # Ground-truth override
    if ci["state"] == "failed":
        prob = max(prob, 85)
    elif ci["state"] == "passed":
        prob = min(prob, 25)
    verdict = "BLOCK" if ci["state"] == "failed" else _verdict(prob)

    # ── Confidence: how much evidence actually fired ──────────────────────
    active = sum([mem_signal >= 0.35, len(hanging) > 0, shape_signal >= 0.25, sum(risk_counts.values()) > 0])
    strong_ground = ci["state"] in ("failed", "passed")
    if strong_ground or active >= 3:
        conf_label = "high"
    elif active == 2:
        conf_label = "medium"
    else:
        conf_label = "low"
    conf_score = round(min(1.0, active / 4 + (0.35 if strong_ground else 0.0)), 2)

    yield {
        "type": "signals",
        "memory": round(mem_signal, 3),
        "hanging": round(hang_signal, 3),
        "shape": round(shape_signal, 3),
        "risk": round(risk_signal, 3),
        "ci": ci,
        "hanging_points": hanging,
        "memory_matches": memory_matches,
        "shape_reasons": shape_reasons,
        "risk_counts": risk_counts,
        "confidence": conf_label,
        "confidence_score": conf_score,
    }

    # ── Record the forecast for the learning loop ─────────────────────────
    prediction_store.record_prediction(f"{owner}/{repo_name}", pr_number, head_sha,
                                       prob, verdict, conf_label)

    # ── Narrative ─────────────────────────────────────────────────────────
    yield {"type": "step", "message": "Synthesizing the forecast…"}
    narr = await _narrate(f"{owner}/{repo_name}", pr.get("title", ""), prob, verdict,
                          memory_matches, hanging, shape_reasons, risk_counts, ci)

    yield {
        "type": "result",
        "verdict": verdict,
        "probability": prob,
        "color": VERDICT_COLOR[verdict],
        "confidence": conf_label,
        "confidence_score": conf_score,
        "narrative": narr.get("narrative", ""),
        "must_test": narr.get("must_test", []),
        "hanging_points": hanging,
        "memory_matches": memory_matches,
        "shape_reasons": shape_reasons,
        "ci": ci,
        "meta": {
            "repo": f"{owner}/{repo_name}",
            "pr": pr_number,
            "pr_title": pr.get("title", ""),
            "pr_url": pr.get("html_url", ""),
            "head_sha": head_sha,
            "changed_files": len(changed_files),
            "risk_counts": risk_counts,
            "signals": {"memory": round(mem_signal, 3), "hanging": round(hang_signal, 3),
                        "shape": round(shape_signal, 3), "risk": round(risk_signal, 3)},
            "weights": {"memory": W_MEMORY, "hanging": W_HANGING, "shape": W_SHAPE, "risk": W_RISK},
        },
    }
