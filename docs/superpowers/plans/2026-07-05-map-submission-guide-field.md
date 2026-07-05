# Map Submission Guide Field Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional Guide URL field to the map submission modal that validates the URL, warns in the preview when it's unreachable, lets the user fix it via an Edit Guide button, and stores valid guides in the `guides` table inside the submission transaction.

**Architecture:** Extract the URL check out of `URLTransformer` into a reusable `validate_url` coroutine. `MapSubmission` carries `guide_url` / `guide_valid`; the modal validates on submit but never blocks, the preview renders a warning plus an always-visible Edit Guide button (mirroring Edit Levels), and Confirm inserts only valid guides.

**Tech Stack:** Python 3.14, discord.py UI (modals/LayoutView), msgspec structs, aiohttp, pytest (no async plugin — tests drive coroutines with `asyncio.run()`).

**Spec:** `docs/superpowers/specs/2026-07-05-map-submission-guide-field-design.md`

## Global Constraints

- **Never run `git commit`** — the user commits explicitly themselves (standing user preference; overrides any commit step conventions).
- Run tests with `uv run pytest <path> -v`.
- SQL stays as inline `query` locals inside service methods (no new SQL needed in this plan — `MapsService.add_guide` already exists).
- No new dependencies. No pytest-asyncio: async code under test runs via `asyncio.run()` with fake sessions/services.
- Discord modals allow max 5 top-level components; `MapSubmitModal` currently has 4.

---

### Task 1: Extract `validate_url` from `URLTransformer`

**Files:**
- Modify: `utilities/transformers.py:232-243`
- Test: `tests/test_transformers.py`

