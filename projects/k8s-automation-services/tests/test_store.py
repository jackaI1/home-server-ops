from concurrent.futures import ThreadPoolExecutor

import pytest

from automation.domain import Problem, validate_job
from automation.store import Store


def test_restart_preserves_job_and_idempotent_submission(tmp_path):
    path = tmp_path / "audit.db"
    first = Store(path).submit("check-001", {"device": "lab-switch", "task": "inventory"})
    again = Store(path).submit("check-001", {"device": "lab-switch", "task": "inventory"})
    assert again["id"] == first["id"]
    assert Store(path).get(first["id"])["status"] == "queued"
    assert [e["event"] for e in Store(path).get(first["id"])["events"]] == ["queued"]


def test_idempotency_key_cannot_change_work(tmp_path):
    store = Store(tmp_path / "audit.db")
    store.submit("key", {"device": "lab-switch", "task": "inventory"})
    with pytest.raises(Problem, match="different") as error:
        store.submit("key", {"device": "lab-switch", "task": "link-check"})
    assert error.value.status == 409


def test_claim_is_atomic_and_completion_fenced(tmp_path):
    store = Store(tmp_path / "audit.db")
    job = store.submit("key", {"device": "lab-switch", "task": "inventory"})
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(lambda _: store.claim(), range(8)))
    claimed = [c for c in claims if c]
    assert len(claimed) == 1
    lease = claimed[0]["lease"]
    with pytest.raises(Problem):
        store.finish(job["id"], "wrong-lease", "succeeded", {})
    store.finish(job["id"], lease, "succeeded", {"hostname": "lab-switch"})
    result = store.get(job["id"])
    assert result["result"] == {"hostname": "lab-switch"}
    assert [e["event"] for e in result["events"]] == ["queued", "claimed", "succeeded"]
    assert "lease" not in result


def test_expired_lease_retries_and_rejects_stale_worker(tmp_path):
    clock = [100.0]
    store = Store(tmp_path / "audit.db", clock=lambda: clock[0], lease_seconds=10)
    job = store.submit("key", {"device": "lab-switch", "task": "inventory"})
    old = store.claim()
    clock[0] = 111.0
    new = store.claim()
    assert new["id"] == old["id"]
    assert new["lease"] != old["lease"]
    with pytest.raises(Problem):
        store.finish(job["id"], old["lease"], "succeeded", {})
    clock[0] = 122.0
    store.claim()
    clock[0] = 133.0
    assert store.claim() is None
    assert store.get(job["id"])["status"] == "failed"
    assert store.get(job["id"])["attempts"] == 3


def test_cannot_complete_expired_lease_without_reclaim(tmp_path):
    clock = [100.0]
    store = Store(tmp_path / "audit.db", clock=lambda: clock[0], lease_seconds=10)
    job = store.submit("key", {"device": "lab-switch", "task": "inventory"})
    claim = store.claim()
    clock[0] = 111.0
    with pytest.raises(Problem):
        store.finish(job["id"], claim["lease"], "succeeded", {})


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"device": "8.8.8.8", "task": "inventory"},
        {"device": "lab-switch", "task": "rm -rf /"},
        {"device": "lab-switch", "task": "inventory", "command": "whoami"},
    ],
)
def test_rejects_unapproved_work(payload):
    with pytest.raises(Problem):
        validate_job(payload)


def test_missing_job_has_404(tmp_path):
    with pytest.raises(Problem) as error:
        Store(tmp_path / "audit.db").get("missing")
    assert error.value.status == 404
