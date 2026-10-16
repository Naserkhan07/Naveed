"""Configuration, paths and the (tiny) settings model.

Everything Naveed can be told lives in one dataclass tree so the control panel,
the CLI and the tests all read the same values.  Values are resolved in this
order, last one wins:

1. built-in defaults (this file),
2. ``~/.naveed/config.env`` — a plain ``KEY=value`` file, no dependency needed,
3. real environment variables,
4. explicit CLI flags (``python -m naveed --model ...``).

The file is ``.env``-style on purpose: it keeps credentials out of source control,
works the same on every OS, and can be edited by hand or from the panel's
settings sheet.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "AgentSettings",
    "CaptureSettings",
    "Config",
    "LLMSettings",
    "OverlaySettings",
    "SafetySettings",
    "SkillsSettings",
    "load_config",
    "config_paths",
    "parse_env_file",
    "PROVIDER_PRESETS",
    "write_env_file",
]

APP_DIR_NAME = ".naveed"
ENV_FILE_NAME = "config.env"

#: Ready-made **LLM APIs**, so "use a small LLM" is a two-word answer. Naveed is
#: configured with an *API* — a URL and a model — not with a key: everything local
#: needs no token at all, and a hosted gateway only needs one if it asks for it.
PROVIDER_PRESETS: Dict[str, Dict[str, str]] = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "note": "small, fast, vision-capable",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "qwen/qwen2.5-vl-7b-instruct",
        "note": "cheap vision models from many vendors behind one API",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.2-11b-vision-preview",
        "note": "very low latency",
    },
    "ollama": {
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "qwen2.5vl:7b",
        "note": "fully local, no token needed",
    },
    "lmstudio": {
        "base_url": "http://127.0.0.1:1234/v1",
        "model": "qwen2.5-vl-7b-instruct",
        "note": "local server with a GUI",
    },
}


# --- sections ---------------------------------------------------------------

@dataclass
class LLMSettings:
    """The "small LLM" that decides what to click — configured as an *API*.

    Naveed is pointed at an OpenAI-compatible LLM API: a URL and a model name.
    That is the whole configuration for a local Ollama/LM Studio/llama.cpp server,
    which is the intended way to run it. ``token`` exists only for the case where
    an endpoint insists on an ``Authorization`` header (a hosted gateway, usually);
    it is optional, it is never required, and nothing in Naveed asks for one.
    """

    base_url: str = "http://127.0.0.1:11434/v1"
    token: str = ""
    model: str = "qwen2.5vl:7b"
    vision: bool = True
    temperature: float = 0.15
    max_tokens: int = 700
    timeout: float = 45.0
    max_retries: int = 2
    extra_headers: Dict[str, str] = field(default_factory=dict)
    #: Sent as ``reasoning_effort`` when the endpoint understands it.
    reasoning_effort: str = ""

    @property
    def configured(self) -> bool:
        """True when an LLM API is set up at all.

        Deliberately says nothing about keys: whether the API *answers* is a
        question for :meth:`naveed.agent.llm.LLMClient.probe`, which reports what
        the endpoint actually said. Claiming "no model" because there is no key is
        what made a perfectly good local server look unconfigured.
        """
        return bool(self.model and self.base_url)

    @property
    def local(self) -> bool:
        """True for an endpoint on this machine (no token, nothing leaves the PC)."""
        return any(host in self.base_url for host in ("127.0.0.1", "localhost", "0.0.0.0", "[::1]"))

    @property
    def label(self) -> str:
        return f"{self.model} @ {self.base_url.split('//')[-1].split('/')[0]}"


@dataclass
class OverlaySettings:
    """The floating companion window."""

    size: int = 168                 # mascot body size in logical pixels
    padding: int = 46               # transparent margin for glow/shadow/rings
    x: Optional[int] = None         # None -> wherever OVERLAY_ANCHOR says
    y: Optional[int] = None
    #: below_camera | middle | top | bottom | top_left | top_right | bottom_right
    #: "below_camera" is the default: centred just under the webcam bezel, where
    #: the mascot never covers the window you are reading.
    anchor: str = "below_camera"
    #: come back where it was dragged to (state/overlay.json)
    remember_position: bool = True
    offset_from_middle: float = 0.16  # only used by the "middle" anchor
    scale_with_screen: bool = True
    always_on_top: bool = True
    click_through_when_idle: bool = False
    start_hidden: bool = False
    show_panel_on_start: bool = True
    fps: int = 45
    panel_pinned: bool = True       # panel follows the mascot when it is dragged
    hotkey: str = "ctrl+alt+space"
    tray: bool = True
    #: Panel placement: above | below | left | right
    panel_anchor: str = "above"


@dataclass
class WebSettings:
    """The optional HTTP front end — the same bot, reachable over a browser.

    Off by default: Naveed is a floating desktop window, and the HTTP front end is
    a deliberate second way in (``python -m naveed --serve``), not a fallback for
    when the window cannot start. A machine where Qt is missing gets the reason,
    not a web page.
    """

    host: str = "127.0.0.1"          # loopback unless you ask for more
    port: int = 8765                 # a busy port falls back to a free one
    #: require the token when listening beyond loopback. Turning this off is for
    #: a container port on a network you already trust; loopback never needs one.
    token: bool = True
    open_browser: bool = False       # open the page automatically with the overlay
    enabled: bool = False            # opt-in: --serve, or WEB_ENABLED=true


@dataclass
class CaptureSettings:
    """Screen watching and capture behaviour."""

    directory: str = ""             # "" -> ~/.naveed/screenshots
    interval: float = 2.0
    idle_interval: float = 6.0
    settle_after: int = 3
    max_history: int = 100
    max_captures: int = 100
    save_frames: bool = True
    target: str = "active_window"    # active_window | primary
    noise_floor: float = 0.02
    scene_threshold: float = 0.45
    jpeg_quality: int = 72
    max_prompt_side: int = 1280      # image size sent to the model
    monitor_primary_only: bool = False


@dataclass
class SafetySettings:
    """Guardrails, modelled on voiceuse's ``SafetyGuard``.

    Destructive intent is detected *before* execution and can require a spoken
    confirmation, a panel confirmation, or be refused outright.
    """

    confirm_destructive: bool = True
    confirm_timeout: float = 12.0
    allow_shell: bool = False
    shell_allowlist: List[str] = field(default_factory=list)
    blocked_patterns: List[str] = field(default_factory=list)
    destructive_keywords: List[str] = field(default_factory=lambda: list(DEFAULT_DESTRUCTIVE_KEYWORDS))
    max_actions_per_task: int = 25
    typed_text_limit: int = 4000
    #: Refuse to type into password fields / credential prompts.
    block_credential_entry: bool = True
    dry_run: bool = False


DEFAULT_DESTRUCTIVE_KEYWORDS: Tuple[str, ...] = (
    "delete", "remove", "erase", "format", "wipe", "uninstall", "shutdown",
    "restart", "reboot", "kill", "terminate", "taskkill", "rmdir", "rm -rf",
    "del ", "drop table", "truncate", "overwrite", "replace all", "reset",
    "transfer", "payment", "purchase", "buy", "checkout", "subscribe",
    "send", "post", "publish", "upload", "submit", "sign out", "log out",
    "change password", "reg delete", "diskpart", "chmod 777", "sudo",
)

DEFAULT_BLOCKED_PATTERNS: Tuple[str, ...] = (
    r"rm\s+-rf\s+/(?:\s|$)",
    r":\(\)\s*\{.*\};:",          # fork bomb
    r"mkfs\.",
    r"dd\s+if=.*of=/dev/",
    r"format\s+[a-z]:",
    r"shutdown\s+/[sr]",
    r"reg\s+delete\s+HKLM",
    r"diskpart",
    r">\s*/dev/sd[a-z]",
)


@dataclass
class AgentSettings:
    """Task execution loop."""

    max_steps: int = 18
    #: Wall-clock budget for one task; the loop stops cleanly when it is spent.
    max_task_seconds: float = 240.0
    step_timeout: float = 32.0
    settle_timeout: float = 5.0
    screenshot_each_step: bool = True
    remember_last_tasks: int = 20
    use_ocr: bool = True
    describe_actions: bool = True
    retry_on_no_change: int = 1
    history_lines: int = 4
    speak_plan: bool = True


@dataclass
class VoiceSettings:
    """Offline speech in and out."""

    stt: str = "auto"               # auto | faster_whisper | vosk | none
    whisper_model: str = "base.en"
    whisper_device: str = "auto"
    whisper_compute: str = "int8"
    tts: str = "auto"                # auto | piper | pyttsx3 | none
    piper_voice: str = ""            # path to a .onnx voice, or a preset name
    piper_dir: str = ""              # "" -> ~/.naveed/models/piper
    rate: float = 1.0
    volume: float = 1.0
    language: str = "en"
    input_device: Optional[str] = None
    silence_seconds: float = 1.0
    max_command_seconds: float = 20.0
    wake_word: str = ""


# --- root config ------------------------------------------------------------


@dataclass
class SkillsSettings:
    """Knowledge packs (taught apps) and the optional API fast path."""

    enabled: bool = True
    directory: str = ""              # "" -> ~/.naveed/skills
    inject: bool = True              # put matched knowledge into the prompt
    max_context_chars: int = 3600    # budget for that knowledge (characters)
    teach_hotkey: str = "ctrl+alt+t"

    # --- the API fast path (off until configured) ------------------------
    # When a base URL is set, packs may offer direct REST tools. Reads are
    # allowed by default; writes need allow_api_writes, because an API call is
    # not the same thing as a click that a human can see happening.
    allow_api: bool = True
    allow_api_writes: bool = False
    polarion_base_url: str = ""
    polarion_token: str = ""
    polarion_project: str = ""
    polarion_endpoints: Dict[str, str] = field(default_factory=dict)


@dataclass
class Config:
    """The whole configuration tree."""

    llm: LLMSettings = field(default_factory=LLMSettings)
    overlay: OverlaySettings = field(default_factory=OverlaySettings)
    web: WebSettings = field(default_factory=WebSettings)
    capture: CaptureSettings = field(default_factory=CaptureSettings)
    safety: SafetySettings = field(default_factory=SafetySettings)
    agent: AgentSettings = field(default_factory=AgentSettings)
    voice: VoiceSettings = field(default_factory=VoiceSettings)
    skills: SkillsSettings = field(default_factory=SkillsSettings)
    #: where config.env itself was loaded from (empty when none was found)
    source_file: str = ""
    home: str = ""
    debug: bool = False

    # --- paths --------------------------------------------------------
    @property
    def base_dir(self) -> Path:
        return Path(self.home) if self.home else Path.home() / APP_DIR_NAME

    @property
    def screenshots_dir(self) -> Path:
        return Path(self.capture.directory) if self.capture.directory else self.base_dir / "screenshots"

    @property
    def logs_dir(self) -> Path:
        return self.base_dir / "logs"

    @property
    def models_dir(self) -> Path:
        return self.base_dir / "models"

    @property
    def state_dir(self) -> Path:
        return self.base_dir / "state"

    @property
    def skills_dir(self) -> Path:
        return Path(self.skills.directory) if self.skills.directory else self.base_dir / "skills"

    def ensure_dirs(self) -> "Config":
        for path in (self.base_dir, self.screenshots_dir, self.logs_dir, self.models_dir, self.state_dir, self.skills_dir):
            try:
                Path(path).mkdir(parents=True, exist_ok=True)
            except OSError:
                continue
        return self

    # --- serialisation -------------------------------------------------
    def as_dict(self, *, redact: bool = True) -> Dict[str, Any]:
        payload = asdict(self)
        if redact and payload.get("llm", {}).get("token"):
            payload["llm"]["token"] = "***"
        return payload

    def merged(self, **overrides: Any) -> "Config":
        """Return a copy with dotted-path overrides applied (``llm.model=...``).

        The sections are *replaced*, not mutated. ``dataclasses.replace`` is a
        shallow copy, so an earlier version set the field on a section object the
        caller still shared: `--dry-run` (and the panel's checkbox, and a recipe
        rehearsal) turned dry-run on in the live config for the rest of the
        session. Overriding one field must never reach back into the original.
        """
        clone = replace(self)
        for dotted, value in overrides.items():
            if value is None:
                continue
            section_name, _, field_name = dotted.partition(".")
            section = getattr(clone, section_name, None)
            if section is None or not field_name:
                continue
            if not hasattr(section, field_name):
                continue
            current = getattr(section, field_name)
            try:
                coerced = _coerce(value, type(current))
            except (TypeError, ValueError):
                coerced = value
            if hasattr(section, "__dataclass_fields__"):
                setattr(clone, section_name, replace(section, **{field_name: coerced}))
            else:
                setattr(section, field_name, coerced)
        return clone


# --- loading ----------------------------------------------------------------

def config_paths() -> List[Path]:
    """Candidate ``config.env`` locations, most specific first."""
    paths: List[Path] = []
    env_home = os.environ.get("NAVEED_HOME")
    if env_home:
        paths.append(Path(env_home) / ENV_FILE_NAME)
    paths.append(Path.cwd() / ENV_FILE_NAME)
    paths.append(Path.home() / APP_DIR_NAME / ENV_FILE_NAME)
    return paths


def _strip_inline_comment(value: str) -> str:
    """Drop a trailing ``# comment`` from a value.

    The shipped ``examples/config.env.example`` annotates almost every line this
    way, and until this existed the annotation was part of the value: numbers and
    booleans failed to parse and *silently kept their default* (so an edit did
    nothing), while strings kept the comment glued on (``LLM_MODEL`` became
    ``qwen2.5vl:7b  # a model``). A ``#`` only starts a comment when a space comes
    before it, so tokens and URLs that contain ``#`` survive.
    """
    quote = ""
    for index, character in enumerate(value):
        if quote:
            quote = "" if character == quote else quote
            continue
        if character in "\"'":
            quote = character
            continue
        if character == "#" and (index == 0 or value[index - 1].isspace()):
            return value[:index].strip()
    return value.strip()


def parse_env_file(path: Path) -> Dict[str, str]:
    """Parse a ``KEY=value`` file.

    Quotes are stripped, ``#`` starts a comment (at the start of a line, or after
    a space), and ``export`` prefixes are tolerated so the same file can be
    ``source``-d in a shell.
    """
    values: Dict[str, str] = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return values
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        value = _strip_inline_comment(value)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]        # inside quotes, everything is literal
        values[key] = value
    return values


def _coerce(value: Any, target_type: Any) -> Any:
    """Best-effort conversion of a string env value to the field's type."""
    if value is None or not isinstance(value, str):
        return value
    text = value.strip()
    if target_type is bool:
        return text.lower() in ("1", "true", "yes", "on", "y")
    if target_type is int:
        return int(float(text))
    if target_type is float:
        return float(text)
    if target_type is list or getattr(target_type, "__origin__", None) is list:
        items = [item.strip() for item in text.replace(";", ",").split(",")]
        return [item for item in items if item]
    if target_type is dict or getattr(target_type, "__origin__", None) is dict:
        # JSON is accepted because a mapping like the Polarion endpoints is much
        # easier to write that way — and silently mangling it into
        # '{"comments": "/polarion...' produced an endpoint that could only 404.
        if text.startswith("{"):
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                return {str(key): str(value) for key, value in parsed.items()}
        # Otherwise: ``key:value`` pairs, separated by ``;`` when one is present
        # (URLs contain commas, so a comma-separated list is not safe for these).
        separator = ";" if ";" in text else ","
        pairs = [pair for pair in text.split(separator) if ":" in pair]
        return {pair.split(":", 1)[0].strip(): pair.split(":", 1)[1].strip() for pair in pairs}
    return text