**Interfaces:**
- Produces: `async def validate_url(session: aiohttp.ClientSession, value: str) -> str` in `utilities/transformers.py`, exported via `__all__`. Normalizes scheme, GETs the URL, raises `UserFacingError("URL is invalid.")` on non-200 or `aiohttp.ClientError`, returns the resolved URL (`str(resp.url)`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_transformers.py`:

```python
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import aiohttp

from utilities.errors import UserFacingError
from utilities.transformers import validate_url


class FakeSession:
    """Stands in for aiohttp.ClientSession: records URLs, returns a canned response."""

    def __init__(
        self,
        *,
        status: int = 200,
        resolved: str = "https://example.com/",
        error: Exception | None = None,
    ) -> None:
        self._status = status
        self._resolved = resolved
        self._error = error
        self.requested: list[str] = []

    def get(self, url: str):
        self.requested.append(url)
        if self._error is not None:
            raise self._error

        @asynccontextmanager
        async def _response():
            yield SimpleNamespace(status=self._status, url=self._resolved)

        return _response()


def test_validate_url_prepends_https_and_returns_resolved() -> None:
    session = FakeSession(resolved="https://example.com/guide")
    result = asyncio.run(validate_url(session, "  example.com/guide "))
    assert session.requested == ["https://example.com/guide"]
    assert result == "https://example.com/guide"


def test_validate_url_keeps_explicit_scheme() -> None:
    session = FakeSession()
    asyncio.run(validate_url(session, "http://example.com"))
    assert session.requested == ["http://example.com"]


def test_validate_url_non_200_rejected() -> None:
    session = FakeSession(status=404)
    with pytest.raises(UserFacingError):
        asyncio.run(validate_url(session, "https://example.com"))


def test_validate_url_client_error_rejected() -> None:
    session = FakeSession(error=aiohttp.ClientError())
    with pytest.raises(UserFacingError):
        asyncio.run(validate_url(session, "https://example.com"))
```

(`pytest` is already imported at the top of this file; add the new imports below the existing ones.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_transformers.py -v`
Expected: 4 new tests FAIL with `ImportError: cannot import name 'validate_url'`

- [ ] **Step 3: Implement `validate_url` and slim `URLTransformer`**

In `utilities/transformers.py`, replace the `URLTransformer` class body and add the module-level function directly above it:

```python
async def validate_url(session: aiohttp.ClientSession, value: str) -> str:
    """Normalize the scheme, fetch the URL, and return its resolved form.

    Raises UserFacingError when the URL doesn't answer with HTTP 200.
    """
    value = value.strip()
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    try:
        async with session.get(value) as resp:
            if resp.status != 200:
                raise UserFacingError("URL is invalid.")
            return str(resp.url)
    except aiohttp.ClientError:
        raise UserFacingError("URL is invalid.") from None


class URLTransformer(app_commands.Transformer):
    async def transform(self, itx: AkandeItx, value: str) -> str:
        return await validate_url(itx.client.session, value)
```

Add `"validate_url"` to `__all__` (keep it alphabetically sorted with the existing entries).

`aiohttp` must be a runtime import for the signature — it already is (line 7).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_transformers.py -v`
Expected: all PASS (old tests included).

---

### Task 2: `MapSubmission` guide fields + preview rendering

**Files:**
- Modify: `extensions/maps/views.py:148-192` (`MapSubmission`, `map_submission_body`, new constant + helper)
- Test: `tests/test_map_views.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `MapSubmission.guide_url: str | None = None` and `MapSubmission.guide_valid: bool = True` (defaults keep existing call sites working).
  - `_GUIDE_WARNING: str` module constant.
  - `def _drop_invalid_guide(sub: MapSubmission) -> MapSubmission` — returns `sub` untouched when valid, else a copy with `guide_url=None, guide_valid=True`.
  - `map_submission_body` renders `` `Guide` <url> `` in the details when `guide_url` is set, and `_GUIDE_WARNING` as a separate body string when the guide is set but invalid.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_map_views.py` (extend the existing import from `extensions.maps.views` with `_GUIDE_WARNING` and `_drop_invalid_guide`):

```python
def _sub(**overrides) -> MapSubmission:
    defaults = dict(
        map_code="ABC123",
        map_name="Hanamura",
        map_types=["Single"],
        description="",
        levels=["Alpha"],
        image_url=None,
    )
    return MapSubmission(**defaults | overrides)


def test_map_submission_body_renders_guide_line() -> None:
    body = map_submission_body(
        _sub(guide_url="https://example.com/guide"), header="Preview"
    )
    strings = [item for item in body if isinstance(item, str)]
    assert any("`Guide` https://example.com/guide" in s for s in strings)
    assert _GUIDE_WARNING not in strings


def test_map_submission_body_omits_guide_line_when_absent() -> None:
    body = map_submission_body(_sub(), header="Preview")
    strings = [item for item in body if isinstance(item, str)]
    assert not any("`Guide`" in s for s in strings)
    assert _GUIDE_WARNING not in strings


def test_map_submission_body_warns_on_invalid_guide() -> None:
    body = map_submission_body(
        _sub(guide_url="https://example.com/dead", guide_valid=False),
        header="Preview",
    )
    strings = [item for item in body if isinstance(item, str)]
    assert _GUIDE_WARNING in strings


def test_drop_invalid_guide_blanks_only_invalid() -> None:
    invalid = _sub(guide_url="https://example.com/dead", guide_valid=False)
    dropped = _drop_invalid_guide(invalid)
    assert dropped.guide_url is None
    assert dropped.guide_valid is True

    valid = _sub(guide_url="https://example.com/guide")
    assert _drop_invalid_guide(valid) is valid
```

Note: the existing `MapSubmission(...)` constructions in older tests keep working because the new fields default.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_map_views.py -v`
Expected: new tests FAIL with `ImportError: cannot import name '_GUIDE_WARNING'`

- [ ] **Step 3: Implement fields, rendering, and helper**

In `extensions/maps/views.py`:

Add below `_LEVELS_MAX_LENGTH` (line 35):

```python
_GUIDE_WARNING = (
    "⚠️ Guide URL is unreachable — fix it with Edit Guide or it will be skipped."
)
```

Extend the struct (line 148):

```python
class MapSubmission(msgspec.Struct, frozen=True):
    """Everything a map submission card needs to render."""

    map_code: str
    map_name: str
    map_types: list[str]
    description: str
    levels: list[str]
    image_url: str | None
    guide_url: str | None = None
    guide_valid: bool = True
```

Add the helper directly below the struct:

```python
def _drop_invalid_guide(sub: MapSubmission) -> MapSubmission:
    """An announceable submission: an unreachable guide is removed, not shown."""
    if sub.guide_valid:
        return sub
    return structs.replace(sub, guide_url=None, guide_valid=True)
```

In `map_submission_body`, extend the details string:

```python
    details = (
        f"`Code` **{sub.map_code}**\n"
        f"`Map` {sub.map_name}\n"
        f"`Type` {', '.join(sub.map_types)}"
        + (f"\n`Description` {sub.description}" if sub.description else "")
        + (f"\n`Guide` {sub.guide_url}" if sub.guide_url else "")
    )
```

and add the warning to the returned list, after `detail_item`:

```python
    return [
        f"## {header}",
        detail_item,
        *((_GUIDE_WARNING,) if sub.guide_url and not sub.guide_valid else ()),
        *((ui.Separator(), _levels_display(sub.levels)) if include_levels else ()),
        *((gallery,) if showcase_image and sub.image_url else ()),
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_map_views.py -v`
Expected: all PASS.

---

### Task 3: Modal guide field, validation, and persistence

**Files:**
- Modify: `extensions/maps/views.py:195-321` (`MapSubmitModal`), imports, plus two new module-level helpers
- Test: `tests/test_map_views.py`

**Interfaces:**
- Consumes: `validate_url` from Task 1; `MapSubmission.guide_url` / `guide_valid` and `_drop_invalid_guide` from Task 2.
- Produces:
  - `async def _validate_guide(session: aiohttp.ClientSession, raw: str) -> tuple[str | None, bool]` — `(None, True)` for blank input; `(resolved_url, True)` when reachable; `(normalized_input, False)` when not.
  - `async def _persist_submission(svc, sub: MapSubmission, *, creator_id: int) -> None` — creates the map, creator, levels, and (only when set **and** valid) the guide. Callers wrap it in a transaction.
  - `MapSubmitModal` gains `self._guide` (`ui.TextInput`, optional, max_length 200) as the 5th component, labeled "Guide URL".

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_map_views.py` (extend the views import with `_validate_guide` and `_persist_submission`; add `import asyncio` at the top; `FakeSession` mirrors the one in `tests/test_transformers.py`):

```python
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace


class FakeSession:
    def __init__(self, *, status: int = 200, resolved: str = "https://example.com/") -> None:
        self._status = status
        self._resolved = resolved

    def get(self, url: str):
        @asynccontextmanager
        async def _response():
            yield SimpleNamespace(status=self._status, url=self._resolved)

        return _response()


class RecordingMaps:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def create_map(self, **kwargs) -> None:
        self.calls.append(("create_map", kwargs))

    async def add_creator(self, map_code: str, user_id: int) -> None:
        self.calls.append(("add_creator", map_code, user_id))

    async def add_levels(self, map_code: str, levels: list[str]) -> None:
        self.calls.append(("add_levels", map_code, levels))

    async def add_guide(self, map_code: str, url: str) -> None:
        self.calls.append(("add_guide", map_code, url))


def test_validate_guide_blank_is_no_guide() -> None:
    assert asyncio.run(_validate_guide(FakeSession(), "   ")) == (None, True)


def test_validate_guide_reachable_returns_resolved() -> None:
    session = FakeSession(resolved="https://example.com/guide")
    assert asyncio.run(_validate_guide(session, "example.com/guide")) == (
        "https://example.com/guide",
        True,
    )


def test_validate_guide_unreachable_keeps_normalized_input() -> None:
    session = FakeSession(status=404)
    assert asyncio.run(_validate_guide(session, "example.com/dead")) == (
        "https://example.com/dead",
        False,
    )


def _persist(sub: MapSubmission) -> RecordingMaps:
    maps = RecordingMaps()
    svc = SimpleNamespace(maps=maps)
    asyncio.run(_persist_submission(svc, sub, creator_id=42))
    return maps


def test_persist_submission_inserts_valid_guide() -> None:
    maps = _persist(_sub(guide_url="https://example.com/guide"))
    assert ("add_guide", "ABC123", "https://example.com/guide") in maps.calls


def test_persist_submission_skips_invalid_guide() -> None:
    maps = _persist(_sub(guide_url="https://example.com/dead", guide_valid=False))
    assert not any(call[0] == "add_guide" for call in maps.calls)
    assert any(call[0] == "create_map" for call in maps.calls)


def test_persist_submission_skips_absent_guide() -> None:
    maps = _persist(_sub())
    assert not any(call[0] == "add_guide" for call in maps.calls)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_map_views.py -v`
Expected: new tests FAIL with `ImportError: cannot import name '_validate_guide'`

- [ ] **Step 3: Implement helpers and wire the modal**

In `extensions/maps/views.py`:

Add imports: `import aiohttp` (with the other third-party imports) and extend the utilities import line:

```python
from utilities.transformers import validate_url
```

Add the two helpers below `_drop_invalid_guide`:

```python
async def _validate_guide(
    session: aiohttp.ClientSession, raw: str
) -> tuple[str | None, bool]:
    """Normalized guide URL and whether it answered; ``(None, True)`` if blank."""
    raw = raw.strip()
    if not raw:
        return None, True
    try:
        return await validate_url(session, raw), True
    except UserFacingError:
        if not raw.startswith(("http://", "https://")):
            raw = "https://" + raw
        return raw, False


async def _persist_submission(
    svc: Services, sub: MapSubmission, *, creator_id: int
) -> None:
    """Write a confirmed submission; callers wrap this in a transaction."""
    await svc.maps.create_map(
        map_name=sub.map_name,
        map_type=sub.map_types,
        map_code=sub.map_code,
        description=sub.description or None,
        image=None,
    )
    await svc.maps.add_creator(sub.map_code, creator_id)
    await svc.maps.add_levels(sub.map_code, sub.levels)
    if sub.guide_url and sub.guide_valid:
        await svc.maps.add_guide(sub.map_code, sub.guide_url)
```

Add `Services` to the `TYPE_CHECKING` import block: `from database import Services` (the container yielded by `itx.client.acquire()`, defined in `database/__init__.py:23`).

In `MapSubmitModal.__init__`, add the 5th component after the screenshot upload:

```python
        self._guide = ui.TextInput(
            required=False,
            max_length=200,
            placeholder="https://youtu.be/...",
        )
        self.add_item(
            ui.Label(
                text="Guide URL",
                description="Optional link to a guide for this map.",
                component=self._guide,
            )
        )
```

Replace `MapSubmitModal.on_submit`:

```python
    async def on_submit(self, itx: AkandeItx) -> None:
        guide_url, guide_valid = await _validate_guide(
            itx.client.session, self._guide.value
        )
        sub = MapSubmission(
            map_code=self.map_code,
            map_name=self.map_name,
            map_types=self.map_types.values,
            description=self.description.value,
            levels=_parse_levels(self.levels.value),
            image_url=self.image.url if self.image else None,
            guide_url=guide_url,
            guide_valid=guide_valid,
        )
        final = await MapSubmissionReview.prompt(itx, sub)
        if final is None:
            return

        async with itx.client.acquire() as svc, transaction(svc.db):
            await _persist_submission(svc, final, creator_id=itx.user.id)

        await self._announce(itx, _drop_invalid_guide(final))
```

(`_announce` needs no changes: the guide line flows in through `map_submission_body`, and `_drop_invalid_guide` guarantees no unreachable URL is announced.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_map_views.py tests/test_transformers.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint/typecheck**

Run: `uv run ruff check extensions/maps/views.py utilities/transformers.py tests/`
Expected: clean (fix anything reported).

---

### Task 4: Edit Guide button on the review

**Files:**
- Modify: `extensions/maps/views.py:323-424` (`_ReviewButtons`, `MapSubmissionReview`, new `_GuideEditModal`)
- Test: `tests/test_map_views.py`

**Interfaces:**
- Consumes: `_validate_guide` (Task 3), `MapSubmission.guide_url`/`guide_valid` (Task 2).
- Produces:
  - `class _GuideEditModal(ui.Modal, title="Edit Guide")` — one optional `ui.TextInput` prefilled with the staged URL; empty input clears the guide.
  - `MapSubmissionReview.update_guide(itx, url: str | None, *, valid: bool)` — swaps the staged guide and re-renders in place (mirror of `update_levels`).
  - An **Edit Guide** grey button between Edit Levels and Cancel in `_ReviewButtons`.

- [ ] **Step 1: Write the failing test**

The modal/button behavior is interaction-driven; the unit-testable surface is the staged-state swap. Append to `tests/test_map_views.py` (extend the views import with `MapSubmissionReview`):

```python
def test_update_guide_swaps_staged_submission() -> None:
    review = MapSubmissionReview.__new__(MapSubmissionReview)  # skip discord setup
    review.sub = _sub(guide_url="https://example.com/dead", guide_valid=False)

    class _Response:
        async def edit_message(self, **kwargs) -> None:
            pass

    async def _run() -> None:
        review._render = lambda footer: None  # rendering needs discord items
        review._buttons = None
        await review.update_guide(
            SimpleNamespace(response=_Response()),
            "https://example.com/guide",
            valid=True,
        )

    asyncio.run(_run())
    assert review.sub.guide_url == "https://example.com/guide"
    assert review.sub.guide_valid is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_map_views.py::test_update_guide_swaps_staged_submission -v`
Expected: FAIL with `AttributeError: ... has no attribute 'update_guide'`

- [ ] **Step 3: Implement modal, button, and `update_guide`**

In `extensions/maps/views.py`, add below `_LevelEditModal`:

```python
class _GuideEditModal(ui.Modal, title="Edit Guide"):
    """Fix or remove the staged guide URL; empty input clears it."""

    def __init__(self, review: MapSubmissionReview) -> None:
        super().__init__()
        self._review = review
        self.guide = ui.TextInput(
            required=False,
            max_length=200,
            default=review.sub.guide_url or "",
            placeholder="https://youtu.be/...",
        )
        self.add_item(
            ui.Label(
                text="Guide URL",
                description="Leave empty to remove the guide.",
                component=self.guide,
            )
        )

    async def on_submit(self, itx: AkandeItx) -> None:
        url, valid = await _validate_guide(itx.client.session, self.guide.value)
        await self._review.update_guide(itx, url, valid=valid)

    async def on_error(self, itx: AkandeItx, error: Exception) -> None:
        if isinstance(error, UserFacingError):
            await views.send_error(itx, str(error))
            return
        await super().on_error(itx, error)
```

In `_ReviewButtons`, add between `edit_levels` and `cancel`:

```python
    @ui.button(label="Edit Guide", style=discord.ButtonStyle.grey)
    async def edit_guide(
        self, interaction: discord.Interaction, button: ui.Button
    ) -> None:
        assert self.view
        await interaction.response.send_modal(_GuideEditModal(self.view))
```

In `MapSubmissionReview`, add below `update_levels`:

```python
    async def update_guide(
        self, itx: discord.Interaction, url: str | None, *, valid: bool
    ) -> None:
        """Swap the staged guide and re-render the preview in place."""
        self.sub = structs.replace(self.sub, guide_url=url, guide_valid=valid)
        self._render(self._buttons)
        await itx.response.edit_message(view=self)
```

- [ ] **Step 4: Run the full suite and lint**

Run: `uv run pytest tests/ -v && uv run ruff check .`
Expected: all tests PASS, ruff clean.

---

## Verification

- `uv run pytest tests/ -v` — full suite green.
- `uv run ruff check .` — clean.
- Manual (optional, needs a running bot): submit a map with a bogus guide URL → preview shows the ⚠️ warning and Edit Guide button; fix the URL → warning clears; confirm → guide appears via `/view-guide`.
