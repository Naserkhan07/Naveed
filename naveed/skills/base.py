"""Knowledge packs: how Naveed is taught a specific application.

A small vision model knows YouTube. It does **not** know that a Polarion work
item's long description is a rich-text editor inside an iframe, that the status
field only offers the transitions the workflow allows, that `Save` is per-field
rather than per-page, or that the customer renamed "Severity" to something else.
Left to guess, the model flails for eighteen steps and gives up.

Fine-tuning a model is not something a desktop app can do on your machine, so
Naveed is taught the way a new colleague is: **someone tells it the facts, and
shows it the steps.** That is what a *skill* is:

* **detection** — window title / URL / process patterns that say "this is that
  app", plus keywords in the request;
* **knowledge** — short facts injected into the planner's prompt only while that
  app is in front (so they cost nothing elsewhere and never crowd out the other
  context);
* **shortcuts, glossary, gotchas** — the things that turn a 12-click detour into
  one keystroke or prevent a wrong assumption;
* **recipes** — named, parameterised step sequences: some shipped by hand, some
  **learned by watching you do it once** (:mod:`naveed.skills.recorder`);
* **tools** — optional direct calls (a REST API) for when clicking through a UI
  is simply the wrong tool for the job. Tools are only offered when they are
  actually configured, so the model never plans a route that cannot run.

Everything here is **data**, not code paths, so a pack can live in this package,
in `~/.naveed/skills/*.json`, or in the `learned/` folder that teaching writes to,
and all three are loaded the same way.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "RecipeStep",
    "Recipe",
    "SkillTool",
    "Skill",
    "SkillStore",
    "MatchResult",
    "render_recipe",
    "substitute",
    "match_skills",
    "build_skill_context",
    "recipe_from_dict",
    "skill_from_dict",
]

#: A parameter reference inside a recipe step, e.g. ``"{{title}}"``.
PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
#: How much skill text may be injected into one prompt. Small models do worse with
#: a long prompt, and the screenshots already cost more than this does.
CONTEXT_BUDGET = 3600
#: Share of a skill's budget reserved for the *facts* (so that a pack with a lot of
#: procedural detail cannot crowd out the things that are true about the app).
FACTS_SHARE = 0.26
#: And a ceiling for each actionable section, in characters.
SECTION_CAPS = {"shortcuts": 470, "gotchas": 360, "editing": 360, "tools": 700, "routines": 440}


def substitute(value: Any, arguments: Dict[str, Any]) -> Any:
    """Replace ``{{name}}`` placeholders in strings, lists and dicts."""
    if isinstance(value, str):
        def replace(match: re.Match) -> str:
            name = match.group(1)
            if name in arguments:
                return str(arguments[name])
            return match.group(0)

        return PLACEHOLDER.sub(replace, value)
    if isinstance(value, list):
        return [substitute(item, arguments) for item in value]
    if isinstance(value, dict):
        return {key: substitute(item, arguments) for key, item in value.items()}
    return value


def placeholders(value: Any) -> List[str]:
    """Every parameter name referenced inside *value*."""
    found: List[str] = []
    if isinstance(value, str):
        found.extend(PLACEHOLDER.findall(value))
    elif isinstance(value, list):
        for item in value:
            found.extend(placeholders(item))
    elif isinstance(value, dict):
        for item in value.values():
            found.extend(placeholders(item))
    return found


# --- recipes ---------------------------------------------------------------

@dataclass
class RecipeStep:
    """One recorded (or hand-written) step.

    Coordinates are recorded *relative to the active window* as well as on
    screen, and carry the visible text near the click (`anchor`). That is what
    lets a recipe still work when the window has been moved since it was taught:
    the absolute point is tried first, and the anchor is used to relocate the
    element when the window has shifted.
    """

    kind: str = "click"
    params: Dict[str, Any] = field(default_factory=dict)
    note: str = ""
    anchor: str = ""
    window: str = ""
    offset: Optional[Tuple[int, int]] = None   # (dx, dy) from the window's top-left
    button: str = "left"
    delay: float = 0.35

    def to_action_params(self) -> Dict[str, Any]:
        params = dict(self.params)
        if self.kind in ("click", "double_click", "right_click", "move") and self.offset is not None and "x" not in params:
            params["x"], params["y"] = self.offset
        if self.anchor and not params.get("target"):
            params["target"] = self.anchor
        return params

    def to_dict(self) -> Dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value not in (None, "", {}, [])}


@dataclass
class Recipe:
    """A named sequence of steps, with parameters."""

    name: str
    description: str = ""
    app: str = ""
    params: Dict[str, str] = field(default_factory=dict)     # name -> description
    defaults: Dict[str, Any] = field(default_factory=dict)
    steps: List[RecipeStep] = field(default_factory=list)
    skill: str = ""
    learned: bool = False
    source: str = ""
    runs: int = 0
    successes: int = 0

    # --- use ------------------------------------------------------------
    def missing_arguments(self, arguments: Dict[str, Any]) -> List[str]:
        needed = set(self.params) | set(placeholders([step.params for step in self.steps]))
        supplied = set(arguments) | set(self.defaults)
        return sorted(name for name in needed if name not in supplied)

    def render(self, arguments: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Expand to action dictionaries with the arguments filled in."""
        values = dict(self.defaults)
        values.update(arguments or {})
        rendered: List[Dict[str, Any]] = []
        for step in self.steps:
            params = substitute(step.to_action_params(), values)
            payload: Dict[str, Any] = {"type": step.kind}
            payload.update(params)
            if step.note:
                payload["note"] = substitute(step.note, values)
            rendered.append(payload)
        return rendered

    def signature(self) -> str:
        return f"{self.name}({', '.join(sorted(self.params))})"

    def describe(self) -> str:
        detail = f" — {self.description}" if self.description else ""
        return f"{self.signature()}{detail}"

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "name": self.name,
            "description": self.description,
            "app": self.app,
            "params": self.params,
            "defaults": self.defaults,
            "steps": [step.to_dict() for step in self.steps],
            "skill": self.skill,
            "learned": self.learned,
        }
        return {key: value for key, value in payload.items() if value not in ("", {}, [], None)}


