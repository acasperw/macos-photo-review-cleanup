import json
import sqlite3
import statistics
from collections import Counter

import click


def _pct(n: int, total: int) -> str:
    return f"{n:>7,}  ({n / total:5.1%})" if total else f"{n:>7,}"


def _section(title: str) -> None:
    click.echo()
    click.secho(title, bold=True)


def print_flag_summary(conn: sqlite3.Connection, min_confidence: float, examples: int) -> None:
    total = conn.execute("SELECT COUNT(*) FROM analysis").fetchone()[0]
    counts = conn.execute(
        "SELECT category, COUNT(*) n FROM flags WHERE confidence >= ? GROUP BY category ORDER BY n DESC",
        (min_confidence,),
    ).fetchall()
    flagged = conn.execute(
        "SELECT COUNT(DISTINCT uuid) FROM flags WHERE confidence >= ?", (min_confidence,)
    ).fetchone()[0]

    _section(f"Flagged (confidence ≥ {min_confidence})")
    for row in counts:
        click.echo(f"  {row['category']:<14}{_pct(row['n'], total)}")
    click.echo(f"  {'any':<14}{_pct(flagged, total)}")

    for row in counts:
        _section(f"{row['category']} — examples")
        for ex in conn.execute(
            """SELECT a.original_filename, a.date, f.confidence, f.reason FROM flags f
               JOIN assets a USING(uuid) WHERE f.category = ? AND f.confidence >= ?
               ORDER BY RANDOM() LIMIT ?""",
            (row["category"], min_confidence, examples),
        ):
            click.echo(f"  {ex['confidence']:.2f}  {ex['date'][:10]}  {ex['original_filename']}")
            click.echo(f"        {ex['reason']}")


def print_report(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT * FROM assets ORDER BY date").fetchall()
    total = len(rows)
    if not total:
        click.echo("No assets scanned yet. Run `photo-review scan` first.")
        return

    photos = [r for r in rows if r["kind"] == "photo"]
    videos = [r for r in rows if r["kind"] == "video"]

    _section("Overview")
    click.echo(f"  assets          {total:>7,}   ({rows[0]['date'][:10]} → {rows[-1]['date'][:10]})")
    click.echo(f"  photos          {_pct(len(photos), total)}")
    click.echo(f"  videos          {_pct(len(videos), total)}")

    _section("Storage")
    click.echo(f"  original local  {_pct(sum(not r['is_missing'] for r in rows), total)}")
    click.echo(f"  iCloud only     {_pct(sum(r['is_missing'] for r in rows), total)}")
    click.echo(f"  has preview     {_pct(sum(bool(r['derivative_path']) for r in rows), total)}")
    sizes = [r["filesize"] for r in rows if r["filesize"]]
    click.echo(f"  total size      {sum(sizes) / 1e9:>7.1f} GB")

    _section("Flags")
    for col in ("favorite", "hidden", "screenshot", "screen_recording", "burst",
                "burst_selected", "live_photo", "selfie", "portrait", "shared", "syndicated"):
        click.echo(f"  {col:<16}{_pct(sum(r[col] for r in rows), total)}")

    _section("Edits (by editor)")
    click.echo(f"  has adjustments {_pct(sum(r['has_adjustments'] for r in rows), total)}")
    click.echo(f"  → user edited   {_pct(sum(r['user_edited'] for r in rows), total)}")
    editors = Counter(
        (r["adjustment_editor"], r["adjustment_format_id"]) for r in rows if r["has_adjustments"]
    )
    for (editor, fmt), n in editors.most_common(15):
        click.echo(f"    {n:>6,}  editor={editor}  format={fmt}")

    _section("Imported by")
    for (app, bundle), n in Counter(
        (r["imported_by_app"], r["imported_by_bundle"]) for r in rows
    ).most_common(15):
        click.echo(f"  {n:>7,}  {app} ({bundle})")
    click.echo(f"  no camera make  {_pct(sum(not r['camera_make'] for r in photos), len(photos))}  (photos)")

    _section("People")
    click.echo(f"  named people    {_pct(sum(r['named_persons'] != '[]' for r in rows), total)}")
    click.echo(f"  unnamed faces   {_pct(sum(bool(r['unnamed_faces']) for r in rows), total)}")

    _section("Apple scores (photos)")
    score_rows = [json.loads(r["scores"]) for r in photos if r["scores"]]
    click.echo(f"  photos with scores {_pct(len(score_rows), len(photos))}")
    if score_rows:
        click.echo(f"  {'field':<28}{'non-zero':>10}{'min':>8}{'median':>8}{'max':>8}")
        for field in score_rows[0]:
            vals = [s[field] for s in score_rows if s.get(field) is not None]
            nonzero = sum(1 for v in vals if v)
            if not vals:
                continue
            click.echo(
                f"  {field:<28}{nonzero / len(score_rows):>10.1%}"
                f"{min(vals):>8.3f}{statistics.median(vals):>8.3f}{max(vals):>8.3f}"
            )

    _section("Apple labels (top 40)")
    labels = Counter(label for r in rows for label in json.loads(r["labels"] or "[]"))
    click.echo(f"  assets with labels {_pct(sum(r['labels'] not in (None, '[]') for r in rows), total)}")
    for label, n in labels.most_common(40):
        click.echo(f"  {n:>7,}  {label}")

    _section("Apple AI captions")
    captions = [r["ai_caption"] for r in rows if r["ai_caption"]]
    click.echo(f"  with caption    {_pct(len(captions), total)}")
    for c in captions[:: max(1, len(captions) // 5)][:5]:
        click.echo(f"    “{c}”")

    _section("Size / duration")
    small = sum(1 for r in photos if r["width"] and r["height"] and r["width"] * r["height"] < 1_000_000)
    click.echo(f"  photos < 1 MP   {_pct(small, len(photos))}")
    durations = [r["duration"] for r in videos if r["duration"] is not None]
    if videos:
        click.echo(f"  videos < 3 s    {_pct(sum(d < 3 for d in durations), len(videos))}")
        click.echo(f"  videos 3–10 s   {_pct(sum(3 <= d < 10 for d in durations), len(videos))}")
        click.echo(f"  videos ≥ 10 s   {_pct(sum(d >= 10 for d in durations), len(videos))}")
        click.echo(f"  no duration     {_pct(len(videos) - len(durations), len(videos))}")

    _section("Analysis")
    stats = conn.execute("SELECT brightness, sharpness FROM analysis").fetchall()
    click.echo(f"  analyzed        {_pct(len(stats), total)}")
    if stats:
        for col in ("brightness", "sharpness"):
            vals = sorted(s[col] for s in stats)
            p = lambda q: vals[min(len(vals) - 1, int(q * len(vals)))]
            click.echo(f"  {col:<16}p5={p(0.05):.3f}  p25={p(0.25):.3f}  median={p(0.5):.3f}  p95={p(0.95):.3f}")
