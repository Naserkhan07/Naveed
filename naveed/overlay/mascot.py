"""The character itself: geometry, expression and animation.

Everything about Naveed's look is *drawn* from :mod:`naveed.overlay.theme`
proportions rather than loaded from a sprite, for three reasons:

1. it stays razor sharp at any size and any DPI, including the transparent
   always-on-top overlay where scaled bitmaps show obvious edges;
2. expressions are parameters (``blink``, ``mouth``, ``state``), so the mascot can
   blink, breathe, think, and lip-sync to synthesised speech without an asset
   pipeline;
3. the same code paints through Qt at runtime and through Pillow in
   :mod:`naveed.render.preview`, which is how the character can be reviewed,
   documented and regression-tested on a machine with no display.

The design follows the reference exactly: rounded-square body, orange-to-coral
gradient top half, puffy white cloud face, two round black eyes with a glint, a
tiny open pink mouth, two soft pink blush marks — symmetrical, no hair, ears,
limbs, clothing or extra details.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from ..render.canvas import Canvas, Color, with_alpha
from .theme import MASCOT, PALETTE, state_color

__all__ = [
    "MascotAnimator",
    "STATES",
    "paint_mascot",
    "paint_mascot_shadow",
    "mascot_bounds",
]

#: Every expression the companion can hold.
STATES: Tuple[str, ...] = (
    "idle",
    "listening",
    "thinking",
    "speaking",
    "acting",
    "success",
    "error",
    "sleeping",
)

_EYE_STYLE: Dict[str, str] = {
    "idle": "round",
    "listening": "wide",
    "thinking": "look-up",
    "speaking": "round",
    "acting": "focus",
    "success": "happy",
    "error": "flat",
    "sleeping": "closed",
}


# --- animation --------------------------------------------------------------

@dataclass
class AnimationFrame:
    """The animated parameters one painted frame needs."""

    float_offset: float = 0.0
    blink: float = 1.0          # 1.0 open, 0.06 closed
    mouth: float = 0.0          # 0.0 closed, 1.0 wide open
    phase: float = 0.0          # generic progress for rings/spinners
    squash: float = 0.0         # -1..1, gentle breathing squash


class MascotAnimator:
    """Time-based animation state: float, blink, mouth, pulse.

    Kept free of any toolkit so the same animator can drive the Qt overlay at
    30 fps and the preview generator at whatever timestamps it likes.
    """

    def __init__(self, *, seed: Optional[int] = None, float_period: float = 3.4, float_amplitude: float = 0.022) -> None:
        self._random = random.Random(seed)
        self.time = 0.0
        self.float_period = float_period
        self.float_amplitude = float_amplitude
        self._next_blink = self._random.uniform(1.6, 4.2)
        self._blink_t = -1.0
        self.blink_duration = 0.16
        self._speech_phase = 0.0
        self._mouth = 0.0
        self._state = "idle"
        self._state_time = 0.0

    # --- state --------------------------------------------------------
    def set_state(self, state: str) -> None:
        if state not in STATES:
            state = "idle"
        if state != self._state:
            self._state = state
            self._state_time = 0.0
            if state in ("speaking", "listening"):
                self._next_blink = self.time + self._random.uniform(1.0, 2.0)

    @property
    def state(self) -> str:
        return self._state

    def speak_pulse(self, mouth: Optional[float] = None) -> None:
        """Feed an explicit mouth openness, or ``None`` for synthetic speaking."""
        if mouth is not None:
            self._mouth = min(max(float(mouth), 0.0), 1.0)

    def update(self, delta: float) -> AnimationFrame:
        """Advance by *delta* seconds and return the frame to paint."""
        delta = max(0.0, min(delta, 0.25))
        self.time += delta
        self._state_time += delta

        # Blinking: skipped while asleep (eyes are already closed) and driven
        # randomly so it never looks like a metronome.
        if self._state == "sleeping":
            self._blink_t = -1.0
        elif self._blink_t >= 0.0:
            self._blink_t += delta
        elif self.time >= self._next_blink:
            self._blink_t = 0.0
            self._next_blink = self.time + self._random.uniform(2.2, 6.4)

        blink = 1.0
        if self._state == "sleeping":
            blink = 0.0
        elif self._blink_t >= 0.0:
            progress = self._blink_t / self.blink_duration
            if progress >= 1.0:
                self._blink_t = -1.0
            else:
                # Close then open: a smooth half-sine over the blink window.
                blink = max(0.06, abs(math.cos(progress * math.pi)))

        # Mouth: real speech input when it arrives, otherwise a plausible
        # synthetic cadence while "speaking".
        mouth = self._mouth
        if self._state == "speaking":
            self._speech_phase += delta * 9.0
            synthetic = 0.5 + 0.5 * math.sin(self._speech_phase) * math.sin(self._speech_phase * 0.37 + 1.1)
            mouth = max(self._mouth, abs(synthetic) ** 0.8)
            self._mouth *= max(0.0, 1.0 - delta * 3.0)
        elif self._state == "listening":
            mouth = 0.18 + 0.08 * math.sin(self.time * 3.0)
        else:
            self._mouth *= max(0.0, 1.0 - delta * 4.0)

        amplitude = self.float_amplitude
        if self._state == "thinking":
            amplitude *= 1.5
        float_offset = math.sin(self.time * (2.0 * math.pi / self.float_period)) * amplitude
        squash = math.sin(self.time * 1.7) * 0.035

        return AnimationFrame(
            float_offset=float_offset,
            blink=blink,
            mouth=min(mouth, 1.0),
            phase=self.time,
            squash=squash,
        )


# --- painting helpers -------------------------------------------------------

def mascot_bounds(left: float, top: float, size: float) -> Tuple[float, float, float, float]:
    """Body rectangle inside a *size* x *size* paint box."""
    inset = size * MASCOT.body_inset
    return (left + inset, top + inset, size - inset * 2.0, size - inset * 2.0)


def _stroke_arc(
    canvas: Canvas,
    cx: float,
    cy: float,
    radius: float,
    start: float,
    end: float,
    color: Color,
    width: float,
    *,
    steps: int = 22,
) -> None:
    """Arc as a polyline: works identically on QPainter and Pillow."""
    if end < start:
        start, end = end, start
    previous: Optional[Tuple[float, float]] = None
    for index in range(steps + 1):
        angle = start + (end - start) * (index / float(steps))
        point = (cx + math.cos(angle) * radius, cy + math.sin(angle) * radius)
        if previous is not None:
            canvas.line(previous[0], previous[1], point[0], point[1], color=color, width=width)
        previous = point


def _sparkle(canvas: Canvas, cx: float, cy: float, radius: float, color: Color) -> None:
    """Four-point glint used for the success state."""
    points = [
        (cx, cy - radius),
        (cx + radius * 0.22, cy - radius * 0.22),
        (cx + radius, cy),
        (cx + radius * 0.22, cy + radius * 0.22),
        (cx, cy + radius),
        (cx - radius * 0.22, cy + radius * 0.22),
        (cx - radius, cy),
        (cx - radius * 0.22, cy - radius * 0.22),
    ]
    canvas.polygon(points, fill=color)


def paint_mascot_shadow(canvas: Canvas, left: float, top: float, size: float, *, strength: float = 0.34) -> None:
    """Soft drop shadow beneath the floating body.

    Painted separately from :func:`paint_mascot` so the overlay can put the
    shadow on the desktop layer while the body floats above it, which is what
    makes the character read as *floating* instead of stuck to the glass.
    """
    body_left, body_top, body_size, _ = mascot_bounds(left, top, size)
    cx = body_left + body_size / 2.0
    cy = body_top + body_size * 0.99
    canvas.radial(
        cx,
        cy,
        body_size * 0.46,
        [
            (0.0, with_alpha("#000000", strength)),
            (0.55, with_alpha("#000000", strength * 0.45)),
            (1.0, with_alpha("#000000", 0.0)),
        ],
    )


def paint_mascot(
    canvas: Canvas,
    left: float,
    top: float,
    size: float,
    *,
    state: str = "idle",
    blink: float = 1.0,
    mouth: float = 0.0,
    phase: float = 0.0,
    squash: float = 0.0,
    shadow: bool = True,
    glow: bool = True,
) -> None:
    """Paint the companion into *canvas* at ``(left, top, size)``.

    Drawing may extend slightly outside the box (shadow, glow, thought dots,
    sleep marks), so a widget should reserve about 24 % padding.
    """
    state = state if state in STATES else "idle"
    metrics = MASCOT
    x, y, s, _ = mascot_bounds(left, top, size)
    # Breathing squash keeps the silhouette alive even when nothing else moves.
    s_y = s * (1.0 - squash * 0.5)
    y_shift = (s - s_y) * 0.5
    cx = x + s / 2.0
    cy = y_shift + y + s_y / 2.0
    accent = state_color(state)

    if shadow:
        paint_mascot_shadow(canvas, left, top, size)

    # --- ambient glow (also the state indicator) ----------------------
    if glow:
        glow_alpha = 0.26 if state == "idle" else 0.4
        canvas.radial(
            cx,
            cy,
            s * metrics.glow_radius,
            [
                (0.0, with_alpha(accent, glow_alpha)),
                (0.62, with_alpha(accent, glow_alpha * 0.42)),
                (1.0, with_alpha(accent, 0.0)),
            ],
        )

    # --- listening rings ----------------------------------------------
    if state == "listening":
        for index in range(2):
            pulse = (phase * 0.9 + index * 0.5) % 1.0
            radius = s * metrics.ring_radius + s * 0.18 * pulse
            alpha = 0.42 * (1.0 - pulse)
            canvas.circle(cx, cy, radius, outline=with_alpha(accent, alpha), outline_width=max(1.5, s * 0.012))

    # --- body ---------------------------------------------------------
    radius = s * metrics.body_radius
    canvas.gradient(
        x,
        y_shift + y,
        s,
        s_y,
        [
            (0.0, PALETTE["orange"]),
            (metrics.gradient_mid, PALETTE["orange"]),
            (metrics.gradient_coral, PALETTE["coral"]),
            (1.0, PALETTE["coral_deep"]),
        ],
        radius=radius,
        direction="vertical",
    )
    # Glossy top-left sheen, the "premium app icon" light.
    canvas.radial(
        x + s * 0.31,
        y_shift + y + s_y * 0.13,
        s * 0.52,
        [(0.0, with_alpha("#FFFFFF", 0.24)), (0.62, with_alpha("#FFFFFF", 0.05)), (1.0, with_alpha("#FFFFFF", 0.0))],
    )
    # Inner rim light so the body separates from any wallpaper behind it.
    canvas.rect(
        x,
        y_shift + y,
        s,
        s_y,
        radius=radius,
        outline=with_alpha("#FFFFFF", 0.18),
        outline_width=max(1.0, s * 0.008),
    )

    # --- white cloud face ---------------------------------------------
    # The cloud is a puffy mass filling the lower half of the body: a wide
    # rounded block, billowing scallops along its top edge, and a wavy underside
    # that sits on a slightly shaded base so the silhouette reads as a cloud
    # rather than a pasted white rectangle.
    cloud_left = x
    cloud_width = s
    cloud_top = y_shift + y + s_y * metrics.cloud_top
    cloud_bottom = y_shift + y + s_y * metrics.cloud_bottom
    cloud_height = cloud_bottom - cloud_top
    scallop_radius = s * metrics.scallop_radius

    # Shaded base under the cloud: the soft grey-blue underside of the face.
    base_top = y_shift + y + s_y * metrics.cloud_base_top
    canvas.rect(
        x,
        base_top,
        s,
        max(1.0, (y_shift + y + s_y) - base_top),
        radius=s * metrics.body_radius,
        fill=PALETTE["cloud_base"],
    )

    # The cloud mass itself.
    canvas.rect(cloud_left, cloud_top, cloud_width, cloud_height, radius=s * metrics.cloud_radius, fill=PALETTE["cloud"])

    # Scallops along the top edge.  End scallops are smaller, and each one casts
    # a soft shadow onto the orange behind it, which is what gives the cloud its
    # puffy depth.  Order matters: shadow, then all the white caps, so no shadow
    # ever lands on top of a neighbour.
    scallop_centres = []
    for index in range(metrics.scallop_count):
        ratio = (index + 0.5) / metrics.scallop_count
        distance_from_edge = abs(ratio - 0.5) * 2.0
        radius = scallop_radius * (1.0 - (1.0 - metrics.scallop_edge_scale) * distance_from_edge)
        scallop_centres.append((cloud_left + cloud_width * ratio, radius))
    for centre_x, radius in scallop_centres:
        canvas.circle(
            centre_x,
            cloud_top + scallop_radius * 0.10,
            radius + max(1.0, s * 0.010),
            fill=with_alpha(PALETTE["cloud_shade"], 0.16),
        )
    for centre_x, radius in scallop_centres:
        canvas.circle(centre_x, cloud_top + scallop_radius * 0.10, radius, fill=PALETTE["cloud"])

    # A soft contact shadow seats the cloud onto the orange torso.
    canvas.radial(
        cx,
        cloud_top + cloud_height * 0.08,
        s * 0.52,
        [(0.0, with_alpha(PALETTE["cloud_shade"], 0.34)), (1.0, with_alpha(PALETTE["cloud_shade"], 0.0))],
    )
    canvas.rect(cloud_left, cloud_top, cloud_width, cloud_height, radius=s * metrics.cloud_radius, fill=PALETTE["cloud"])

    # Soft shading and highlight so the white is not flat.
    canvas.radial(
        cx,
        y_shift + y + s_y * 0.97,
        s * 0.46,
        [(0.0, with_alpha(PALETTE["cloud_deep"], 0.34)), (1.0, with_alpha(PALETTE["cloud_deep"], 0.0))],
    )
    canvas.radial(
        cx - s * 0.04,
        cloud_top + cloud_height * 0.22,
        s * 0.36,
        [(0.0, with_alpha("#FFFFFF", 0.85)), (1.0, with_alpha("#FFFFFF", 0.0))],
    )

    # --- blush --------------------------------------------------------
    for direction in (-1, 1):
        blush_x = cx + direction * s * metrics.blush_dx
        canvas.radial(
            blush_x,
            y_shift + y + s_y * metrics.blush_y,
            s * metrics.blush_radius,
            [
                (0.0, with_alpha(PALETTE["blush"], 0.62)),
                (0.62, with_alpha(PALETTE["blush"], 0.34)),
                (1.0, with_alpha(PALETTE["blush"], 0.0)),
            ],
        )

    # --- eyes ---------------------------------------------------------
    eye_style = _EYE_STYLE.get(state, "round")
    eye_radius = s * metrics.eye_radius * (1.06 if eye_style == "wide" else 1.0)
    look_up = eye_style == "look-up"
    eye_y = y_shift + y + s_y * metrics.eye_y - (s * 0.014 if look_up else 0.0)
    for direction in (-1, 1):
        eye_x = cx + direction * s * metrics.eye_dx
        if eye_style in ("happy", "closed", "flat"):
            if eye_style == "happy":
                _stroke_arc(canvas, eye_x, eye_y + eye_radius * 0.5, eye_radius * 1.05, math.pi * 1.15, math.pi * 1.85, PALETTE["ink"], max(1.6, s * 0.026))
            else:
                canvas.line(
                    eye_x - eye_radius * 0.95,
                    eye_y,
                    eye_x + eye_radius * 0.95,
                    eye_y,
                    color=PALETTE["ink"],
                    width=max(1.6, s * 0.024),
                )
            continue

        openness = 1.0 if state == "sleeping" else blink
        if openness <= 0.16:
            canvas.line(
                eye_x - eye_radius * 0.9,
                eye_y,
                eye_x + eye_radius * 0.9,
                eye_y,
                color=PALETTE["ink"],
                width=max(1.4, s * 0.02),
            )
            continue

        height = eye_radius * 2.0 * openness
        canvas.ellipse(
            eye_x - eye_radius,
            eye_y - height / 2.0,
            eye_radius * 2.0,
            height,
            fill=PALETTE["ink"],
        )
        if openness > 0.55:
            glint = s * metrics.eye_highlight * (0.75 if eye_style == "focus" else 1.0)
            canvas.circle(
                eye_x - eye_radius * 0.34,
                eye_y - height * 0.24,
                glint,
                fill=with_alpha("#FFFFFF", 0.92),
            )
            canvas.circle(
                eye_x + eye_radius * 0.34,
                eye_y + height * 0.22,
                glint * 0.42,
                fill=with_alpha("#FFFFFF", 0.5),
            )

    # --- mouth --------------------------------------------------------
    mouth_w = s * metrics.mouth_w * (1.0 + 0.55 * mouth)
    mouth_h = s * metrics.mouth_h * (0.55 + 1.15 * mouth)
    mouth_y = y_shift + y + s_y * metrics.mouth_y
    if state == "success":
        _stroke_arc(canvas, cx, mouth_y - s * 0.02, s * 0.075, math.pi * 0.18, math.pi * 0.82, PALETTE["ink"], max(1.8, s * 0.028))
    else:
        canvas.ellipse(
            cx - mouth_w / 2.0,
            mouth_y - mouth_h / 2.0,
            mouth_w,
            mouth_h,
            fill=PALETTE["pink_deep"],
        )
        canvas.ellipse(
            cx - mouth_w * 0.36,
            mouth_y - mouth_h * 0.24,
            mouth_w * 0.72,
            mouth_h * 0.62,
            fill=PALETTE["pink"],
        )

    # --- state adornments --------------------------------------------
    if state == "thinking":
        for index in range(3):
            dot_phase = (phase * 1.5 - index * 0.22) % 1.0
            lift = max(0.0, math.sin(dot_phase * math.pi)) * s * 0.045
            canvas.circle(
                cx + (index - 1) * s * 0.11,
                y_shift + y + s_y + s * 0.085 - lift,
                s * 0.028,
                fill=with_alpha(accent, 0.85 - index * 0.13),
            )
    elif state == "acting":
        spin = (phase * 1.1) % 1.0
        start = spin * math.tau
        _stroke_arc(
            canvas,
            cx,
            cy,
            s * (metrics.ring_radius + 0.05),
            start,
            start + math.pi * 1.25,
            with_alpha(accent, 0.9),
            max(2.0, s * 0.016),
            steps=26,
        )
    elif state == "success":
        for index, (dx, dy) in enumerate(((-0.44, -0.30), (0.46, -0.34), (0.5, 0.3), (-0.5, 0.26))):
            _sparkle(
                canvas,
                cx + s * dx,
                cy + s * dy,
                s * (0.05 if index % 2 == 0 else 0.038),
                with_alpha(accent, 0.95),
            )
    elif state == "error":
        bubble_w, bubble_h = s * 0.20, s * 0.16
        bubble_x = cx + s * 0.28
        bubble_y = y_shift + y + s_y * 0.10
        canvas.line(bubble_x - bubble_w * 0.1, bubble_y + bubble_h, bubble_x - bubble_w * 0.35, bubble_y + bubble_h * 1.25, color=PALETTE["error"], width=max(2.0, s * 0.02))
        canvas.rect(bubble_x - bubble_w / 2.0, bubble_y, bubble_w, bubble_h, radius=bubble_h * 0.42, fill=PALETTE["error"])
        canvas.text(
            bubble_x,
            bubble_y + bubble_h * 0.5,
            "!",
            size=max(9.0, s * 0.12),
            color="#FFFFFF",
            weight="bold",
            anchor="mm",
        )
    elif state == "sleeping":
        for index in range(3):
            drift = ((phase * 0.35) + index * 0.33) % 1.0
            canvas.text(
                cx + s * (0.30 + index * 0.10),
                y_shift + y + s_y * (0.10 - index * 0.06) - drift * s * 0.06,
                "z",
                size=max(8.0, s * (0.075 + index * 0.022)),
                color=with_alpha(PALETTE["sleeping"], max(0.0, 0.85 - index * 0.2)),
                weight="bold",
                anchor="mm",
            )
