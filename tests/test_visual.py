"""Visual regression: the mascot still looks like the reference.

Pixel assertions on generated art are crude, but they catch exactly the mistakes
that hurt: the cloud drifting up into the orange, the eyes sliding off-centre, a
state losing its expression, or the palette silently changing.  They also run
anywhere — no display and no Qt — because the art is rendered through
:mod:`naveed.render.preview` with Pillow.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from naveed.overlay.mascot import STATES, paint_mascot
from naveed.render.pillow_canvas import PillowCanvas

SIZE = 200
PAD = int(SIZE * 0.24)
OUT = "/tmp/naveed-visual"


def render(state: str = "idle", *, mouth: float = 0.0, size: int = SIZE, background=None):
    """Paint the mascot onto its own transparent canvas.

    Transparent, not dark: the mascot is drawn on a transparent always-on-top
    window, so "does it leave an opaque rectangle behind it" is a real bug class
    and has to be testable.  Pass ``background="#101018"`` for a viewable sheet.
    """
    canvas = PillowCanvas(size + PAD * 2, size + PAD * 2, background=background)
    paint_mascot(canvas, PAD, PAD, size, state=state, blink=1.0, mouth=mouth, phase=0.3)
    return canvas.image


def at(image, fraction_x: float, fraction_y: float):
    """Sample the body at a fractional position (0, 0 = body top-left)."""
    x = int(PAD + SIZE * fraction_x)
    y = int(PAD + SIZE * fraction_y)
    return image.getpixel((x, y))


class MascotLookTests(unittest.TestCase):
    def test_upper_half_is_orange_and_lower_half_is_white(self):
        image = render("idle")
        top = at(image, 0.5, 0.12)
        self.assertGreater(top[0], 200, "the upper half should be the orange gradient")
        self.assertLess(top[2], 150)
        lower = at(image, 0.5, 0.80)
        self.assertGreater(min(lower[:3]), 220, "the lower half should be the white cloud")

    def test_gradient_runs_from_orange_to_coral(self):
        image = render("idle")
        left = at(image, 0.06, 0.10)
        middle = at(image, 0.5, 0.30)
        self.assertNotEqual(left[:3], middle[:3], "the body must have a visible gradient")

    def test_eyes_are_dark_and_symmetric(self):
        from naveed.overlay.theme import MASCOT

        image = render("idle")
        left_eye = at(image, 0.5 - MASCOT.eye_dx, MASCOT.eye_y)
        right_eye = at(image, 0.5 + MASCOT.eye_dx, MASCOT.eye_y)
        for eye in (left_eye, right_eye):
            self.assertLess(sum(eye[:3]), 280, "the eyes should be near-black")
        self.assertLess(abs(left_eye[0] - right_eye[0]), 40, "the eyes should match")

    def test_face_is_left_right_symmetric(self):
        image = render("idle").convert("RGB")
        width, height = image.size
        centre = width // 2
        top = int(PAD + SIZE * 0.52)
        bottom = int(PAD + SIZE * 0.92)
        mismatches = 0
        samples = 0
        for y in range(top, bottom, 3):
            for offset in range(4, int(SIZE * 0.42), 3):
                left = image.getpixel((centre - offset, y))
                right = image.getpixel((centre + offset, y))
                samples += 1
                if sum(abs(left[index] - right[index]) for index in range(3)) > 26:
                    mismatches += 1
        self.assertLess(
            mismatches / max(1, samples),
            0.06,
            "the cloud face must be symmetrical about the centre line",
        )

    def test_blush_is_on_both_cheeks(self):
        from naveed.overlay.theme import MASCOT

        image = render("idle")
        for direction in (-1, 1):
            pixel = at(image, 0.5 + direction * MASCOT.blush_dx, MASCOT.blush_y)
            self.assertGreater(pixel[0], pixel[2], "the cheeks should be warm pink on both sides")

    def test_mouth_is_pink_and_opens_while_speaking(self):
        from naveed.overlay.theme import MASCOT

        closed = render("idle", mouth=0.0)
        speaking = render("speaking", mouth=1.0)
        column = int(PAD + SIZE * 0.5)
        centre_row = int(PAD + SIZE * MASCOT.mouth_y)

        closed_pixel = closed.getpixel((column, centre_row))
        self.assertGreater(closed_pixel[0], closed_pixel[2], "the mouth should be pink/red")

        def pink_rows(image) -> int:
            rows = 0
            for y in range(centre_row - int(SIZE * 0.09), centre_row + int(SIZE * 0.09)):
                pixel = image.getpixel((column, y))
                if pixel[0] > 180 and pixel[1] < 200 and pixel[0] - pixel[2] > 20:
                    rows += 1
            return rows

        self.assertGreater(pink_rows(speaking), pink_rows(closed), "the mouth must open when speaking")

    def test_transparent_background_outside_the_body(self):
        image = render("idle")
        for point in ((2, 2), (image.width - 3, 2), (2, image.height - 3), (image.width - 3, image.height - 3)):
            self.assertEqual(image.getpixel(point)[3], 0, "the corners must stay transparent")
        # The body itself must be fully opaque, or the desktop would show through
        # the mascot's face.
        self.assertEqual(at(image, 0.5, 0.5)[3], 255)

    def test_every_state_renders_and_they_all_differ(self):
        rendered = {}
        for state in STATES:
            image = render(state, mouth=0.5)
            rendered[state] = image.tobytes()
        self.assertEqual(len(set(rendered.values())), len(STATES), "two expressions render identically")


class PreviewTests(unittest.TestCase):
    def test_mascot_export_is_transparent_and_correctly_sized(self):
        from PIL import Image

        from naveed.render.preview import render_mascot_png

        path = render_mascot_png(f"{OUT}-mascot.png", size=256)
        with Image.open(path) as image:
            self.assertEqual(image.size, (256, 256))
            self.assertEqual(image.mode, "RGBA")
            lowest, highest = image.getchannel("A").getextrema()
            self.assertEqual(lowest, 0, "the export must include transparent pixels")
            self.assertGreater(highest, 200, "the body must be opaque somewhere")

    def test_expression_sheet_grid_matches_its_columns(self):
        from PIL import Image

        from naveed.render.preview import render_mascot_sheet

        size = 120
        padding = int(size * 0.24)
        cell = size + padding * 2
        path = render_mascot_sheet(f"{OUT}-states.png", size=size)
        with Image.open(path) as image:
            self.assertEqual(image.size, (cell * 4, cell * 2))
        self.assertTrue(os.path.exists(path))

    def test_panel_mock_keeps_the_panel_proportions(self):
        from PIL import Image

        from naveed.overlay.theme import PANEL
        from naveed.render.preview import render_panel_mock

        scale = 1.4
        path = render_panel_mock(f"{OUT}-panel.png", scale=scale)
        with Image.open(path) as image:
            # 16px margin all round, and the glass body at the panel's own ratio.
            expected_w = int(PANEL.width * scale) + 32
            expected_h = int(PANEL.height * scale) + 32
            self.assertEqual(image.size, (expected_w, expected_h))

    def test_desktop_mock_places_the_panel_above_the_mascot(self):
        from PIL import Image

        from naveed.render.preview import render_desktop_mock

        path = render_desktop_mock(f"{OUT}-desktop.png", width=900, height=600)
        with Image.open(path) as image:
            self.assertEqual(image.size, (900, 600))
            panel_band = image.crop((250, 120, 650, 250)).convert("L")
            empty_band = image.crop((0, 0, 160, 30)).convert("L")

            def mean(band) -> float:
                data = list(band.getdata())
                return sum(data) / max(1, len(data))

            self.assertGreater(mean(panel_band), mean(empty_band), "the panel should be visible above the mascot")

    def test_render_all_writes_the_whole_family(self):
        from naveed.render.preview import render_all

        outputs = render_all(f"{OUT}-family.png", size=90)
        self.assertEqual(set(outputs), {"states", "mascot", "panel", "desktop"})
        for path in outputs.values():
            self.assertTrue(os.path.exists(path), path)


class CanvasTests(unittest.TestCase):
    def test_gradient_radius_preserves_alpha(self):
        canvas = PillowCanvas(120, 60)
        canvas.gradient(0, 0, 120, 60, [(0.0, "#FFFFFF14"), (1.0, "#FFFFFF00")], radius=12)
        self.assertLess(canvas.image.getpixel((60, 30))[3], 40, "semi-transparent gradients must stay translucent")
        self.assertEqual(canvas.image.getpixel((0, 0))[3], 0, "the corners must be clipped by the radius")

    def test_colour_parsing_accepts_every_documented_form(self):
        from naveed.render.canvas import parse_color

        self.assertEqual(parse_color("#fff"), (255, 255, 255, 255))
        self.assertEqual(parse_color("#FF8A2B"), (255, 138, 43, 255))
        self.assertEqual(parse_color("#FF8A2B80"), (255, 138, 43, 128))
        self.assertEqual(parse_color("255,138,43"), (255, 138, 43, 255))
        self.assertIsNone(parse_color(None))

    def test_radial_gradient_fades_to_zero(self):
        canvas = PillowCanvas(100, 100)
        canvas.radial(50, 50, 40, [(0.0, "#FF8A2BFF"), (1.0, "#FF8A2B00")])
        self.assertEqual(canvas.image.getpixel((95, 95))[3], 0, "the radial gradient must fade out")


if __name__ == "__main__":
    unittest.main(verbosity=2)
