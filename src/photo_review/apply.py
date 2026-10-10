import shlex
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ALBUM_NAME = "Photo Review"


def _automation_help() -> str:
    return (
        "macOS isn't letting this app control Photos.\n"
        "VS Code's built-in terminal often can't get this permission. Instead, open the Terminal app and run:\n"
        f"    cd {shlex.quote(str(Path.cwd()))} && uv run photo-review apply --yes\n"
        "Click OK when macOS asks to let Terminal control Photos.\n"
        "(Or: System Settings → Privacy & Security → Automation → switch on 'Photos' for your terminal app.)"
    )


def check_photos_access() -> None:
    import photoscript

    try:
        photoscript.PhotosLibrary().folders()
    except Exception as e:
        if "-1743" in str(e) or "Not authorized" in str(e):
            raise PermissionError(_automation_help()) from e
        raise


def pending_removals(conn: sqlite3.Connection, reapply: bool = False) -> dict[str, list[str]]:
    sql = "SELECT category, uuid FROM decisions WHERE decision = 'remove'"
    if not reapply:
        sql += " AND applied_at IS NULL"
    out: dict[str, list[str]] = {}
    for row in conn.execute(sql + " ORDER BY category"):
        out.setdefault(row["category"], []).append(row["uuid"])
    return out


def add_to_album(conn: sqlite3.Connection, removals: dict[str, list[str]]) -> list[tuple[str, str]]:
    """Add all photos marked 'remove' to the single top-level review album. Returns failures."""
    import photoscript
    from osxphotos.photosalbum import PhotosAlbumPhotoScript

    photos, failed = {}, []
    for uuid in {u for uuids in removals.values() for u in uuids}:
        try:
            photos[uuid] = photoscript.Photo(uuid)
        except Exception as e:
            failed.append((uuid, str(e)))
    if not photos:
        return failed

    PhotosAlbumPhotoScript(ALBUM_NAME).update(list(photos.values()))
    now = datetime.now(timezone.utc).isoformat()
    with conn:
        conn.executemany(
            "UPDATE decisions SET applied_at = ? WHERE uuid = ? AND category = ?",
            [(now, uuid, category) for category, uuids in removals.items() for uuid in uuids if uuid in photos],
        )
    return failed
