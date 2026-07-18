import json
import sys
import os

KNOWN_DEP_KEYS = {"dependencies", "depends_on"}
SUSPECT_DEP_KEYS = {"requires", "blocked_by", "after", "needs", "prereqs", "blockers"}

def validate_dag(dag):
    graph = {}
    nodes = dag.get("nodes", dag.get("tasks", dag)) if isinstance(dag, dict) else dag

    if not isinstance(nodes, (list, dict)):
        print("ERROR: Invalid DAG format. Must be a list or dict of nodes.")
        sys.exit(1)

    # Build graph and collect all defined node IDs
    all_defined_nodes = set()
    if isinstance(nodes, list):
        for node in nodes:
            node_id = node.get("id", node.get("task_id", node.get("name")))
            if not node_id:
                continue
            all_defined_nodes.add(node_id)
            deps = node.get("dependencies", node.get("depends_on", []))
            graph[node_id] = deps
            # Suspect-key drift detection
            if not deps and isinstance(node, dict):
                suspect_found = SUSPECT_DEP_KEYS.intersection(node.keys())
                if suspect_found:
                    print(f"ERROR: Node '{node_id}' has unrecognized dependency key(s) {suspect_found}. "
                          f"Must use 'dependencies' or 'depends_on'. Fix the DAG.", file=sys.stderr)
                    sys.exit(1)
    elif isinstance(nodes, dict):
        for node_id, node_data in nodes.items():
            all_defined_nodes.add(node_id)
            if isinstance(node_data, dict):
                deps = node_data.get("dependencies", node_data.get("depends_on", []))
                graph[node_id] = deps
                # Suspect-key drift detection
                if not deps:
                    suspect_found = SUSPECT_DEP_KEYS.intersection(node_data.keys())
                    if suspect_found:
                        print(f"ERROR: Node '{node_id}' has unrecognized dependency key(s) {suspect_found}. "
                              f"Must use 'dependencies' or 'depends_on'. Fix the DAG.", file=sys.stderr)
                        sys.exit(1)
            elif isinstance(node_data, list):
                graph[node_id] = node_data
            else:
                graph[node_id] = []

    # Check for missing/dangling dependencies
    for node_id, deps in graph.items():
        for dep in deps:
            if dep not in all_defined_nodes:
                print(f"ERROR: Dangling dependency detected. '{node_id}' depends on '{dep}', which does not exist.")
                sys.exit(1)

    visited = set()
    rec_stack = set()

    def is_cyclic(node):
        visited.add(node)
        rec_stack.add(node)
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                if is_cyclic(neighbor):
                    return True
            elif neighbor in rec_stack:
                return True
        rec_stack.remove(node)
        return False

    for node in graph.keys():
        if node not in visited:
            if is_cyclic(node):
                print(f"ERROR: Cycle Detected involving node '{node}'. Mathematical validation failed.")
                sys.exit(1)

    return True

if __name__ == "__main__":
    dag_path = sys.argv[1] if len(sys.argv) > 1 else "enterprise_state/JIRA_DAG.json"
    if not os.path.exists(dag_path):
        print(f"ERROR: DAG file {dag_path} not found.")
        sys.exit(1)
    try:
        with open(dag_path, 'r') as f:
            dag = json.load(f)
        validate_dag(dag)
        print("SUCCESS: DAG validated mathematically. No circular or dangling dependencies found.")
        sys.exit(0)
    except json.JSONDecodeError:
        print("ERROR: Invalid JSON format in DAG.")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Unhandled exception during validation: {e}")
        sys.exit(1)
