import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import db
from .analyze import load_image
from .classify import CATEGORIES

STATIC = Path(__file__).parent / "web"
THUMB_SIZE = 480

ITEM_COLS = """
    a.uuid, a.original_filename, a.date, a.kind, a.duration, a.favorite, a.user_edited,
    a.named_persons, a.ai_caption, a.scores, a.width, a.height, an.sharpness
"""


class Decision(BaseModel):
    uuid: str
    category: str
    decision: Literal["remove", "keep"] | None


class DecisionBatch(BaseModel):
    items: list[Decision]


def _item(row) -> dict:
    scores = json.loads(row["scores"]) if row["scores"] else {}
    pixels = (row["width"] or 0) * (row["height"] or 0)
    return {
        "uuid": row["uuid"],
        "filename": row["original_filename"],
        "date": row["date"][:16].replace("T", " "),
        "kind": row["kind"],
        "duration": row["duration"],
        "favorite": bool(row["favorite"]),
        "user_edited": bool(row["user_edited"]),
        "named": json.loads(row["named_persons"] or "[]"),
        "caption": row["ai_caption"],
        "score": scores.get("overall"),
        "sharpness": row["sharpness"],
        "mp": round(pixels / 1e6, 1),
    }


def create_app(db_path: Path) -> FastAPI:
    app = FastAPI(title="Photo Review")
    thumbs_dir = db_path.parent / "thumbs"
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    def derivative_path(uuid: str) -> tuple[str, str]:
        row = db.connect(db_path).execute(
            "SELECT uuid, derivative_path FROM assets WHERE uuid = ?", (uuid,)
        ).fetchone()
        if not row or not row["derivative_path"] or not Path(row["derivative_path"]).is_file():
            raise HTTPException(404)
        return row["uuid"], row["derivative_path"]

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/thumb/{uuid}")
    def thumb(uuid: str):
        uuid, src = derivative_path(uuid)
        dest = thumbs_dir / f"{uuid}.jpg"
        if not dest.exists():
            img = load_image(src)
            img.thumbnail((THUMB_SIZE, THUMB_SIZE))
            tmp = dest.with_suffix(f".{threading.get_ident()}.tmp")
            img.save(tmp, "JPEG", quality=85)
            tmp.replace(dest)
        return FileResponse(dest, headers={"Cache-Control": "max-age=86400"})

    @app.get("/full/{uuid}")
    def full(uuid: str):
        return FileResponse(derivative_path(uuid)[1])

    @app.get("/api/summary")
    def summary(min_confidence: float = 0.5):
        conn = db.connect(db_path)
        out = []
        for key, label in CATEGORIES.items():
            threshold = 0 if key == "duplicate" else min_confidence
            flagged, pending = conn.execute(
                """SELECT COUNT(*), SUM(d.uuid IS NULL) FROM flags f
                   LEFT JOIN decisions d ON d.uuid = f.uuid AND d.category = f.category
                   WHERE f.category = ? AND f.confidence >= ?""",
                (key, threshold),
            ).fetchone()
            counts = dict(conn.execute(
                "SELECT decision, COUNT(*) FROM decisions WHERE category = ? GROUP BY decision", (key,)
            ).fetchall())
            out.append({"key": key, "label": label, "flagged": flagged, "pending": pending or 0,
                        "remove": counts.get("remove", 0), "keep": counts.get("keep", 0)})
        remove_unique, not_applied = conn.execute(
            """SELECT COUNT(DISTINCT uuid), COUNT(DISTINCT CASE WHEN applied_at IS NULL THEN uuid END)
               FROM decisions WHERE decision = 'remove'"""
        ).fetchone()
        return {"categories": out, "remove_unique": remove_unique, "not_applied": not_applied}

    @app.get("/api/clusters")
    def clusters():
        rows = db.connect(db_path).execute(
            f"""SELECT c.cluster_id, c.is_keeper, c.similarity, f.confidence, f.reason, d.decision, {ITEM_COLS}
                FROM clusters c JOIN assets a USING(uuid) LEFT JOIN analysis an USING(uuid)
                LEFT JOIN flags f ON f.uuid = c.uuid AND f.category = 'duplicate'
                LEFT JOIN decisions d ON d.uuid = c.uuid AND d.category = 'duplicate'
                ORDER BY a.date"""
        ).fetchall()
        groups: dict[int, list] = {}
        for r in rows:
            groups.setdefault(r["cluster_id"], []).append({
                **_item(r),
                "is_keeper": bool(r["is_keeper"]),
                "similarity": r["similarity"],
                "confidence": r["confidence"],
                "reason": r["reason"],
                "suggested": "remove" if r["confidence"] is not None else "keep",
                "decision": r["decision"],
            })
        return {"clusters": [{"id": cid, "members": m} for cid, m in groups.items()]}

    @app.get("/api/flags/{category}")
    def flags(category: str, min_confidence: float = 0.5):
        if category not in CATEGORIES or category == "duplicate":
            raise HTTPException(404)
        rows = db.connect(db_path).execute(
            f"""SELECT f.confidence, f.reason, d.decision, {ITEM_COLS}
                FROM flags f JOIN assets a USING(uuid) LEFT JOIN analysis an USING(uuid)
                LEFT JOIN decisions d ON d.uuid = f.uuid AND d.category = f.category
                WHERE f.category = ? AND (f.confidence >= ? OR d.decision IS NOT NULL)
                ORDER BY f.confidence DESC, a.date""",
            (category, min_confidence),
        ).fetchall()
        return {"items": [
            {**_item(r), "confidence": r["confidence"], "reason": r["reason"], "decision": r["decision"]}
            for r in rows
        ]}

    @app.post("/api/decisions")
    def decide(batch: DecisionBatch):
        conn = db.connect(db_path)
        now = datetime.now(timezone.utc).isoformat()
        with conn:
            for d in batch.items:
                if d.category not in CATEGORIES:
                    raise HTTPException(400, f"Unknown category {d.category}")
                if d.decision is None:
                    conn.execute("DELETE FROM decisions WHERE uuid = ? AND category = ?", (d.uuid, d.category))
                    continue
                conn.execute(
                    """INSERT INTO decisions (uuid, category, decision, decided_at)
                       SELECT uuid, ?, ?, ? FROM assets WHERE uuid = ?
                       ON CONFLICT(uuid, category) DO UPDATE SET
                         decision = excluded.decision,
                         decided_at = excluded.decided_at,
                         applied_at = CASE WHEN decisions.decision = excluded.decision
                                           THEN decisions.applied_at END""",
                    (d.category, d.decision, now, d.uuid),
                )
        return {"ok": True}

    return app
