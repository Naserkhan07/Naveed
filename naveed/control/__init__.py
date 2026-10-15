"""Everything that touches the real machine: input, safety, OS actions, OCR."""

from __future__ import annotations

from ..lazy import lazy_attrs
from .actions import ACTION_KINDS, Action, ActionError, ActionPlan, describe_actions, normalize_action, normalize_plan
from .input import InputController, InputError
from .keys import normalize_key, parse_hotkey
from .os_control import ActionResult, OsController
from .safety import RiskLevel, SafetyCheck, SafetyGuard, describe_risk

__all__ = [
    "ACTION_KINDS", "Action", "ActionError", "ActionPlan", "ActionResult", "InputController",
    "InputError", "OsController", "RiskLevel", "SafetyCheck", "SafetyGuard", "describe_actions",
    "describe_risk", "find_text", "normalize_action", "normalize_key", "normalize_plan",
    "parse_hotkey", "read_text",
]

__getattr__ = lazy_attrs(
    globals(),
    {
        "ocr": "naveed.control.ocr",
        "find_text": "naveed.control.ocr:find_text",
        "read_text": "naveed.control.ocr:read_text",
    },
)
