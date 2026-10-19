"""Single registry consumed by the BFF and rendered verbatim by the PWA."""
import json

from app.domains.online.foundation.business import default_capabilities

# key, French label, capability, implemented, description
MODULES = {
    "home": ("Accueil", None, True, "Votre activité au quotidien."),
    "orders": ("Commandes", "checkout", True, "Suivez vos commandes et leurs paiements."),
    "stock": ("Stock", "catalog", False, "Suivez les quantités disponibles et les alertes."),
    "catalog": ("Produits", "catalog", False, "Présentez et gérez votre catalogue."),
    "customers": ("Clients", "checkout", False, "Retrouvez vos relations clients."),
    "notifications": ("Notifications", "notifications", True, "Retrouvez les événements de votre boutique."),
    "kitchen": ("Cuisine", "checkout", False, "Organisez la préparation en cuisine."),
    "menu": ("Menu", "catalog", False, "Composez votre carte et vos menus."),
    "availability": ("Disponibilités", "catalog", False, "Indiquez les plats disponibles."),
    "delivery": ("Livraisons", "delivery", False, "Organisez les livraisons de vos commandes."),
    "calendar": ("Calendrier", "checkout", False, "Visualisez les périodes de location."),
    "bookings": ("Réservations", "checkout", False, "Gérez les réservations de matériel."),
    "assets": ("Équipements", "catalog", False, "Gérez votre parc de matériel."),
    "returns": ("Retours", "checkout", False, "Suivez les retours et l’état du matériel."),
    "deposits": ("Cautions", "payments", False, "Suivez les cautions de vos locations."),
    "more": ("Plus", None, True, "Tous vos espaces de travail."),
    "profile": ("Profil", None, True, "L’identité de votre boutique."),
    "settings": ("Paramètres", None, True, "Installation et notifications sur cet appareil."),
}
VERTICALS = {
    "commerce": ("Commerce", ("home", "orders", "stock", "catalog"), ("customers", "notifications")),
    "restaurant": ("Restaurant", ("kitchen", "orders", "menu", "availability"), ("delivery", "customers", "notifications")),
    "rental": ("Location", ("calendar", "bookings", "assets", "returns"), ("deposits", "customers", "notifications")),
}


def configuration(store):
    known = store.business_type in VERTICALS
    try:
        raw = json.loads(store.capabilities_json) if store.capabilities_json is not None else list(default_capabilities(store.business_type))
        caps = sorted(set(raw)) if isinstance(raw, list) and all(isinstance(x, str) for x in raw) else []
    except (TypeError, ValueError):
        caps = []
    if not known:
        caps = []
    label, mobile, extra = VERTICALS.get(store.business_type, ("Configuration à compléter", ("home",), ()))
    keys = list(dict.fromkeys((*mobile, "more", "home", *extra, "profile", "settings")))
    navigation = []
    for key in keys:
        title, capability, implemented, description = MODULES[key]
        permitted = capability is None or capability in caps
        href = "/merchant" if key == "home" else f"/merchant/{key}" if key in {"orders", "notifications", "catalog"} else f"/merchant/module/{key}"
        navigation.append({"key": key, "label": title, "href": href,
                           "enabled": permitted and implemented, "mobile": key in (*mobile, "more"),
                           "description": description, "reason": None if permitted and implemented else "Module non activé"})
    return {"business_label": label, "capabilities": caps, "navigation": navigation, "configuration_required": not known}
