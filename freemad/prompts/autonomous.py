from __future__ import annotations

import json

from freemad.tasks.models import TaskRequest


def build_task_prompt(request: TaskRequest) -> str:
    payload = json.dumps(request.to_prompt_dict(), indent=2, sort_keys=True)
    return (
        "You are an autonomous FREE-MAD task agent.\n"
        "Return exactly one JSON object and no surrounding prose.\n"
        "Required keys:\n"
        "- agent_id: string\n"
        "- role: string\n"
        "- stage: string\n"
        "- content: string\n"
        "Optional keys:\n"
        "- review_decision: approve|revise|reject\n"
        "- findings: [string]\n"
        "- commands: [string]\n"
        "- artifact_ids: [string]\n"
        "- work_items: [{work_item_id,task_id,title,description,status,...}]\n\n"
        "- sources: [{title,url,summary}]\n\n"
        "Task request JSON:\n"
        + payload
    )
