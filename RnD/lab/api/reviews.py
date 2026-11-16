"""Reviews router: the notification reviews of a recording and the export."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from lab import issues, notes, reviews
from lab.api.deps import _recording
from lab.features import (
    reviews as _reviews_home,  # noqa: F401  (imported at startup: its LAB_DIR copies recordings.LAB_DIR)
)

router = APIRouter()


# --- notification (speech + beeps) reviews (§10, §14) ----------------------------------------------------

if TYPE_CHECKING:
    from collections.abc import Callable


def _review_call(fn: Callable[..., Any], *args: Any) -> Any:
    try:
        return fn(*args)
    except reviews.ReviewError as exc:
        raise HTTPException(exc.status, exc.message) from None


# (declared before the {name}.json run route; no path clash, kept with its peers)
@router.get("/api/reviews/export")
def export_reviews(recording: str | None = None) -> dict[str, Any]:
    if recording is not None:
        _recording(recording)
        ids = [recording]
    else:
        ids = reviews.recordings_with_reviews()
    return {**reviews.export(ids), "notes": notes.get(), "issues": issues.export_items()}


@router.get("/api/recordings/{rec_id}/reviews")
def list_reviews(rec_id: str) -> dict[str, Any]:
    _recording(rec_id)
    return reviews.list_annotations(rec_id)  # type: ignore[no-any-return]  # lab flat modules are untyped (Any)


@router.post("/api/recordings/{rec_id}/reviews", status_code=201)
def post_review(rec_id: str, body: dict[str, Any]) -> dict[str, Any]:
    rec = _recording(rec_id)
    return _review_call(reviews.create, rec_id, rec["duration"], body)  # type: ignore[no-any-return]  # lab flat modules are untyped (Any)


@router.put("/api/recordings/{rec_id}/reviews/{ann_id}")
def put_review(rec_id: str, ann_id: str, body: dict[str, Any]) -> dict[str, Any]:
    rec = _recording(rec_id)
    return _review_call(reviews.update, rec_id, rec["duration"], ann_id, body)  # type: ignore[no-any-return]  # lab flat modules are untyped (Any)


@router.delete("/api/recordings/{rec_id}/reviews/{ann_id}", status_code=204)
def delete_review(rec_id: str, ann_id: str) -> Response:
    _recording(rec_id)
    _review_call(reviews.delete, rec_id, ann_id)
    return Response(status_code=204)
