#!/usr/bin/env python3
"""Unit tests for dag_subgraph.py"""
import json, os, sys, unittest

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dag_subgraph import extract_subgraph


class TestDAGSubgraph(unittest.TestCase):

    def setUp(self):
        """Create a standard test DAG."""
        self.dag = {"nodes": [
            {"id": "SETUP", "dependencies": []},
            {"id": "BACKEND", "dependencies": ["SETUP"]},
            {"id": "FRONTEND", "dependencies": ["SETUP"]},
            {"id": "DB", "dependencies": ["BACKEND"]},
            {"id": "INTEGRATION", "dependencies": ["BACKEND", "FRONTEND", "DB"]}
        ]}

    def test_target_with_parents_and_children(self):
        """BACKEND has parent SETUP and children DB, INTEGRATION."""
        # extract_subgraph calls sys.exit(0) on success, so capture that
        with self.assertRaises(SystemExit) as ctx:
            extract_subgraph(self.dag, "BACKEND")
        self.assertEqual(ctx.exception.code, 0)

    def test_root_node(self):
        """SETUP has no parents but has children BACKEND, FRONTEND."""
        with self.assertRaises(SystemExit) as ctx:
            extract_subgraph(self.dag, "SETUP")
        self.assertEqual(ctx.exception.code, 0)

    def test_leaf_node(self):
        """INTEGRATION has parents but no children."""
        with self.assertRaises(SystemExit) as ctx:
            extract_subgraph(self.dag, "INTEGRATION")
        self.assertEqual(ctx.exception.code, 0)

    def test_nonexistent_node(self):
        """Requesting a node that doesn't exist should exit with code 1."""
        with self.assertRaises(SystemExit) as ctx:
            extract_subgraph(self.dag, "GHOST")
        self.assertEqual(ctx.exception.code, 1)

    def test_dict_format_dag(self):
        """DAG in dict format should also work."""
        dag = {"nodes": {
            "A": {"dependencies": []},
            "B": {"dependencies": ["A"]},
            "C": {"dependencies": ["B"]}
        }}
        with self.assertRaises(SystemExit) as ctx:
            extract_subgraph(dag, "B")
        self.assertEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
