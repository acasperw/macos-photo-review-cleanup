import shlex
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

ALBUM_NAME = "Photo Review"


class DeleteCancelled(Exception):
    pass


def _automation_help() -> str:
    return (
        "macOS isn't letting this app control Photos.\n"
        "VS Code's built-in terminal often can't get this permission. Instead, open the Terminal app and run:\n"
        f"    cd {shlex.quote(str(Path.cwd()))} && uv run photo-review apply --yes --album\n"
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


def _photokit_authorize() -> None:
    import Photos

    level = Photos.PHAccessLevelReadWrite
    status = Photos.PHPhotoLibrary.authorizationStatusForAccessLevel_(level)
    if status == Photos.PHAuthorizationStatusNotDetermined:
        answered = threading.Event()
        Photos.PHPhotoLibrary.requestAuthorizationForAccessLevel_handler_(level, lambda _: answered.set())
        answered.wait(300)
        status = Photos.PHPhotoLibrary.authorizationStatusForAccessLevel_(level)
    if status != Photos.PHAuthorizationStatusAuthorized:
        raise PermissionError(
            "macOS isn't letting this app access your Photos library (full access is needed to delete).\n"
            "Open the Terminal app and run:\n"
            f"    cd {shlex.quote(str(Path.cwd()))} && uv run photo-review apply --yes\n"
            "Or: System Settings → Privacy & Security → Photos → set your terminal app to 'Full Access'."
        )


def delete_from_library(conn: sqlite3.Connection, removals: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    """Delete photos marked 'remove' via PhotoKit; macOS shows a confirmation dialog. Returns (deleted, not_found)."""
    import Photos

    _photokit_authorize()
    uuids = sorted({u for uuids in removals.values() for u in uuids})
    options = Photos.PHFetchOptions.alloc().init()
    options.setIncludeHiddenAssets_(True)
    options.setIncludeAllBurstAssets_(True)
    assets = Photos.PHAsset.fetchAssetsWithLocalIdentifiers_options_(uuids, options)
    found = {assets.objectAtIndex_(i).localIdentifier().split("/")[0] for i in range(assets.count())}
    not_found = [u for u in uuids if u not in found]
    if not found:
        return [], not_found

    finished, outcome = threading.Event(), {}

    def on_complete(ok, error):
        outcome["ok"], outcome["error"] = ok, error
        finished.set()

    Photos.PHPhotoLibrary.sharedPhotoLibrary().performChanges_completionHandler_(
        lambda: Photos.PHAssetChangeRequest.deleteAssets_(assets), on_complete
    )
    finished.wait()
    if not outcome["ok"]:
        error = outcome["error"]
        if error is not None and error.code() == Photos.PHPhotosErrorUserCancelled:
            raise DeleteCancelled()
        raise RuntimeError(f"Photos did not delete anything: {error.localizedDescription() if error else 'unknown error'}")

    deleted = sorted(found)
    with conn:
        for table in ("flags", "clusters", "decisions", "analysis", "assets"):
            conn.executemany(f"DELETE FROM {table} WHERE uuid = ?", [(u,) for u in deleted])
    return deleted, not_found