#: ``NAVEED_LLM_MODEL`` / ``LLM_TOKEN`` style environment names per field.
_ENV_PREFIX = "NAVEED_"
_ENV_ALIASES: Dict[str, str] = {
    "llm.token": "LLM_TOKEN",
    "llm.base_url": "LLM_API",
    "llm.model": "NAVEED_MODEL",
}

#: Older names, accepted so an existing config keeps working. Nothing documents
#: them: Naveed is configured with an API, and a key is not a concept here.
_LEGACY_ALIASES: Dict[str, str] = {
    "llm.token": "OPENAI_API_KEY",
    "llm.base_url": "OPENAI_BASE_URL",
}

#: Field names that are not literal field names: ``LLM_API=`` in config.env means
#: the endpoint, ``LLM_KEY=`` the optional token, and so on.
_FIELD_ALIASES: Dict[str, Dict[str, str]] = {
    "llm": {
        "api": "base_url",
        "url": "base_url",
        "endpoint": "base_url",
        "key": "token",
        "apikey": "token",
        "api_key": "token",
        "access_token": "token",
    },
}


def _apply_mapping(config: Config, values: Dict[str, str]) -> Config:
    """Apply ``SECTION_FIELD`` / ``SECTION.FIELD`` keys onto *config*."""
    for key, value in values.items():
        dotted = ""
        if "." in key:
            dotted = key
        elif "_" in key:
            head, _, tail = key.partition("_")
            if hasattr(config, head.lower()):
                dotted = f"{head.lower()}.{tail.lower()}"
        if not dotted:
            continue
        section_name, _, field_name = dotted.partition(".")
        field_name = _FIELD_ALIASES.get(section_name, {}).get(field_name, field_name)
        section = getattr(config, section_name, None)
        if section is None or not hasattr(section, field_name):
            continue
        current = getattr(section, field_name)
        try:
            setattr(section, field_name, _coerce(value, type(current)))
        except (TypeError, ValueError):
            continue
    return config


