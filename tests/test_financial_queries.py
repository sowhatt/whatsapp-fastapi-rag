from app.services.financial_queries_service import (
    detect_financial_query,
)


def test_detect_profitable_products():
    assert (
        detect_financial_query(
            "Quels produits me rapportent le plus ?"
        )
        == "product_profitability"
    )


def test_detect_loss_products():
    assert (
        detect_financial_query(
            "Quels produits me font perdre de l'argent ?"
        )
        == "product_losses"
    )


def test_detect_customer_receivables():
    assert (
        detect_financial_query(
            "Qui me doit le plus ?"
        )
        == "customer_receivables"
    )


def test_detect_stock_concentration():
    assert (
        detect_financial_query(
            "Où est bloqué mon argent ?"
        )
        == "stock_concentration"
    )


def test_detect_nigeria_purchases():
    assert (
        detect_financial_query(
            "Mes achats au Nigeria"
        )
        == "nigeria_purchases"
    )


def test_nigeria_query_not_generic_purchase():
    from app.business.assistant import detect_business_intent

    text = "Mes achats au Nigeria"

    assert detect_financial_query(text) == "nigeria_purchases"

    # Le pattern business historique peut encore reconnaître "achat".
    # C'est volontaire : l'orchestrateur donne la priorité à la BI.
    assert detect_business_intent(text) == "purchase_create"
