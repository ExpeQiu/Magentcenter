from agentcenter_fleet.store import EdgeStore


def test_edge_store_dedupes_and_keeps_unacked_result(tmp_path):
    store = EdgeStore(tmp_path / "edge.db")
    assert store.begin("task-1", 1) is True
    assert store.begin("task-1", 1) is False
    store.save_result("task-1", {"status": "completed", "output": "ok"})
    pending = store.pending()
    assert pending[0]["result"]["output"] == "ok"
    store.ack("task-1")
    assert store.pending() == []
