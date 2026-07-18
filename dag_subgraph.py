import json
import sys
import os
from collections import defaultdict

KNOWN_DEP_KEYS = {"dependencies", "depends_on"}
SUSPECT_DEP_KEYS = {"requires", "blocked_by", "after", "needs", "prereqs", "blockers"}

def find_parallelizable_nodes(dag):
    """Find nodes that can execute in parallel (no dependencies between them)."""
    nodes = dag.get("nodes", dag.get("tasks", dag)) if isinstance(dag, dict) else dag

    node_dict = {}
    if isinstance(nodes, list):
        for node in nodes:
            node_id = node.get("id", node.get("task_id", node.get("name")))
            if node_id:
                node_dict[node_id] = node
    elif isinstance(nodes, dict):
        for node_id, node_data in nodes.items():
            if isinstance(node_data, dict):
                node_dict[node_id] = node_data

    in_degree = defaultdict(int)
    deps = defaultdict(set)

    for node_id, node_data in node_dict.items():
        node_deps = node_data.get("dependencies", node_data.get("depends_on", []))
        if not node_deps:
            node_deps = []
        for d in node_deps:
            deps[d].add(node_id)
            in_degree[node_id] += 1

    ready = [n for n in node_dict if in_degree[n] == 0]
    parallel_batches = []

    while ready:
        parallel_batches.append(ready)
        next_ready = []
        for completed in ready:
            for dependent in deps[completed]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    next_ready.append(dependent)
        ready = next_ready

    return parallel_batches

def get_parallel_info(dag_path):
    """Get parallel execution information for the entire DAG."""
    if not os.path.exists(dag_path):
        print(f"ERROR: DAG file {dag_path} not found.")
        sys.exit(1)

    try:
        with open(dag_path, 'r', encoding='utf-8') as f:
            dag = json.load(f)
    except json.JSONDecodeError:
        print("ERROR: Invalid JSON format in DAG.")
        sys.exit(1)

    batches = find_parallelizable_nodes(dag)
    total_nodes = sum(len(b) for b in batches)

    result = {
        "total_nodes": total_nodes,
        "parallel_batches": batches,
        "max_parallelism": max(len(b) for b in batches) if batches else 0,
        "estimated_speedup": sum(len(b) for b in batches[1:]) / total_nodes if total_nodes > 0 else 0
    }

    print(json.dumps(result, indent=2))
    sys.exit(0)

def extract_subgraph(dag, target_node_id):
    nodes = dag.get("nodes", dag.get("tasks", dag)) if isinstance(dag, dict) else dag

    if not isinstance(nodes, (list, dict)):
        print("ERROR: Invalid DAG format.")
        sys.exit(1)

    # Convert to a standard dictionary format {node_id: node_data}
    node_dict = {}
    if isinstance(nodes, list):
        for node in nodes:
            node_id = node.get("id", node.get("task_id", node.get("name")))
            if node_id:
                node_dict[node_id] = node
    elif isinstance(nodes, dict):
        for node_id, node_data in nodes.items():
            if isinstance(node_data, dict):
                node_data["id"] = node_id
                node_dict[node_id] = node_data
            elif isinstance(node_data, list):
                node_dict[node_id] = {"id": node_id, "dependencies": node_data}

    if target_node_id not in node_dict:
        print(f"ERROR: Target node '{target_node_id}' not found in DAG.")
        sys.exit(1)

    # Find 1-degree dependencies (parents)
    target_node = node_dict[target_node_id]
    parents = target_node.get("dependencies", target_node.get("depends_on", []))
    if not parents:
        suspects = SUSPECT_DEP_KEYS.intersection(target_node.keys())
        if suspects:
            print(f"WARNING: Target node '{target_node_id}' uses unrecognized dependency key(s) {suspects}. "
                  f"Expected 'dependencies' or 'depends_on'. Missing context may result.", file=sys.stderr)

    # Find 1-degree dependents (children)
    children = []
    for n_id, n_data in node_dict.items():
        n_deps = n_data.get("dependencies", n_data.get("depends_on", []))
        if not n_deps:
            suspects = SUSPECT_DEP_KEYS.intersection(n_data.keys())
            if suspects:
                print(f"WARNING: Node '{n_id}' uses unrecognized dependency key(s) {suspects}. "
                      f"Expected 'dependencies' or 'depends_on'. Missing context may result.", file=sys.stderr)
        if target_node_id in n_deps:
            children.append(n_id)

    # Build the subgraph
    subgraph = {
        "target_node": target_node,
        "dependencies_1_degree": [node_dict[p] for p in parents if p in node_dict],
        "dependents_1_degree": [node_dict[c] for c in children if c in node_dict]
    }

    print(json.dumps(subgraph, indent=2))
    sys.exit(0)

if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--parallel":
        if len(sys.argv) >= 3:
            get_parallel_info(sys.argv[2])
        elif len(sys.argv) == 2:
            get_parallel_info("enterprise_state/JIRA_DAG.json")
        sys.exit(0)

    if len(sys.argv) < 3:
        print("Usage: python3 dag_subgraph.py <path_to_dag> <target_node_id>")
        print("       python3 dag_subgraph.py --parallel [dag_path]")
        sys.exit(1)

    dag_path = sys.argv[1]
    target_id = sys.argv[2]

    if not os.path.exists(dag_path):
        print(f"ERROR: DAG file {dag_path} not found.")
        sys.exit(1)

    try:
        with open(dag_path, 'r', encoding='utf-8') as f:
            dag = json.load(f)
        extract_subgraph(dag, target_id)
    except json.JSONDecodeError:
        print("ERROR: Invalid JSON format in DAG.")
        sys.exit(1)
