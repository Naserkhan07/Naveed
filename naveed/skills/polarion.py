"""The Polarion ALM knowledge pack.

Polarion is the case that motivated this whole subsystem. A general vision model
asked to "set the status of PROJ-1042 to Verified and add a comment" will hunt
through a menu, open the wrong work item, and edit a field that the workflow has
locked. Someone who uses Polarion daily would do it in four actions, because they
know the form, the field names, and which fields the workflow freezes.

So this pack teaches Naveed exactly that, and nothing else:

* **where it is** — Polarion in the browser (title contains "Polarion", URL has a
  ``/polarion/`` or ``/_polarion/`` path) or the desktop client;
* **what the vocabulary means** — work item, type, status, resolution, severity,
  assignment, comment, space, LiveDoc, baseline, approval, custom field… so that
  "ticket", "requirement", "defect" and "task" all resolve to the right thing;
* **how the UI is shaped** — the ID ``PROJ-1234`` opens a work item, fields save
  individually in the modern UI, long descriptions are rich-text editors, the
  workflow may lock fields;
* **what to prefer** — the REST API when a base URL and a personal access token
  are configured (:func:`polarion_*` tools below), the UI otherwise, and the new
  ``edit_field``/``read_field`` actions rather than retyping a whole field;
* **how to do the everyday jobs** — the recipes for creating a work item,
  changing status, commenting, reassigning, editing a custom field, querying with
  a Lucene-style query.

**Everything specific to *your* server lives in the overlay, not in this file.**
Run ``python -m naveed --teach`` to record your own routes, and put your project
ID and custom field names in ``~/.naveed/skills/polarion.local.json``::

    {
      "overlay_for": "polarion",
      "knowledge": ["Our project id is PROJ and the custom field is 'Verified By'."],
      "shortcuts": {"open a work item by id": "type PROJ-1234 then Enter"}
    }

Nothing here phones home: the API tools only exist after you configure a base URL
and token in ``config.env``.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from .base import Recipe, RecipeStep, Skill, SkillTool

logger = logging.getLogger(__name__)

__all__ = ["SKILL", "build_skill", "polarion_request", "work_item_url"]

# --- the app's own vocabulary ----------------------------------------------

DETECTION_WINDOW = [r"polarion", r"work item", r"\(PROJ-", r"_polarion"]
DETECTION_URL = [r"/polarion/", r"/_polarion/", r"polarion/#/project/"]
DETECTION_PROCESS = [r"polarion"]
KEYWORDS = ["polarion", "work item", "workitem", "livedoc", "baseline", "test case", "requirement", "defect"]

KNOWLEDGE = [
    "Polarion ALM (Siemens) stores everything as work items. A work item has a project-qualified ID like PROJ-1234, a Type (requirement, task, defect, test case…), a Title, a Description, a Status, and optionally Resolution, Severity, Priority, Assignee, Due Date and custom fields.",
    "A work item ID typed into the search/quick-access box and confirmed with Enter opens that work item directly — this is almost always faster than finding it in a table.",
    "In the modern (Web) UI the fields of an open work item are edited in place: click the field, change it, and save. The Description is a rich-text editor, not a plain textarea.",
    "In the classic UI a work item opens as a form with an Edit button and one Save button for the whole form.",
    "The Status dropdown only offers the transitions the project's workflow allows from the current state; a state that is not in the list cannot be set by hand either. If the wanted status is missing, report that rather than trying another route.",
    "Approved and/or released work items can be locked by the workflow: their fields are read-only until the approval is retracted. A field that refuses typing is usually locked, not broken.",
    "Custom fields are project-specific and their labels differ between installations ('Verified By', 'Customer Impact', 'Component'). Never assume a custom field exists — look for it in the work item form.",
    "The Save button applies per-field in the modern UI; after editing, confirm the field shows the new value before claiming success.",
    "Comments are added in the Comments section at the bottom of the work item (in the modern UI) and are saved with their own Post/Save button.",
    "Polarion has a REST API at <server>/polarion/rest/v1/... Authentication is a Bearer personal access token. When a base URL and token are configured, prefer the API tools below over clicking: they are exact and cannot hit the wrong row.",
    "Search accepts a Lucene-style query in the search field (for example: type:defect AND status:open). Combined with the Ctrl+F find bar on a table, this beats scrolling.",
    "Wide work-item tables can be filtered by column and exported; for bulk edits prefer the table's multi-select plus the bulk action, but confirm the selection count before applying anything.",
]

SHORTCUTS = {
    "open a work item by id": "type the ID (e.g. PROJ-1234) in the search box, then Enter",
    "find text on the page": "ctrl+f",
    "save the field you just edited": "the field's own Save button (modern UI) or ctrl+s (classic form)",
    "go to the project's work items": "ctrl+alt+w in the classic UI, or the Work Items link in the space",
    "open the logged-in user's tasks": "the My Work Items / Dashboard view",
    "previous / next tab": "ctrl+tab",
    "refresh the view": "f5",
    "add a comment": "click the Comments box at the bottom of the work item and post it",
}

GLOSSARY = {
    "work item": "the single editable record — a requirement, task, defect or test case",
    "type": "which kind of work item it is (requirement, task, defect, test case)",
    "status": "the workflow state (draft, open, in progress, verified, done…)",
    "resolution": "why it is closed (fixed, rejected, duplicate…)",
    "space": "a folder-like container of documents and work items inside a project",
    "livedoc": "a document whose sections are themselves work items",
    "baseline": "a frozen snapshot of a document or space",
    "approval": "the workflow step that locks a work item once it is approved",
    "custom field": "a project-defined extra field, with a project-specific label",
    "link": "a typed relation between work items (verifies, depends on, duplicates…)",
}

GOTCHAS = [
    "Do not retype a whole Description to change one sentence — read it, change that part, write it back (read_field then edit_field).",
    "The workflow may forbid the status you were asked for; say so instead of trying another field.",
    "A locked field silently ignores typing. If an edit does not take, check whether the work item is Approved/Released.",
    "The description editor is rich text: pasting plain text is fine, but re-sending the whole field can lose formatting the user cares about. Prefer a targeted edit over a full replacement.",
    "IDs are project-qualified; PROJ-42 and OTHR-42 are different work items. Never drop or invent the project prefix.",
    "Tables reload asynchronously. After changing a filter or query, wait for the row count to settle before clicking a row, or the click lands on a stale row.",
]

EDITING_TIPS = [
    "To change an existing value, use read_field first (it copies the field's exact text), then edit_field with operation 'replace' for a surgical change, or 'set' only when the whole value must change.",
    "To append a comment-style note to an existing description, use edit_field with operation 'append' — never 'set', which would delete the original text.",
    "If a field is inside a rich-text editor, click it first and let the caret settle before reading or writing.",
    "After the edit, the field must show the new value; edit_field verifies this automatically and reports honestly when it does not.",
]

# --- API fast path ----------------------------------------------------------

DEFAULT_ENDPOINTS = {
    "work_items": "/polarion/rest/v1/projects/{project}/workitems",
    "work_item": "/polarion/rest/v1/projects/{project}/workitems/{id}",
    "query": "/polarion/rest/v1/projects/{project}/workitems?query={query}",
}


def _settings(config: Any) -> Any:
    return getattr(config, "skills", None)


def api_configured(config: Any) -> bool:
    settings = _settings(config)
    return bool(settings and getattr(settings, "polarion_base_url", "") and getattr(settings, "allow_api", True))


def api_writes_allowed(config: Any) -> bool:
    settings = _settings(config)
    return bool(api_configured(config) and getattr(settings, "allow_api_writes", False))


def work_item_url(config: Any, work_item_id: str) -> str:
    """A deep link to a work item, for opening it in the browser."""
    settings = _settings(config)
    base = str(getattr(settings, "polarion_base_url", "") or "").rstrip("/")
    project = str(getattr(settings, "polarion_project", "") or "")
    if not base:
        return ""
    identifier = work_item_id.strip()
    if project and "-" not in identifier:
        identifier = f"{project}-{identifier}"
    return f"{base}/polarion/#/project/{project}/workitem?id={identifier}" if project else f"{base}/polarion/#/workitem?id={identifier}"


def polarion_request(
    config: Any,
    path: str,
    *,
    method: str = "GET",
    payload: Optional[Dict[str, Any]] = None,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    """One REST call, with the error messages a human can act on.

    Kept deliberately small: stdlib ``urllib``, no session, no retries beyond
    what the caller needs, and errors that name the status code and the endpoint
    instead of raising a traceback into the UI.
    """
    settings = _settings(config)
    base = str(getattr(settings, "polarion_base_url", "") or "").rstrip("/")
    token = str(getattr(settings, "polarion_token", "") or "")
    if not base:
        raise RuntimeError(
            "Polarion is not configured. Set SKILLS_POLARION_BASE_URL (and SKILLS_POLARION_TOKEN) "
            'in ~/.naveed/config.env, or leave the API alone and let me drive the UI instead.'
        )
    url = base + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method.upper())
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - user's own server
            body = response.read().decode("utf-8", "replace")
            status = getattr(response, "status", 200)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:400]
        if error.code in (401, 403):
            raise RuntimeError(
                f"Polarion refused the request ({error.code}). Check SKILLS_POLARION_TOKEN — "
                f"it needs to be a personal access token with access to this project."
            ) from error
        if error.code == 404:
            raise RuntimeError(f"Polarion has no such endpoint or work item: {method} {path}") from error
        raise RuntimeError(f"Polarion returned {error.code} for {method} {path}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Could not reach Polarion at {base}: {error.reason}") from error

    if not body.strip():
        return {"status": status, "data": {}}
    try:
        return {"status": status, "data": json.loads(body)}
    except ValueError:
        return {"status": status, "data": {"raw": body[:2000]}}


def _endpoint(config: Any, key: str, **values: Any) -> str:
    settings = _settings(config)
    endpoints = dict(DEFAULT_ENDPOINTS)
    endpoints.update(dict(getattr(settings, "polarion_endpoints", {}) or {}))
    return endpoints[key].format(**values)


def _project(config: Any, project: str = "") -> str:
    settings = _settings(config)
    return project or str(getattr(settings, "polarion_project", "") or "")


# --- tools ------------------------------------------------------------------

def polarion_search(config: Any, query: str = "", project: str = "", limit: int = 20) -> str:
    """Search work items with a Lucene-style query."""
    project = _project(config, project)
    if not project:
        return ("I need your Polarion project id (SKILLS_POLARION_PROJECT in config.env) "
                "before I can search by API — or open the project in the browser and I will use the UI.")
    if query:
        path = _endpoint(config, "query", project=project, query=urllib.parse.quote(query))
    else:
        path = _endpoint(config, "work_items", project=project)
    response = polarion_request(config, path)
    items = _items(response.get("data"))
    if not items:
        return f"no work items matched {query!r} in {project}"
    lines = []
    for item in items[: int(limit) or 20]:
        identifier = item.get("id") or item.get("shortId") or "?"
        attributes = item.get("attributes", {}) if isinstance(item.get("attributes"), dict) else {}
        title = attributes.get("title") or item.get("title") or ""
        status = attributes.get("status") or item.get("status") or ""
        lines.append(f"{identifier}: {str(title)[:90]} [{status}]")
    return "\n".join(lines)


def polarion_get_work_item(config: Any, id: str = "", work_item_id: str = "", project: str = "", fields: str = "") -> str:
    """Read one work item (its title, type, status, assignee and description)."""
    identifier = (id or work_item_id or "").strip()
    if not identifier:
        return "I need the work item id, for example PROJ-1234."
    project = _project(config, project) or (identifier.split("-")[0] if "-" in identifier else "")
    short = identifier.split("-", 1)[1] if "-" in identifier else identifier
    response = polarion_request(config, _endpoint(config, "work_item", project=project, id=short))
    item = _items(response.get("data"))
    if not item and isinstance(response.get("data"), dict):
        item = [response["data"]]
    if not item:
        return f"Polarion returned nothing for {identifier}."
    attributes = item[0].get("attributes", {}) if isinstance(item[0].get("attributes"), dict) else {}
    wanted = [name.strip() for name in fields.split(",") if name.strip()] if fields else [
        "title", "type", "status", "resolution", "assignee", "severity", "priority", "description"
    ]
    lines = [f"{identifier}:"]
    for name in wanted:
        value = attributes.get(name)
        if isinstance(value, dict):
            value = value.get("value") or value.get("name") or value.get("id")
        if value is None:
            value = item[0].get(name)
        if value is None:
            continue
        text = re.sub(r"<[^>]+>", " ", str(value))
        text = re.sub(r"\s+", " ", text).strip()
        lines.append(f"  {name}: {text[:400]}")
    return "\n".join(lines)


def polarion_update_work_item(
    config: Any,
    id: str = "",
    work_item_id: str = "",
    field: str = "",
    value: str = "",
    fields: str = "",
    project: str = "",
) -> str:
    """Change one or more fields of a work item (title, status, assignee, custom field…)."""
    identifier = (id or work_item_id or "").strip()
    if not identifier:
        return "I need the work item id, for example PROJ-1234."
    updates: Dict[str, Any] = {}
    if fields:
        try:
            parsed = json.loads(fields)
            if isinstance(parsed, dict):
                updates.update(parsed)
        except ValueError:
            for pair in fields.split(","):
                if "=" in pair:
                    name, _, text = pair.partition("=")
                    updates[name.strip()] = text.strip()
    if field:
        updates[field] = value
    if not updates:
        return "Tell me which field to change and what to set it to."

    project = _project(config, project) or (identifier.split("-")[0] if "-" in identifier else "")
    short = identifier.split("-", 1)[1] if "-" in identifier else identifier
    body = {"data": {"type": "workitems", "id": f"{project}/{short}", "attributes": updates}}
    response = polarion_request(config, _endpoint(config, "work_item", project=project, id=short), method="PATCH", payload=body)
    changed = ", ".join(f"{name}={value!r}" for name, value in updates.items())
    return f"updated {identifier}: {changed} (HTTP {response.get('status')})"


def polarion_add_comment(config: Any, id: str = "", work_item_id: str = "", comment: str = "", text: str = "", project: str = "") -> str:
    """Add a comment to a work item (via the document's comment field where the
    server supports it, otherwise fall back to the UI)."""
    identifier = (id or work_item_id or "").strip()
    body_text = (comment or text or "").strip()
    if not identifier or not body_text:
        return "I need both the work item id and the comment text."
    settings = _settings(config)
    endpoints = dict(DEFAULT_ENDPOINTS)
    endpoints.update(dict(getattr(settings, "polarion_endpoints", {}) or {}))
    template = endpoints.get("comments")
    if not template:
        return (
            "This Polarion server is not configured with a comments endpoint, so I should add the "
            f"comment in the UI instead — open {identifier} and I will post it in the Comments box."
        )
    project = _project(config, project) or (identifier.split("-")[0] if "-" in identifier else "")
    short = identifier.split("-", 1)[1] if "-" in identifier else identifier
    path = template.format(project=project, id=short)
    payload = {"data": {"type": "comments", "attributes": {"text": {"type": "text/html", "value": body_text}}}}
    response = polarion_request(config, path, method="POST", payload=payload)
    return f"added the comment to {identifier} (HTTP {response.get('status')})"


def _items(data: Any) -> List[Dict[str, Any]]:
    """Pull the work-item list out of a JSON:API-ish response, whatever it looks like."""
    if isinstance(data, dict):
        if isinstance(data.get("data"), list):
            return [item for item in data["data"] if isinstance(item, dict)]
        if isinstance(data.get("data"), dict):
            return [data["data"]]
        for key in ("workitems", "items", "results"):
            if isinstance(data.get(key), list):
                return [item for item in data[key] if isinstance(item, dict)]
        if any(key in data for key in ("id", "attributes")):
            return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


# --- recipes ----------------------------------------------------------------

def _recipe(*, name: str, description: str, params: Dict[str, str], steps: List[Dict[str, Any]], defaults: Optional[Dict[str, Any]] = None) -> Recipe:
    recipe = Recipe(name=name, description=description, app="polarion", skill="polarion", params=params, defaults=defaults or {})
    for raw in steps:
        recipe.steps.append(
            RecipeStep(
                kind=str(raw.get("type") or "click"),
                params={key: value for key, value in raw.items() if key not in ("type", "note", "anchor")},
                note=str(raw.get("note") or ""),
                anchor=str(raw.get("anchor") or ""),
            )
        )
    return recipe


RECIPES: List[Recipe] = [
    _recipe(
        name="polarion-open-work-item",
        description="open a work item by its project-qualified id (and wait for it to load)",
        params={"work_item_id": "e.g. PROJ-1234"},
        steps=[
            {"type": "focus_window", "title": "Polarion", "note": "make sure Polarion is in front"},
            {"type": "click", "target": "Search", "anchor": "Search", "note": "the quick search box", "x": 420, "y": 96},
            {"type": "hotkey", "hotkey": "ctrl+a"},
            {"type": "type", "text": "{{work_item_id}}"},
            {"type": "key", "key": "Enter", "note": "opens the work item"},
            {"type": "wait", "seconds": 2.0},
        ],
    ),
    _recipe(
        name="polarion-set-status",
        description="change the Status of an open work item, following the workflow",
        params={"status": "the target status, exactly as the dropdown spells it"},
        steps=[
            {"type": "edit_field", "target": "Status", "anchor": "Status", "operation": "set", "value": "{{status}}", "note": "pick the status field"},
            {"type": "wait", "seconds": 0.6},
            {"type": "read_field", "target": "Status", "anchor": "Status", "note": "confirm the workflow accepted it"},
        ],
    ),
    _recipe(
        name="polarion-append-description",
        description="add text to the end of a work item's Description without losing what is there",
        params={"text": "the text to add"},
        steps=[
            {"type": "edit_field", "target": "Description", "anchor": "Description", "operation": "append", "value": "{{text}}", "note": "append rather than replace"},
            {"type": "wait", "seconds": 0.8},
        ],
    ),
    _recipe(
        name="polarion-search",
        description="search the project with a Lucene-style query",
        params={"query": "e.g. type:defect AND status:open"},
        steps=[
            {"type": "find", "text": "{{query}}", "note": "ctrl+f on the work-item table"},
            {"type": "wait", "seconds": 1.2},
        ],
    ),
]

TOOLS: List[SkillTool] = [
    SkillTool(
        name="polarion_search",
        description="search work items by Lucene query through the REST API",
        function=polarion_search,
        params={"query": "Lucene-style query", "project": "project id (optional)"},
        available=api_configured,
    ),
    SkillTool(
        name="polarion_get_work_item",
        description="read a work item's fields exactly (title, status, assignee, description)",
        function=polarion_get_work_item,
        params={"id": "work item id, e.g. PROJ-1234", "fields": "comma-separated fields (optional)"},
        available=api_configured,
    ),
    SkillTool(
        name="polarion_update_work_item",
        description="change fields on a work item through the REST API (exact, no clicking)",
        function=polarion_update_work_item,
        params={"id": "work item id", "field": "field name", "value": "new value"},
        writes=True,
        available=api_writes_allowed,
    ),
    SkillTool(
        name="polarion_add_comment",
        description="add a comment to a work item through the REST API",
        function=polarion_add_comment,
        params={"id": "work item id", "comment": "the comment text"},
        writes=True,
        available=lambda config: api_writes_allowed(config) and bool(
            getattr(_settings(config), "polarion_endpoints", {}).get("comments")
        ),
    ),
]


def build_skill() -> Skill:
    """The pack as an object (a function so users can rebuild after an overlay)."""
    return Skill(
        id="polarion",
        name="Polarion ALM",
        summary="Siemens Polarion ALM. Work items, their workflow states, and how to edit one without breaking the workflow.",
        window_patterns=DETECTION_WINDOW,
        url_patterns=DETECTION_URL,
        process_patterns=DETECTION_PROCESS,
        keywords=KEYWORDS,
        knowledge=list(KNOWLEDGE),
        shortcuts=dict(SHORTCUTS),
        glossary=dict(GLOSSARY),
        gotchas=list(GOTCHAS),
        editing_tips=list(EDITING_TIPS),
        prefer_api=True,
        recipes=list(RECIPES),
        tools=list(TOOLS),
        source="built-in",
    )


SKILL = build_skill()
