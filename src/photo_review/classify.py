import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from .analyze import load_embeddings

STORE_MIN_CONFIDENCE = 0.3

# Labels double as album names, so they must not contain "/".
CATEGORIES = {
    "duplicate": "Duplicates",
    "screenshot": "Screenshots",
    "document": "Documents & receipts",
    "forwarded": "Forwarded & web images",
    "poor_quality": "Blurry, dark & accidental",
    "low_res": "Low resolution",
    "short_video": "Short videos",
}

# Linking rules for "similar shot" clusters.
NEAR_WINDOW_S, NEAR_SIM = 10 * 60, 0.92
DAY_WINDOW_S, DAY_SIM = 24 * 3600, 0.97
PHASH_MAX_DIST = 6

PROMPTS = {
    "screenshot": [
        "a screenshot of a phone screen",
        "a screenshot of a website",
        "a screenshot of a chat conversation",
    ],
    "document": [
        "a photo of a receipt",
        "a photo of a printed document",
        "a photo of a whiteboard with writing",
        "a photo of a parking sign",
        "a photo of a form or letter",
        "a photo of a product label or barcode",
    ],
    "meme": [
        "a meme with text on an image",
        "an internet meme",
        "a cartoon or comic strip",
    ],
    "accidental": [
        "a blurry out of focus photo",
        "an accidental photo taken inside a pocket",
        "a completely black photo",
        "an accidental photo of the floor",
    ],
    "normal": [
        "a photo of people", "a portrait of a person", "a group photo of friends", "a selfie",
        "a photo of a landscape", "a photo of a city street", "a photo of a building",
        "a photo of a pet", "a photo of an animal", "a photo of food", "a photo of a concert",
        "a photo of a room interior", "a photo of a car", "a photo of plants or flowers",
        "a photo of the sky", "a photo of a beach or the sea", "a photo of children playing",
        "a photo of a party", "a photo at night", "a photo of sports", "a photo of a cake",
    ],
}

WEB_BUNDLES = {
    "com.reddit.Reddit", "com.apple.mobilesafari", "com.apple.SafariViewService",
    "com.openai.chat", "com.google.gemini", "com.burbn.instagram", "com.atebits.Tweetie2",
    "com.pinterest", "com.zhiliaoapp.musically", "com.google.chrome.ios", "com.facebook.Facebook",
}
MESSAGING_BUNDLES = {
    "net.whatsapp.WhatsApp", "org.whispersystems.signal", "ph.telegra.Telegraph",
    "com.apple.MobileSMS", "com.facebook.Messenger",
}

SCREENSHOT_CAPTION = re.compile(r"\bscreen ?shot\b", re.I)
DOCUMENT_CAPTION = re.compile(
    r"\b(receipt|invoice|document|letter|form|piece of paper|paper with|menu|whiteboard|"
    r"ticket|barcode|qr code|label|parking|sign with)\b", re.I)
MEME_CAPTION = re.compile(r"\b(meme|cartoon|comic|text that says|with the words)\b", re.I)
DOCUMENT_LABELS = {"Document", "Receipt", "Handwriting", "Whiteboard", "Paper", "Barcode", "QR Code"}


@dataclass
class Asset:
    uuid: str
    idx: int  # row in embedding matrix
    ts: float
    kind: str
    filename: str
    favorite: bool
    user_edited: bool
    named: list[str]
    screenshot: bool
    screen_recording: bool
    portrait: bool
    bundle: str | None
    app: str | None
    camera_make: str | None
    labels: set[str]
    caption: str
    overall: float
    failure: float
    brightness: float
    sharpness: float
    pixels: int
    filesize: int
    duration: float | None
    phash: int
    clip: dict[str, float] = field(default_factory=dict)

    @property
    def protected(self) -> bool:
        return self.favorite or self.user_edited


