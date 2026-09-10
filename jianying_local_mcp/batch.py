"""Compose validated edits in memory and commit only one managed revision."""
from __future__ import annotations

from copy import deepcopy
from .core import ProjectStore, normalize_plan, project_name, summarize
from .advanced import apply_motion, update_clip_features
from .subtitles import parse_srt
from . import workflow


class _MemoryStore:
    """Small adapter for the existing, tested editing functions; no disk writes."""
    edit = ProjectStore.edit

    def __init__(self, plan, probe):
        self.plan = deepcopy(plan)
        self.probe = probe

    def load_managed(self, name):
        if name != self.plan['name']:
            raise ValueError('Unknown in-memory revision')
        return deepcopy(self.plan)

    def create(self, plan, dry_run=True):
        # Validate every intermediate state, preserving workflow guards and
        # normalized defaults needed by later actions. Media probes are cached.
        self.plan = normalize_plan(plan, self.probe)
        return {'plan': self.plan, 'summary': summarize(self.plan), 'dry_run': True}


def _arguments(step, required, optional=()):
    if set(step) - {'action', *required, *optional} or set(required) - set(step):
        raise ValueError(f'Expected action with required fields {sorted(required)}; optional {sorted(optional)}')
    return {k: deepcopy(v) for k, v in step.items() if k != 'action'}


def _apply(memory, step, index):
    if not isinstance(step, dict):
        raise ValueError('Each step must be an object')
    action = step.get('action')
    name = memory.plan['name']
    target = f'batch-stage-{index}'
    if target == name:
        target += '-next'
    if action == 'edit':
        args = _arguments(step, {'operations'})
        return memory.edit(name, target, **args)
    if action == 'features':
        args = _arguments(step, {'clip_ids', 'features'})
        return update_clip_features(memory, name, target, **args)
    if action == 'motion':
        args = _arguments(step, {'clip_ids', 'preset'}, {'strength'})
        return apply_motion(memory, name, target, **args)
    if action == 'subtitles':
        args = _arguments(step, {'content'}, {'track', 'offset', 'font_size', 'color'})
        clips = parse_srt(**args)
        if not clips:
            raise ValueError('SRT contains no cues')
        return memory.edit(name, target, [{'op':'append', 'clip':c} for c in clips])
    if action == 'style_subtitles':
        args = _arguments(step, {'style'}, {'track', 'clip_ids'})
        return workflow.style_subtitles(memory, name, target, **args)
    if action == 'reorder':
        args = _arguments(step, {'track', 'clip_ids'}, {'start'})
        return workflow.reorder_track(memory, name, target, **args)
    if action == 'ripple_delete':
        args = _arguments(step, {'start', 'end'})
        return workflow.ripple_delete(memory, name, target, **args)
    raise ValueError('Supported actions: edit, features, motion, subtitles, style_subtitles, reorder, ripple_delete')


def change_scope(before, after):
    """Conservative review hints; these never certify a native render."""
    old = {c['id']:c for c in before['clips']}
    new = {c['id']:c for c in after['clips']}
    changed = {k for k in old.keys() | new.keys() if old.get(k) != new.get(k)}
    def visual_order(plan):
        # Native sorts video/image tracks before text tracks, stable within type.
        videos = list(dict.fromkeys(c['track'] for c in plan['clips'] if c['kind'] in {'video','image'}))
        texts = list(dict.fromkeys(c['track'] for c in plan['clips'] if c['kind'] == 'text'))
        return videos + texts
    layer_order_changed = visual_order(before) != visual_order(after)
    if layer_order_changed:
        # Removing and appending an otherwise identical clip can reorder whole
        # tracks. Include all visual ranges conservatively, even with equal IDs.
        changed.update(c['id'] for plan in (before, after) for c in plan['clips'] if c['kind'] != 'audio')
    ids = sorted(changed)
    intervals, kinds = [], set()
    audio_changed = False
    for cid in ids:
        a, b = old.get(cid), new.get(cid)
        for c in (a, b):
            if c:
                intervals.append((c['start'], c['start']+c['duration']))
                kinds.add(c['kind'])
        # Video edits may alter its own audio; conservatively review audio too.
        audio_changed |= any(c and (c['kind']=='audio' or (c['kind']=='video' and c.get('has_audio'))) for c in (a,b))
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return {'changed_clip_count':len(ids), 'changed_clip_ids':ids[:50],
            'changed_ids_truncated':len(ids)>50,
            'affected_ranges_seconds':merged[:50], 'ranges_truncated':len(merged)>50,
            'changed_kinds':sorted(kinds), 'audio_review_required':bool(audio_changed),
            'visual_layer_order_changed':layer_order_changed,
            'note':'Review hints only. Check neighboring frames/transitions; complete native export acceptance is still required.'}


def batch_edit(store: ProjectStore, name: str, new_name: str, steps: list[dict], dry_run=True):
    """All actions succeed before one final create; failures leave no revisions."""
    new_name = project_name(new_name)
    if name == new_name:
        raise ValueError('Use a new revision name')
    if not isinstance(steps, list) or not 1 <= len(steps) <= 100:
        raise ValueError('Provide 1-100 batch steps')
    target = store.workspace / new_name
    if target.exists() or target.is_symlink():
        raise ValueError('A project with that name already exists; use a new revision name')
    original = store.load_managed(name)
    memory = _MemoryStore(original, store.probe)
    for index, step in enumerate(steps, 1):
        try:
            _apply(memory, step, index)
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError(f'Batch step {index}: {exc}') from exc
    final = deepcopy(memory.plan)
    final['name'] = new_name
    # Derive every fallible response field before the only filesystem commit.
    try:
        scope = change_scope(original, final)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f'Invalid source manifest for change review: {exc}') from exc
    result = store.create(final, dry_run=dry_run)
    result.update(source_project_unchanged=name, batch_steps=len(steps),
                  committed_revisions=0 if dry_run else 1,
                  review_scope=scope)
    return result
