from __future__ import annotations

import json
from pathlib import Path

from .models import QuestionContract, SemanticRule


def load_semantic_rules(path: Path) -> tuple[str, list[SemanticRule]]:
    if not path.exists():
        return "unversioned", []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return str(payload.get("version", "unversioned")), [
        SemanticRule.model_validate(item) for item in payload.get("rules", [])
    ]


def applicable_semantic_rules(
    contract: QuestionContract,
    rules: list[SemanticRule],
) -> list[SemanticRule]:
    concepts = set(contract.concepts)
    metric_concepts = {metric.concept for metric in contract.metrics}
    selected: list[SemanticRule] = []
    for rule in rules:
        if rule.status != "active" or rule.concept not in concepts:
            continue
        allowed_metrics = set(rule.applies_when.get("metric_concepts", []))
        blocked_metrics = set(rule.does_not_apply_when.get("metric_concepts", []))
        if allowed_metrics and not (allowed_metrics & metric_concepts):
            continue
        if blocked_metrics & metric_concepts:
            continue
        selected.append(rule)
    return selected
