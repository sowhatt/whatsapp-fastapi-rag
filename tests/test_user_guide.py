import pytest

from app.business.assistant import (
    is_stock_view_request,
    is_summary_keyword_request,
)
from app.services.calculator_service import (
    looks_like_calculation,
)
from app.services.customer_supplier_service import (
    is_customer_list_request,
    is_supplier_list_request,
)
from app.services.receipt_service import (
    is_receipt_request,
)
from app.services.sales_list_service import (
    is_sales_list_request,
)
from app.services.user_guide_service import (
    GUIDE_SECTIONS,
    SECTION_ORDER,
    handle_user_guide_request,
    iter_guide_examples,
    render_guide_index,
    render_guide_section,
)


ALL_EXAMPLES = list(
    iter_guide_examples()
)


def test_guide_index_lists_every_section():
    message = render_guide_index()

    for section_name in SECTION_ORDER:
        title = GUIDE_SECTIONS[
            section_name
        ]["title"]

        assert title in message

    assert len(message) < 3500


@pytest.mark.parametrize(
    (
        "section_name",
        "label",
        "phrase",
        "confirmation",
    ),
    ALL_EXAMPLES,
)
def test_every_documented_phrase_is_reachable(
    section_name,
    label,
    phrase,
    confirmation,
):
    message = render_guide_section(
        section_name
    )

    assert label in message
    assert phrase in message

    if confirmation:
        assert "Confirmation" in message

    assert len(message) < 3500


@pytest.mark.parametrize(
    "section_name",
    SECTION_ORDER,
)
def test_each_guide_command_opens_section(
    section_name,
):
    response = handle_user_guide_request(
        f"Guide {section_name}"
    )

    assert response is not None
    assert (
        GUIDE_SECTIONS[
            section_name
        ]["title"]
        in response
    )


@pytest.mark.parametrize(
    "spoken_request",
    [
        "Guide",
        "Guide vocal",
        "Guide utilisateur",
        "Mode d'emploi",
        "Comment utiliser Whatzabi",
        "Aide vocale",
    ],
)
def test_guide_index_voice_variants(spoken_request):
    response = handle_user_guide_request(
        spoken_request
    )

    assert response is not None
    assert "Guide vocal Whatzabi" in response


def test_unknown_section_returns_index():
    response = handle_user_guide_request(
        "Guide quelque chose"
    )

    assert response is not None
    assert "Rubrique inconnue" in response
    assert "Guide vocal Whatzabi" in response


def test_normal_message_is_not_intercepted():
    assert (
        handle_user_guide_request(
            "J'ai vendu deux sacs de riz"
        )
        is None
    )


def test_documented_sales_list_is_recognized():
    assert is_sales_list_request(
        "Liste des ventes."
    )


def test_documented_receipt_is_recognized():
    assert is_receipt_request(
        "Envoie le reçu de la vente 3."
    )


def test_documented_customer_list_is_recognized():
    assert is_customer_list_request(
        "Liste des clients."
    )


def test_documented_supplier_list_is_recognized():
    assert is_supplier_list_request(
        "Liste des fournisseurs."
    )


def test_documented_summary_is_recognized():
    assert is_summary_keyword_request(
        "Résumé du jour."
    )


def test_documented_stock_request_is_recognized():
    assert is_stock_view_request(
        "Quels produits ai-je dans mon stock ?"
    )


def test_documented_calculation_is_recognized():
    assert looks_like_calculation(
        "Calcule vingt pour cent "
        "de cinquante mille."
    )
