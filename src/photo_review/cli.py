from datetime import datetime, timedelta
from itertools import batched
from pathlib import Path

import click

from . import db
from .report import print_flag_summary, print_report
from .scan import load_photos, to_record

BATCH_SIZE = 500
IMAGE_BATCH_SIZE = 32


@click.group()
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=db.DEFAULT_DB,
              show_default=True, help="SQLite cache file.")
@click.pass_context
def cli(ctx: click.Context, db_path: Path) -> None:
    """Review and streamline an Apple Photos library."""
    ctx.obj = db_path


@cli.command()
@click.option("--from", "from_date", type=click.DateTime(["%Y-%m-%d"]),
              default=lambda: (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d"),
              show_default="1 year ago", help="Start date (inclusive).")
@click.option("--to", "to_date", type=click.DateTime(["%Y-%m-%d"]), default=None,
              help="End date (exclusive). Defaults to now.")
@click.option("--library", type=click.Path(exists=True), default=None,
              help="Path to a .photoslibrary. Defaults to the system library.")
@click.pass_obj
def scan(db_path: Path, from_date: datetime, to_date: datetime | None, library: str | None) -> None:
    """Read photo/video metadata (incl. Apple scores) into the local cache."""
    click.echo("Loading Photos library (this can take a minute)…")
    photos = load_photos(library, from_date, to_date)
    click.echo(f"Found {len(photos):,} assets from {from_date:%Y-%m-%d}"
               f"{f' to {to_date:%Y-%m-%d}' if to_date else ''}.")

    conn = db.connect(db_path)
    batch, failed = [], []
    with click.progressbar(photos, label="Scanning") as bar:
        for photo in bar:
            try:
                batch.append(to_record(photo))
            except Exception as e:
                failed.append((photo.uuid, e))
            if len(batch) >= BATCH_SIZE:
                db.upsert(conn, "assets", batch)
                batch = []
    db.upsert(conn, "assets", batch)

    click.echo(f"Saved {len(photos) - len(failed):,} assets to {db_path}.")
    gone = db.prune_missing(conn, {p.uuid for p in photos}, from_date, to_date)
    if gone:
        for uuid in gone:
            (db_path.parent / "thumbs" / f"{uuid}.jpg").unlink(missing_ok=True)
        click.echo(f"Removed {len(gone):,} assets that are no longer in Photos (deleted).")
    for uuid, e in failed[:10]:
        click.secho(f"  failed {uuid}: {e}", fg="yellow")
    if len(failed) > 10:
        click.secho(f"  …and {len(failed) - 10} more failures", fg="yellow")


@cli.command()
@click.option("--force", is_flag=True, help="Re-analyze assets that were already analyzed.")
@click.pass_obj
def analyze(db_path: Path, force: bool) -> None:
    """Compute perceptual hashes, brightness/sharpness and CLIP embeddings from previews."""
    from .analyze import analyze_batch, pending
    from .clip import Clip

    conn = db.connect(db_path)
    todo = pending(conn, force)
    if not todo:
        click.echo("Nothing to analyze.")
        return

    click.echo(f"Analyzing {len(todo):,} assets. Loading CLIP model (first run downloads it)…")
    clip = Clip()
    failed = []
    with click.progressbar(length=len(todo), label=f"Analyzing on {clip.device}") as bar:
        for chunk in batched(todo, IMAGE_BATCH_SIZE):
            records, chunk_failed = analyze_batch(clip, list(chunk))
            db.upsert(conn, "analysis", records)
            failed.extend(chunk_failed)
            bar.update(len(chunk))

    click.echo(f"Analyzed {len(todo) - len(failed):,} assets.")
    for uuid, e in failed[:10]:
        click.secho(f"  failed {uuid}: {e}", fg="yellow")


@cli.command()
@click.option("--min-confidence", default=0.5, show_default=True, help="Threshold for the summary.")
@click.option("--examples", default=4, show_default=True, help="Examples to show per category.")
@click.pass_obj
def classify(db_path: Path, min_confidence: float, examples: int) -> None:
    """Group similar shots, pick keepers and flag likely junk."""
    from .classify import classify as run_classify

    conn = db.connect(db_path)
    click.echo("Classifying…")
    result = run_classify(conn)
    if not result["assets"]:
        click.echo("Nothing analyzed yet. Run `photo-review analyze` first.")
        return
    click.echo(f"{result['clusters']:,} similar-shot groups covering {result['clustered']:,} assets.")
    print_flag_summary(conn, min_confidence, examples)


@cli.command()
@click.option("--port", default=8765, show_default=True)
@click.option("--no-browser", is_flag=True, help="Don't open the browser automatically.")
@click.pass_obj
def review(db_path: Path, port: int, no_browser: bool) -> None:
    """Open the local review web UI."""
    import threading
    import webbrowser

    import uvicorn

    from .webapp import create_app

    url = f"http://127.0.0.1:{port}"
    click.echo(f"Review UI at {url} (Ctrl+C to stop)")
    if not no_browser:
        threading.Timer(1.0, webbrowser.open, [url]).start()
    uvicorn.run(create_app(db_path), host="127.0.0.1", port=port, log_level="warning")


@cli.command()
@click.option("--yes", is_flag=True, help="Actually add to the album (default is a dry run).")
@click.option("--reapply", is_flag=True, help="Include items already added in a previous run.")
@click.pass_obj
def apply(db_path: Path, yes: bool, reapply: bool) -> None:
    """Add photos you marked 'remove' to the 'Photo Review' album in Photos. Never deletes."""
    from .apply import ALBUM_NAME, add_to_album, check_photos_access, pending_removals
    from .classify import CATEGORIES

    conn = db.connect(db_path)
    removals = pending_removals(conn, reapply)
    if not removals:
        click.echo("Nothing to apply. Mark items as 'remove' in `photo-review review` first.")
        return

    unique = {u for uuids in removals.values() for u in uuids}
    for category, uuids in removals.items():
        click.echo(f"  {CATEGORIES[category]:<28}{len(uuids):>6,}")
    click.echo(f"  {'Total → ' + ALBUM_NAME:<28}{len(unique):>6,}")

    if not yes:
        click.secho("Dry run. Re-run with --yes to add these to the album in Photos.", fg="yellow")
        return

    click.echo("Adding to album (Photos will open; allow automation access if asked)…")
    try:
        check_photos_access()
    except PermissionError as e:
        raise click.ClickException(str(e)) from e
    failed = add_to_album(conn, removals)
    if failed:
        click.secho(f"{len(failed)} of {len(unique)} photos could not be added:", fg="red")
        for uuid, e in failed[:10]:
            click.secho(f"  {uuid}: {e}", fg="yellow")
    if len(failed) < len(unique):
        click.echo(f"Done. Open Photos → '{ALBUM_NAME}', check the photos, then select all and delete.")


@cli.command()
@click.pass_obj
def inspect(db_path: Path) -> None:
    """Summarise what metadata/scores are available in the cache."""
    print_report(db.connect(db_path))
