import sqlite3
from datetime import datetime, timezone

from .classify import CATEGORIES

ALBUM_FOLDER = "Photo Review"


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
