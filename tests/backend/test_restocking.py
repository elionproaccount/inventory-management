"""Tests for the restocking order endpoints"""
import pytest
import main


@pytest.fixture(autouse=True)
def clear_restocking_orders():
    """Submitted orders are held in module-level memory, so isolate each test"""
    main.restocking_orders.clear()
    yield
    main.restocking_orders.clear()


class TestDemandUnitCost:
    def test_forecasts_expose_unit_cost(self, client):
        response = client.get("/api/demand")
        assert response.status_code == 200
        for forecast in response.json():
            assert forecast["unit_cost"] is not None
            assert forecast["unit_cost"] > 0


class TestCreateRestockingOrder:
    def test_create_order_succeeds(self, client):
        response = client.post("/api/restocking-orders", json={
            "items": [{"sku": "WDG-001", "quantity": 100}, {"sku": "GSK-203", "quantity": 50}]
        })
        assert response.status_code == 201
        order = response.json()
        assert order["status"] == "Submitted"
        assert order["order_number"].startswith("RST-")
        assert len(order["items"]) == 2
        assert order["lead_time_days"] > 0
        # 100 * 24.99 + 50 * 8.75
        assert order["total_value"] == pytest.approx(2936.5)

    def test_price_comes_from_server_not_client(self, client):
        response = client.post("/api/restocking-orders", json={
            "items": [{"sku": "WDG-001", "quantity": 1, "unit_cost": 0.01}]
        })
        assert response.status_code == 201
        assert response.json()["items"][0]["unit_cost"] == 24.99

    def test_lead_time_is_longest_item(self, client):
        # PSU-501 has order history; WDG-001 has none and uses the overall average
        psu = client.post("/api/restocking-orders", json={"items": [{"sku": "PSU-501", "quantity": 1}]}).json()
        wdg = client.post("/api/restocking-orders", json={"items": [{"sku": "WDG-001", "quantity": 1}]}).json()
        both = client.post("/api/restocking-orders", json={
            "items": [{"sku": "PSU-501", "quantity": 1}, {"sku": "WDG-001", "quantity": 1}]
        }).json()
        assert both["lead_time_days"] == max(psu["lead_time_days"], wdg["lead_time_days"])

    def test_unknown_sku_rejected(self, client):
        response = client.post("/api/restocking-orders", json={"items": [{"sku": "NOPE-000", "quantity": 5}]})
        assert response.status_code == 400

    def test_duplicate_sku_rejected(self, client):
        response = client.post("/api/restocking-orders", json={
            "items": [{"sku": "WDG-001", "quantity": 5}, {"sku": "WDG-001", "quantity": 5}]
        })
        assert response.status_code == 400

    def test_empty_items_rejected(self, client):
        response = client.post("/api/restocking-orders", json={"items": []})
        assert response.status_code == 422

    @pytest.mark.parametrize("quantity", [0, -3])
    def test_non_positive_quantity_rejected(self, client, quantity):
        response = client.post("/api/restocking-orders", json={"items": [{"sku": "WDG-001", "quantity": quantity}]})
        assert response.status_code == 422


class TestGetRestockingOrders:
    def test_empty_by_default(self, client):
        response = client.get("/api/restocking-orders")
        assert response.status_code == 200
        assert response.json() == []

    def test_newest_first(self, client):
        first = client.post("/api/restocking-orders", json={"items": [{"sku": "WDG-001", "quantity": 1}]}).json()
        second = client.post("/api/restocking-orders", json={"items": [{"sku": "GSK-203", "quantity": 1}]}).json()
        listed = client.get("/api/restocking-orders").json()
        assert [o["order_number"] for o in listed] == [second["order_number"], first["order_number"]]

    def test_does_not_affect_regular_orders(self, client):
        before = len(client.get("/api/orders").json())
        client.post("/api/restocking-orders", json={"items": [{"sku": "WDG-001", "quantity": 1}]})
        assert len(client.get("/api/orders").json()) == before
