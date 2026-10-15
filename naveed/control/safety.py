"""Guardrails: what Naveed must ask about, and what it must refuse.

Modelled on **voice-computer-use-agent**
(https://github.com/jarmen423/voice-computer-use-agent, MIT) —
``voiceuse/safety.py``, whose :class:`SafetyGuard` inspects every tool call
against a configurable keyword list and drives a confirmation loop before
anything destructive runs, with a configurable timeout.

Naveed keeps that shape and adds the parts a *small* model needs, because a
7B-class planner is much more likely than GPT-4-class to phrase something
dangerous innocuously:

* **Hard refusal patterns** — regexes for genuinely unrecoverable commands
  (``rm -rf /``, ``mkfs``, ``dd of=/dev/sd*``, ``reg delete HKLM``, fork bombs).
  These are never confirmed, always refused.
* **Risk levels** — SAFE / CAUTION / DESTRUCTIVE / BLOCKED, so the panel can
  colour the action instead of showing a yes/no dialog for a scroll.
* **Credential protection** — typing into a sign-in / password / 2FA / payment
  context is refused outright and handed back to the human.  A desktop companion
  must never be the thing that types your password.
* **Confirmation ownership** — the guard never talks to the user itself; it calls
  the ``confirm`` callback the UI injected (panel sheet, voice, or auto-approve
  in tests), and treats "no answer in time" as *denied*.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..config import DEFAULT_BLOCKED_PATTERNS, DEFAULT_DESTRUCTIVE_KEYWORDS, SafetySettings
from .actions import Action

__all__ = [
    "RiskLevel",
    "SafetyCheck",
    "SafetyDecision",
    "SafetyGuard",
    "describe_risk",
]

#: Windows/app contexts in which typing is considered credential material.
CREDENTIAL_CONTEXTS = (
    r"\bsign\s?in\b", r"\blog\s?in\b", r"\bpassword\b", r"\bpasscode\b", r"\bpassphrase\b",
    r"\b2fa\b", r"\btwo[- ]factor\b", r"\bverification code\b", r"\bone[- ]time\b",
    r"\botp\b", r"\bsecurity code\b", r"\bcvv\b", r"\bcard number\b", r"\biban\b",
    r"\bpassword manager\b", r"\bkeychain\b", r"\bcredentials?\b",
)

#: Wording that means a *secret* is being handed over (as opposed to an email).
PASSWORD_INTENT = re.compile(
    r"\b(password|passcode|passphrase|pin\b|2fa|two[- ]factor|verification code|one[- ]time|otp\b|"
    r"security code|cvv|cvc|card number|credit card|seed phrase|private key|api key|token)\b",
    re.IGNORECASE,
)

#: Values that are never typed by an assistant, whatever the context.
SECRETISH_VALUE = (
    r"^(?:[A-Za-z0-9_\-]{16,})$",                      # long token-ish strings
    r"^(?:sk|pk|ghp|xox[baprs])[_\-][A-Za-z0-9_\-]{10,}$",  # API keys
    r"^https?://[^\s]*:[^\s]*@",                       # URL with embedded creds
    r"^\d{12,19}$",                                     # card numbers
)


class RiskLevel(IntEnum):
    """How much damage an action could do."""

    SAFE = 0
    CAUTION = 1
    DESTRUCTIVE = 2
    BLOCKED = 3


def describe_risk(level: RiskLevel) -> str:
    return {
        RiskLevel.SAFE: "safe",
        RiskLevel.CAUTION: "worth a look",
        RiskLevel.DESTRUCTIVE: "destructive",
        RiskLevel.BLOCKED: "refused",
    }[level]


@dataclass
class SafetyDecision:
    """Outcome of inspecting one action."""

    level: RiskLevel = RiskLevel.SAFE
    reason: str = ""
    matched: str = ""
    needs_confirmation: bool = False

    @property
    def allowed(self) -> bool:
        return self.level is not RiskLevel.BLOCKED

    @property
    def requires_confirmation(self) -> bool:
        return self.needs_confirmation and self.level is not RiskLevel.BLOCKED


@dataclass
class SafetyCheck:
    """Verdict handed back to the executor.

    Named to mirror voiceuse's ``SafetyCheckResult``: ``is_safe``,
    ``requires_confirmation``, ``confirmation_prompt``, ``is_allowed``,
    ``denial_reason``.
    """

    is_safe: bool = True
    requires_confirmation: bool = False
    confirmation_prompt: str = ""
    is_allowed: bool = True
    denial_reason: str = ""
    risk: RiskLevel = RiskLevel.SAFE
    matched: str = ""

    @property
    def blocked(self) -> bool:
        return not self.is_allowed


class SafetyGuard:
    """Inspects actions and asks the human when it must."""

    def __init__(
        self,
        settings: Optional[SafetySettings] = None,
        *,
        confirm: Optional[Callable[[str, float], bool]] = None,
        announce: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.settings = settings or SafetySettings()
        self.confirm = confirm
        self.announce = announce
        patterns: Sequence[str] = tuple(self.settings.blocked_patterns) or DEFAULT_BLOCKED_PATTERNS
        self._blocked = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
        keywords: Sequence[str] = tuple(self.settings.destructive_keywords) or DEFAULT_DESTRUCTIVE_KEYWORDS
        self._keywords = tuple(keyword.lower() for keyword in keywords)
        self._credential = [re.compile(pattern, re.IGNORECASE) for pattern in CREDENTIAL_CONTEXTS]
        self._secretish = [re.compile(pattern, re.IGNORECASE) for pattern in SECRETISH_VALUE]
        self.history: List[Dict[str, Any]] = []

    # --- inspection ----------------------------------------------------
    def check(self, action: Action, *, context: str = "", raw_text: str = "") -> SafetyCheck:
        """Inspect *action* before it runs.

        ``context`` is free text describing where the action lands — normally the
        active window title plus, when available, the text near the click point.
        """
        haystack = " ".join(
            [
                action.kind,
                " ".join(str(value) for value in action.params.values() if isinstance(value, (str, int, float))),
                action.note,
                context,
                raw_text,
            ]
        )
        lowered = haystack.lower()

        # 1. Hard refusals.
        if action.kind == "shell":
            decision = self._check_shell(action)
            if decision.level is RiskLevel.BLOCKED:
                return self._finalize(action, decision)

        for pattern in self._blocked:
            match = pattern.search(haystack)
            if match:
                return self._finalize(
                    action,
                    SafetyDecision(
                        level=RiskLevel.BLOCKED,
                        reason=f"that command matches a pattern Naveed never runs ({match.group(0)!r})",
                        matched=match.group(0),
                    ),
                )

        # 2. Credentials are always the human's job.
        #
        # Two situations are refused.  (a) The value itself is secret-like: API
        # keys, tokens, card numbers, long random strings.  (b) The user asked a
        # secret to be handed over ("log in and type my password", "enter the
        # 2FA code").  Typing an email or a username into a login page is *not*
        # refused — that is an ordinary assistant job, and refusing it would make
        # Naveed useless for exactly the tasks people want.
        if action.kind in ("type", "key", "hotkey", "clipboard_set") and self.settings.block_credential_entry:
            credential_field = ""
            for pattern in self._credential:
                match = pattern.search(context) or pattern.search(action.note)
                if match:
                    credential_field = match.group(0)
                    break

            intent = bool(
                PASSWORD_INTENT.search(raw_text)
                or PASSWORD_INTENT.search(action.note)
                or PASSWORD_INTENT.search(action.params.get("label") or "")
            )

            value_is_secret = False
            if action.kind in ("type", "clipboard_set"):
                text = action.text.strip()
                for pattern in self._secretish:
                    if pattern.match(text):
                        value_is_secret = True
                        break
                # A bare 4-8 digit value in a sign-in window is a PIN, not prose.
                if not value_is_secret and credential_field and re.fullmatch(r"\d{4,8}", text or ""):
                    value_is_secret = True
            if intent and action.kind == "type":
                value_is_secret = True

            if value_is_secret or (intent and action.kind in ("key", "hotkey", "clipboard_set")):
                return self._finalize(
                    action,
                    SafetyDecision(
                        level=RiskLevel.BLOCKED,
                        reason=(
                            "this is a password, code, key or similar secret, and Naveed will not type "
                            "secrets — please type this one yourself"
                        ),
                        matched=credential_field or "secret",
                    ),
                )

        # 3. Shell needs the opt-in switch.
        if action.kind == "shell":
            decision = self._check_shell(action)
            return self._finalize(action, decision)

        # 4. Keyword-based destructive intent.
        for keyword in self._keywords:
            if keyword in lowered:
                return self._finalize(
                    action,
                    SafetyDecision(
                        level=RiskLevel.DESTRUCTIVE,
                        reason=f"it could be destructive (“{keyword}”)",
                        matched=keyword,
                        needs_confirmation=self.settings.confirm_destructive,
                    ),
                )

        # 5. Mild caution for things that leave the machine.
        if action.kind in ("open_url", "open_app", "open_file", "clipboard_set", "focus_window"):
            return self._finalize(action, SafetyDecision(level=RiskLevel.CAUTION, reason=""))

        return self._finalize(action, SafetyDecision(level=RiskLevel.SAFE))

    def _check_shell(self, action: Action) -> SafetyDecision:
        command = str(action.get("command") or "").strip()
        if not command:
            return SafetyDecision(level=RiskLevel.BLOCKED, reason="empty command")
        if not self.settings.allow_shell:
            return SafetyDecision(
                level=RiskLevel.BLOCKED,
                reason="running shell commands is switched off (SAFETY_ALLOW_SHELL=false)",
            )
        allowlist = [item.lower() for item in self.settings.shell_allowlist]
        if allowlist and not any(command.lower().startswith(item) for item in allowlist):
            return SafetyDecision(
                level=RiskLevel.BLOCKED,
                reason=f"'{command.split()[0]}' is not in the allowed command list",
                matched=command.split()[0],
            )
        if self.settings.confirm_destructive:
            return SafetyDecision(
                level=RiskLevel.DESTRUCTIVE,
                reason="it runs a shell command",
                needs_confirmation=True,
            )
        return SafetyDecision(level=RiskLevel.CAUTION)

    def _finalize(self, action: Action, decision: SafetyDecision) -> SafetyCheck:
        prompt = ""
        if decision.level is RiskLevel.DESTRUCTIVE and decision.needs_confirmation:
            prompt = f"{action.describe()} — {decision.reason}. Shall I go ahead?"
        check = SafetyCheck(
            is_safe=decision.level is RiskLevel.SAFE,
            requires_confirmation=decision.requires_confirmation,
            confirmation_prompt=prompt,
            is_allowed=decision.allowed,
            denial_reason="" if decision.allowed else decision.reason,
            risk=decision.level,
            matched=decision.matched,
        )
        self.history.append(
            {
                "at": time.time(),
                "action": action.to_dict(),
                "level": int(decision.level),
                "risk": describe_risk(decision.level),
                "allowed": check.is_allowed,
                "reason": decision.reason,
            }
        )
        if len(self.history) > 200:
            del self.history[:100]
        return check

    # --- confirmation ---------------------------------------------------
    def request_confirmation(self, check: SafetyCheck, action: Action) -> bool:
        """Ask the human, honouring the configured timeout.

        A missing callback means "not confirmable", and the action is *denied* —
        failing closed is the only safe default for a guard.
        """
        if not check.requires_confirmation:
            return check.is_allowed
        prompt = check.confirmation_prompt or f"{action.describe()} — go ahead?"
        if self.confirm is None:
            return False
        try:
            return bool(self.confirm(prompt, self.settings.confirm_timeout))
        except Exception:
            return False

    def review(self, action: Action, *, context: str = "", raw_text: str = "") -> SafetyCheck:
        """Check *and*, when needed, ask — the single call the executor makes."""
        check = self.check(action, context=context, raw_text=raw_text)
        if check.blocked:
            if self.announce is not None and check.denial_reason:
                try:
                    self.announce(check.denial_reason)
                except Exception:
                    pass
            return check
        if check.requires_confirmation:
            approved = self.request_confirmation(check, action)
            if not approved:
                check.is_allowed = False
                check.denial_reason = "you did not confirm it"
        return check
