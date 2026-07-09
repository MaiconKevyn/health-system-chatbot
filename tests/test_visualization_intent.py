from health_system_chatbot.visualization.intent import detect_visualization_intent


def test_detects_explicit_chart_request_and_cleans_analysis_question():
    intent = detect_visualization_intent(
        "Gere um grafico de barras com a distribuicao de internacoes por sexo"
    )

    assert intent.requested is True
    assert intent.chart_hint == "bar"
    assert intent.source == "explicit_current_query"
    assert "grafico" not in intent.analysis_question
    assert "internacoes por sexo" in intent.analysis_question


def test_does_not_treat_chart_advice_as_database_visualization_request():
    intent = detect_visualization_intent("Que tipo de grafico faria sentido para essa base?")

    assert intent.requested is False
    assert intent.analysis_question == "Que tipo de grafico faria sentido para essa base?"
