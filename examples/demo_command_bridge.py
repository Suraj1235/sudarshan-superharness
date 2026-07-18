#!/usr/bin/env python3
"""Deterministic command-provider demo used to exercise the bridge without an API key."""

import json
import sys


PLAN_STARTED = [
    {
        "id": "T1",
        "description": "Implement calculator",
        "status": "in_progress",
        "depends_on": [],
    },
    {
        "id": "T2",
        "description": "Test calculator",
        "status": "pending",
        "depends_on": ["T1"],
    },
]
PLAN_TESTING = [
    {**PLAN_STARTED[0], "status": "done"},
    {**PLAN_STARTED[1], "status": "in_progress"},
]
PLAN_DONE = [
    {**PLAN_STARTED[0], "status": "done"},
    {**PLAN_STARTED[1], "status": "done"},
]
ACTIONS = [
    {"action": "set_plan", "tasks": PLAN_STARTED},
    {
        "action": "write_file",
        "path": "calc.py",
        "content": "def add(a, b):\n    return a + b\n",
    },
    {"action": "set_plan", "tasks": PLAN_TESTING},
    {
        "action": "write_file",
        "path": "test_calc.py",
        "content": (
            "import unittest\n\n"
            "from calc import add\n\n\n"
            "class TestAdd(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(add(2, 3), 5)\n\n\n"
            "if __name__ == '__main__':\n"
            "    unittest.main()\n"
        ),
    },
    {"action": "set_plan", "tasks": PLAN_DONE},
    {"action": "finish", "summary": "Calculator library implemented and verified."},
]


def main() -> int:
    request = json.load(sys.stdin)
    state_text = request["messages"][1]["content"].split("\n", 1)[1]
    step = int(json.loads(state_text)["step"])
    if step >= len(ACTIONS):
        print(json.dumps({"error": f"demo has no action for step {step}"}), file=sys.stderr)
        return 2
    response = {
        "text": json.dumps(ACTIONS[step]),
        "input_tokens": 10,
        "output_tokens": 5,
    }
    print(json.dumps(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
