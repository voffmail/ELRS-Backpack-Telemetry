import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "make_webflasher.py"


class TestMakeWebflasher(unittest.TestCase):
    def build_site(self, binaries):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            source = tmp / "source"
            source.mkdir()
            (source / "index.html").write_text("<!doctype html><html></html>")
            args = [sys.executable, str(SCRIPT), "--version", "test"]
            for target, data in binaries.items():
                image = tmp / f"{target}.bin"
                image.write_bytes(data)
                args += ["--binary", f"{target}={image}"]
            out = tmp / "out"
            args += ["--out", str(out), "--source", str(source)]
            subprocess.run(args, check=True, capture_output=True, text=True)
            return {
                path.relative_to(out).as_posix(): path.read_bytes()
                for path in out.rglob("*")
                if path.is_file()
            }

    def test_selects_two_targets(self):
        files = self.build_site({"c3": b"c3-image", "s3": b"s3-image"})

        self.assertEqual(files["firmware-merged-c3.bin"], b"c3-image")
        self.assertEqual(files["firmware-merged-s3.bin"], b"s3-image")
        self.assertNotIn("targets.json", files)
        self.assertNotIn("manifest-c3.json", files)
        self.assertNotIn("manifest-s3.json", files)

        manifest = json.loads(files["manifest.json"])
        self.assertEqual(
            [build["chipFamily"] for build in manifest["builds"]],
            ["ESP32-C3", "ESP32-S3"],
        )
        self.assertEqual(
            [build["parts"][0]["path"] for build in manifest["builds"]],
            ["firmware-merged-c3.bin", "firmware-merged-s3.bin"],
        )

    def test_bare_binary_defaults_to_c3(self):
        files = self.build_site({"c3": b"c3-image"})
        manifest = json.loads(files["manifest.json"])
        self.assertEqual(
            [build["chipFamily"] for build in manifest["builds"]],
            ["ESP32-C3"],
        )

    def test_rejects_unknown_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            source = tmp / "source"
            source.mkdir()
            (source / "index.html").write_text("<!doctype html>")
            image = tmp / "image.bin"
            image.write_bytes(b"x")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--version",
                    "test",
                    "--binary",
                    f"esp32={image}",
                    "--out",
                    str(tmp / "out"),
                    "--source",
                    str(source),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unknown target", result.stderr)


if __name__ == "__main__":
    unittest.main()
