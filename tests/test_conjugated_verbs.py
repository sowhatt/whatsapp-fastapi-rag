"""
Le raccourci rapide de détection (avant tout appel à l'IA) doit
reconnaître une vente ou un achat quelle que soit sa conjugaison
(impératif, présent, passé composé, singulier/pluriel) — pas
seulement l'impératif « vends »/« achat ».
"""
from app.business.assistant import detect_business_intent
from app.services.sales_list_service import is_sales_list_request


def test_vente_toutes_formes():
    for phrase in [
        "Vends deux sacs de riz à Awa",
        "Vente de riz à Awa",
        "J'ai vendu deux sacs de riz à Awa",
        "Deux sacs de riz vendus à Awa",
        "Vendre deux sacs de riz à Awa",
    ]:
        assert detect_business_intent(phrase) == "sale_create", phrase


def test_achat_toutes_formes():
    for phrase in [
        "Achat cinq sacs de riz chez Soglo",
        "Acheter cinq sacs de riz chez Soglo",
        "J'achète cinq sacs de riz chez Soglo",
        "J'ai acheté cinq sacs de riz chez Soglo",
        "Cinq sacs de riz achetés chez Soglo",
    ]:
        assert detect_business_intent(phrase) == "purchase_create", phrase


def test_listes_de_ventes_gardent_la_priorite():
    for phrase in ["ventes par client", "liste des ventes", "ventes de Awa", "ventes par catégorie"]:
        assert is_sales_list_request(phrase), phrase
