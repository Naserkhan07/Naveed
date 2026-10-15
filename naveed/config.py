"""Configuration, paths and the (tiny) settings model.

Everything Naveed can be told lives in one dataclass tree so the control panel,
the CLI and the tests all read the same values.  Values are resolved in this
order, last one wins:

1. built-in defaults (this file),
2. ``~/.naveed/config.env`` — a plain ``KEY=value`` file, no dependency needed,
3. real environment variables,
4. explicit CLI flags (``python -m naveed --model ...``).

The file is ``.env``-style on purpose: it keeps API keys out of source control,
works the same on every OS, and can be edited by hand or from the panel's
settings sheet.
"""

from __future__ import annotations

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
    "load_config",
    "config_paths",
    "parse_env_file",
    "PROVIDER_PRESETS",
    "write_env_file",
]

APP_DIR_NAME = ".naveed"
ENV_FILE_NAME = "config.env"

#: Ready-made providers, so "use a small LLM" is a two-word answer.
PROVIDER_PRESETS: Dict[str, Dict[str, str]] = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "note": "small, fast, vision-capable",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "qwen/qwen2.5-vl-7b-instruct",
        "note": "cheap vision models, one key for many vendors",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.2-11b-vision-preview",
        "note": "very low latency",
    },
    "ollama": {
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "qwen2.5vl:7b",
        "note": "fully local, no key needed",
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
    """The "small LLM" that decides what to click.

    Any OpenAI-compatible endpoint works, including a local llama.cpp/Ollama
    server, so Naveed can run with no cloud key at all when a local model is
    present.
    """

    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
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
        """True when a request could plausibly succeed."""
        if not self.model or not self.base_url:
            return False
        local = any(host in self.base_url for host in ("127.0.0.1", "localhost", "0.0.0.0"))
        return bool(self.api_key) or local

    @property
    def label(self) -> str:
        return f"{self.model} @ {self.base_url.split('//')[-1].split('/')[0]}"


@dataclass
class OverlaySettings:
    """The floating companion window."""

    size: int = 168                 # mascot body size in logical pixels
    padding: int = 46               # transparent margin for glow/shadow/rings
    x: Optional[int] = None         # None -> centred horizontally
    y: Optional[int] = None         # None -> slightly below the vertical midpoint
    offset_from_middle: float = 0.16
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
class Config:
    """The whole configuration tree."""

    llm: LLMSettings = field(default_factory=LLMSettings)
    overlay: OverlaySettings = field(default_factory=OverlaySettings)
    capture: CaptureSettings = field(default_factory=CaptureSettings)
    safety: SafetySettings = field(default_factory=SafetySettings)
    agent: AgentSettings = field(default_factory=AgentSettings)
    voice: VoiceSettings = field(default_factory=VoiceSettings)
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

    def ensure_dirs(self) -> "Config":
        for path in (self.base_dir, self.screenshots_dir, self.logs_dir, self.models_dir, self.state_dir):
            try:
                Path(path).mkdir(parents=True, exist_ok=True)
            except OSError:
                continue
        return self

    # --- serialisation -------------------------------------------------
    def as_dict(self, *, redact: bool = True) -> Dict[str, Any]:
        payload = asdict(self)
        if redact and payload.get("llm", {}).get("api_key"):
            payload["llm"]["api_key"] = "***"
        return payload

    def merged(self, **overrides: Any) -> "Config":
        """Return a copy with dotted-path overrides applied (``llm.model=...``)."""
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


def parse_env_file(path: Path) -> Dict[str, str]:
    """Parse a ``KEY=value`` file.

    Quotes are stripped, ``#`` starts a comment, and ``export`` prefixes are
    tolerated so the same file can be ``source``-d in a shell.
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
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
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
        pairs = [pair for pair in text.split(",") if ":" in pair]
        return {pair.split(":", 1)[0].strip(): pair.split(":", 1)[1].strip() for pair in pairs}
    return text


#: ``NAVEED_LLM_MODEL`` / ``OPENAI_API_KEY`` style environment names per field.
_ENV_PREFIX = "NAVEED_"
_ENV_ALIASES: Dict[str, str] = {
    "llm.api_key": "OPENAI_API_KEY",
    "llm.base_url": "OPENAI_BASE_URL",
    "llm.model": "NAVEED_MODEL",
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

    The API key is written verbatim so the file is a working configuration, and
    the file is created with owner-only permissions where the OS supports it.
    """
    target = Path(path) if path else (Path(config.base_dir) / ENV_FILE_NAME)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Naveed configuration",
        "# Generated by Naveed. Edit by hand or from the panel's settings sheet.",
        f"# provider presets: {', '.join(sorted(PROVIDER_PRESETS))}",
        "",
        "LLM_BASE_URL=" + config.llm.base_url,
        "LLM_API_KEY=" + config.llm.api_key,
        "LLM_MODEL=" + config.llm.model,
        f"LLM_VISION={'true' if config.llm.vision else 'false'}",
        f"LLM_TEMPERATURE={config.llm.temperature}",
        f"LLM_MAX_TOKENS={config.llm.max_tokens}",
        "",
        f"OVERLAY_SIZE={config.overlay.size}",
        f"OVERLAY_ALWAYS_ON_TOP={'true' if config.overlay.always_on_top else 'false'}",
        f"OVERLAY_HOTKEY={config.overlay.hotkey}",
        f"OVERLAY_TRAY={'true' if config.overlay.tray else 'false'}",
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
