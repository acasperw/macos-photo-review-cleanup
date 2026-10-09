import dataclasses
import json
import os
from datetime import datetime, timezone

import osxphotos

UNKNOWN_PERSON = "_UNKNOWN_"
# Camera-applied effects (Portrait, Photographic Styles) and screenshot markup aren't protected edits.
NON_USER_EDITOR_PREFIXES = ("com.apple.camera", "com.apple.ScreenshotServices")


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _adjustment_info(photo: osxphotos.PhotoInfo) -> tuple[str | None, str | None]:
    if not photo.hasadjustments:
        return None, None
    adj = _safe(lambda: photo.adjustments)
    if adj is None:
        return None, None
    return adj.editor, adj.format_id


def _is_user_edit(has_adjustments: bool, editor: str | None) -> bool:
    if not has_adjustments:
        return False
    # Unknown editor is treated as a user edit so it stays protected.
    return not (editor and editor.startswith(NON_USER_EDITOR_PREFIXES))


def _derivative_path(photo: osxphotos.PhotoInfo) -> str | None:
    for path in _safe(lambda: photo.path_derivatives, []) or []:
        if os.path.isfile(path):
            return path
    return None


def load_photos(
    library: str | None, from_date: datetime | None, to_date: datetime | None
) -> list[osxphotos.PhotoInfo]:
    photosdb = osxphotos.PhotosDB(dbfile=library) if library else osxphotos.PhotosDB()
    return photosdb.photos(from_date=from_date, to_date=to_date, images=True, movies=True)


def to_record(photo: osxphotos.PhotoInfo) -> dict:
    editor, format_id = _adjustment_info(photo)
    exif = _safe(lambda: photo.exif_info)
    persons = _safe(lambda: photo.persons, []) or []
    imported_app, imported_bundle = _safe(lambda: photo.imported_by, (None, None))
    score = _safe(lambda: dataclasses.asdict(photo.score))

    return {
        "uuid": photo.uuid,
        "date": _iso(photo.date),
        "date_added": _iso(_safe(lambda: photo.date_added)),
        "kind": "video" if photo.ismovie else "photo",
        "original_filename": photo.original_filename,
        "uti": _safe(lambda: photo.uti_original) or _safe(lambda: photo.uti),
        "width": _safe(lambda: photo.original_width) or photo.width,
        "height": _safe(lambda: photo.original_height) or photo.height,
        "filesize": _safe(lambda: photo.original_filesize),
        "duration": getattr(exif, "duration", None),
        "favorite": int(photo.favorite),
        "hidden": int(photo.hidden),
        "has_adjustments": int(bool(photo.hasadjustments)),
        "adjustment_editor": editor,
        "adjustment_format_id": format_id,
        "user_edited": int(_is_user_edit(photo.hasadjustments, editor)),
        "screenshot": int(bool(_safe(lambda: photo.screenshot))),
        "screen_recording": int(bool(_safe(lambda: photo.screen_recording))),
        "burst": int(bool(photo.burst)),
        "burst_key": _safe(lambda: photo.burst_key) if photo.burst else None,
        "burst_selected": int(bool(_safe(lambda: photo.burst_selected))),
        "live_photo": int(bool(photo.live_photo)),
        "selfie": int(bool(_safe(lambda: photo.selfie))),
        "portrait": int(bool(_safe(lambda: photo.portrait))),
        "imported_by_app": imported_app,
        "imported_by_bundle": imported_bundle,
        "camera_make": getattr(exif, "camera_make", None),
        "camera_model": getattr(exif, "camera_model", None),
        "named_persons": json.dumps(sorted({p for p in persons if p != UNKNOWN_PERSON})),
        "unnamed_faces": sum(1 for p in persons if p == UNKNOWN_PERSON),
        "labels": json.dumps(_safe(lambda: photo.labels, []) or []),
        "scores": json.dumps(score) if score else None,
        "ai_caption": _safe(lambda: photo.ai_caption) or None,
        "is_missing": int(bool(photo.ismissing)),
        "in_cloud": int(bool(_safe(lambda: photo.incloud))),
        "shared": int(bool(_safe(lambda: photo.shared))),
        "syndicated": int(bool(_safe(lambda: photo.syndicated))),
        "original_path": photo.path,
        "derivative_path": _derivative_path(photo),
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }
