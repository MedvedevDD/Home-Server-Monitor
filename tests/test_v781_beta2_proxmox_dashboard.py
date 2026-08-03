import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_dashboard():
    return json.loads((ROOT / "dashboard" / "Proxmox.json").read_text(encoding="utf-8"))


def test_proxmox_dashboard_supports_short_ranges():
    dashboard = load_dashboard()
    assert dashboard["refresh"] == "30s"
    assert "5m" in dashboard["timepicker"]["time_options"]
    assert "1h" in dashboard["timepicker"]["time_options"]

    panels = {panel["id"]: panel for panel in dashboard["panels"]}
    for panel_id in (1, 2, 3, 4):
        query = panels[panel_id]["targets"][0]["query"]
        assert "time > now() - 10m" in query
        assert "$timeFilter" not in query

    for panel_id in (5, 6, 7):
        target = panels[panel_id]["targets"][0]
        assert "WHERE $timeFilter" in target["query"]
        assert "GROUP BY time(30s)" in target["query"]
        assert target["interval"] == "30s"
