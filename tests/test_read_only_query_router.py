from app.business.assistant import (
    is_stock_view_request,
)
from app.services.read_only_query_router import (
    ReadOnlyQueryRoute,
    SemanticReadOnlyIntent,
    _looks_like_analytics_question,
    _resolve_semantic_decision,
    detect_read_only_query,
)
from app.services.inventory_queries_service import (
    handle_inventory_query,
)
from app.services.sales_list_service import (
    is_sales_list_request,
)


def test_voice_agent_means_argent_in_context():
    route = detect_read_only_query(
        "Où est bloqué mon agent ?"
    )

    assert route is not None
    assert route.query_type == "stock_concentration"


def test_singular_stockout_question():
    route = detect_read_only_query(
        "Quel produit risque bientôt une rupture de stock ?"
    )

    assert route is not None
    assert route.query_type == "stockout_risk"


def test_slow_movers_win_over_generic_stock_view():
    text = (
        "Quels sont les produits qui dorment "
        "dans mon stock ?"
    )

    assert is_stock_view_request(text) is True

    route = detect_read_only_query(text)

    assert route is not None
    assert route.query_type == "slow_movers"


def test_week_comparison_wins_over_sales_list():
    text = (
        "Compare mes ventes de cette semaine "
        "et la semaine dernière."
    )

    assert is_sales_list_request(text) is True

    route = detect_read_only_query(text)

    assert route is not None
    assert route.query_type == "week_comparison"


def test_normal_stock_request_is_not_bi():
    assert (
        detect_read_only_query("Mon stock")
        is None
    )


def test_normal_sales_list_is_not_bi():
    assert (
        detect_read_only_query("Mes ventes")
        is None
    )


def test_sale_creation_is_never_bi():
    assert (
        detect_read_only_query(
            "Vente 2 sacs de riz à Awa pour 100000"
        )
        is None
    )


def test_semantic_fallback_is_closed_and_read_only(
    monkeypatch,
):
    expected = ReadOnlyQueryRoute(
        family="inventory",
        query_type="slow_movers",
        source="semantic",
        confidence=0.91,
    )

    monkeypatch.setattr(
        "app.services.read_only_query_router."
        "classify_semantic_read_only_query",
        lambda text: expected,
    )

    route = detect_read_only_query(
        "Qu'est-ce qui reste trop longtemps "
        "dans mes rayons ?"
    )

    assert route == expected


def test_voice_transcription_comment_evoluent_ventes():
    route = detect_read_only_query(
        "Comment évoluent mes ventes ?"
    )

    assert route is not None
    assert route.family == "adaptive_forecast"
    assert route.query_type == "adaptive_month_forecast"
    assert route.source == "deterministic"


def test_voice_transcription_produits_dorme():
    route = detect_read_only_query(
        "Quels produits dorme dans mon stock ?"
    )

    assert route is not None
    assert route.family == "inventory"
    assert route.query_type == "slow_movers"
    assert route.source == "deterministic"


def test_ambiguous_voice_stock_question_reaches_semantic_gate():
    assert _looks_like_analytics_question(
        "Quels produits d'horne dans mon stock ?"
    ) is True


def test_explicit_stock_write_is_blocked_from_semantic_gate():
    assert _looks_like_analytics_question(
        "Quels produits dois-je ajouter dans mon stock ?"
    ) is False


def test_ambiguous_voice_accepts_lower_semantic_threshold():
    decision = _resolve_semantic_decision(
        text="Quels produits d'armes dans mon stock ?",
        parsed=SemanticReadOnlyIntent(
            intent="slow_movers",
            confidence=0.72,
            reason="Probable erreur de transcription vocale",
        ),
    )

    assert decision.reason == "accepted"
    assert decision.route is not None
    assert decision.route.query_type == "slow_movers"
    assert decision.route.source == "semantic"


def test_ambiguous_unknown_returns_safe_clarification():
    decision = _resolve_semantic_decision(
        text="Quels produits d'armes dans mon stock ?",
        parsed=SemanticReadOnlyIntent(
            intent="unknown",
            confidence=0.40,
        ),
    )

    assert decision.route is not None
    assert (
        decision.route.query_type
        == "inventory_clarification"
    )


def test_ambiguous_non_inventory_intent_is_rejected():
    decision = _resolve_semantic_decision(
        text="Quels produits d'armes dans mon stock ?",
        parsed=SemanticReadOnlyIntent(
            intent="business_advisor",
            confidence=0.95,
        ),
    )

    assert decision.route is not None
    assert (
        decision.route.query_type
        == "inventory_clarification"
    )
    assert (
        decision.reason
        == "non_inventory_intent_rejected"
    )


def test_inventory_clarification_does_not_query_database():
    response = handle_inventory_query(
        query_type="inventory_clarification",
        merchant_id=1,
        db=None,
    )

    assert "Je veux vérifier" in response
    assert "produits qui dorment" in response
