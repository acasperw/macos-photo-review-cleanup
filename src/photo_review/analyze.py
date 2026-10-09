import sqlite3
from datetime import datetime, timezone

import imagehash
import numpy as np
from PIL import Image, ImageOps

from .clip import MODEL_ID, Clip

STATS_SIZE = 512


def pending(conn: sqlite3.Connection, force: bool = False) -> list[sqlite3.Row]:
    sql = """
        SELECT a.uuid, a.derivative_path FROM assets a
        LEFT JOIN analysis an ON an.uuid = a.uuid
        WHERE a.derivative_path IS NOT NULL
    """
    if not force:
        sql += " AND (an.uuid IS NULL OR an.model IS NOT ?)"
        return conn.execute(sql, (MODEL_ID,)).fetchall()
    return conn.execute(sql).fetchall()


def load_image(path: str) -> Image.Image:
    with Image.open(path) as img:
        return ImageOps.exif_transpose(img).convert("RGB")


def image_stats(img: Image.Image) -> tuple[float, float]:
    """Return (brightness 0–1, sharpness as Laplacian variance at a fixed scale)."""
    gray = img.convert("L")
    gray.thumbnail((STATS_SIZE, STATS_SIZE))
    g = np.asarray(gray, dtype=np.float32)
    lap = -4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
    return float(g.mean() / 255), float(lap.var())


def analyze_batch(clip: Clip, rows: list[sqlite3.Row]) -> tuple[list[dict], list[tuple[str, str]]]:
    images, records, failed = [], [], []
    for row in rows:
        try:
            img = load_image(row["derivative_path"])
        except Exception as e:
            failed.append((row["uuid"], str(e)))
            continue
        brightness, sharpness = image_stats(img)
        images.append(img)
        records.append({
            "uuid": row["uuid"],
            "source_path": row["derivative_path"],
            "phash": str(imagehash.phash(img)),
            "brightness": brightness,
            "sharpness": sharpness,
            "model": MODEL_ID,
            "embedding": None,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        })

    if images:
        for record, emb in zip(records, clip.embed_images(images)):
            record["embedding"] = emb.astype(np.float32).tobytes()
    return records, failed


def load_embeddings(conn: sqlite3.Connection) -> tuple[list[str], np.ndarray]:
    rows = conn.execute(
        "SELECT uuid, embedding FROM analysis WHERE model = ? AND embedding IS NOT NULL", (MODEL_ID,)
    ).fetchall()
    uuids = [r["uuid"] for r in rows]
    matrix = np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows]) if rows else np.empty((0, 0))
    return uuids, matrix
