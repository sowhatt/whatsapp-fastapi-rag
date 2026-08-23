from app.business.assistant import (
    BUSINESS_MENU,
    detect_business_intent,
)


def test_financial_intelligence_visible_in_menu():
    assert "Analyse financière" in BUSINESS_MENU


def test_financial_intelligence_menu_number():
    assert detect_business_intent("11") == "financial_intelligence"


def test_financial_intelligence_natural_language():
    cases = [
        "analyse financière",
        "analyse financiere",
        "comment va mon commerce",
        "santé financière",
        "performance financière",
        "rentabilité globale",
    ]

    for text in cases:
        assert (
            detect_business_intent(text)
            == "financial_intelligence"
        )
