"""Push eval sets to LangSmith as datasets for tracked evaluation runs.

LangSmith datasets let you re-run evals over time, compare model versions,
and surface regressions in the UI. This script uploads each task's eval
set as a versioned dataset so reviewers can:

1. See per-case results in the LangSmith UI
2. Run evaluations against new model/prompt versions
3. Track quality drift over time

Usage:
    LANGSMITH_API_KEY=... python -m evals.upload_to_langsmith
    LANGSMITH_API_KEY=... python -m evals.upload_to_langsmith --task task2

Datasets created (idempotent — overwrites if same name):
    - signal-foundry-task1-cicd  (5 cases)
    - signal-foundry-task2-browser  (33 cases)
    - signal-foundry-task3-sec  (16 cases)
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

EVAL_FILES = {
    "task1": ("signal-foundry-task1-cicd", Path("evals/task1/scenarios.json")),
    "task2": ("signal-foundry-task2-browser", Path("evals/task2/eval_set.json")),
    "task3": ("signal-foundry-task3-sec", Path("evals/task3/eval_set.json")),
}


def _flatten_case(case: dict) -> tuple[dict, dict]:
    """Map our eval-case shape onto LangSmith (inputs, outputs) tuples.

    Inputs = the request payload the API would receive.
    Outputs = the expected behavior text — used by LLM-as-judge evaluators.
    """
    inputs = case.get("input_data", case)
    outputs = {
        "expected_behavior": case.get("expected_behavior", ""),
        "difficulty": case.get("difficulty", "normal"),
        "tags": case.get("tags", []),
    }
    return inputs, outputs


def upload_one(task: str) -> None:
    name, path = EVAL_FILES[task]
    if not path.exists():
        print(f"[skip] {task}: {path} not found")
        return

    cases = json.loads(path.read_text())
    print(f"[{task}] uploading {len(cases)} cases to LangSmith dataset '{name}'...")

    try:
        from langsmith import Client
    except ImportError:
        print("ERROR: pip install langsmith")
        return

    client = Client()

    # Create or overwrite dataset
    try:
        existing = client.read_dataset(dataset_name=name)
        client.delete_dataset(dataset_id=existing.id)
        print(f"  · deleted existing dataset {name}")
    except Exception:
        pass

    ds = client.create_dataset(
        dataset_name=name,
        description=f"Signal-Foundry {task} eval set — committed real-world cases.",
    )
    for case in cases:
        inputs, outputs = _flatten_case(case)
        client.create_example(
            dataset_id=ds.id,
            inputs=inputs,
            outputs=outputs,
            metadata={"case_id": case.get("case_id", ""), "tags": case.get("tags", [])},
        )
    print(f"  · uploaded {len(cases)} cases. View: https://smith.langchain.com/")


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload eval sets to LangSmith")
    parser.add_argument(
        "--task",
        choices=["task1", "task2", "task3", "all"],
        default="all",
        help="Which eval set(s) to upload",
    )
    args = parser.parse_args()

    if not os.environ.get("LANGSMITH_API_KEY"):
        print("ERROR: LANGSMITH_API_KEY not set")
        return

    targets = ["task1", "task2", "task3"] if args.task == "all" else [args.task]
    for t in targets:
        upload_one(t)


if __name__ == "__main__":
    main()