def load_config(
    *,
    env_file: Optional[str] = None,
    use_environment: bool = True,
    ensure_dirs: bool = True,
    **overrides: Any,
) -> Config:
    """Build the effective configuration.

    ``env_file`` forces one specific file; otherwise the first existing file from
    :func:`config_paths` is used.  Real environment variables always win over the
    file so a CI system or a launcher script can override anything.
    """
    config = Config(home=os.environ.get("NAVEED_HOME", ""))
    candidates = [Path(env_file)] if env_file else config_paths()
    for candidate in candidates:
        if candidate.is_file():
            config.source_file = str(candidate)
            _apply_mapping(config, parse_env_file(candidate))
            break

    if use_environment:
        env_values: Dict[str, str] = {}
        for key, value in os.environ.items():
            if key.upper().startswith(_ENV_PREFIX):
                env_values[key[len(_ENV_PREFIX):]] = value
        for dotted, env_name in _ENV_ALIASES.items():
            if dotted not in env_values and os.environ.get(env_name):
                env_values[dotted] = os.environ[env_name]
        for dotted, env_name in _LEGACY_ALIASES.items():
            if dotted not in env_values and os.environ.get(env_name):
                env_values[dotted] = os.environ[env_name]
        _apply_mapping(config, env_values)
        if os.environ.get("NAVEED_PROVIDER"):
            _apply_preset(config, os.environ["NAVEED_PROVIDER"])

    # CLI-style overrides: llm_model="x" or "llm.model"="x"
    normalized: Dict[str, Any] = {}
    for key, value in overrides.items():
        normalized[key.replace("_", ".", 1) if "_" in key and "." not in key else key] = value
    config = config.merged(**normalized)

    if ensure_dirs:
        config.ensure_dirs()
    return config