def load_assets(conn: sqlite3.Connection) -> tuple[list[Asset], np.ndarray]:
    uuids, emb = load_embeddings(conn)
    index = {u: i for i, u in enumerate(uuids)}
    rows = conn.execute(
        "SELECT a.*, an.phash, an.brightness, an.sharpness FROM assets a JOIN analysis an USING(uuid)"
    ).fetchall()
    assets = []
    for r in rows:
        if r["uuid"] not in index:
            continue
        scores = json.loads(r["scores"]) if r["scores"] else {}
        assets.append(Asset(
            uuid=r["uuid"], idx=index[r["uuid"]],
            ts=datetime.fromisoformat(r["date"]).timestamp(),
            kind=r["kind"], filename=r["original_filename"],
            favorite=bool(r["favorite"]), user_edited=bool(r["user_edited"]),
            named=json.loads(r["named_persons"]),
            screenshot=bool(r["screenshot"]), screen_recording=bool(r["screen_recording"]),
            portrait=bool(r["portrait"]),
            bundle=r["imported_by_bundle"], app=(r["imported_by_app"] or "").strip("\u200e") or None,
            camera_make=r["camera_make"],
            labels=set(json.loads(r["labels"] or "[]")),
            caption=r["ai_caption"] or "",
            overall=scores.get("overall") or 0.0, failure=scores.get("failure") or 0.0,
            brightness=r["brightness"], sharpness=r["sharpness"],
            pixels=(r["width"] or 0) * (r["height"] or 0), filesize=r["filesize"] or 0,
            duration=r["duration"], phash=int(r["phash"], 16),
        ))
    assets.sort(key=lambda a: a.ts)
    return assets, emb


def clip_category_probs(assets: list[Asset], emb: np.ndarray) -> None:
    from .clip import Clip

    labels, texts = zip(*[(cat, t) for cat, ts in PROMPTS.items() for t in ts])
    text_emb = Clip().embed_texts(list(texts))
    logits = 100 * emb @ text_emb.T
    probs = np.exp(logits - logits.max(axis=1, keepdims=True))
    probs /= probs.sum(axis=1, keepdims=True)
    for a in assets:
        p = probs[a.idx]
        a.clip = {cat: float(sum(p[i] for i, c in enumerate(labels) if c == cat)) for cat in PROMPTS}


# --- similar-shot clusters -------------------------------------------------

def find_clusters(assets: list[Asset], emb: np.ndarray) -> list[list[Asset]]:
    n = len(assets)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    times = np.array([a.ts for a in assets])
    kinds = np.array([a.kind for a in assets])
    hashes = np.array([a.phash for a in assets], dtype=np.uint64)
    E = emb[[a.idx for a in assets]]

    for i in range(n):
        end = np.searchsorted(times, times[i] + DAY_WINDOW_S, side="right")
        js = np.arange(i + 1, end)
        js = js[kinds[js] == kinds[i]]
        if not len(js):
            continue
        sims = E[js] @ E[i]
        dt = times[js] - times[i]
        dist = np.bitwise_count(hashes[js] ^ hashes[i])
        link = ((sims >= NEAR_SIM) & (dt <= NEAR_WINDOW_S)) | (sims >= DAY_SIM) | (dist <= PHASH_MAX_DIST)
        for j in js[link]:
            parent[find(int(j))] = find(i)

    # Exact visual copies anywhere in the scanned range.
    by_hash: dict[tuple[str, int], int] = {}
    for i, a in enumerate(assets):
        first = by_hash.setdefault((a.kind, a.phash), i)
        if first != i:
            parent[find(i)] = find(first)

    groups = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(assets[i])
    return [g for g in groups.values() if len(g) > 1]


def keeper_key(a: Asset) -> tuple:
    return (a.favorite, a.user_edited, bool(a.named), a.overall, a.sharpness, a.pixels, a.filesize)


KEY_REASONS = ("keeper is a favorite", "keeper has your edit", "keeper has named people", None,
               "keeper is sharper", "keeper has higher resolution", "keeper is a larger file")


def keeper_reason(keeper: Asset, other: Asset) -> str:
    for reason, k, o in zip(KEY_REASONS, keeper_key(keeper), keeper_key(other)):
        if k != o:
            return reason or f"keeper has higher Apple score ({k:.2f} vs {o:.2f})"
    return "tie; kept earliest"


def _fmt_dt(seconds: float) -> str:
    seconds = abs(seconds)
    if seconds < 60:
        return f"{seconds:.0f}s apart"
    if seconds < 3600:
        return f"{seconds / 60:.0f} min apart"
    return f"{seconds / 3600:.1f} h apart"


# --- junk signals ----------------------------------------------------------

def _noisy_or(signals: list[tuple[float, str]]) -> float:
    p = 1.0
    for s, _ in signals:
        p *= 1 - s
    return 1 - p


def _clip_signal(signals: list, prob: float, label: str, min_prob: float = 0.4, weight: float = 0.6) -> None:
    if prob >= min_prob:
        signals.append((weight * prob, f"CLIP: {label} ({prob:.2f})"))


def _caption(a: Asset) -> str:
    return f"caption: “{a.caption[:70]}”"


