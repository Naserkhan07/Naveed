"""Knowledge packs, recipes, teaching, and the Polarion pack.

The claim being tested is the whole point of the subsystem: **Naveed can be taught
a specific application's task without anyone fine-tuning a model.** That means
four things have to work together, so all four are covered here:

1. a pack's knowledge reaches the planner's prompt *only* when the right app is in
   front, and stays inside its size budget;
2. a recorded demonstration turns into a recipe with parameters, and replays;
3. a `recipe` action expands into real, safety-checked steps (it is shorthand,
   not a bypass);
4. an API tool is offered only when it is configured, and a tool that writes data
   cannot run without confirmation.

Nothing here needs a display, a model, a mouse or a network connection: the
Polarion HTTP calls are stubbed, and the input side uses the fake field from
`tests/test_editing.py`.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from naveed.config import load_config
from naveed.skills import base as skills_base
from naveed.skills import polarion
from naveed.skills.base import (
    Recipe,
    RecipeStep,
    SkillStore,
    build_skill_context,
    match_skills,
    recipe_from_dict,
    render_recipe,
    skill_from_dict,
)
from naveed.skills.recorder import ActionRecorder, RecordedEvent, TeachingSession, distill_recipe, suggest_parameters

from test_editing import FakeController, FakeField


class FakeWindow:
    """A window that a pack can be matched against."""

    def __init__(self, title: str, process: str = "chrome", url: str = "") -> None:
        self.title = title
        self.process = process
        self.url = url

    def describe(self) -> str:
        return self.title


POLARION_WINDOW = FakeWindow("PROJ-1042 - Requirement - Polarion — Chrome", "chrome", "https://alm.example/polarion/#/project/PROJ/workitem?id=PROJ-1042")
EDITOR_WINDOW = FakeWindow("main.py — naveed — Visual Studio Code", "code")


class PackLoadingTests(unittest.TestCase):
    def test_built_in_packs_load(self):
        store = SkillStore(load_config()).load()
        ids = [skill.id for skill in store.skills]
        self.assertIn("polarion", ids)
        self.assertIn("generic", ids)
        self.assertEqual(store.errors, [])

    def test_polarion_pack_carries_the_knowledge_it_claims(self):
        skill = polarion.SKILL
        self.assertGreaterEqual(len(skill.knowledge), 10)
        self.assertGreaterEqual(len(skill.shortcuts), 5)
        self.assertGreaterEqual(len(skill.gotchas), 5)
        self.assertGreaterEqual(len(skill.recipes), 4)
        # Every recipe must be usable: named, described, and with declared params.
        for recipe in skill.recipes:
            self.assertTrue(recipe.name.startswith("polarion"))
            self.assertTrue(recipe.description)
            self.assertTrue(recipe.steps)

    def test_recipes_only_reference_real_actions(self):
        from naveed.control.actions import ACTION_KINDS

        for recipe in polarion.SKILL.recipes + skills_base.SkillStore(load_config()).load().find_skill("generic").recipes:
            for step in recipe.steps:
                self.assertIn(step.kind, ACTION_KINDS, f"{recipe.name} uses {step.kind}")

    def test_a_skill_loads_from_json(self):
        skill = skill_from_dict(
            {
                "id": "jira",
                "name": "Jira",
                "window_patterns": ["jira"],
                "knowledge": ["issues are keyed PROJ-123"],
                "shortcuts": {"new issue": "c"},
                "recipes": [{"name": "jira-comment", "params": {"text": "the comment"}, "steps": [{"type": "type", "text": "{{text}}"}]}],
            }
        )
        self.assertEqual(skill.id, "jira")
        self.assertEqual(skill.recipes[0].name, "jira-comment")
        self.assertEqual(skill.recipes[0].params["text"], "the comment")

    def test_user_packs_and_overlays_are_loaded_from_the_skills_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "skills"
            directory.mkdir()
            (directory / "mine.json").write_text(
                json.dumps({"id": "acme", "name": "Acme", "window_patterns": ["acme"], "knowledge": ["the customer portal"]}),
                encoding="utf-8",
            )
            (directory / "polarion.local.json").write_text(
                json.dumps(
                    {
                        "overlay_for": "polarion",
                        "knowledge": ["Our project id is PROJ and the field is called 'Verified By'."],
                        "shortcuts": {"our status shortcut": "ctrl+alt+s"},
                    }
                ),
                encoding="utf-8",
            )
            config = load_config()
            config.skills.directory = str(directory)
            store = SkillStore(config).load()
            ids = [skill.id for skill in store.skills]
            self.assertIn("acme", ids)
            polarion_skill = store.find_skill("polarion")
            self.assertTrue(any("Verified By" in fact for fact in polarion_skill.knowledge), "overlay knowledge must be merged in")
            self.assertIn("our status shortcut", polarion_skill.shortcuts)

    def test_a_broken_pack_file_is_reported_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "skills"
            directory.mkdir()
            (directory / "broken.json").write_text("{not json at all", encoding="utf-8")
            config = load_config()
            config.skills.directory = str(directory)
            store = SkillStore(config).load()
            self.assertTrue(store.skills, "the built-in packs must still load")
            self.assertTrue(store.errors)


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.store = SkillStore(load_config()).load()

    def test_a_polarion_window_selects_the_polarion_pack(self):
        matches = match_skills(self.store, window=POLARION_WINDOW, task="set the status")
        self.assertTrue(matches)
        self.assertEqual(matches[0].skill.id, "polarion")
        self.assertIn("app in front", matches[0].reason)

    def test_a_polarion_request_selects_the_pack_even_from_another_app(self):
        matches = match_skills(self.store, window=EDITOR_WINDOW, task="open the polarion work item PROJ-42")
        ids = [match.skill.id for match in matches]
        self.assertIn("polarion", ids)
        polarion_match = next(match for match in matches if match.skill.id == "polarion")
        self.assertIn("request mentions it", polarion_match.reason)

    def test_a_window_match_outranks_a_mention(self):
        matches = match_skills(self.store, window=POLARION_WINDOW, task="polarion work item")
        self.assertEqual(matches[0].skill.id, "polarion")
        self.assertEqual(matches[0].score, 3.0)   # window + keyword

    def test_an_unrelated_window_selects_nothing_specific(self):
        matches = match_skills(self.store, window=EDITOR_WINDOW, task="fix the import error")
        self.assertEqual([match.skill.id for match in matches], [])

    def test_detection_accepts_urls_and_processes(self):
        skill = polarion.SKILL
        self.assertTrue(skill.matches_window(FakeWindow("whatever", "chrome", "https://alm.example/polarion/#/project/PROJ")))
        self.assertTrue(skill.matches_window(FakeWindow("Polarion", "polarion")))
        self.assertFalse(skill.matches_window(FakeWindow("Gmail", "chrome", "https://mail.google.com")))


class PromptInjectionTests(unittest.TestCase):
    def setUp(self):
        self.store = SkillStore(load_config()).load()
        self.config = load_config()

    def context(self, window, task=""):
        matches = match_skills(self.store, window=window, task=task)
        return build_skill_context(matches, task=task, config=self.config)

    def test_the_context_names_the_app_and_states_the_facts(self):
        block = self.context(POLARION_WINDOW, "set the status of PROJ-1042")
        self.assertIn("POLARION", block)
        self.assertIn("FACTS:", block)
        self.assertIn("SHORTCUTS", block)
        self.assertIn("WATCH OUT", block)
        self.assertIn("work item", block.lower())

    def test_editing_guidance_is_included(self):
        block = self.context(POLARION_WINDOW)
        self.assertIn("EDITING THIS APP", block)
        self.assertIn("read_field", block)

    def test_the_context_stays_inside_its_budget(self):
        matches = match_skills(self.store, window=POLARION_WINDOW, task="polarion work item")
        block = build_skill_context(matches, budget=800, config=self.config)
        self.assertLessEqual(len(block), 900)

    def test_without_matches_the_prompt_gains_nothing(self):
        self.assertEqual(self.context(EDITOR_WINDOW), "")

    def test_api_tools_are_only_advertised_once_configured(self):
        block = self.context(POLARION_WINDOW)
        self.assertNotIn("polarion_update_work_item", block, "an unconfigured API must not tempt the model")

        config = load_config()
        config.skills.polarion_base_url = "https://alm.example"
        config.skills.allow_api_writes = True
        matches = match_skills(self.store, window=POLARION_WINDOW, task="polarion work item")
        block = build_skill_context(matches, config=config)
        self.assertIn("polarion_update_work_item", block)
        self.assertIn('"type":"skill_tool"', block.replace(" ", ""))

    def test_read_only_tools_appear_without_write_permission(self):
        config = load_config()
        config.skills.polarion_base_url = "https://alm.example"
        matches = match_skills(self.store, window=POLARION_WINDOW)
        block = build_skill_context(matches, config=config)
        self.assertIn("polarion_get_work_item", block)
        self.assertNotIn("polarion_update_work_item", block)

    def test_routines_are_advertised_by_name_with_their_arguments(self):
        block = self.context(POLARION_WINDOW)
        self.assertIn("KNOWN ROUTINES", block)
        self.assertIn("polarion-set-status", block)
        self.assertIn("status", block)


class RecipeTests(unittest.TestCase):
    def test_rendering_fills_in_the_arguments(self):
        recipe = Recipe(
            name="demo",
            params={"who": "a name"},
            steps=[RecipeStep(kind="type", params={"text": "hello {{who}}"}), RecipeStep(kind="click", params={"x": 1, "y": 2})],
        )
        rendered = render_recipe(recipe, {"who": "Naseer"})
        self.assertEqual(rendered[0]["type"], "type")
        self.assertEqual(rendered[0]["text"], "hello Naseer")
        self.assertEqual(rendered[1]["type"], "click")

    def test_defaults_fill_missing_arguments(self):
        recipe = Recipe(name="demo", params={"status": "state"}, defaults={"status": "Open"}, steps=[RecipeStep(kind="type", params={"text": "{{status}}"})])
        self.assertEqual(recipe.missing_arguments({}), [])
        self.assertEqual(render_recipe(recipe)[0]["text"], "Open")

    def test_missing_arguments_are_reported(self):
        recipe = Recipe(name="demo", params={"status": "state", "id": "the id"}, steps=[RecipeStep(kind="type", params={"text": "{{status}}"})])
        self.assertEqual(recipe.missing_arguments({}), ["id", "status"])

    def test_parameters_hidden_inside_steps_are_still_required(self):
        recipe = Recipe(name="demo", steps=[RecipeStep(kind="type", params={"text": "{{later}}"})])
        self.assertEqual(recipe.missing_arguments({}), ["later"])

    def test_recipe_json_round_trip(self):
        payload = {
            "name": "polaris",
            "description": "d",
            "params": {"id": "work item id"},
            "steps": [
                {"type": "click", "x": 10, "y": 20, "anchor": "Search", "offset": [4, 8], "note": "the box"},
                {"type": "hotkey", "hotkey": "ctrl+s"},
            ],
        }
        recipe = recipe_from_dict(payload)
        self.assertEqual(recipe.steps[0].anchor, "Search")
        self.assertEqual(recipe.steps[0].offset, (4, 8))
        self.assertEqual(recipe.to_dict()["steps"][0]["anchor"], "Search")


class StorePersistenceTests(unittest.TestCase):
    def test_a_learned_recipe_is_saved_and_found_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config()
            config.skills.directory = str(Path(tmp) / "skills")
            store = SkillStore(config).load()

            recipe = Recipe(name="polarion-my-task", description="mine", app="polarion", params={"id": "the id"},
                            steps=[RecipeStep(kind="click", params={"x": 5, "y": 6})], learned=True)
            path = store.save_recipe(recipe)
            self.assertTrue(Path(path).exists())
            self.assertIn("learned", str(path))

            reloaded = SkillStore(config).load()
            found = reloaded.find_recipe("polarion-my-task")
            self.assertIsNotNone(found)
            self.assertTrue(found.learned)
            self.assertEqual(found.params, {"id": "the id"})

    def test_a_learned_recipe_attaches_to_the_app_it_was_taught_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config()
            config.skills.directory = str(Path(tmp) / "skills")
            store = SkillStore(config).load()
            store.save_recipe(
                Recipe(name="polarion-weekly", app="Polarion", skill="polarion", steps=[RecipeStep(kind="wait", params={"seconds": 1})], learned=True)
            )
            reloaded = SkillStore(config).load()
            polarion_skill = reloaded.find_skill("polarion")
            self.assertIn("polarion-weekly", [recipe.name for recipe in polarion_skill.recipes])

    def test_find_recipe_accepts_a_unique_prefix(self):
        store = SkillStore(load_config()).load()
        self.assertIsNotNone(store.find_recipe("polarion-set-status"))
        self.assertIsNotNone(store.find_recipe("polarion-set"))


class TeachingTests(unittest.TestCase):
    """Recording a demonstration and turning it into a recipe."""

    def record(self, events):
        session = TeachingSession(name="taught-task", started=0.0, window_at_start="Polarion", window_rect=(100, 50, 1200, 800))
        for event in events:
            event.window = event.window or "Polarion"
            event.window_rect = event.window_rect or (100, 50, 1200, 800)
            session.events.append(event)
        return session

    def test_a_demonstration_becomes_ordered_steps(self):
        session = self.record([
            RecordedEvent(kind="click", at=1.0, x=300, y=200),
            RecordedEvent(kind="text", at=1.4, text="PROJ-1042"),
            RecordedEvent(kind="key", at=2.0, key="enter"),
        ])
        recipe = distill_recipe(session)
        kinds = [step.kind for step in recipe.steps]
        self.assertEqual(kinds, ["click", "type", "key"])
        self.assertEqual(recipe.steps[1].params["text"], "PROJ-1042")
        self.assertEqual(recipe.steps[2].params["key"], "enter")

    def test_clicks_keep_their_offset_inside_the_window(self):
        session = self.record([RecordedEvent(kind="click", at=1.0, x=340, y=120)])
        recipe = distill_recipe(session)
        # 340-100, 120-50
        self.assertEqual(recipe.steps[0].offset, (240, 70))

    def test_typing_is_joined_into_one_step_and_split_on_a_pause(self):
        session = self.record([
            RecordedEvent(kind="text", at=1.0, text="hello"),
            RecordedEvent(kind="text", at=1.1, text=" world"),
            RecordedEvent(kind="text", at=5.0, text="second"),
        ])
        recipe = distill_recipe(session)
        self.assertEqual([step.kind for step in recipe.steps], ["type", "type"])
        self.assertEqual(recipe.steps[0].params["text"], "hello world")
        self.assertEqual(recipe.steps[1].params["text"], "second")

    def test_a_chord_is_recorded_as_a_chord_not_as_text(self):
        session = self.record([
            RecordedEvent(kind="text", at=1.0, text="hello"),
            RecordedEvent(kind="key", at=1.2, key="a", modifiers=("ctrl",)),
            RecordedEvent(kind="key", at=1.6, key="s", modifiers=("ctrl", "shift")),
        ])
        recipe = distill_recipe(session)
        self.assertEqual([step.kind for step in recipe.steps], ["type", "hotkey", "hotkey"])
        self.assertEqual(recipe.steps[1].params["hotkey"], "ctrl+a")
        self.assertEqual(recipe.steps[2].params["hotkey"], "ctrl+shift+s")

    def test_two_quick_clicks_become_a_double_click(self):
        session = self.record([
            RecordedEvent(kind="click", at=1.0, x=500, y=400),
            RecordedEvent(kind="click", at=1.2, x=502, y=401),
        ])
        recipe = distill_recipe(session)
        self.assertEqual([step.kind for step in recipe.steps], ["double_click"])

    def test_two_slow_clicks_stay_two_clicks(self):
        session = self.record([
            RecordedEvent(kind="click", at=1.0, x=500, y=400),
            RecordedEvent(kind="click", at=4.0, x=500, y=400),
        ])
        recipe = distill_recipe(session)
        self.assertEqual([step.kind for step in recipe.steps], ["click", "click"])

    def test_a_right_click_stays_a_right_click(self):
        session = self.record([RecordedEvent(kind="click", at=1.0, x=10, y=10, button="right")])
        recipe = distill_recipe(session)
        self.assertEqual(recipe.steps[0].kind, "right_click")

    def test_the_visible_label_becomes_the_anchor(self):
        session = self.record([RecordedEvent(kind="click", at=1.0, x=300, y=200, screenshot="/tmp/shot.png")])
        recipe = distill_recipe(session, ocr=lambda path, x, y: "Status")
        step = recipe.steps[0]
        self.assertEqual(step.anchor, "Status")
        self.assertEqual(step.params["target"], "Status")
        self.assertEqual(step.window, "Polarion")

    def test_an_ocr_failure_leaves_the_coordinates_usable(self):
        session = self.record([RecordedEvent(kind="click", at=1.0, x=300, y=200, screenshot="/tmp/shot.png")])

        def broken(path, x, y):
            raise RuntimeError("no engine")

        recipe = distill_recipe(session, ocr=broken)
        self.assertEqual(recipe.steps[0].params["x"], 300)
        self.assertEqual(recipe.steps[0].anchor, "")

    def test_typed_values_become_parameters_when_told_to(self):
        session = self.record([
            RecordedEvent(kind="text", at=1.0, text="PROJ-1042"),
            RecordedEvent(kind="click", at=2.0, x=1, y=1),
            RecordedEvent(kind="text", at=2.4, text="Verified"),
        ])
        recipe = distill_recipe(session, variables={"PROJ-1042": "work_item_id", "Verified": "status"})
        texts = [step.params.get("text") for step in recipe.steps if step.kind == "type"]
        self.assertEqual(texts, ["{{work_item_id}}", "{{status}}"])
        self.assertEqual(set(recipe.params), {"work_item_id", "status"})

    def test_parameter_suggestions_are_shy_about_fixed_labels(self):
        suggestions = suggest_parameters(["PROJ-1042", "Verified", "naseer@example.com", "2026-01-31", "12"])
        self.assertEqual(suggestions["PROJ-1042"], "work_item_id")
        self.assertEqual(suggestions["naseer@example.com"], "email")
        self.assertEqual(suggestions["2026-01-31"], "date")
        self.assertNotIn("Verified", suggestions, "a fixed word like a status value is not a parameter")
        self.assertNotIn("12", suggestions)

    def test_two_values_that_suggest_the_same_name_get_distinct_names(self):
        suggestions = suggest_parameters(["PROJ-1", "PROJ-2"])
        self.assertEqual(set(suggestions.values()), {"work_item_id", "work_item_id_2"})

    def test_the_recorder_wraps_all_of_this(self):
        recorder = ActionRecorder("taught", window=lambda: FakeWindow("Polarion"), now=lambda: 0.0)
        recorder.start()
        recorder.click(100, 200, at=1.0)
        recorder.key("a", modifiers=("ctrl",), at=1.5)
        recorder.type("hello", at=1.8)
        session = recorder.stop()
        self.assertGreater(session.duration, 0)
        recipe = recorder.recipe(variables={})
        self.assertEqual([step.kind for step in recipe.steps], ["click", "hotkey", "type"])
        self.assertEqual(recipe.app, "Polarion")

    def test_an_empty_recording_produces_no_steps_rather_than_a_broken_recipe(self):
        recipe = distill_recipe(TeachingSession(name="nothing"))
        self.assertEqual(recipe.steps, [])


class TaughtTaskReplaysTests(unittest.TestCase):
    """The end-to-end promise: demonstrate once, replay without a model."""

    def test_a_taught_recipe_replays_against_a_real_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config()
            config.skills.directory = str(Path(tmp) / "skills")
            store = SkillStore(config).load()

            # 1. the demonstration: click the field, select all, type the new status
            session = TeachingSession(name="polarion-set-status-ish", window_at_start="Polarion", window_rect=(0, 0, 1000, 700))
            session.events = [
                RecordedEvent(kind="click", at=1.0, x=300, y=200),
                RecordedEvent(kind="key", at=1.4, key="a", modifiers=("ctrl",)),
                RecordedEvent(kind="text", at=1.8, text="Verified"),
            ]
            recipe = distill_recipe(session, variables={"Verified": "status"}, description="taught")
            store.save_recipe(recipe)

            # 2. replay through the real controller and a fake field
            from naveed.control.actions import normalize_action
            from naveed.control.os_control import OsController

            field = FakeField("Open")
            controller = FakeController(field)
            os_controller = OsController(config, input_controller=controller)
            os_controller.global_point = lambda action, frame=None, **kwargs: (action.x, action.y)
            field.text = "INITIAL"   # ctrl+a then typing replaces the selection

            reloaded = SkillStore(config).load()
            found = reloaded.find_recipe("polarion-set-status-ish")
            self.assertIsNotNone(found)

            messages = []
            for payload in render_recipe(found, {"status": "Verified"}):
                action = normalize_action(payload)
                action.params.pop("target", None)
                result = os_controller.perform(action)
                messages.append((action.kind, result.ok, result.message))
            self.assertTrue(all(ok for _kind, ok, _message in messages), messages)
            self.assertEqual(field.text, "INITIALVerified")


class PolarionApiTests(unittest.TestCase):
    """The REST fast path, with the network stubbed out."""

    def setUp(self):
        self.config = load_config()
        self.calls = []
        self.original = polarion.polarion_request

        def fake_request(config, path, *, method="GET", payload=None, timeout=30.0):
            self.calls.append({"path": path, "method": method, "payload": payload})
            if "/workitems/1042" in path and method == "GET":
                return {
                    "status": 200,
                    "data": {
                        "data": {
                            "id": "PROJ/PROJ-1042",
                            "attributes": {
                                "title": "The work item title",
                                "status": "open",
                                "assignee": {"name": "Naseer"},
                                "description": {"type": "text/html", "value": "<p>Some <b>html</b></p>"},
                            },
                        }
                    },
                }
            if method == "GET":
                return {"status": 200, "data": {"data": [{"id": "PROJ/PROJ-1", "attributes": {"title": "First", "status": "open"}}]}}
            return {"status": 200, "data": {}}

        polarion.polarion_request = fake_request

    def tearDown(self):
        polarion.polarion_request = self.original

    def configured(self, *, writes=True):
        config = load_config()
        config.skills.polarion_base_url = "https://alm.example"
        config.skills.polarion_token = "token-123"
        config.skills.polarion_project = "PROJ"
        config.skills.allow_api_writes = writes
        return config

    def test_tools_are_unavailable_until_the_server_is_configured(self):
        config = load_config()
        self.assertFalse(polarion.api_configured(config))
        self.assertFalse(polarion.api_writes_allowed(config))
        self.assertTrue(all(not tool.is_available(config) for tool in polarion.TOOLS))

    def test_reads_work_when_only_a_base_url_is_set(self):
        config = self.configured(writes=False)
        tool = next(tool for tool in polarion.TOOLS if tool.name == "polarion_get_work_item")
        self.assertTrue(tool.is_available(config))
        write_tool = next(tool for tool in polarion.TOOLS if tool.name == "polarion_update_work_item")
        self.assertFalse(write_tool.is_available(config), "writes need explicit permission")

    def test_reading_a_work_item_flattens_the_fields(self):
        text = polarion.polarion_get_work_item(self.configured(), id="PROJ-1042")
        self.assertIn("PROJ-1042", text)
        self.assertIn("the work item title", text.lower())
        self.assertIn("open", text)
        self.assertIn("Naseer", text)
        self.assertNotIn("<b>", text, "html must be flattened for the model")
        self.assertEqual(self.calls[0]["method"], "GET")
        self.assertIn("/projects/PROJ/workitems/1042", self.calls[0]["path"])

    def test_updating_a_work_item_patches_only_what_was_asked(self):
        message = polarion.polarion_update_work_item(self.configured(), id="PROJ-1042", field="status", value="verified")
        self.assertIn("updated PROJ-1042", message)
        call = self.calls[-1]
        self.assertEqual(call["method"], "PATCH")
        self.assertEqual(call["payload"]["data"]["attributes"], {"status": "verified"})

    def test_several_fields_can_be_updated_at_once(self):
        polarion.polarion_update_work_item(self.configured(), id="PROJ-1042", fields="status=verified,severity=high")
        self.assertEqual(self.calls[-1]["payload"]["data"]["attributes"], {"status": "verified", "severity": "high"})

    def test_search_returns_readable_rows(self):
        text = polarion.polarion_search(self.configured(), query="type:defect")
        self.assertIn("PROJ-1", text)
        self.assertIn("First", text)
        self.assertIn("type%3Adefect", self.calls[-1]["path"], "the query must be url-encoded")

    def test_search_without_a_project_id_explains_itself(self):
        config = self.configured()
        config.skills.polarion_project = ""
        message = polarion.polarion_search(config, query="x")
        self.assertIn("project id", message)
        self.assertEqual(self.calls, [])

    def test_a_missing_base_url_never_points_at_a_random_server(self):
        polarion.polarion_request = self.original  # the stub would hide the guard
        with self.assertRaises(RuntimeError) as caught:
            polarion.polarion_get_work_item(load_config(), id="PROJ-1")
        self.assertIn("not configured", str(caught.exception))
        self.assertIn("SKILLS_POLARION_BASE_URL", str(caught.exception))

    def test_comments_need_an_endpoint_and_say_so(self):
        message = polarion.polarion_add_comment(self.configured(), id="PROJ-1042", comment="hello")
        self.assertIn("comments endpoint", message)
        self.assertEqual(self.calls, [])

    def test_comments_use_the_configured_endpoint_when_present(self):
        config = self.configured()
        config.skills.polarion_endpoints = {"comments": "/polarion/rest/v1/projects/{project}/workitems/{id}/comments"}
        message = polarion.polarion_add_comment(config, id="PROJ-1042", comment="<p>hi</p>")
        self.assertIn("added the comment", message)
        self.assertEqual(self.calls[-1]["method"], "POST")
        self.assertIn("/workitems/1042/comments", self.calls[-1]["path"])

    def test_deep_links_are_built_from_the_config(self):
        url = polarion.work_item_url(self.configured(), "1042")
        self.assertIn("/polarion/#/project/PROJ/workitem?id=PROJ-1042", url)


class ConfigFileTests(unittest.TestCase):
    """The config file itself, because a silently ignored setting is a bug the
    user can never diagnose: the shipped example annotates nearly every line."""

    def parse(self, body: str) -> dict:
        directory = tempfile.mkdtemp(prefix="naveed-cfg-")
        path = Path(directory) / "config.env"
        path.write_text(body, encoding="utf-8")
        from naveed.config import parse_env_file

        return parse_env_file(path)

    def test_a_trailing_comment_is_not_part_of_the_value(self):
        values = self.parse("OVERLAY_SIZE=200   # mascot size in pixels\n")
        self.assertEqual(values["OVERLAY_SIZE"], "200")

    def test_a_hash_inside_a_value_or_url_survives(self):
        values = self.parse(
            "SKILLS_POLARION_TOKEN=pat#1\n"
            "URL=https://x.example/a#frag\n"
            'SEMVER="1.2#3"   # quoted\n'
        )
        self.assertEqual(values["SKILLS_POLARION_TOKEN"], "pat#1")
        self.assertEqual(values["URL"], "https://x.example/a#frag")
        self.assertEqual(values["SEMVER"], "1.2#3")

    def test_the_shipped_example_file_round_trips_into_settings(self):
        example = Path(__file__).resolve().parent.parent / "examples" / "config.env.example"
        values = self.parse(example.read_text(encoding="utf-8"))
        # every uncommented key in the shipped example must be a real setting
        config = load_config()
        sections = {name.lower(): section for name, section in vars(config).items() if hasattr(section, "__dataclass_fields__")}
        unknown = []
        for key in values:
            head, _, tail = key.partition("_")
            section = sections.get(head.lower())
            if section is None or not hasattr(section, tail.lower()):
                unknown.append(key)
        self.assertEqual(unknown, [])
        self.assertEqual(values["SKILLS_TEACH_HOTKEY"], "ctrl+alt+t")
        self.assertEqual(values["SKILLS_MAX_CONTEXT_CHARS"], "3600")

    def test_merging_a_setting_does_not_reach_back_into_the_original(self):
        original = load_config()
        clone = original.merged(**{"safety.dry_run": True, "skills.max_context_chars": 1234})
        self.assertTrue(clone.safety.dry_run)
        self.assertFalse(original.safety.dry_run, "a dry run must not turn dry-run on for the session")
        self.assertEqual(clone.skills.max_context_chars, 1234)
        self.assertNotEqual(original.skills.max_context_chars, 1234)
        self.assertIsNot(clone.safety, original.safety, "sections must be copied, not shared")

    def test_numbers_in_the_example_are_actually_parsed(self):
        directory = tempfile.mkdtemp(prefix="naveed-cfg-")
        path = Path(directory) / "config.env"
        path.write_text("OVERLAY_SIZE=200   # not the default\nCAPTURE_INTERVAL=9.5  # nor this\n", encoding="utf-8")
        config = load_config(env_file=str(path), use_environment=False, ensure_dirs=False)
        self.assertEqual(config.overlay.size, 200, "a number with a comment must still be a number")
        self.assertEqual(config.capture.interval, 9.5)


class PolarionConfigFileTests(unittest.TestCase):
    """The documented config.env lines must actually configure the pack.

    This is the one place where a user's typo or our own doc could disagree with
    the code, and the failure mode is nasty: a mapping that silently becomes
    ``{"comments": "/polarion...`` and 404s forever. So a real file is written and
    a real config is loaded from it.
    """

    def load(self, body: str):
        directory = tempfile.mkdtemp(prefix="naveed-skills-")
        path = Path(directory) / "config.env"
        path.write_text(body, encoding="utf-8")
        return load_config(env_file=str(path), use_environment=False, ensure_dirs=False)

    def tearDown(self):
        polarion.polarion_request = getattr(self, "_original", polarion.polarion_request)

    def test_the_documented_keys_reach_the_settings(self):
        config = self.load(
            """
            # as written in docs/POLARION.md
            SKILLS_POLARION_BASE_URL=https://alm.example.com
            SKILLS_POLARION_TOKEN=pat-abc
            SKILLS_POLARION_PROJECT=PROJ
            SKILLS_ALLOW_API=true
            SKILLS_ALLOW_API_WRITES=true
            """
        )
        self.assertEqual(config.skills.polarion_base_url, "https://alm.example.com")
        self.assertEqual(config.skills.polarion_token, "pat-abc")
        self.assertEqual(config.skills.polarion_project, "PROJ")
        self.assertTrue(polarion.api_configured(config))
        self.assertTrue(polarion.api_writes_allowed(config))
        self.assertTrue(all(tool.is_available(config) for tool in polarion.TOOLS if tool.name != "polarion_add_comment"))

    def test_endpoints_survive_the_trip_through_a_config_file(self):
        config = self.load(
            """
            SKILLS_POLARION_BASE_URL=https://alm.example.com
            SKILLS_POLARION_TOKEN=pat-abc
            SKILLS_ALLOW_API_WRITES=true
            SKILLS_POLARION_ENDPOINTS={"comments": "/polarion/rest/v1/projects/{project}/workitems/{id}/comments"}
            """
        )
        self.assertEqual(
            config.skills.polarion_endpoints["comments"],
            "/polarion/rest/v1/projects/{project}/workitems/{id}/comments",
        )
        comment_tool = next(tool for tool in polarion.TOOLS if tool.name == "polarion_add_comment")
        self.assertTrue(comment_tool.is_available(config))

    def test_the_plain_key_colon_value_form_also_works(self):
        config = self.load(
            """
            SKILLS_POLARION_ENDPOINTS=comments:/polarion/rest/v1/workitems/{id}/comments
            """
        )
        self.assertEqual(config.skills.polarion_endpoints, {"comments": "/polarion/rest/v1/workitems/{id}/comments"})

    def test_writes_stay_off_unless_asked_for(self):
        config = self.load("SKILLS_POLARION_BASE_URL=https://alm.example.com\n")
        write_tool = next(tool for tool in polarion.TOOLS if tool.name == "polarion_update_work_item")
        self.assertFalse(write_tool.is_available(config))


class PolarionTransportTests(unittest.TestCase):
    """`polarion_request` itself: the layer that turns HTTP into English.

    The tool-level tests above stub this function out, so the error mapping and
    the request headers are checked here, against a stubbed socket instead.
    """

    def setUp(self):
        config = load_config()
        config.skills.polarion_base_url = "https://alm.example/"
        config.skills.polarion_token = "pat-123"
        self.config = config

    def request(self, *, body="", status=200, error=None):
        """Run one call with urlopen replaced, returning the Request that was made."""
        seen = {}

        class FakeResponse:
            def __init__(self):
                self.status = status

            def read(self):
                return body.encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(request, timeout=None):
            seen["request"] = request
            seen["timeout"] = timeout
            if error is not None:
                raise error
            return FakeResponse()

        with mock.patch("naveed.skills.polarion.urllib.request.urlopen", fake_urlopen):
            result = polarion.polarion_request(self.config, "/polarion/rest/v1/projects/PROJ/workitems/1042")
        return result, seen.get("request")

    def test_a_401_names_the_token_not_a_stack_trace(self):
        error = urllib.error.HTTPError(
            "https://alm.example/x", 401, "Unauthorized", {}, io.BytesIO(b'{"errors":[]}')
        )
        with self.assertRaises(RuntimeError) as caught:
            self.request(error=error)
        message = str(caught.exception)
        self.assertIn("401", message)
        self.assertIn("SKILLS_POLARION_TOKEN", message)

    def test_a_403_is_treated_as_a_token_problem_too(self):
        error = urllib.error.HTTPError("https://alm.example/x", 403, "Forbidden", {}, io.BytesIO(b""))
        with self.assertRaises(RuntimeError) as caught:
            self.request(error=error)
        self.assertIn("SKILLS_POLARION_TOKEN", str(caught.exception))

    def test_a_404_names_the_endpoint_that_was_missed(self):
        error = urllib.error.HTTPError("https://alm.example/x", 404, "Not Found", {}, io.BytesIO(b""))
        with self.assertRaises(RuntimeError) as caught:
            self.request(error=error)
        message = str(caught.exception)
        self.assertIn("no such endpoint or work item", message)
        self.assertIn("/workitems/1042", message)

    def test_an_unexpected_status_carries_the_body(self):
        error = urllib.error.HTTPError("https://alm.example/x", 500, "Server Error", {}, io.BytesIO(b'{"errors":[{"detail":"boom"}]}'))
        with self.assertRaises(RuntimeError) as caught:
            self.request(error=error)
        self.assertIn("500", str(caught.exception))
        self.assertIn("boom", str(caught.exception))

    def test_an_unreachable_server_says_which_server(self):
        error = urllib.error.URLError("Name or service not known")
        with self.assertRaises(RuntimeError) as caught:
            self.request(error=error)
        self.assertIn("https://alm.example", str(caught.exception))
        self.assertIn("Name or service not known", str(caught.exception))

    def test_the_token_travels_as_a_bearer_header(self):
        _, request = self.request(body='{"data": {}}')
        self.assertEqual(request.get_header("Authorization"), "Bearer pat-123")
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertTrue(request.full_url.startswith("https://alm.example/polarion/rest/v1/"))

    def test_an_empty_body_is_not_an_error(self):
        result, _ = self.request(body="   ")
        self.assertEqual(result, {"status": 200, "data": {}})

    def test_a_non_json_body_is_kept_as_raw_text(self):
        result, _ = self.request(body="<html>maintenance</html>")
        self.assertIn("maintenance", result["data"]["raw"])

    def test_a_trailing_slash_in_the_base_url_does_not_double_up(self):
        _, request = self.request(body="{}")
        self.assertNotIn("//polarion", request.full_url.replace("https://", ""))

    def test_an_explicit_project_beats_everything_else(self):
        config = load_config()
        config.skills.polarion_project = "DEFAULT"
        self.assertEqual(polarion._split_id(config, "OPS-7", "GIVEN"), ("GIVEN", "7"))
        self.assertEqual(polarion._split_id(config, "OPS-7"), ("OPS", "7"))
        self.assertEqual(polarion._split_id(config, "1042"), ("DEFAULT", "1042"))
        self.assertEqual(polarion._split_id(load_config(), "1042"), ("", "1042"))

    def test_a_bare_id_lands_on_the_configured_project(self):
        config = load_config()
        config.skills.polarion_base_url = "https://alm.example"
        config.skills.polarion_token = "pat-123"
        config.skills.polarion_project = "PROJ"
        config.skills.polarion_endpoints = {}
        seen = {}

        class FakeResponse:
            status = 200

            def read(self):
                return b'{"data": {"id": "PROJ/PROJ-1042", "attributes": {"title": "T"}}}'

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(request, timeout=None):
            seen["url"] = request.full_url
            return FakeResponse()

        with mock.patch("naveed.skills.polarion.urllib.request.urlopen", fake_urlopen):
            text = polarion.polarion_get_work_item(config, id="1042")
        self.assertIn("PROJ-1042", text)
        self.assertIn("/projects/PROJ/workitems/1042", seen["url"])

    def test_a_qualified_id_supplies_its_own_project(self):
        config = load_config()
        config.skills.polarion_base_url = "https://alm.example"
        config.skills.polarion_project = "WRONG"
        seen = {}

        class FakeResponse:
            status = 200

            def read(self):
                return b'{"data": {"id": "OPS/X-7", "attributes": {"title": "T"}}}'

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(request, timeout=None):
            seen["url"] = request.full_url
            return FakeResponse()

        with mock.patch("naveed.skills.polarion.urllib.request.urlopen", fake_urlopen):
            polarion.polarion_get_work_item(config, id="X-7")
        self.assertIn("/projects/X/workitems/7", seen["url"])


class ExecutorIntegrationTests(unittest.TestCase):
    """Recipes and pack tools inside the agent loop."""

    def setUp(self):
        from naveed.agent.executor import NaveedAgent

        self.config = load_config()
        self.agent = NaveedAgent(self.config)

    def test_a_recipe_action_expands_into_its_steps_before_running(self):
        from naveed.control.actions import normalize_action

        expanded = self.agent.expand_recipes([normalize_action({"type": "recipe", "name": "polarion-set-status", "args": {"status": "Verified"}})])
        kinds = [action.kind for action in expanded]
        self.assertIn("edit_field", kinds)
        self.assertNotIn("recipe", kinds)
        edit = next(action for action in expanded if action.kind == "edit_field")
        self.assertEqual(edit.params["value"], "Verified")
        self.assertEqual(edit.params["operation"], "set")

    def test_an_unknown_recipe_becomes_a_question_not_a_crash(self):
        from naveed.control.actions import normalize_action

        expanded = self.agent.expand_recipes([normalize_action({"type": "recipe", "name": "does-not-exist"})])
        self.assertEqual(len(expanded), 1)
        self.assertEqual(expanded[0].kind, "ask")
        self.assertIn("do not know a routine", expanded[0].params["question"])

    def test_a_recipe_missing_its_arguments_asks_for_them(self):
        from naveed.control.actions import normalize_action

        expanded = self.agent.expand_recipes([normalize_action({"type": "recipe", "name": "polarion-open-work-item"})])
        self.assertEqual(expanded[0].kind, "ask")
        self.assertIn("work_item_id", expanded[0].params["question"])

    def test_nested_recipes_expand_without_looping_forever(self):
        from naveed.control.actions import normalize_action
        from naveed.skills.base import Recipe, RecipeStep

        outer = Recipe(name="outer", steps=[RecipeStep(kind="recipe", params={"name": "inner"})])
        inner = Recipe(name="inner", steps=[RecipeStep(kind="recipe", params={"name": "outer"})])
        self.agent.skills.learned.extend([outer, inner])
        expanded = self.agent.expand_recipes([normalize_action({"type": "recipe", "name": "outer"})])
        self.assertLessEqual(len(expanded), 3)

    def test_a_pack_tool_runs_through_the_controller_and_is_confirmed_when_it_writes(self):
        from naveed.control.actions import normalize_action
        from naveed.control.os_control import OsController
        from naveed.skills.base import SkillTool

        calls = []

        def read_tool(config, id="", **kwargs):
            calls.append(("read", id))
            return f"read {id}"

        def write_tool(config, id="", **kwargs):
            calls.append(("write", id))
            return f"wrote {id}"

        read = SkillTool(name="read_thing", description="r", function=read_tool, params={"id": "id"})
        write = SkillTool(name="write_thing", description="w", function=write_tool, params={"id": "id"}, writes=True)
        tools = {"read_thing": read, "write_thing": write}

        controller = OsController(self.config, tools=lambda skill, name: tools.get(name))
        result = controller.perform(normalize_action({"type": "skill_tool", "skill": "demo", "tool": "read_thing", "args": {"id": "X-1"}}))
        self.assertTrue(result.ok, result.message)
        self.assertEqual(calls, [("read", "X-1")])

        # A tool that writes must not run without the human saying yes.
        result = controller.perform(normalize_action({"type": "skill_tool", "skill": "demo", "tool": "write_thing", "args": {"id": "X-2"}}))
        self.assertFalse(result.ok)
        self.assertEqual(calls, [("read", "X-1")], "the write must not have happened")

    def test_an_unavailable_tool_is_refused_with_a_reason(self):
        from naveed.control.actions import normalize_action
        from naveed.control.os_control import OsController

        controller = OsController(self.config, tools=lambda skill, name: polarion.SKILL.tool(name))
        result = controller.perform(normalize_action({"type": "skill_tool", "skill": "polarion", "tool": "polarion_get_work_item", "args": {"id": "PROJ-1"}}))
        self.assertFalse(result.ok)
        self.assertIn("not available", result.message)

    def test_skill_knowledge_is_injected_once_per_app(self):
        from naveed.agent.executor import Task

        task = Task(prompt="set the status of PROJ-1042")
        first = self.agent._skill_context(task, POLARION_WINDOW)
        self.assertIn("POLARION", first)
        task.steps.append({"step": 1})
        self.assertEqual(self.agent._skill_context(task, POLARION_WINDOW), "", "must not repeat every step")

    def test_switching_apps_reinjects_the_right_pack(self):
        from naveed.agent.executor import Task

        task = Task(prompt="edit this file")
        task.steps.append({"step": 1})
        self.agent._skill_context(task, POLARION_WINDOW)
        self.assertEqual(self.agent._skill_context(task, EDITOR_WINDOW), "")
        again = self.agent._skill_context(task, POLARION_WINDOW)
        self.assertIn("POLARION", again, "returning to the app must bring its notes back")

    def test_disabling_skills_injects_nothing(self):
        from naveed.agent.executor import NaveedAgent, Task

        config = load_config()
        config.skills.inject = False
        agent = NaveedAgent(config)
        self.assertEqual(agent._skill_context(Task(prompt="polarion work item"), POLARION_WINDOW), "")


class RecipePlanOutputTests(unittest.TestCase):
    """`--run-recipe --dry-run` must *show* the steps, not just claim to run them.

    Reviewing a routine before letting it loose is the whole point of a dry run,
    and a faithful replay is exactly why the user wants to read it first.
    """

    def test_the_steps_are_printed_as_sentences(self):
        from naveed.app import NaveedApp
        from naveed.skills import polarion

        recipe = next(item for item in polarion.RECIPES if item.name == "polarion-open-work-item")
        lines = NaveedApp._recipe_lines(recipe, {"work_item_id": "PROJ-1042"})
        self.assertTrue(lines, "a routine with steps must render something")
        joined = "\n".join(lines)
        self.assertIn("PROJ-1042", joined, "the argument must be substituted, not left as {work_item_id}")
        self.assertNotIn("{work_item_id}", joined)
        self.assertIn("click at", joined)
        self.assertIn("ctrl+a", joined)

    def test_the_dry_run_prints_the_plan_and_says_it_is_not_performing_it(self):
        import contextlib
        import io as io_module

        from naveed.agent import bridge as bridge_module
        from naveed.app import NaveedApp

        app = object.__new__(NaveedApp)
        app.config = load_config()
        app.bridge = None
        app.recent_tasks = []
        app._teach_stop = False

        instances = []

        class FakeBridge:
            def __init__(self, config):
                self.config = config
                self.started = False
                instances.append(self)

            def start(self):
                self.started = True

            def stop(self):
                self.started = False

            def run_recipe(self, recipe, arguments, *, on_step=None):
                self.replayed = (recipe.name, arguments)
                return f"ran {recipe.name}: 3 step(s) from the recording"

        buffer = io_module.StringIO()
        with mock.patch.object(bridge_module, "AgentBridge", FakeBridge):
            with contextlib.redirect_stdout(buffer):
                code = NaveedApp.run_recipe(app, "polarion-set-status", {"status": "Verified"}, dry_run=True)
        output = buffer.getvalue()

        self.assertEqual(code, 0)
        self.assertIn("polarion-set-status", output)
        self.assertIn("dry run", output, "the user must be told nothing is being performed")
        self.assertGreaterEqual(len([line for line in output.splitlines() if line.strip().startswith(("1.", "2.", "3."))]), 1,
                                "a dry run exists to show the steps")
        self.assertIn("Verified", output, "the argument must be visible in the plan")

        (bridge,) = instances
        self.assertTrue(bridge.started is False, "the bridge must be stopped again")
        self.assertEqual(bridge.replayed[0], "polarion-set-status")
        self.assertEqual(bridge.replayed[1], {"status": "Verified"})
        self.assertTrue(bridge.config.safety.dry_run, "the replay must run in dry-run mode")
        self.assertFalse(app.config.safety.dry_run, "the user's own config must not be mutated")


if __name__ == "__main__":
    unittest.main(verbosity=2)
