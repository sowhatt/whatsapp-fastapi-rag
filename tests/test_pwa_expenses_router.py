from app.main import app


def test_pwa_expenses_routes_are_registered():
    paths = app.openapi()["paths"]

    assert "/pwa/expenses" in paths
    assert "get" in paths["/pwa/expenses"]
    assert "post" in paths["/pwa/expenses"]


def test_pwa_expenses_post_and_get_are_distinct_operations():
    operations = app.openapi()["paths"]["/pwa/expenses"]

    assert operations["get"]["summary"]
    assert operations["post"]["summary"]
