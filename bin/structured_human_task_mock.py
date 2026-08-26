#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from typing import Any


def _extract_request(prompt: str) -> dict[str, Any]:
    marker = "Task request JSON:\n"
    index = prompt.find(marker)
    if index == -1:
        return {}
    payload = prompt[index + len(marker) :].strip()
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return {}


def _single_select_request() -> dict[str, Any]:
    return {
        "request_id": "storage-backend",
        "kind": "single_select",
        "question": "Which storage backend should we use first?",
        "context": "Planner and reviewer need a product decision before implementation starts.",
        "required": True,
        "allow_free_text": False,
        "options": [
            {
                "id": "sqlite",
                "label": "SQLite",
                "description": "Fastest to ship and easy to verify locally.",
            },
            {
                "id": "postgres",
                "label": "Postgres",
                "description": "Heavier setup, but closer to production.",
            },
        ],
    }


def _multi_select_request() -> dict[str, Any]:
    return {
        "request_id": "reviewers",
        "kind": "multi_select",
        "question": "Which reviewers should stay assigned?",
        "context": "The task needs a quorum decision for implementation and verification.",
        "required": True,
        "allow_free_text": True,
        "options": [
            {
                "id": "claude",
                "label": "Claude",
                "description": "Architecture and plan pressure.",
            },
            {
                "id": "codex",
                "label": "Codex",
                "description": "Implementation and verification pressure.",
            },
            {
                "id": "arbiter",
                "label": "Arbiter",
                "description": "Hold a third reviewer in reserve.",
            },
        ],
        "placeholder": "Add any policy note for the reviewer quorum.",
    }


def _free_text_request() -> dict[str, Any]:
    return {
        "request_id": "success-criteria",
        "kind": "free_text",
        "question": "What success criteria should the task optimize for?",
        "context": "The team can proceed, but product priority is ambiguous.",
        "required": True,
        "allow_free_text": True,
        "options": [],
        "placeholder": "Example: optimize for fastest local delivery, not production scale.",
    }


def _question_for(goal: str) -> str:
    normalized_goal = goal.lower()
    request = _single_select_request()
    if "multi" in normalized_goal:
        request = _multi_select_request()
    elif "free text" in normalized_goal or "free-text" in normalized_goal:
        request = _free_text_request()
    options = ", ".join(o["label"] for o in request["options"])
    return request["question"] + (f" ({options})" if options else "")


def _response_for(
    stage: str, role: str, goal: str, has_human_response: bool
) -> dict[str, Any]:
    if role == "researcher" and stage == "research":
        return {
            "agent_id": "mock-researcher",
            "stage": stage,
            "role": role,
            "content": "Research bundle: compared SQLite, Postgres, and quorum review options.",
            "sources": [
                {
                    "title": "Local repo walkthrough",
                    "url": "file:///workspace",
                    "summary": "Used only local context for this deterministic smoke test.",
                }
            ],
        }
    if role == "reviewer" and stage == "research":
        return {
            "agent_id": "mock-reviewer",
            "stage": stage,
            "role": role,
            "content": "Research approved for planning.",
            "review_decision": "approve",
        }
    if role == "planner" and stage == "draft_plan":
        return {
            "agent_id": "mock-planner",
            "stage": stage,
            "role": role,
            "content": "Draft plan: collect clarification, lock the plan, then proceed.",
        }
    if role == "reviewer" and stage == "plan_review":
        if has_human_response:
            return {
                "agent_id": "mock-reviewer",
                "stage": stage,
                "role": role,
                "content": "Human clarification received. The plan is now implementation-ready.",
                "review_decision": "approve",
            }
        return {
            "agent_id": "mock-reviewer",
            "stage": stage,
            "role": role,
            "content": "The plan needs one explicit human choice before approval.",
            "review_decision": "revise",
            "findings": [_question_for(goal)],
        }
    if role == "arbiter" and stage == "plan_review":
        # Withholding approval here is what parks the task in waiting_for_human; the
        # finding becomes the question the operator sees in `task status`.
        return {
            "agent_id": "mock-arbiter",
            "stage": stage,
            "role": role,
            "content": "Cannot arbitrate a product decision; asking the human.",
            "review_decision": "reject",
            "findings": [_question_for(goal)],
        }
    if role == "planner" and stage == "finalize":
        return {
            "agent_id": "mock-planner",
            "stage": stage,
            "role": role,
            "content": "Final plan approved and ready for implementation.",
        }
    return {
        "agent_id": f"mock-{role}",
        "stage": stage,
        "role": role,
        "content": f"Mock handled {stage} as {role}.",
    }


def main() -> int:
    prompt = sys.stdin.read()
    request = _extract_request(prompt)
    stage = str(request.get("stage", "research"))
    role = str(request.get("role", "reviewer"))
    goal = str(request.get("goal", ""))
    feedback = request.get("feedback", [])
    has_human_response = isinstance(feedback, list) and any(
        str(item).startswith("HUMAN_INPUT:") for item in feedback
    )
    sys.stdout.write(
        json.dumps(_response_for(stage, role, goal, has_human_response), sort_keys=True)
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
