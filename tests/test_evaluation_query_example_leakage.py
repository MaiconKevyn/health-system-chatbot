from __future__ import annotations

from types import SimpleNamespace

from evaluation.chatbot.ablation.contracts import SharedEvalContext, VariantSpec
from evaluation.chatbot.ablation.runner import AblationRunOptions, run_ablation
from evaluation.chatbot.ablation.strategies import OpenAIDirectStrategy
from evaluation.chatbot.evaluate_extraction_accuracy import evaluate_item
from health_system_chatbot.config import ChatbotConfig
from health_system_chatbot.context_retrieval import retrieve_query_examples
from health_system_chatbot.models import GroundTruthItem, Stage1Context


def _config(tmp_path):
    return ChatbotConfig(
        project_root=tmp_path,
        db_path=tmp_path / "missing.duckdb",
        openai_api_key="test-key",
    )


def _item():
    return GroundTruthItem(
        id="GT_LEAK",
        question_pt="Quantas internações existem?",
        sql="SELECT COUNT(*) FROM internacoes",
    )


def test_query_examples_never_leak_from_ground_truth(tmp_path):
    # The example bank is a curated corpus disjoint from any evaluation dataset;
    # retrieve_query_examples must source from it exclusively, never from
    # ctx.ground_truth, even when a ground-truth item is a perfect text match.
    leaked_item = GroundTruthItem(
        id="GT_LEAK",
        question_pt="Quantas internações existem?",
        sql="SELECT COUNT(*) FROM internacoes",
    )
    safe_item = GroundTruthItem(
        id="EX_SAFE",
        question_pt="Quantas internações existem?",
        sql="SELECT COUNT(*) AS total_internacoes FROM internacoes",
    )
    ctx = Stage1Context(
        project_root=str(tmp_path),
        ground_truth=[leaked_item],
        example_bank=[safe_item],
    )

    examples = retrieve_query_examples("Quantas internações existem?", ctx)

    returned_ids = [example.id for example in examples]
    assert "GT_LEAK" not in returned_ids
    assert returned_ids == ["EX_SAFE"]


def test_agent_evaluator_context_retrieval_uses_stage1_context(monkeypatch, tmp_path):
    observed = {}

    monkeypatch.setattr(
        "evaluation.chatbot.evaluate_extraction_accuracy.classify_question",
        lambda *_args, **_kwargs: SimpleNamespace(status="answerable"),
    )

    def fake_retrieve_context(*_args, **kwargs):
        observed.update(kwargs)
        raise RuntimeError("stop after retrieval contract check")

    monkeypatch.setattr(
        "evaluation.chatbot.evaluate_extraction_accuracy.retrieve_context",
        fake_retrieve_context,
    )

    evaluate_item(
        _item(),
        config=_config(tmp_path),
        ctx=Stage1Context(project_root=str(tmp_path)),
        allow_llm=False,
        max_rows=10,
        timeout_seconds=1,
        numeric_tolerance=1e-6,
    )

    # include_query_examples is no longer forced off here: the example bank is
    # already leak-safe, so the evaluator should see the same context-building
    # behavior production does (default True).
    assert observed.get("include_query_examples", True) is True


def test_direct_api_evaluator_disables_ground_truth_query_examples(monkeypatch, tmp_path):
    observed = {}

    def fake_retrieve_context(*_args, **kwargs):
        observed.update(kwargs)
        raise RuntimeError("stop after retrieval contract check")

    monkeypatch.setattr(
        "evaluation.chatbot.ablation.strategies.retrieve_context",
        fake_retrieve_context,
    )
    strategy = OpenAIDirectStrategy(
        VariantSpec(
            name="openai_raw_full_context",
            kind="openai_baseline",
            description="Direct API test",
            baseline_mode="full_context",
        )
    )
    context = SharedEvalContext(
        config=_config(tmp_path),
        stage1_context=Stage1Context(project_root=str(tmp_path)),
        max_rows=10,
        timeout_seconds=1,
        numeric_tolerance=1e-6,
    )

    try:
        strategy.run_item(_item(), context=context)
    except RuntimeError as exc:
        assert str(exc) == "stop after retrieval contract check"

    assert observed["include_query_examples"] is False


def test_ablation_runner_removes_ground_truth_from_shared_context(monkeypatch, tmp_path):
    observed = {}

    class FakeStrategy:
        name = "fake"

        def run_item(self, item, *, context):
            observed["ground_truth"] = context.stage1_context.ground_truth
            return {
                "id": item.id,
                "variant": "full_agent",
                "strategy": self.name,
                "result_match": False,
                "generated_sql_valid": False,
                "generated_execution_status": "skipped",
                "error_category": "test",
            }

    monkeypatch.setattr(
        "evaluation.chatbot.ablation.runner.build_strategy",
        lambda _spec: FakeStrategy(),
    )
    monkeypatch.setattr(
        "evaluation.chatbot.ablation.runner.write_ablation_outputs",
        lambda **_kwargs: {"variant_ranking": []},
    )
    item = _item()
    stage1_context = Stage1Context(project_root=str(tmp_path), ground_truth=[item])

    run_ablation(
        config=_config(tmp_path),
        stage1_context=stage1_context,
        items=[item],
        options=AblationRunOptions(
            run_id="no_leak",
            run_dir=tmp_path / "no_leak",
            run_config={},
            variant_names=["full_agent"],
            max_rows=10,
            timeout_seconds=1,
            numeric_tolerance=1e-6,
        ),
    )

    assert observed["ground_truth"] == []
    assert stage1_context.ground_truth == [item]
