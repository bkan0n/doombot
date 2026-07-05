# Map Submission Guide Field — Design

**Date:** 2026-07-05
**Status:** Approved

## Goal

Let map creators attach a guide URL while submitting a map, instead of running
`/add-guide` afterwards. The guide is stored in the existing `guides` table as
part of the submission transaction.

## Current state

- `MapSubmitModal` (`extensions/maps/views.py`) collects map types,
  description, levels, and screenshot — 4 of Discord's 5 modal component slots.
- `MapSubmissionReview` shows a preview card with Confirm / Edit Levels /
  Cancel buttons; Edit Levels opens `_LevelEditModal` which re-renders the
  preview in place via `update_levels`.
- `/add-guide` (`extensions/maps/cog.py`) validates URLs with
  `URLTransformer` (`utilities/transformers.py`): normalize scheme → HTTP GET →
  require status 200 → return resolved URL.
- `MapsService.add_guide(map_code, url)` inserts into the `guides` table.

## Design

### Modal field

`MapSubmitModal` gains a fifth component: a short, optional `TextInput`
labeled "Guide URL". This fills Discord's last modal slot.

### Validation helper

Extract the body of `URLTransformer.transform` into a module-level coroutine
in `utilities/transformers.py`:

```python
async def validate_url(session: aiohttp.ClientSession, value: str) -> str
```

It normalizes the scheme (prepend `https://` when missing), performs a GET,
raises `UserFacingError("URL is invalid.")` unless the response is 200, and
returns the resolved URL. `URLTransformer.transform` becomes a thin wrapper.
Both submission modals reuse it.

### Data model

`MapSubmission` gains two fields:

- `guide_url: str | None` — the normalized URL as entered (kept even when
  validation fails, so the edit modal can prefill it).
- `guide_valid: bool` — result of the last validation attempt. `True` when no
  guide was entered.

### Submit flow

In `MapSubmitModal.on_submit`, if a guide URL was entered, call
`validate_url`. On success store the resolved URL with `guide_valid=True`;
on `UserFacingError` keep the normalized input with `guide_valid=False`.
The submission always proceeds to the preview.

### Preview

- `map_submission_body` renders a `` `Guide` <url> `` line in the details when
  `guide_url` is set, and appends a warning line when `guide_valid` is false:
  "⚠️ Guide URL is unreachable — fix it with Edit Guide or it will be
  skipped."
- `_ReviewButtons` gains an always-visible **Edit Guide** button (mirroring
  Edit Levels) that opens `_GuideEditModal`, prefilled with the current URL.
- `_GuideEditModal.on_submit` revalidates via `validate_url` and calls
  `MapSubmissionReview.update_guide(itx, url, valid)`, which swaps the staged
  guide and re-renders in place. Clearing the field removes the guide
  (`guide_url=None`, `guide_valid=True`).

### Confirm

In `MapSubmitModal.on_submit` after the review resolves: when `final.guide_url`
is set **and** `final.guide_valid`, call
`svc.maps.add_guide(final.map_code, final.guide_url)` inside the existing
transaction, alongside `add_creator` and `add_levels`.

When the staged guide is invalid at confirm time, the map submits without it —
no error, the preview warning already said it would be skipped. The user can
`/add-guide` later.

### Announcement

The new-maps announcement card uses `map_submission_body`, so a valid guide
line appears automatically. Before announcing, blank the guide fields on the
submission when the guide was invalid/dropped so no broken URL is shown.

## Error handling

- Guide validation failure never blocks or discards a submission.
- `validate_url` network errors (`aiohttp.ClientError`) are treated as
  invalid, same as today's `URLTransformer`.
- No duplicate-guide check is needed: the map is brand new, so its guide list
  is empty.

## Testing

Extend `tests/test_map_views.py`:

- Valid guide URL → stored on the submission, `guide_valid=True`, guide line
  rendered in the body.
- Invalid guide URL → submission proceeds, `guide_valid=False`, warning line
  rendered.
- Confirm with valid guide → `add_guide` called inside the transaction.
- Confirm with invalid guide → `add_guide` not called; map still created.
- Edit Guide modal → revalidates and updates the staged submission; clearing
  the field removes the guide.
- HTTP checks mocked; no live network in tests.

## Out of scope

- Multiple guide URLs at submission time (use `/add-guide` for extras).
- Changes to `/add-guide` or `/view-guide` behavior.
