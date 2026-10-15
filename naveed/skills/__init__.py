"""Knowledge packs: what Naveed knows about a specific application.

* :mod:`naveed.skills.base` — the model (skills, recipes, tools) and the store;
* :mod:`naveed.skills.polarion` — the Polarion ALM pack, including REST tools;
* :mod:`naveed.skills.generic` — the rules that apply to editing in any app;
* :mod:`naveed.skills.recorder` — learn a task by performing it once.

Nothing here is imported at package import time beyond the lazy table, so
``import naveed`` stays cheap and a broken user pack cannot stop the app starting.
"""

from __future__ import annotations

from ..lazy import lazy_attrs

__all__ = [
    "Skill",
    "SkillStore",
    "SkillTool",
    "Recipe",
    "RecipeStep",
    "MatchResult",
    "ActionRecorder",
    "TeachingSession",
    "build_skill_context",
    "distill_recipe",
    "match_skills",
    "recipe_from_dict",
    "render_recipe",
    "skill_from_dict",
    "suggest_parameters",
]

__getattr__ = lazy_attrs(
    globals(),
    {
        "base": "naveed.skills.base",
        "Skill": "naveed.skills.base:Skill",
        "SkillStore": "naveed.skills.base:SkillStore",
        "SkillTool": "naveed.skills.base:SkillTool",
        "Recipe": "naveed.skills.base:Recipe",
        "RecipeStep": "naveed.skills.base:RecipeStep",
        "MatchResult": "naveed.skills.base:MatchResult",
        "build_skill_context": "naveed.skills.base:build_skill_context",
        "match_skills": "naveed.skills.base:match_skills",
        "render_recipe": "naveed.skills.base:render_recipe",
        "recipe_from_dict": "naveed.skills.base:recipe_from_dict",
        "skill_from_dict": "naveed.skills.base:skill_from_dict",
        "recorder": "naveed.skills.recorder",
        "ActionRecorder": "naveed.skills.recorder:ActionRecorder",
        "TeachingSession": "naveed.skills.recorder:TeachingSession",
        "distill_recipe": "naveed.skills.recorder:distill_recipe",
        "suggest_parameters": "naveed.skills.recorder:suggest_parameters",
        "polarion": "naveed.skills.polarion",
        "generic": "naveed.skills.generic",
    },
)
