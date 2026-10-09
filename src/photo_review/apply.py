import sqlite3
from datetime import datetime, timezone

from .classify import CATEGORIES

ALBUM_FOLDER = "Photo Review"

AUTOMATION_HELP = (
    "macOS isn't letting this app control Photos.\n"
    "Open System Settings → Privacy & Security → Automation, find Visual Studio Code (or Terminal) "
    "and switch on 'Photos'. If it isn't listed, run:\n"
    "    tccutil reset AppleEvents com.microsoft.VSCode\n"
    "then quit and reopen VS Code and run apply again; macOS will ask for permission."
)


def check_photos_access() -> None:
    import photoscript

    try:
        photoscript.PhotosLibrary().folders()
    except Exception as e:
        if "-1743" in str(e) or "Not authorized" in str(e):
            raise PermissionError(AUTOMATION_HELP) from e
        raise


def pending_removals(conn: sqlite3.Connection, reapply: bool = False) -> dict[str, list[str]]:
    sql = "SELECT category, uuid FROM decisions WHERE decision = 'remove'"
    if not reapply:
        sql += " AND applied_at IS NULL"
    out: dict[str, list[str]] = {}
    for row in conn.execute(sql + " ORDER BY category"):
        out.setdefault(row["category"], []).append(row["uuid"])
    return out


def add_to_albums(conn: sqlite3.Connection, removals: dict[str, list[str]]) -> list[tuple[str, str]]:
    """Add photos to 'Photo Review/<category>' and 'Photo Review/All'. Returns failures."""
    import photoscript
    from osxphotos.photosalbum import PhotosAlbumPhotoScript

    failed, added_all = [], {}
    for category, uuids in removals.items():
        photos = []
        for uuid in uuids:
            try:
                photos.append(photoscript.Photo(uuid))
            except Exception as e:
                failed.append((uuid, str(e)))
        if not photos:
            continue
        PhotosAlbumPhotoScript(f"{ALBUM_FOLDER}/{CATEGORIES[category]}", split_folder="/").update(photos)
        added_all.update({p.uuid: p for p in photos})
        now = datetime.now(timezone.utc).isoformat()
        with conn:
            conn.executemany(
                "UPDATE decisions SET applied_at = ? WHERE uuid = ? AND category = ?",
                [(now, p.uuid, category) for p in photos],
            )

    if added_all:
        PhotosAlbumPhotoScript(f"{ALBUM_FOLDER}/All", split_folder="/").update(list(added_all.values()))
    return failed
