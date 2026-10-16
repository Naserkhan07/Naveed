"""Screen awareness: capture recovery, diffing, geometry, retention.

These are the ports from the three reference repositories, so they are tested
against the *original behaviours*: the empty-frame recovery chain (brah), the
display-size mismatch guard (brah), the change threshold (OpenDesktop), monitor
selection by largest overlap and HiDPI coordinate scaling (voiceuse).
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from naveed.screen import capture_fallback as cf
from naveed.screen.diff import ChangeDetector, NOISE_FLOOR, diff_ratio, signature_from_pixels
from naveed.screen.displays import Monitor, monitor_at_point, monitor_for_rect, virtual_desktop
from naveed.screen.retention import CAPTURE_NAME_RE, ScreenshotStore, capture_filename, prune_saved_screenshots


class FakeImage:
    """Duck-typed PIL image: size, mode, getextrema, getchannel."""

    def __init__(self, width, height, mode="RGB", extrema=None):
        self.size = (width, height)
        self.mode = mode
        self._extrema = extrema or [(0, 255)] * (4 if mode == "RGBA" else 3)

    def getextrema(self):
        return self._extrema

    def getchannel(self, name):
        return FakeChannel(self._extrema[3] if len(self._extrema) > 3 else (0, 0))


class FakeChannel:
    def __init__(self, extrema):
        self._extrema = extrema

    def getextrema(self):
        return self._extrema


class CaptureFallbackTests(unittest.TestCase):
    def test_empty_frame_detection_cases(self):
        self.assertEqual(cf.is_empty_frame(None), (True, "no_frame"))
        self.assertEqual(cf.is_empty_frame(FakeImage(0, 0)), (True, "zero_size"))
        self.assertEqual(cf.is_empty_frame(FakeImage(10, 10, "RGBA", [(0, 0)] * 4)), (True, "fully_transparent"))
        self.assertEqual(cf.is_empty_frame(FakeImage(10, 10, "RGB", [(7, 7)] * 3)), (True, "uniform_frame"))
        self.assertEqual(cf.is_empty_frame(FakeImage(10, 10, "RGB", [(0, 255)] * 3)), (False, ""))

    def test_resolve_frame_prefers_first_working_backend(self):
        good = FakeImage(1920, 1080, "RGB", [(0, 255)] * 3)
        calls = []

        def broken():
            calls.append("broken")
            return FakeImage(0, 0)

        def working():
            calls.append("working")
            return good

        image, via = cf.resolve_frame([broken, working], monitor_size=(1920, 1080))
        self.assertIs(image, good)
        self.assertEqual(via, "working")
        self.assertEqual(calls, ["broken", "working"])

    def test_resolve_frame_keeps_wrong_size_frame_as_last_resort(self):
        # Port of brah's display-mismatch guard: a wrong-size capture is flagged
        # but still returned rather than failing the whole request.
        small = FakeImage(1280, 720, "RGB", [(0, 255)] * 3)
        image, via = cf.resolve_frame([lambda: small], monitor_size=(3840, 2160), scale=1.0)
        self.assertIs(image, small)

    def test_resolve_frame_reports_every_attempt_when_all_fail(self):
        with self.assertRaises(cf.CaptureError) as context:
            cf.resolve_frame([lambda: FakeImage(0, 0), lambda: FakeImage(0, 0)], monitor_size=(800, 600))
        message = str(context.exception)
        self.assertIn("empty image", message)
        self.assertIn("capture", message.lower())

    def test_backend_exception_does_not_stop_the_chain(self):
        def exploding():
            raise RuntimeError("no display")

        def working():
            return FakeImage(800, 600, "RGB", [(0, 255)] * 3)

        image, via = cf.resolve_frame([exploding, working], monitor_size=(800, 600))
        self.assertEqual(via, "working")

    def test_permission_text_only_blames_permissions_when_missing(self):
        granted = cf.describe_capture_failure("Empty image.", cf.SCREEN_ACCESS_GRANTED)
        denied = cf.describe_capture_failure("Empty image.", cf.SCREEN_ACCESS_DENIED)
        self.assertIn("already granted", granted)
        self.assertIn("permission", granted.lower())
        self.assertNotIn("already granted", denied)

    def test_size_matching_tolerance(self):
        self.assertTrue(cf.sizes_match((1920, 1080), (1920, 1080)))
        self.assertTrue(cf.sizes_match((1922, 1081), (1920, 1080)))
        self.assertFalse(cf.sizes_match((1280, 720), (1920, 1080)))

    def test_expected_pixel_size_uses_scale(self):
        self.assertEqual(cf.expected_pixel_size(1512, 982, 2.0), (3024, 1964))


class DiffTests(unittest.TestCase):
    def test_signature_shape_and_stability(self):
        pixels = bytes(range(256)) * 12
        first = signature_from_pixels(pixels, 32, 32)
        second = signature_from_pixels(pixels, 32, 32)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64 * 36)

    def test_noise_below_threshold_is_not_a_change(self):
        detector = ChangeDetector()
        base = bytes([100]) * (64 * 36)
        detector.observe(base)
        noisy = bytearray(base)
        for index in range(0, len(noisy), 5):
            noisy[index] = 103
        report = detector.observe(bytes(noisy))
        self.assertFalse(report.changed)
        self.assertLess(report.ratio, NOISE_FLOOR)

    def test_large_change_is_a_scene(self):
        detector = ChangeDetector()
        detector.observe(bytes([0]) * (64 * 36))
        report = detector.observe(bytes([255]) * (64 * 36))
        self.assertTrue(report.changed)
        self.assertTrue(report.scene)

    def test_settle_after_repeated_identical_frames(self):
        detector = ChangeDetector(settle_frames=2)
        detector.observe(b"a" * 100)
        self.assertFalse(detector.observe(b"a" * 100).settled)
        self.assertTrue(detector.observe(b"a" * 100).settled)

    def test_diff_ratio_handles_mismatched_lengths(self):
        self.assertEqual(diff_ratio(b"abc", b"abcd"), 1.0)


class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.monitors = [
            Monitor(0, 0, 0, 1920, 1080, 1.0, "built-in", True),
            Monitor(1, 1920, 0, 2560, 1440, 1.25, "side", False),
        ]

    def test_monitor_for_rect_picks_largest_overlap(self):
        straddling = (1700, 200, 600, 500)   # 300px on the first, 300px... 220 on the second
        self.assertEqual(monitor_for_rect(straddling, self.monitors).name, "side")
        mostly_first = (1500, 200, 800, 500)
        self.assertEqual(monitor_for_rect(mostly_first, self.monitors).name, "built-in")

    def test_monitor_at_point_and_virtual_desktop(self):
        self.assertEqual(monitor_at_point(2500, 300, self.monitors).name, "side")
        self.assertEqual(monitor_at_point(-50, -50, self.monitors).name, "built-in")
        self.assertEqual(virtual_desktop(self.monitors), (0, 0, 4480, 1440))

    def test_hidpi_frame_coordinates_scale_to_logical_pixels(self):
        side = self.monitors[1]
        # A 3200x1800 capture of a 2560x1440 logical display: the model's pixel
        # must land at the same visual place the user meant.
        self.assertEqual(side.to_global(1600, 900, frame_size=(3200, 1800)), (1920 + 1280, 720))
        self.assertEqual(side.to_local(3200, 720, frame_size=(3200, 1800)), (1600, 900))

    def test_clamp_keeps_points_inside_the_monitor(self):
        built_in = self.monitors[0]
        self.assertEqual(built_in.clamp_global(9999, 9999), (1918, 1078))
        self.assertEqual(built_in.clamp_global(-400, -400), (1, 1))


class RetentionTests(unittest.TestCase):
    def test_capture_names_match_the_original_regex(self):
        self.assertTrue(CAPTURE_NAME_RE.match(capture_filename()))
        self.assertTrue(CAPTURE_NAME_RE.match("screenshot-2026-01-02T03-04-05-006Z.png"))

    def test_prune_keeps_newest_and_protects_the_active_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            # Explicit names: the real generator includes a uuid, so two captures
            # can never collide, and the ordering under test needs distinct names.
            names = [
                "screenshot-2026-01-02T03-04-0%d-00%dZ.png" % (index, index) for index in range(4)
            ]
            for index, name in enumerate(names):
                path = os.path.join(directory, name)
                with open(path, "wb") as handle:
                    handle.write(b"png")
                os.utime(path, (1000 + index, 1000 + index))
            result = prune_saved_screenshots(directory, max_captures=2, protected_name=names[0])
            remaining = sorted(name for name in os.listdir(directory))
            self.assertIn(names[0], remaining)          # protected survives
            self.assertIn(names[3], remaining)          # newest survives
            self.assertEqual(result["deleted"], 2)

    def test_store_saves_prunes_and_lists(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ScreenshotStore(directory, max_captures=3)
            for index in range(5):
                store.save_bytes(f"capture-{index}".encode(), protect=(index == 4))
            listing = store.recent(with_data_url=False)
            # The store must never hold more than max_captures, and the protected
            # capture (the one the agent is using) must be among the survivors.
            self.assertEqual(len(listing), 3)
            # Ordering is by mtime and every write here lands in the same
            # millisecond, so assert survival rather than position.
            self.assertIn(store._protected, {entry["name"] for entry in listing})
            stats = store.stats()
            self.assertEqual(stats["count"], len(os.listdir(directory)))
            self.assertLessEqual(stats["count"], 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
