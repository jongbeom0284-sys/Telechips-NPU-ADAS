#!/usr/bin/env python3
"""Run synthetic perception results through the published control decision."""
import argparse
from dataclasses import asdict
import importlib.util
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('adas_control', root / 'control/Data_parsing_student.py')
control = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = control
spec.loader.exec_module(control)

SCENARIOS = {
    'lane-following': {'lane': {'steer': 0.15, 'unit': 'normalized'}, 'objects': []},
    'center-close': {'lane': {'steer': 0.1}, 'objects': [{'x': 500, 'y': 200, 'w': 300, 'h': 200, 'score': 0.9}]},
    'center-caution': {'lane': {'steer': 0.1}, 'objects': [{'x': 600, 'y': 200, 'w': 80, 'h': 100}]},
    'sharp-turn': {'lane': {'steer': -0.7}, 'objects': []},
}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', choices=SCENARIOS, default='lane-following')
    args = parser.parse_args()
    data = SCENARIOS[args.scenario]
    print(json.dumps({'synthetic_input': data, 'decision': asdict(control.decide_control_from_json(data))}, indent=2))

if __name__ == '__main__':
    main()