def recipe_from_dict(payload: Dict[str, Any], *, skill: str = "", source: str = "") -> Recipe:
    """Build a recipe from JSON, tolerating the shapes a human might write."""
    steps: List[RecipeStep] = []
    for raw in payload.get("steps") or []:
        if isinstance(raw, str):
            # "type {{title}}" style shorthand.
            parts = raw.split(" ", 1)
            steps.append(RecipeStep(kind=parts[0], params={"text": parts[1]} if len(parts) > 1 else {}))
            continue
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("type") or raw.get("kind") or "click")
        params = {key: value for key, value in raw.items() if key not in ("type", "kind", "note", "anchor", "window", "offset", "button", "delay")}
        offset = raw.get("offset")
        steps.append(
            RecipeStep(
                kind=kind,
                params=params,
                note=str(raw.get("note") or ""),
                anchor=str(raw.get("anchor") or ""),
                window=str(raw.get("window") or ""),
                offset=tuple(offset) if isinstance(offset, (list, tuple)) and len(offset) == 2 else None,
                button=str(raw.get("button") or "left"),
                delay=float(raw.get("delay") or 0.35),
            )
        )
    return Recipe(
        name=str(payload.get("name") or "unnamed"),
        description=str(payload.get("description") or ""),
        app=str(payload.get("app") or ""),
        params={str(key): str(value) for key, value in (payload.get("params") or {}).items()},
        defaults=dict(payload.get("defaults") or {}),
        steps=steps,
        skill=str(payload.get("skill") or skill),
        learned=bool(payload.get("learned")),
        source=source,
    )


