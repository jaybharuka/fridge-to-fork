"""
Fridge to Fork — Web App Backend
=================================
FastAPI server with real-time SSE streaming.

Run:
    uvicorn app:app --host 0.0.0.0 --port 8000 --reload

Then open on your phone:
    http://<your-pc-ip>:8000
"""

import asyncio
import json
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse

load_dotenv()

from fridge_to_fork.step1_fridge_vision import identify_ingredients
from fridge_to_fork.step2_meal_planner import plan_meals
from fridge_to_fork.step3_order_router import route_order

app = FastAPI(title="Fridge to Fork", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


@app.get("/", response_class=HTMLResponse)
async def index():
    return (Path(__file__).parent / "templates" / "index.html").read_text(encoding="utf-8")


@app.get("/health")
async def health():
    return {"status": "ok", "api_key_set": bool(os.environ.get("GOOGLE_API_KEY"))}


@app.post("/api/scan")
async def scan(
    file: UploadFile = File(...),
    target_dish: str | None = Form(None)
):
    img_bytes = await file.read()
    suffix = Path(file.filename or "image.jpg").suffix or ".jpg"
    delivery_address = os.environ.get("DELIVERY_ADDRESS", "Mumbai, India")

    async def stream():
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(img_bytes)
                tmp_path = tmp.name

            # ── Step 1: Vision ──────────────────────────────────────────────
            yield _sse({"type": "progress", "step": 1, "message": "Scanning your fridge with AI vision…"})
            fridge = await asyncio.to_thread(identify_ingredients, tmp_path)
            yield _sse({
                "type": "step1",
                "raw_description": fridge.raw_description,
                "ingredients": [
                    {
                        "name": i.name,
                        "quantity": i.quantity or "—",
                        "confidence": round(i.confidence * 100),
                    }
                    for i in sorted(fridge.ingredients, key=lambda x: -x.confidence)
                ],
            })

            # ── Step 2: Meal planning ───────────────────────────────────────
            if target_dish:
                yield _sse({"type": "progress", "step": 2, "message": f"Evaluating '{target_dish}'…"})
            else:
                yield _sse({"type": "progress", "step": 2, "message": "Planning your meals…"})
                
            plan = await asyncio.to_thread(plan_meals, fridge, target_dish=target_dish)
            yield _sse({
                "type": "step2",
                "decision": plan.decision.value,
                "recommended_meal": plan.recommended_meal.name if plan.recommended_meal else None,
                "reasoning": plan.reasoning,
                "suggestions": [
                    {
                        "name": s.name,
                        "description": s.description,
                        "cuisine": s.cuisine,
                        "can_cook_now": s.can_cook_now,
                        "missing_ingredients": s.missing_ingredients,
                        "prep_time_minutes": s.prep_time_minutes,
                    }
                    for s in plan.suggestions
                ],
            })

            # ── Step 3: Order routing ───────────────────────────────────────
            yield _sse({"type": "progress", "step": 3, "message": "Routing your order…"})
            result = await route_order(plan, delivery_address, dry_run=True)
            yield _sse({
                "type": "step3",
                "decision": plan.decision.value,
                "placed": bool(result and result.success),
                "order_id": result.order_id if result else None,
                "platform": result.platform if result else None,
                "items": result.items if result else [],
                "eta_minutes": result.estimated_minutes if result else None,
            })

            yield _sse({"type": "complete"})

        except Exception as exc:
            yield _sse({"type": "error", "message": str(exc)})
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