def junk_signals(a: Asset) -> dict[str, list[tuple[float, str]]]:
    out: dict[str, list[tuple[float, str]]] = defaultdict(list)

    s = out["screenshot"]
    if a.screenshot:
        s.append((0.95, "Apple: screenshot"))
    if a.screen_recording:
        s.append((0.9, "Apple: screen recording"))
    if SCREENSHOT_CAPTION.search(a.caption):
        s.append((0.7, _caption(a)))
    if "Screenshot" in a.labels:
        s.append((0.6, "Apple label: Screenshot"))
    _clip_signal(s, a.clip.get("screenshot", 0), "looks like a screenshot", min_prob=0.5)

    d = out["document"]
    if found := a.labels & DOCUMENT_LABELS:
        d.append((0.45, f"Apple label: {', '.join(sorted(found))}"))
    if DOCUMENT_CAPTION.search(a.caption):
        d.append((0.5, _caption(a)))
    _clip_signal(d, a.clip.get("document", 0), "receipt/document/sign", weight=0.7)

    f = out["forwarded"]
    if a.bundle in WEB_BUNDLES:
        f.append((0.55, f"saved from {a.app or a.bundle}"))
    elif a.bundle in MESSAGING_BUNDLES:
        f.append((0.3, f"received via {a.app or a.bundle}"))
    if not a.camera_make and not a.screenshot and a.kind == "photo":
        f.append((0.2, "no camera info"))
    if MEME_CAPTION.search(a.caption):
        f.append((0.5, _caption(a)))
    _clip_signal(f, a.clip.get("meme", 0), "meme/cartoon")

    if a.kind == "photo":
        q = out["poor_quality"]
        if a.brightness < 0.04:
            q.append((0.7, f"very dark (brightness {a.brightness:.2f})"))
        elif a.brightness < 0.08:
            q.append((0.45, f"dark (brightness {a.brightness:.2f})"))
        if not a.portrait and not a.screenshot:
            if a.sharpness < 60:
                q.append((0.55, f"very blurry (sharpness {a.sharpness:.0f})"))
            elif a.sharpness < 120:
                q.append((0.3, f"soft focus (sharpness {a.sharpness:.0f})"))
        if a.failure <= -0.1:
            q.append((0.35, f"Apple failure score {a.failure:.2f}"))
        if 0 < a.overall < 0.15:
            q.append((0.3, f"low Apple score {a.overall:.2f}"))
        _clip_signal(q, a.clip.get("accidental", 0), "blurry/accidental")

        if not a.screenshot and 0 < a.pixels < 1_000_000:
            out["low_res"].append((0.75 if a.pixels < 300_000 else 0.55, f"{a.pixels / 1e6:.2f} MP"))

    if a.kind == "video" and a.duration is not None and not a.screen_recording:
        if a.duration < 1.5:
            out["short_video"].append((0.8, f"{a.duration:.1f}s long"))
        elif a.duration < 3:
            out["short_video"].append((0.6, f"{a.duration:.1f}s long"))

    return out


# --- main entry ------------------------------------------------------------

def classify(conn: sqlite3.Connection) -> dict:
    assets, emb = load_assets(conn)
    if not assets:
        return {"assets": 0}
    clip_category_probs(assets, emb)

    cluster_rows, flag_rows = [], []
    clusters = find_clusters(assets, emb)
    for cid, group in enumerate(clusters, start=1):
        keeper = max(group, key=keeper_key)
        for a in group:
            sim = float(emb[a.idx] @ emb[keeper.idx])
            cluster_rows.append((a.uuid, cid, int(a is keeper), sim))
            if a is keeper or a.protected:
                continue
            reason = (f"similar to {keeper.filename} ({sim:.2f}, {_fmt_dt(a.ts - keeper.ts)}); "
                      f"{keeper_reason(keeper, a)}")
            flag_rows.append((a.uuid, "duplicate", sim, reason))

    for a in assets:
        if a.protected or a.named:
            continue
        for category, signals in junk_signals(a).items():
            conf = _noisy_or(signals)
            if conf >= STORE_MIN_CONFIDENCE:
                flag_rows.append((a.uuid, category, conf, "; ".join(r for _, r in signals)))

    with conn:
        conn.execute("DELETE FROM clusters")
        conn.execute("DELETE FROM flags")
        conn.executemany("INSERT INTO clusters VALUES (?, ?, ?, ?)", cluster_rows)
        conn.executemany("INSERT INTO flags VALUES (?, ?, ?, ?)", flag_rows)

    return {"assets": len(assets), "clusters": len(clusters), "clustered": len(cluster_rows)}
