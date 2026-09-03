"""Evidence contract for the repeatable borderless-layout browser acceptance.

Validates that scripts/verify_ontology_layout_borderless_ui.mjs exists in the
repo, that the recorded narrow-hover tooltip evidence is complete, truthful
and inside the 700x900 viewport, and that the g3/g4 screenshots are two
distinct real captures. Screenshot hashes are recomputed here from the actual
files instead of trusting the JSON values.
"""
import hashlib
import json
import struct
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "verify_ontology_layout_borderless_ui.mjs"
EVIDENCE_DIR = REPO / "docs" / "test-evidence"
JSON_FILE = EVIDENCE_DIR / "ontology-layout-borderless-browser-acceptance.json"
G3 = EVIDENCE_DIR / "g3-narrow-menu.png"
G4 = EVIDENCE_DIR / "g4-narrow-hover.png"
BORDERLESS_SPEC = REPO / "docs" / "specs" / "ontology-layout-borderless-options.md"
RADIAL_HINT = "以当前锚点为中心，按照最短关系距离由内向外分环排列。"
OLD_IDENTICAL_HASH = "6bf23ec951709b44b1e92a12a469497bdb557de04622c5e33a7b24f6eec570c5"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def png_size(path: Path):
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def load_json() -> dict:
    return json.loads(JSON_FILE.read_text(encoding="utf-8"))


class OntologyLayoutBrowserEvidenceTests(unittest.TestCase):
    def test_repeatable_script_exists_and_avoids_tmp(self) -> None:
        """1. In-repo script exists; 2. no /tmp/browser-borderless reference."""
        self.assertTrue(SCRIPT.is_file(), f"missing {SCRIPT.relative_to(REPO)}")
        src = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("/tmp/browser-borderless", src)

    def test_json_has_independent_narrow_hover_visible_check(self) -> None:
        """3. JSON contains the independent check 'narrow hover tooltip visible'."""
        data = load_json()
        checks = data.get("checks") or []
        names = [c.get("name") for c in checks]
        self.assertIn("narrow hover tooltip visible", names)
        check = next(c for c in checks if c.get("name") == "narrow hover tooltip visible")
        self.assertTrue(check.get("ok"), f"check not ok: {check.get('detail')}")

    def test_json_records_exact_radial_hint_text(self) -> None:
        """4. JSON records the precise radial tooltip sentence."""
        data = load_json()
        tip = data.get("narrowHoverTooltip") or {}
        self.assertEqual(tip.get("text"), RADIAL_HINT)

    def test_json_records_tooltip_visibility_and_geometry(self) -> None:
        """5. hidden/display/visibility/opacity/size/rect/viewport/option."""
        data = load_json()
        tip = data.get("narrowHoverTooltip") or {}
        self.assertFalse(tip.get("hidden"))
        self.assertNotEqual(tip.get("display"), "none")
        self.assertNotEqual(tip.get("visibility"), "hidden")
        self.assertNotEqual(str(tip.get("opacity")), "0")
        rect = tip.get("rect") or {}
        self.assertGreater(rect.get("width", 0), 0)
        self.assertGreater(rect.get("height", 0), 0)
        self.assertEqual(tip.get("optionValue"), "radial")
        self.assertTrue(tip.get("insideViewport"))
        viewport = tip.get("viewport") or {}
        self.assertEqual(viewport.get("width"), 700)
        self.assertEqual(viewport.get("height"), 900)
        self.assertGreaterEqual(rect.get("left", -1), 0)
        self.assertGreaterEqual(rect.get("top", -1), 0)
        self.assertLessEqual(rect.get("right", 10 ** 9), 700)
        self.assertLessEqual(rect.get("bottom", 10 ** 9), 900)

    def test_json_records_after_leave_hidden(self) -> None:
        """6. Leaving the listbox hides the tooltip again."""
        data = load_json()
        after = (data.get("narrowHoverTooltip") or {}).get("afterLeave") or {}
        self.assertTrue(after.get("hidden") is True or after.get("display") == "none")

    def test_json_records_g3_g4_hashes(self) -> None:
        """7. JSON contains screenshot SHA-256 for g3 and g4."""
        data = load_json()
        shots = data.get("screenshots") or {}
        self.assertIn("g3", shots)
        self.assertIn("g4", shots)
        self.assertRegex(shots["g3"].get("sha256", ""), r"^[0-9a-f]{64}$")
        self.assertRegex(shots["g4"].get("sha256", ""), r"^[0-9a-f]{64}$")
        self.assertNotEqual(shots["g3"]["sha256"], shots["g4"]["sha256"])

    def test_recomputed_hashes_match_json(self) -> None:
        """8. Recompute hashes from the actual files; do not trust JSON alone."""
        data = load_json()
        shots = data.get("screenshots") or {}
        for name, path in (("g3", G3), ("g4", G4)):
            self.assertEqual(sha256(path), shots[name]["sha256"], f"{name} hash mismatch")

    def test_g3_g4_are_distinct_real_files(self) -> None:
        """9. Both exist, non-empty, same dimensions and different hashes."""
        for path in (G3, G4):
            self.assertTrue(path.is_file(), f"missing {path.name}")
            self.assertGreater(path.stat().st_size, 0, f"{path.name} is empty")
        self.assertEqual(png_size(G3), png_size(G4), "screenshots must share size")
        self.assertNotEqual(sha256(G3), sha256(G4), "g3 and g4 must differ")
        self.assertNotEqual(sha256(G3), OLD_IDENTICAL_HASH)

    def test_json_failed_count_zero(self) -> None:
        """10. JSON failedCount === 0."""
        data = load_json()
        self.assertEqual(data.get("failedCount"), 0)

    def test_borderless_spec_reflects_final_evidence(self) -> None:
        """11. The earlier spec no longer treats identical images as evidence."""
        self.assertTrue(BORDERLESS_SPEC.is_file())
        spec = BORDERLESS_SPEC.read_text(encoding="utf-8")
        self.assertNotIn(OLD_IDENTICAL_HASH, spec)
        g3_hash = sha256(G3)
        g4_hash = sha256(G4)
        self.assertIn(g3_hash, spec, "borderless spec must record the new g3 hash")
        self.assertIn(g4_hash, spec, "borderless spec must record the new g4 hash")


if __name__ == "__main__":
    unittest.main()
