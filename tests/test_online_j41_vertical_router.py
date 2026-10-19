import json
from types import SimpleNamespace
import pytest
from app.merchant.verticals import configuration

@pytest.mark.parametrize('kind,labels', [
    ('commerce', ['Accueil','Commandes','Stock','Produits','Plus']),
    ('restaurant', ['Cuisine','Commandes','Menu','Disponibilités','Plus']),
    ('rental', ['Calendrier','Réservations','Équipements','Retours','Plus']),
])
def test_navigation(kind, labels):
    config = configuration(SimpleNamespace(business_type=kind, capabilities_json=None))
    assert [n['label'] for n in config['navigation'] if n['mobile']] == labels
    for item in config['navigation']:
        if item['key'] in {'kitchen','calendar','bookings','catalog','menu','returns'}:
            assert not item['enabled'] and item['reason'] == 'Module non activé'

@pytest.mark.parametrize('caps', ['[]', '{}', 'invalid', '[123]'])
def test_missing_or_malformed_capabilities_fail_closed(caps):
    config = configuration(SimpleNamespace(business_type='commerce', capabilities_json=caps))
    assert not any(n['enabled'] for n in config['navigation'] if n['key'] in {'orders','notifications','catalog'})


def test_unknown_vertical_is_generic():
    config = configuration(SimpleNamespace(business_type='unknown', capabilities_json=json.dumps(['checkout','notifications'])))
    assert config['configuration_required'] and config['business_label'] == 'Configuration à compléter'
    assert config['capabilities'] == []
    assert not any(n['key'] == 'orders' for n in config['navigation'])
