import struct
import unittest

from tools import mavlink_protocol as mav
from tools import mavlink_sim as sim


class TestMavlinkFraming(unittest.TestCase):
    def test_v2_frames_are_valid(self):
        seq = 7
        frame = sim.heartbeat(seq, custom_mode=1, armed=True)
        frames = list(mav.iter_frames(frame))
        self.assertEqual(len(frames), 1)
        self.assertTrue(frames[0].crc_ok)
        self.assertEqual(frames[0].version, 2)
        self.assertEqual(frames[0].msgid, 0)
        decoded = mav.decode_message(frames[0])
        self.assertEqual(decoded["custom_mode"], 1)
        self.assertTrue(decoded["armed"])

    def test_v1_frame(self):
        payload = struct.pack("<IBBBBB", 2, 2, 0, 0, 3, 3)
        crc = mav.crc16_mcrf4xx(
            bytes((len(payload), 0, 1, 1, 0)) + payload + bytes((mav.CRC_EXTRA[0],))
        )
        frame = bytes((0xFE, len(payload), 0, 1, 1, 0)) + payload + struct.pack("<H", crc)
        frames = list(mav.iter_frames(frame))
        self.assertEqual(len(frames), 1)
        self.assertTrue(frames[0].crc_ok)
        self.assertEqual(frames[0].version, 1)

    def test_multiple_frames_in_one_datagram(self):
        data = sim.heartbeat(0) + sim.sys_status(1, 25200, 120, 72)
        frames = list(mav.iter_frames(data))
        self.assertEqual([f.msgid for f in frames], [0, 1])
        self.assertTrue(all(f.crc_ok for f in frames))

    def test_bad_crc_is_not_valid(self):
        frame = bytearray(sim.heartbeat(0))
        frame[-1] ^= 0xFF
        frames = list(mav.iter_frames(bytes(frame)))
        self.assertTrue(frames)
        self.assertFalse(frames[0].crc_ok)

    def test_gps_decode(self):
        frame = sim.gps_raw_int(
            0, 612539300, 731887950, 120.0, 3, 10, 1200, 9000
        )
        decoded = mav.decode_message(next(iter(mav.iter_frames(frame))))
        self.assertEqual(decoded["fix_type"], 3)
        self.assertEqual(decoded["satellites_visible"], 10)
        self.assertEqual(decoded["lat"], 612539300)
        self.assertEqual(decoded["lon"], 731887950)
        self.assertEqual(decoded["alt"], 120000)
        self.assertEqual(decoded["vel"], 1200)
        self.assertEqual(decoded["cog"], 9000)

    def test_battery_decode(self):
        frame = sim.battery_status(0, 25200, 120, 345, 72)
        decoded = mav.decode_message(next(iter(mav.iter_frames(frame))))
        self.assertEqual(decoded["current_consumed"], 345)
        self.assertEqual(decoded["current_battery"], 120)
        self.assertEqual(decoded["battery_remaining"], 72)
        self.assertEqual(decoded["voltages"][0], 25200)

    def test_simulator_stream_is_valid(self):
        simu = sim.Simulator(duration=2.0, pos_rate=10.0)
        counts = {}
        for _, data in simu.datagrams():
            for frame in mav.iter_frames(data):
                self.assertTrue(frame.crc_ok)
                counts[frame.name] = counts.get(frame.name, 0) + 1
        for name in ("HEARTBEAT", "SYS_STATUS", "GPS_RAW_INT", "ATTITUDE",
                     "BATTERY_STATUS", "RC_CHANNELS_RAW", "VFR_HUD"):
            self.assertIn(name, counts)


if __name__ == "__main__":
    unittest.main()
