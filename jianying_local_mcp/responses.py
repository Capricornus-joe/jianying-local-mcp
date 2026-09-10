"""Small MCP response views; stored plans and native drafts are never changed."""
from __future__ import annotations

from copy import deepcopy

from .core import summarize


CLIP_FIELDS = (
    "id", "kind", "track", "start", "duration", "text", "display_name",
    "source_start", "speed", "volume",
)


def compact_result(result: dict, include_plan: bool = False) -> dict:
    """Keep write metadata, omitting the potentially large plan unless requested.

    A dry-run plan is not a saved project. Its hint deliberately does not claim
    that read_managed_project can retrieve that preview.
    """
    if not isinstance(result, dict):
        raise ValueError("result must be an object")
    if not isinstance(include_plan, bool):
        raise ValueError("include_plan must be a boolean")
    if include_plan or "plan" not in result:
        return deepcopy(result)
    compact = deepcopy({key: value for key, value in result.items() if key != "plan"})
    compact["plan_omitted"] = True
    if result.get("dry_run") is True:
        compact["read_hint"] = (
            "The preview plan was omitted and is not saved. Repeat this write tool "
            "with include_plan=true to inspect its complete preview."
        )
    else:
        compact["read_hint"] = (
            "Use read_managed_project(name, view='clips', offset=0, limit=50) for "
            "clip IDs, or view='full' for the complete saved plan."
        )
    return compact


def project_view(plan: dict, view: str = "summary", offset: int = 0,
                 limit: int = 50, track: str | None = None) -> dict:
    """Return summary, one page of core clip fields, or explicitly the full plan.

    Pagination and an exact track-name filter apply only to the clips view.
    The full view preserves all fields and strings without truncation.
    """
    if not isinstance(plan, dict) or not isinstance(plan.get("clips"), list):
        raise ValueError("plan must be an object with a clips list")
    if not isinstance(view, str) or view not in {"summary", "clips", "full"}:
        raise ValueError("view must be summary, clips, or full")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a nonnegative integer")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise ValueError("limit must be an integer from 1 to 200")
    if track is not None and (not isinstance(track, str) or not track.strip()):
        raise ValueError("track must be a nonempty exact track name or null")
    if view != "clips" and (offset != 0 or limit != 50 or track is not None):
        raise ValueError("offset, limit, and track apply only to the clips view")
    if view == "full":
        return deepcopy(plan)

    summary = summarize(plan)
    if view == "summary":
        return {
            "view": "summary", "summary": summary,
            "read_hint": "Use view='clips' for paginated clip IDs, or view='full' for all plan fields.",
        }
    clips = [clip for clip in plan["clips"] if track is None or clip["track"] == track]
    page = clips[offset:offset + limit]
    return {
        "view": "clips", "summary": summary, "track": track,
        "offset": offset, "limit": limit, "total": len(clips), "returned": len(page),
        "next_offset": offset + len(page) if offset + len(page) < len(clips) else None,
        "clips": [{field: deepcopy(clip[field]) for field in CLIP_FIELDS if field in clip}
                  for clip in page],
        "read_hint": "This page contains core clip fields. Use view='full' for paths, styles and keyframes.",
    }