def _apply_preset(config: Config, name: str) -> Config:
    """Apply one of :data:`PROVIDER_PRESETS` by name."""
    preset = PROVIDER_PRESETS.get(name.strip().lower())
    if not preset:
        return config
    config.llm.base_url = preset.get("base_url", config.llm.base_url)
    config.llm.model = preset.get("model", config.llm.model)
    return config


def write_env_file(config: Config, path: Optional[str] = None) -> str:
    """Write the current settings back out (used by the panel's settings sheet).

    The LLM API (endpoint, model) is what makes the file a working configuration.
    A token is written verbatim only when one is set, so the file is complete; it
    is created with owner-only permissions where the OS supports it.
    """
    target = Path(path) if path else (Path(config.base_dir) / ENV_FILE_NAME)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Naveed configuration",
        "# Generated by Naveed. Edit by hand or from the panel's settings sheet.",
        f"# provider presets: {', '.join(sorted(PROVIDER_PRESETS))}",
        "",
        "LLM_API=" + config.llm.base_url,
        "LLM_MODEL=" + config.llm.model,
        *(("LLM_TOKEN=" + config.llm.token,) if config.llm.token else ()),
        f"LLM_VISION={'true' if config.llm.vision else 'false'}",
        f"LLM_TEMPERATURE={config.llm.temperature}",
        f"LLM_MAX_TOKENS={config.llm.max_tokens}",
        "",
        f"OVERLAY_SIZE={config.overlay.size}",
        f"OVERLAY_ALWAYS_ON_TOP={'true' if config.overlay.always_on_top else 'false'}",
        f"OVERLAY_HOTKEY={config.overlay.hotkey}",
        f"OVERLAY_TRAY={'true' if config.overlay.tray else 'false'}",
        "",
        f"WEB_HOST={config.web.host}",
        f"WEB_PORT={config.web.port}",
        f"WEB_OPEN_BROWSER={'true' if config.web.open_browser else 'false'}",
        "",
        f"CAPTURE_INTERVAL={config.capture.interval}",
        f"CAPTURE_IDLE_INTERVAL={config.capture.idle_interval}",
        f"CAPTURE_TARGET={config.capture.target}",
        f"CAPTURE_SAVE_FRAMES={'true' if config.capture.save_frames else 'false'}",
        f"CAPTURE_MAX_CAPTURES={config.capture.max_captures}",
        "",
        f"SAFETY_CONFIRM_DESTRUCTIVE={'true' if config.safety.confirm_destructive else 'false'}",
        f"SAFETY_ALLOW_SHELL={'true' if config.safety.allow_shell else 'false'}",
        f"SAFETY_DRY_RUN={'true' if config.safety.dry_run else 'false'}",
        "",
        f"VOICE_STT={config.voice.stt}",
        f"VOICE_TTS={config.voice.tts}",
        f"VOICE_WHISPER_MODEL={config.voice.whisper_model}",
        f"VOICE_PIPER_VOICE={config.voice.piper_voice}",
        "",
    ]
    target.write_text("\n".join(lines), encoding="utf-8")
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return str(target)
