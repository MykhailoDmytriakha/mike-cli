"""S1–S4: stamp line at the end of a file."""
import unittest

from mike import stamp


class StampTests(unittest.TestCase):
    def test_apply_then_verify_ok(self):
        text = stamp.apply("# T\n\nbody line\n")
        self.assertTrue(text.endswith("\n"))
        self.assertRegex(text.splitlines()[-1], r"^stamp: [0-9a-f]{12}$")
        self.assertEqual(text.splitlines()[-2], "", "one blank line before the stamp")
        self.assertEqual(stamp.verify(text), (True, "ok"))

    def test_old_stamp_without_blank_line_still_verifies(self):
        text = stamp.apply("# T\nx\n").replace("\n\nstamp:", "\nstamp:")
        self.assertEqual(stamp.verify(text), (True, "ok"))

    def test_apply_replaces_old_stamp(self):
        text = stamp.apply(stamp.apply("# T\nx\n"))
        self.assertEqual(text.count("stamp:"), 1)
        self.assertEqual(stamp.verify(text), (True, "ok"))

    def test_missing(self):
        self.assertEqual(stamp.verify("# T\nx\n"), (False, "missing"))

    def test_mismatch_after_hand_edit(self):
        text = stamp.apply("# T\nx\n").replace("x\n", "x edited\n")
        self.assertEqual(stamp.verify(text), (False, "mismatch"))

    def test_not_last_when_something_appended_after(self):
        text = stamp.apply("# T\nx\n") + "appended by hand\n"
        self.assertEqual(stamp.verify(text), (False, "not-last"))

    def test_split_returns_body_without_stamp(self):
        text = stamp.apply("# T\nx\n")
        body, found = stamp.split(text)
        self.assertEqual(body, "# T\nx\n")
        self.assertEqual(found, stamp.compute(body))

    def test_compute_is_stable_across_trailing_newlines(self):
        self.assertEqual(stamp.compute("a\n"), stamp.compute("a"))
        self.assertEqual(stamp.compute("a\n"), stamp.compute("a\n\n"))


if __name__ == "__main__":
    unittest.main()
