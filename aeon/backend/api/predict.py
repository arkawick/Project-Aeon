from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from typing import Any
import json
import os
import asyncio

from services.predict_service import predict_build
from services import prediction_store
from core.instances import github

router = APIRouter(prefix="/predict", tags=["predict"])


async def _run_forecast(repo: str, pr: int) -> dict[str, Any]:
    """Drain the SSE generator into the final result dict."""
    result: dict = {}
    async for ev in predict_build(repo, pr):
        if ev.get("type") == "result":
            result = ev
        elif ev.get("type") == "error":
            return {"error": ev.get("message", "forecast failed")}
    return result


def _comment_markdown(repo: str, pr: int, r: dict) -> str:
    icon = {"BLOCK": "🔴", "CAUTION": "🟠", "PASS": "🟢"}.get(r.get("verdict"), "⚪")
    lines = [
        f"## {icon} Aeon Merge Gate — **{r.get('verdict')}** · {r.get('probability')}% fail risk "
        f"({r.get('confidence')} confidence)",
        "",
        r.get("narrative", ""),
    ]
    if r.get("ci", {}).get("detail"):
        lines += ["", f"**CI now:** {r['ci']['detail']}"]
    if r.get("hanging_points"):
        lines += ["", "**Hanging points:**"]
        lines += [f"- changed `{h['changed']}` but not coupled `{h['missing']}` "
                  f"({h['co_count']}× together, {int(h['score']*100)}%)" for h in r["hanging_points"][:5]]
    if r.get("must_test"):
        lines += ["", "**Run before merge:**"]
        lines += [f"- [ ] {t}" for t in r["must_test"][:5]]
    lines += ["", "_Forecast by Aeon from this repo's history + live CI — a risk aid, not a guarantee._"]
    return "\n".join(lines)


@router.get("/stream")
async def predict_stream(
    repo:    str = Query(...),
    pr:      int = Query(..., ge=1),
    commits: int = Query(60, ge=10, le=200),
):
    """SSE stream — progress steps, a signals event, then the final verdict."""
    async def generate():
        try:
            async for event in predict_build(repo, pr, max_commits=commits):
                yield f"data: {json.dumps(event)}\n\n"
                await asyncio.sleep(0)
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/stats")
async def predict_stats():
    """Learning-loop scoreboard: accuracy, Brier, calibration, recent outcomes."""
    return prediction_store.stats()


@router.post("/post")
async def predict_post(repo: str = Query(...), pr: int = Query(..., ge=1),
                       comment: bool = Query(True), status: bool = Query(True)):
    """Human-in-the-loop: forecast and post the verdict to the PR (comment + commit status).
    Requires a write-scoped GITHUB_TOKEN and that YOU have write access to the repo."""
    r = await _run_forecast(repo, pr)
    if not r or r.get("error"):
        return {"posted": False, "error": r.get("error", "no result")}

    out: dict[str, Any] = {"verdict": r.get("verdict"), "probability": r.get("probability")}
    if comment:
        out["comment"] = await github.post_pr_comment(repo, pr, _comment_markdown(repo, pr, r))
    if status:
        sha = (r.get("meta") or {}).get("head_sha") or r.get("head_sha") or ""
        state = {"BLOCK": "failure", "CAUTION": "pending", "PASS": "success"}.get(r.get("verdict"), "pending")
        if sha:
            out["status"] = await github.set_commit_status(
                repo, sha, state, f"{r.get('verdict')} — {r.get('probability')}% fail risk")
    return out


@router.post("/webhook")
async def predict_webhook(request: Request):
    """GitHub PR webhook receiver — forecasts every opened/updated PR automatically
    (which also records it into the learning loop). Posts back only when
    PREDICT_AUTO_POST=true (safe default: record only, no outward writes)."""
    payload = await request.json()
    action = payload.get("action", "")
    if action not in ("opened", "synchronize", "reopened"):
        return {"skipped": True, "reason": f"action '{action}' ignored"}
    pr_obj = payload.get("pull_request") or {}
    repo = (payload.get("repository") or {}).get("full_name", "")
    pr = pr_obj.get("number")
    if not repo or not pr:
        return {"skipped": True, "reason": "missing repo/pr"}

    r = await _run_forecast(repo, pr)
    if not r or r.get("error"):
        return {"forecast": False, "error": r.get("error", "no result")}

    result = {"repo": repo, "pr": pr, "verdict": r.get("verdict"), "probability": r.get("probability")}
    if os.getenv("PREDICT_AUTO_POST", "").strip().lower() in ("1", "true", "yes"):
        result["comment"] = await github.post_pr_comment(repo, pr, _comment_markdown(repo, pr, r))
    return result
