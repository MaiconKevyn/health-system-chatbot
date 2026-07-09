from dataclasses import replace

from health_system_chatbot.config import ChatbotConfig
from health_system_chatbot.models import GroundTruthItem, Stage1Context, TableContext
from health_system_chatbot.schema_context import retrieve_context


def _stage_context(tmp_path):
    return Stage1Context(
        project_root=str(tmp_path),
        tables={
            "internacoes": TableContext(
                table_name="internacoes",
                schema_name="main",
                columns=["id", "MORTE"],
                column_types={"id": "INTEGER", "MORTE": "BOOLEAN"},
            )
        },
        ground_truth=[
            GroundTruthItem(
                id="GT1",
                question_pt="Quantas mortes existem?",
                sql="SELECT COUNT(*) FROM internacoes WHERE MORTE = TRUE",
            )
        ],
    )


def test_retrieve_context_can_disable_enrichment(tmp_path):
    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=tmp_path / "missing.duckdb",
        openai_api_key=None,
    )
    ctx = _stage_context(tmp_path)

    enriched = retrieve_context("Quantas mortes existem?", ctx, config=config)
    raw = retrieve_context(
        "Quantas mortes existem?",
        ctx,
        config=replace(config, context_enrichment_enabled=False),
    )

    assert enriched.business_metrics
    assert enriched.query_examples
    assert raw.business_metrics == []
    assert raw.query_examples == []
    assert raw.value_hints == []
    assert raw.catalog_candidates == []
