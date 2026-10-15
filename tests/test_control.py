import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'control'))
import Data_parsing_student as control


class ControlScenarios(unittest.TestCase):
    def test_lane_only_keeps_cruise(self):
        result = control.decide_control_from_json({'lane': {'steer': 0.15}, 'objects': []})
        self.assertEqual(result.speed_kmh, 35)
        self.assertAlmostEqual(result.steer, 0.15)
        self.assertFalse(result.brake_light)

    def test_close_center_obstacle_stops(self):
        result = control.decide_control_from_json({'objects': [{'x': 500, 'y': 200, 'w': 300, 'h': 200}]})
        self.assertEqual(result.zone, control.DetectedZone.CENTER)
        self.assertEqual(result.speed_kmh, 0)
        self.assertTrue(result.brake_light)
        self.assertTrue(result.emergency_light)

    def test_smaller_center_obstacle_slows(self):
        result = control.decide_control_from_json({'objects': [{'bbox': [600, 200, 80, 100]}]})
        self.assertEqual(result.speed_kmh, 20)
        self.assertTrue(result.brake_light)
        self.assertFalse(result.emergency_light)

    def test_lower_side_obstacle_slows(self):
        result = control.decide_control_from_json({'objects': [{'x': 50, 'y': 500, 'w': 100, 'h': 100}]})
        self.assertEqual(result.zone, control.DetectedZone.LEFT_LOWER)
        self.assertEqual(result.speed_kmh, 20)

    def test_degree_input_clamps_and_reduces_speed(self):
        result = control.decide_control_from_json({'lane': {'steer': -60, 'unit': 'deg'}})
        self.assertEqual(result.steer, -1)
        self.assertEqual(result.speed_kmh, 20)
        self.assertTrue(result.left_blinker)

    def test_yolo_empty_result_clears_previous_objects(self):
        current = {'lane': {'steer': 0.2}, 'objects': [{'x': 500, 'y': 200, 'w': 300, 'h': 200}]}
        result = control.merge_ai_result_json(current, {'objects': []}, source='yolo')
        self.assertEqual(result['objects'], [])
        self.assertEqual(result['lane']['steer'], 0.2)

    def test_fragmented_and_concatenated_json(self):
        decoder = control.ResultStreamDecoder()
        chunks = [b'{"lane":{"ste', b'er":0.1}}{"objects":', b'[]}\n']
        messages = []
        for chunk in chunks:
            messages.extend(decoder.feed(chunk))
        self.assertEqual([json.loads(m) for m in messages], [{'lane': {'steer': 0.1}}, {'objects': []}])

    def test_braces_and_escapes_in_string_do_not_split_json(self):
        decoder = control.ResultStreamDecoder()
        payload = {'label': 'object } { with "quote"', 'objects': []}
        messages = list(decoder.feed(json.dumps(payload) + '{}'))
        self.assertEqual(len(messages), 2)
        self.assertEqual(json.loads(messages[0]), payload)

    def test_repeated_can_values_are_throttled_and_retried(self):
        class FakeIPC:
            def __init__(self):
                self.calls = []
            def send_command(self, command, value, subtype=None):
                self.calls.append((command, value, subtype))
                return True
        ipc = FakeIPC()
        now = [0.0]
        handler = control.VehicleCommandHandler(ipc, resend_interval_s=0.5, time_fn=lambda: now[0])
        handler.set_speed(20)
        now[0] = 0.1
        handler.set_speed(20)
        self.assertEqual(len(ipc.calls), 1)
        now[0] = 0.6
        handler.set_speed(20)
        self.assertEqual(len(ipc.calls), 2)


if __name__ == '__main__':
    unittest.main()
