import json
import os
import tempfile
import time
import unittest

import tlm_viewer as view
from tools.mavlink_sim import Simulator


def reset_viewer():
    with view.LOCK:
        view.reset_crsf_state()
        view.reset_mav_state()
        view.reset_stats()
        view.SESSION.update({
            "protocol": None, "id": None, "started_at": None,
            "source": None, "last_valid": 0.0,
        })
        view.ROUTER.update({"candidate": None, "count": 0, "since": 0.0})
        view.RECORD.update({
            "active": False, "id": None, "start_mono": 0.0,
            "started_at": None, "protocol": None, "points": [],
        })
        view.SETTINGS.update({"auto_record_3d": False, "auto_stop_sec": 10})


def feed_sim(sim):
    for _, data in sim.datagrams():
        view.ingest_datagram(data, "test")


class TestMavlinkSession(unittest.TestCase):
    def setUp(self):
        self.old_tracks = view.TRACKS_DIR
        self.tmp = tempfile.TemporaryDirectory()
        view.TRACKS_DIR = self.tmp.name
        reset_viewer()

    def tearDown(self):
        reset_viewer()
        view.TRACKS_DIR = self.old_tracks
        self.tmp.cleanup()

    def test_mavlink_stream_maps_to_viewer_state(self):
        feed_sim(Simulator(duration=1.0, pos_rate=10.0))
        snap = view.snapshot()
        self.assertEqual(snap["protocol"], "mavlink")
        self.assertTrue(snap["stats"]["link_up"])
        self.assertGreater(snap["stats"]["messages"], 0)
        self.assertEqual(snap["gps"]["fix_type"], 3)
        self.assertEqual(snap["flight_mode"], "Angle")
        self.assertTrue(snap["armed"])
        self.assertIsNotNone(snap["battery"])
        self.assertIsNotNone(snap["attitude"])

    def test_crsf_capture_still_works(self):
        with open("testdata/tlm_20261106_full_60s.jsonl", encoding="utf-8") as f:
            for line in f:
                obj = json.loads(line)
                if "data" not in obj:
                    continue
                view.ingest_datagram(bytes.fromhex(obj["data"]), "test")
                if view.snapshot()["link"] is not None:
                    break
        snap = view.snapshot()
        self.assertEqual(snap["protocol"], "crsf")
        self.assertEqual(snap["link"]["lq"], 100)

    def test_protocol_switch_stops_recording(self):
        view.SETTINGS["auto_record_3d"] = True
        feed_sim(Simulator(duration=1.0, pos_rate=10.0, fix=False))
        feed_sim(Simulator(duration=1.0, pos_rate=10.0))
        self.assertTrue(view.RECORD["active"])
        self.assertEqual(view.RECORD["protocol"], "mavlink")
        with open("testdata/tlm_20261106_full_60s.jsonl", encoding="utf-8") as f:
            line = next(line for line in f if '"data"' in line)
            data = bytes.fromhex(json.loads(line)["data"])
        # Simulate the 500 ms silence before the first CRSF datagram.
        view.SESSION["last_valid"] -= 3.0
        for _ in range(3):
            view.ingest_datagram(data, "test")
        self.assertEqual(view.SESSION["protocol"], "crsf")
        self.assertFalse(view.RECORD["active"])
        files = [n for n in os.listdir(view.TRACKS_DIR) if n.endswith(".json")]
        self.assertEqual(len(files), 1)
        with open(os.path.join(view.TRACKS_DIR, files[0]), encoding="utf-8") as f:
            track = json.load(f)
        self.assertEqual(track["version"], 2)
        self.assertIn("mavlink", track["protocols"])
        self.assertGreater(track["point_count"], 0)

    def test_crsf_auto_record_still_works(self):
        view.SETTINGS["auto_record_3d"] = True
        with open("testdata/tlm_20261106_full_60s.jsonl", encoding="utf-8") as f:
            for line in f:
                obj = json.loads(line)
                if "data" not in obj:
                    continue
                view.ingest_datagram(bytes.fromhex(obj["data"]), "test")
                if view.RECORD["active"]:
                    break
        self.assertTrue(view.RECORD["active"])
        self.assertEqual(view.RECORD["protocol"], "crsf")
        self.assertGreater(len(view.RECORD["points"]), 0)
        meta, error = view.stop_recording()
        self.assertEqual(error, "")
        self.assertIsNotNone(meta)
        files = [n for n in os.listdir(view.TRACKS_DIR) if n.endswith(".json")]
        with open(os.path.join(view.TRACKS_DIR, files[0]), encoding="utf-8") as f:
            track = json.load(f)
        self.assertEqual(track["protocols"], ["crsf"])

    def test_mavlink_auto_record_track_schema(self):
        view.SETTINGS["auto_record_3d"] = True
        feed_sim(Simulator(duration=1.0, pos_rate=10.0, fix=False))
        feed_sim(Simulator(duration=1.0, pos_rate=10.0))
        self.assertTrue(view.RECORD["active"])
        meta, error = view.stop_recording()
        self.assertEqual(error, "")
        self.assertIsNotNone(meta)
        files = [n for n in os.listdir(view.TRACKS_DIR) if n.endswith(".json")]
        self.assertEqual(len(files), 1)
        with open(os.path.join(view.TRACKS_DIR, files[0]), encoding="utf-8") as f:
            track = json.load(f)
        self.assertEqual(track["version"], 2)
        self.assertEqual(track["protocols"], ["mavlink"])
        point = track["points"][0]
        self.assertEqual(point["protocol"], "mavlink")
        self.assertIn("session_id", point)
        self.assertIn("mavlink", point["data"])


if __name__ == "__main__":
    unittest.main()
