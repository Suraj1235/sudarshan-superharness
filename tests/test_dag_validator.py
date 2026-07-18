#!/usr/bin/env python3
"""Unit tests for dag_validator.py"""
import json, os, sys, unittest, tempfile

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dag_validator import validate_dag


class TestDAGValidator(unittest.TestCase):

    def test_valid_list_dag(self):
        """Valid DAG with list format should pass."""
        dag = {"nodes": [
            {"id": "A", "dependencies": []},
            {"id": "B", "dependencies": ["A"]},
            {"id": "C", "dependencies": ["A", "B"]}
        ]}
        self.assertTrue(validate_dag(dag))

    def test_valid_dict_dag(self):
        """Valid DAG with dict format should pass."""
        dag = {"nodes": {
            "A": {"dependencies": []},
            "B": {"dependencies": ["A"]},
            "C": {"dependencies": ["B"]}
        }}
        self.assertTrue(validate_dag(dag))

    def test_cycle_detection(self):
        """DAG with a cycle should exit with code 1."""
        dag = {"nodes": [
            {"id": "A", "dependencies": ["C"]},
            {"id": "B", "dependencies": ["A"]},
            {"id": "C", "dependencies": ["B"]}
        ]}
        with self.assertRaises(SystemExit) as ctx:
            validate_dag(dag)
        self.assertEqual(ctx.exception.code, 1)

    def test_dangling_dependency(self):
        """DAG with a dependency on a non-existent node should exit."""
        dag = {"nodes": [
            {"id": "A", "dependencies": []},
            {"id": "B", "dependencies": ["GHOST_NODE"]}
        ]}
        with self.assertRaises(SystemExit) as ctx:
            validate_dag(dag)
        self.assertEqual(ctx.exception.code, 1)

    def test_single_node(self):
        """Single node with no dependencies should pass."""
        dag = {"nodes": [{"id": "SOLO", "dependencies": []}]}
        self.assertTrue(validate_dag(dag))

    def test_self_cycle(self):
        """Node depending on itself should be detected as a cycle."""
        dag = {"nodes": [{"id": "A", "dependencies": ["A"]}]}
        with self.assertRaises(SystemExit) as ctx:
            validate_dag(dag)
        self.assertEqual(ctx.exception.code, 1)

    def test_alternate_key_names(self):
        """DAG using 'tasks' and 'depends_on' keys should also work."""
        dag = {"tasks": [
            {"task_id": "X", "depends_on": []},
            {"task_id": "Y", "depends_on": ["X"]}
        ]}
        self.assertTrue(validate_dag(dag))

    def test_empty_dag(self):
        """Empty DAG should pass (no nodes = no cycles)."""
        dag = {"nodes": []}
        self.assertTrue(validate_dag(dag))


if __name__ == "__main__":
    unittest.main()