def render_recipe(recipe: Recipe, arguments: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    return recipe.render(arguments)


# --- tools (an API fast path) ----------------------------------------------

@dataclass
class SkillTool:
    """A direct call a skill offers, e.g. a REST request.

    ``available`` is checked before the tool is advertised to the model, so a
    pack whose API is not configured does not tempt the planner into a route that
    will fail. ``writes`` marks tools that change data; those are confirmed first
    and are logged like any other action.
    """

    name: str
    description: str
    function: Callable[..., Any]
    params: Dict[str, str] = field(default_factory=dict)
    writes: bool = False
    available: Optional[Callable[[Any], bool]] = None

    def is_available(self, config: Any) -> bool:
        if self.available is None:
            return True
        try:
            return bool(self.available(config))
        except Exception as error:  # a broken check must not break the app
            logger.debug("skill tool %s availability check failed: %s", self.name, error)
            return False

    def signature(self) -> str:
        return f"{self.name}({', '.join(self.params)})"

    def describe(self) -> str:
        return f"{self.signature()} — {self.description}"


# --- skills -----------------------------------------------------------------

@dataclass
class Skill:
    """One application's knowledge pack."""

    id: str
    name: str
    summary: str = ""
    # detection
    window_patterns: List[str] = field(default_factory=list)
    url_patterns: List[str] = field(default_factory=list)
    process_patterns: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    # teaching
    knowledge: List[str] = field(default_factory=list)
    shortcuts: Dict[str, str] = field(default_factory=dict)
    glossary: Dict[str, str] = field(default_factory=dict)
    gotchas: List[str] = field(default_factory=list)
    editing_tips: List[str] = field(default_factory=list)
    prefer_api: bool = False
    # assets
    recipes: List[Recipe] = field(default_factory=list)
    tools: List[SkillTool] = field(default_factory=list)
    source: str = ""
    enabled: bool = True

    # --- detection ------------------------------------------------------
    def matches_window(self, window: Any) -> bool:
        if window is None:
            return False
        haystacks = []
        for attribute in ("title", "process", "app", "name", "url"):
            value = getattr(window, attribute, None)
            if value:
                haystacks.append(str(value))
        if hasattr(window, "describe"):
            try:
                haystacks.append(str(window.describe()))
            except Exception:
                pass
        text = " ".join(haystacks).lower()
        if not text:
            return False
        for pattern in [*self.window_patterns, *self.process_patterns, *self.url_patterns]:
            try:
                if re.search(pattern, text, re.IGNORECASE):
                    return True
            except re.error:
                if pattern.lower() in text:
                    return True
        return False

    def matches_task(self, task: str) -> bool:
        lowered = (task or "").lower()
        return any(keyword.lower() in lowered for keyword in self.keywords if keyword)

    def recipe(self, name: str) -> Optional[Recipe]:
        wanted = (name or "").strip().lower()
        for recipe in self.recipes:
            if recipe.name.lower() == wanted:
                return recipe
        return None

    def tool(self, name: str) -> Optional[SkillTool]:
        for tool in self.tools:
            if tool.name.lower() == (name or "").strip().lower():
                return tool
        return None

    # --- overlays -------------------------------------------------------
    def merged(self, overlay: Dict[str, Any]) -> "Skill":
        """Apply a user's overlay (their project, their field names).

        This is how a pack is tuned to *your* instance without editing the
        shipped copy: lists are extended, dictionaries are merged, and scalars
        are replaced.
        """
        clone = Skill(**{**self.__dict__})
        clone.recipes = list(self.recipes)
        clone.tools = list(self.tools)
        for key, value in overlay.items():
            if not hasattr(clone, key):
                continue
            current = getattr(clone, key)
            if isinstance(current, list) and isinstance(value, list):
                setattr(clone, key, [*current, *value])
            elif isinstance(current, dict) and isinstance(value, dict):
                setattr(clone, key, {**current, **value})
            elif key == "recipes" and isinstance(value, list):
                clone.recipes = [*self.recipes, *[recipe_from_dict(item, skill=self.id) for item in value]]
            else:
                setattr(clone, key, value)
        return clone


def skill_from_dict(payload: Dict[str, Any], *, source: str = "") -> Skill:
    """Build a skill from JSON."""
    recipes = [recipe_from_dict(item, skill=str(payload.get("id") or ""), source=source) for item in payload.get("recipes") or []]
    return Skill(
        id=str(payload.get("id") or payload.get("name") or "skill"),
        name=str(payload.get("name") or payload.get("id") or "Skill"),
        summary=str(payload.get("summary") or ""),
        window_patterns=list(payload.get("window_patterns") or []),
        url_patterns=list(payload.get("url_patterns") or []),
        process_patterns=list(payload.get("process_patterns") or []),
        keywords=list(payload.get("keywords") or []),
        knowledge=list(payload.get("knowledge") or []),
        shortcuts=dict(payload.get("shortcuts") or {}),
        glossary=dict(payload.get("glossary") or {}),
        gotchas=list(payload.get("gotchas") or []),
        editing_tips=list(payload.get("editing_tips") or []),
        prefer_api=bool(payload.get("prefer_api")),
        recipes=recipes,
        source=source,
    )


# --- the store --------------------------------------------------------------

@dataclass
class MatchResult:
    """Why a skill was chosen, so the panel and the logs can say."""

    skill: Skill
    score: float
    reason: str

    def __bool__(self) -> bool:
        return self.score > 0


class SkillStore:
    """Every skill and recipe Naveed can use, from every source.

    Load order (later wins for overlays):

    1. the built-in packs in this package;
    2. ``~/.naveed/skills/*.json`` — your own packs and overlays;
    3. ``~/.naveed/skills/learned/*.json`` — recipes recorded with ``--teach``.
    """

    def __init__(self, config: Any = None, *, builtin: Optional[Sequence[Skill]] = None) -> None:
        self.config = config
        self.skills: List[Skill] = []
        self.learned: List[Recipe] = []
        self.errors: List[str] = []
        self._loaded = False
        if builtin is not None:
            self.skills.extend(builtin)
            self._loaded = True

    # --- discovery ------------------------------------------------------
    @property
    def directory(self) -> Path:
        configured = ""
        try:
            configured = str(getattr(getattr(self.config, "skills", None), "directory", "") or "")
        except Exception:
            configured = ""
        if configured:
            return Path(configured).expanduser()
        home = ""
        try:
            home = str(getattr(self.config, "home", "") or "")
        except Exception:
            home = ""
        base = Path(home) if home else Path.home() / ".naveed"
        return base / "skills"

    def _builtin_packs(self) -> List[Skill]:
        from . import generic, polarion  # local: keeps the package cheap to import

        return [polarion.SKILL, generic.SKILL]

    def load(self, *, force: bool = False) -> "SkillStore":
        if self._loaded and not force:
            return self
        if not self.skills:
            try:
                self.skills = self._builtin_packs()
            except Exception as error:  # pragma: no cover - defensive
                self.errors.append(f"built-in packs failed to load: {error}")
                self.skills = []
        self.learned = []
        directory = self.directory
        try:
            if directory.exists():
                self._load_directory(directory)
                learned_dir = directory / "learned"
                if learned_dir.exists():
                    self._load_recipes(learned_dir, learned=True)
        except OSError as error:
            self.errors.append(f"could not read {directory}: {error}")
        self._loaded = True
        return self

    def _load_directory(self, directory: Path) -> None:
        for path in sorted(directory.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                self.errors.append(f"{path.name}: {error}")
                continue
            entries = payload if isinstance(payload, list) else [payload]
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                if "id" in entry and any(key in entry for key in ("knowledge", "window_patterns", "recipes", "shortcuts")):
                    self.register(skill_from_dict(entry, source=str(path)), overlay=True)
                elif "steps" in entry:
                    self.learned.append(recipe_from_dict(entry, source=str(path)))
                elif "overlay_for" in entry:
                    self.apply_overlay(str(entry["overlay_for"]), entry, source=str(path))

    def _load_recipes(self, directory: Path, *, learned: bool) -> None:
        for path in sorted(directory.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                self.errors.append(f"{path.name}: {error}")
                continue
            entries = payload if isinstance(payload, list) else [payload]
            for entry in entries:
                if isinstance(entry, dict) and "steps" in entry:
                    recipe = recipe_from_dict(entry, source=str(path))
                    recipe.learned = learned or recipe.learned
                    self.learned.append(recipe)
                    self._attach(recipe)

    def register(self, skill: Skill, *, overlay: bool = False) -> Skill:
        """Add a skill, or merge it into an existing one of the same id."""
        for index, existing in enumerate(self.skills):
            if existing.id == skill.id:
                if overlay:
                    merged = existing.merged(skill.__dict__)
                    self.skills[index] = merged
                    return merged
                self.skills[index] = skill
                return skill
        self.skills.append(skill)
        return skill

    def apply_overlay(self, skill_id: str, payload: Dict[str, Any], *, source: str = "") -> None:
        for existing in self.skills:
            if existing.id == skill_id:
                data = {key: value for key, value in payload.items() if key != "overlay_for"}
                merged = existing.merged(data)
                merged.source = source or existing.source
                self.register(merged)
                return

    def _attach(self, recipe: Recipe) -> None:
        """Attach a learned recipe to the skill whose app it was recorded in."""
        target = recipe.skill or recipe.app
        for skill in self.skills:
            if not target:
                continue
            if target and (skill.id.lower() == str(target).lower() or skill.matches_window(_FakeWindow(target))):
                skill.recipes = [*skill.recipes, recipe]
                recipe.skill = skill.id
                return

    # --- queries --------------------------------------------------------
    def all_recipes(self) -> List[Recipe]:
        seen: List[Recipe] = []
        for skill in self.skills:
            seen.extend(skill.recipes)
        seen.extend(recipe for recipe in self.learned if recipe not in seen)
        return seen

    def find_recipe(self, name: str) -> Optional[Recipe]:
        wanted = (name or "").strip().lower()
        for recipe in self.all_recipes():
            if recipe.name.lower() == wanted:
                return recipe
        # Allow "skill:recipe" and unique-prefix lookups.
        for recipe in self.all_recipes():
            if recipe.name.lower().endswith(":" + wanted) or recipe.name.lower().startswith(wanted):
                return recipe
        return None

    def find_skill(self, skill_id: str) -> Optional[Skill]:
        for skill in self.skills:
            if skill.id.lower() == (skill_id or "").strip().lower():
                return skill
        return None

    def summaries(self) -> List[Dict[str, Any]]:
        rows = []
        for skill in self.skills:
            rows.append(
                {
                    "id": skill.id,
                    "name": skill.name,
                    "summary": skill.summary,
                    "window_patterns": skill.window_patterns,
                    "knowledge": len(skill.knowledge),
                    "recipes": [recipe.signature() for recipe in skill.recipes],
                    "tools": [tool.signature() for tool in skill.tools],
                    "source": skill.source or "built-in",
                }
            )
        return rows

    def save_recipe(self, recipe: Recipe, *, directory: Optional[Path] = None) -> Path:
        target_dir = directory or (self.directory / "learned")
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{recipe.name}.json"
        payload = recipe.to_dict()
        payload["learned"] = True
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        # keep the in-memory copy in step with what is on disk
        existing = self.find_recipe(recipe.name)
        if existing is None:
            self.learned.append(recipe)
            self._attach(recipe)
        else:
            existing.steps = recipe.steps
            existing.params = recipe.params
            existing.defaults = recipe.defaults
            existing.description = recipe.description
        return path


@dataclass
class _FakeWindow:
    """A window stand-in, so a recipe's app name can be matched as a title."""

    title: str = ""
    process: str = ""
    app: str = ""

    def __init__(self, title: str) -> None:
        self.title = title
        self.process = title
        self.app = ""

    def describe(self) -> str:
        return self.title


# --- matching ---------------------------------------------------------------

def match_skills(
    store: SkillStore,
    *,
    window: Any = None,
    task: str = "",
    limit: int = 2,
) -> List[MatchResult]:
    """The skills that apply right now, best first.

    The window is the strongest signal — the app in front is where actions will
    land — so a window match outranks a word in the request. Both can match at
    once ("update the Polarion work item" said while Polarion is in front).
    """
    store.load()
    results: List[MatchResult] = []
    for skill in store.skills:
        if not skill.enabled:
            continue
        score = 0.0
        reasons: List[str] = []
        if window is not None and skill.matches_window(window):
            score += 2.0
            reasons.append("it is the app in front")
        if task and skill.matches_task(task):
            score += 1.0
            reasons.append("the request mentions it")
        if score > 0:
            results.append(MatchResult(skill=skill, score=score, reason=" and ".join(reasons)))
    results.sort(key=lambda result: (-result.score, result.skill.id))
    return results[:limit]


# --- prompt composition -----------------------------------------------------

def build_skill_context(
    matches: Sequence[MatchResult],
    *,
    task: str = "",
    budget: int = CONTEXT_BUDGET,
    config: Any = None,
) -> str:
    """The block injected into the planner prompt for the matched skills.

    Ordered by usefulness, and that order is the whole point: a 7B model reads
    the start of a long prompt and the last couple of lines, and skips the middle.
    So the **actionable** sections — shortcuts, the traps, the editing route, and
    the exact JSON for any recipe or tool that is available — are protected by the
    budget, and the prose facts are what gets trimmed when space runs short.

    (That was a real bug, not a hypothetical: the Polarion facts alone filled the
    budget, so the model never saw the shortcuts or the routines, which are the
    parts that make it competent in that app rather than merely informed.)
    """
    if not matches:
        return ""
    budget = max(400, int(budget))
    per_skill_budget = max(320, budget // len(matches))
    sections: List[str] = []

    for result in matches:
        skill = result.skill
        head: List[str] = [f"=== YOU ARE WORKING IN {skill.name.upper()} ({result.reason}) ==="]
        if skill.summary:
            head.append(skill.summary)

        # --- what to do (kept) ------------------------------------------
        actionable: List[str] = []
        if skill.shortcuts:
            lines = ["SHORTCUTS (use a hotkey action rather than hunting through menus):"]
            lines.extend(f"- {name}: {chord}" for name, chord in list(skill.shortcuts.items())[:12])
            actionable.append(_truncate_lines("\n".join(lines), SECTION_CAPS["shortcuts"]))
        if skill.gotchas:
            block_lines = ["WATCH OUT:", *(f"- {gotcha}" for gotcha in skill.gotchas[:6])]
            actionable.append(_truncate_lines("\n".join(block_lines), SECTION_CAPS["gotchas"]))
        if skill.editing_tips:
            block_lines = ["EDITING THIS APP:", *(f"- {tip}" for tip in skill.editing_tips[:5])]
            actionable.append(_truncate_lines("\n".join(block_lines), SECTION_CAPS["editing"]))

        available_tools = [tool for tool in skill.tools if tool.is_available(config)]
        if available_tools:
            lines = ["DIRECT TOOLS (exact, fast — prefer these when they fit the request):"]
            for tool in available_tools[:6]:
                schema = ", ".join('"%s": "..."' % name for name in tool.params)
                lines.append(
                    f'- {{"type":"skill_tool","skill":"{skill.id}","tool":"{tool.name}",'
                    f'"args":{{{schema}}}}} — {tool.description}'
                )
            actionable.append(_truncate_lines("\n".join(lines), SECTION_CAPS["tools"]))
        if skill.recipes:
            lines = ['KNOWN ROUTINES (send {"type":"recipe","name":...,"args":{...}} to run one):']
            for recipe in skill.recipes[:8]:
                arguments = ", ".join(recipe.params) or "none"
                lines.append(f'- "{recipe.name}" — {recipe.description or "recorded earlier"}; args: {arguments}')
            actionable.append(_truncate_lines("\n".join(lines), SECTION_CAPS["routines"]))

        # --- what is true (trimmed first) -------------------------------
        facts: List[str] = []
        if skill.knowledge:
            facts.append("FACTS:")
            facts.extend(f"- {fact}" for fact in skill.knowledge)
        if skill.glossary:
            pairs = "; ".join(f"{term} = {meaning}" for term, meaning in list(skill.glossary.items())[:10])
            facts.append(f"TERMS: {pairs}")

        header = "\n".join(head)
        tail = "\n".join(actionable)
        facts_text = "\n".join(facts)
        # Facts get a guaranteed share; the actionable sections get theirs. Neither
        # is allowed to squeeze the other out entirely.
        room = min(int(per_skill_budget * FACTS_SHARE), max(0, per_skill_budget - len(header) - 40))
        facts_text = _truncate_lines(facts_text, room) if room > 120 else ""
        block = "\n".join(part for part in (header, facts_text, tail) if part)
        if len(block) > per_skill_budget:
            # Only now is the actionable text touched, and the cut is announced so
            # the model knows that something was withheld.
            block = _truncate_lines(block, max(200, per_skill_budget - 30)) + "\n…(more notes omitted)"
        sections.append(block)

    return "\n\n".join(sections)


def _truncate_lines(text: str, limit: int) -> str:
    """Trim *text* to at most *limit* characters, on a line boundary.

    A single line longer than the limit is cut with an ellipsis rather than
    dropped — an early version discarded whole sections this way, which quietly
    removed the shortcuts from the prompt.
    """
    if limit <= 0 or not text:
        return ""
    if len(text) <= limit:
        return text
    kept: List[str] = []
    used = 0
    for line in text.splitlines():
        if used + len(line) + 1 > limit:
            room = limit - used
            if room > 20:
                kept.append(line[: room - 1] + "…")
            break
        kept.append(line)
        used += len(line) + 1
    return "\n".join(kept)
