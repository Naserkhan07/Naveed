"""The planner: screenshot + world state in, JSON actions out.

Wraps :mod:`naveed.agent.llm` and :mod:`naveed.agent.prompts` into three jobs:

``plan``            — one step of a task (returns an :class:`ActionPlan`);
``describe_screen`` — a question about what is on screen, no actions;
``answer``          — the little chat box in the panel.

It is also the place where a *useless* model reply is turned into something the
executor can act on: a reply with prose but no JSON becomes a ``look`` action, and
an empty plan becomes ``done`` with the model's own text as the summary, so the
task loop never spins on nothing.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..config import Config
from ..control.actions import Action, ActionPlan, normalize_plan
from .llm import LLMClient, LLMError, encode_image, extract_json, image_part, text_part
from .prompts import (
    PLANNER_SYSTEM,
    SCREEN_SUMMARY_SYSTEM,
    build_planner_prompt,
    build_question_prompt,
    build_screen_prompt,
)

__all__ = ["Planner", "describe_screen"]

logger = logging.getLogger("naveed.planner")


class Planner:
    """Turns a user request into actions, using a small vision model."""

    def __init__(self, config: Config, *, client: Optional[LLMClient] = None, should_stop: Optional[Callable[[], bool]] = None) -> None:
        self.config = config
        self.should_stop = should_stop
        self.client = client or LLMClient(config.llm, should_stop=should_stop)
        self.last_reply_text = ""
        self.last_error = ""

    # --- task planning ---------------------------------------------------
    def plan(
        self,
        task: str,
        *,
        frame: Any = None,
        window: Any = None,
        world: str = "",
        history: Sequence[Dict[str, Any]] = (),
        monitors: Optional[Sequence[Any]] = None,
        step: int = 1,
        ocr_text: str = "",
        extra_context: str = "",
    ) -> ActionPlan:
        """Ask for the next step. Never raises: failures become an ``ask`` plan."""
        prompt = build_planner_prompt(
            task,
            frame=frame,
            window=window,
            world=world,
            history=history,
            monitors=monitors,
            step=step,
            max_steps=self.config.agent.max_steps,
            ocr_text=ocr_text,
            extra_context=extra_context,
        )
        content: List[Dict[str, Any]] = []
        if frame is not None and self.config.llm.vision:
            content.append(
                image_part(
                    encode_image(
                        frame.image,
                        max_side=self.config.capture.max_prompt_side,
                        quality=self.config.capture.jpeg_quality,
                    )
                )
            )
        content.append(text_part(prompt))
        messages = [
            {"role": "system", "content": PLANNER_SYSTEM},
            {"role": "user", "content": content},
        ]

        try:
            reply = self.client.chat(messages, json_mode=True)
        except LLMError as error:
            self.last_error = str(error)
            return ActionPlan(
                summary="I could not reach the model",
                actions=[Action(kind="ask", params={"question": str(error)})],
            )

        self.last_reply_text = reply.text
        payload = reply.json if reply.json is not None else extract_json(reply.text)
        if payload is None:
            # Prose instead of JSON: take one honest look instead of guessing.
            logger.debug("planner returned non-JSON: %s", reply.text[:200])
            return ActionPlan(
                summary=(reply.text.strip().splitlines() or ["Looking at the screen"])[0][:200],
                understanding=reply.text.strip()[:300],
                actions=[Action(kind="look", params={}, note="Looking at the screen again")],
            )

        plan = normalize_plan(payload, limit=4)
        if not plan.actions and not plan.done:
            plan.actions = [Action(kind="look", params={}, note="Looking at the screen again")]
        if plan.done and not plan.actions:
            plan.actions = [Action(kind="done", params={"summary": plan.summary or "Done"})]
        if not plan.summary:
            plan.summary = plan.actions[0].describe() if plan.actions else "Working on it"
        return plan

    # --- questions about the screen ---------------------------------------
    def describe_screen(
        self,
        question: str = "",
        *,
        frame: Any = None,
        window: Any = None,
        world: str = "",
        ocr_text: str = "",
    ) -> str:
        """Answer a question about the current screen in prose."""
        prompt = build_screen_prompt(question, window=window, world=world, ocr_text=ocr_text)
        content: List[Dict[str, Any]] = []
        if frame is not None and self.config.llm.vision:
            content.append(
                image_part(
                    encode_image(
                        frame.image,
                        max_side=self.config.capture.max_prompt_side,
                        quality=self.config.capture.jpeg_quality,
                    )
                )
            )
        content.append(text_part(prompt))
        try:
            reply = self.client.chat(
                [{"role": "system", "content": SCREEN_SUMMARY_SYSTEM}, {"role": "user", "content": content}],
                max_tokens=400,
            )
        except LLMError as error:
            self.last_error = str(error)
            return f"I could not read the screen: {error}"
        return reply.text or "I could not see anything clearly on this screen."

    # --- chat -------------------------------------------------------------
    def answer(self, question: str, *, window: Any = None, options: Sequence[str] = ()) -> str:
        """Plain chat answer for the panel's input box."""
        prompt = build_question_prompt(question, window=window, options=options)
        try:
            reply = self.client.complete(prompt, system=SCREEN_SUMMARY_SYSTEM, max_tokens=400)
        except LLMError as error:
            self.last_error = str(error)
            return f"({error})"
        return reply.text or "(no answer)"


def describe_screen(planner: Planner, question: str = "", **kwargs: Any) -> str:
    """Module-level convenience wrapper (kept for symmetry with the package API)."""
    return planner.describe_screen(question, **kwargs)
