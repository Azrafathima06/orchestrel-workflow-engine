"""API contract tests against the real FastAPI app and real PostgreSQL.

The dispatcher dependency is overridden with RecordingDispatcher so these
tests exercise the HTTP layer and its database writes without requiring a
reachable broker — dispatch mechanics themselves are covered by the
orchestration test suite (test_reconciler.py, test_runner.py, etc.).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import get_dispatcher
from app.core.states import AttemptStatus, TriggerType, WorkflowStatus
from app.db.models import TaskAttempt
from app.main import app
from app.orchestration.dispatch import RecordingDispatcher
from app.orchestration.materialize import create_run
from tests.integration.factories import (
    TEST_KEY_PREFIX,
    fanout_spec,
    linear_spec,
    persist_definition,
)


@pytest.fixture
def client():
    app.dependency_overrides[get_dispatcher] = lambda: RecordingDispatcher()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_dispatcher, None)


def _set_status(session_factory, run_id, status: WorkflowStatus) -> None:
    with session_factory() as s:
        s.execute(
            text("UPDATE workflow_run SET status = :s WHERE id = :i"),
            {"s": status.value, "i": run_id},
        )
        s.commit()


class TestHealthAndReady:
    def test_health_is_cheap_and_ok(self, client) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_ready_reports_real_database_check(self, client) -> None:
        resp = client.get("/ready")
        assert resp.status_code == 200
        body = resp.json()

        assert body["database"]["ok"] is True
        assert body["database"]["latency_ms"] is not None
        assert body["database"]["latency_ms"] >= 0

        # Broker reachability genuinely depends on the test environment (no
        # port is published to the host) — assert shape, not a specific
        # value, since asserting True here would be lying about a fact we
        # do not control.
        assert isinstance(body["broker"]["ok"], bool)
        if not body["broker"]["ok"]:
            assert body["broker"]["error"] is not None

        assert isinstance(body["workers_observed_5m"], int)
        assert body["workers_observed_5m"] >= 0


class TestWorkflows:
    def test_list_includes_seeded_definitions(self, client, session_factory) -> None:
        with session_factory() as s:
            persist_definition(s, linear_spec("apitest_list"))
            s.commit()

        resp = client.get("/api/v1/workflows")
        assert resp.status_code == 200

        ours = [w for w in resp.json() if w["key"].startswith(TEST_KEY_PREFIX)]
        assert len(ours) >= 1
        w = ours[0]
        assert w["task_count"] == 3
        assert w["last_run"] is None
        assert w["recent_success_count"] == 0
        assert w["recent_failure_count"] == 0

    def test_detail_includes_nodes_edges_and_params_schema(
        self, client, session_factory
    ) -> None:
        with session_factory() as s:
            definition = persist_definition(s, linear_spec("apitest_detail"))
            s.commit()
            key = definition.key

        resp = client.get(f"/api/v1/workflows/{key}")
        assert resp.status_code == 200
        body = resp.json()

        assert len(body["nodes"]) == 3
        assert {"source": "a", "target": "b"} in body["edges"]
        assert {"source": "b", "target": "c"} in body["edges"]
        assert "params_schema" in body
        assert body["recent_runs"] == []

    def test_unknown_workflow_returns_404_error_envelope(self, client) -> None:
        resp = client.get(f"/api/v1/workflows/{TEST_KEY_PREFIX}does_not_exist")
        assert resp.status_code == 404
        body = resp.json()
        assert body["error"]["code"] == "workflow_not_found"
        assert "error" in body and "message" in body["error"]

    def test_trigger_run_returns_202_with_all_tasks_pending(
        self, client, session_factory
    ) -> None:
        with session_factory() as s:
            definition = persist_definition(s, linear_spec("apitest_trigger"))
            s.commit()
            key = definition.key

        resp = client.post(f"/api/v1/workflows/{key}/runs", json={"params": {}})
        assert resp.status_code == 202
        assert "location" in resp.headers.get("location", "").lower() or resp.headers.get(
            "Location"
        )

        body = resp.json()
        assert body["status"] == "pending"
        assert len(body["tasks"]) == 3
        assert all(t["status"] == "pending" for t in body["tasks"])

        # Durably readable back via the run-detail endpoint.
        run_id = body["id"]
        follow_up = client.get(f"/api/v1/runs/{run_id}")
        assert follow_up.status_code == 200
        assert follow_up.json()["id"] == run_id


class TestRunsList:
    def test_pagination_covers_every_item_exactly_once(self, client, session_factory) -> None:
        with session_factory() as s:
            target_def = persist_definition(s, linear_spec("apitest_paging"))
            s.commit()
            # Five runs under the SAME definition (unlike make_run, which
            # persists a fresh definition per call) so filtering by
            # workflow=target_def.key isolates exactly this page of data.
            for _ in range(5):
                create_run(s, target_def, params={}, trigger_type=TriggerType.MANUAL)
            s.commit()

        seen_ids: set[str] = set()
        cursor = None
        pages = 0
        while True:
            params = {"workflow": target_def.key, "limit": 2}
            if cursor:
                params["cursor"] = cursor
            resp = client.get("/api/v1/runs", params=params)
            assert resp.status_code == 200
            body = resp.json()
            assert len(body["items"]) <= 2

            for item in body["items"]:
                assert item["id"] not in seen_ids, "keyset pagination must not repeat a row"
                seen_ids.add(item["id"])

            cursor = body["next_cursor"]
            pages += 1
            if cursor is None:
                break
            assert pages < 10, "pagination did not terminate"

        assert len(seen_ids) == 5

    def test_filter_by_status(self, client, session_factory) -> None:
        with session_factory() as s:
            definition = persist_definition(s, linear_spec("apitest_statusfilter"))
            s.commit()
            # create_run against the SAME definition object, not make_run
            # (which would persist a second, differently-keyed definition
            # per call) — both runs must share definition.key to be
            # filterable by it below.
            run_a = create_run(s, definition, params={}, trigger_type=TriggerType.MANUAL)
            run_b = create_run(s, definition, params={}, trigger_type=TriggerType.MANUAL)
            s.commit()

        _set_status(session_factory, run_a.id, WorkflowStatus.SUCCEEDED)
        _set_status(session_factory, run_b.id, WorkflowStatus.FAILED)

        resp = client.get(
            "/api/v1/runs", params={"workflow": definition.key, "status": "succeeded"}
        )
        assert resp.status_code == 200
        ids = {item["id"] for item in resp.json()["items"]}
        assert str(run_a.id) in ids
        assert str(run_b.id) not in ids

    def test_task_counts_reflect_real_state(self, client, session_factory) -> None:
        with session_factory() as s:
            definition = persist_definition(s, linear_spec("apitest_counts"))
            s.commit()
            run = create_run(s, definition, params={}, trigger_type=TriggerType.MANUAL)
            s.commit()

        with session_factory() as s:
            task = s.execute(
                text("SELECT id FROM task_run WHERE run_id = :r AND task_key = 'a'"),
                {"r": run.id},
            ).scalar_one()
            s.execute(
                text("UPDATE task_run SET status = 'succeeded' WHERE id = :i"), {"i": task}
            )
            s.commit()

        resp = client.get("/api/v1/runs", params={"workflow": definition.key})
        item = next(i for i in resp.json()["items"] if i["id"] == str(run.id))
        assert item["task_counts"]["total"] == 3
        assert item["task_counts"]["succeeded"] == 1
        assert item["task_counts"]["pending"] == 2


class TestRunDetail:
    def test_run_detail_includes_edges_and_retry_count(
        self, client, session_factory
    ) -> None:
        with session_factory() as s:
            definition = persist_definition(s, linear_spec("apitest_rundetail"))
            s.commit()
            run = create_run(s, definition, params={}, trigger_type=TriggerType.MANUAL)
            s.commit()

        with session_factory() as s:
            s.execute(
                text(
                    "UPDATE task_run SET attempt_count = 3 WHERE run_id = :r AND task_key = 'a'"
                ),
                {"r": run.id},
            )
            s.commit()

        resp = client.get(f"/api/v1/runs/{run.id}")
        assert resp.status_code == 200
        body = resp.json()

        assert body["workflow_name"] == definition.name
        assert {"source": "a", "target": "b"} in body["edges"]
        assert body["retry_count"] == 2  # 3 attempts - 1

    def test_unknown_run_returns_404(self, client) -> None:
        resp = client.get("/api/v1/runs/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "run_not_found"


class TestTaskDetail:
    def test_dependencies_and_dependents(self, client, session_factory) -> None:
        with session_factory() as s:
            definition = persist_definition(s, linear_spec("apitest_taskdetail"))
            s.commit()
            run = create_run(s, definition, params={}, trigger_type=TriggerType.MANUAL)
            s.commit()

        with session_factory() as s:
            middle = s.execute(
                text("SELECT id FROM task_run WHERE run_id = :r AND task_key = 'b'"),
                {"r": run.id},
            ).scalar_one()

        resp = client.get(f"/api/v1/runs/{run.id}/tasks/{middle}")
        assert resp.status_code == 200
        body = resp.json()

        assert [d["task_key"] for d in body["dependencies"]] == ["a"]
        assert [d["task_key"] for d in body["dependents"]] == ["c"]
        assert body["attempts"] == []

    def test_unknown_task_returns_404(self, client, session_factory) -> None:
        with session_factory() as s:
            definition = persist_definition(s, linear_spec("apitest_notask"))
            s.commit()
            run = create_run(s, definition, params={}, trigger_type=TriggerType.MANUAL)
            s.commit()

        resp = client.get(f"/api/v1/runs/{run.id}/tasks/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "task_not_found"


class TestStats:
    def test_overview_shape(self, client) -> None:
        resp = client.get("/api/v1/stats/overview")
        assert resp.status_code == 200
        body = resp.json()

        for key in ("total", "succeeded", "failed", "running", "cancelled"):
            assert isinstance(body["runs"][key], int)
            assert body["runs"][key] >= 0

        assert body["retries"] >= 0
        assert body["tasks_executed"] >= 0
        assert body["recovered_tasks"] >= 0
        assert isinstance(body["daily"], list)
        if body["success_rate"] is not None:
            assert 0.0 <= body["success_rate"] <= 1.0


class TestWorkers:
    def test_derives_observation_from_real_attempt(self, client, session_factory) -> None:
        with session_factory() as s:
            definition = persist_definition(s, linear_spec("apitest_workers"))
            s.commit()
            run = create_run(s, definition, params={}, trigger_type=TriggerType.MANUAL)
            s.commit()

        with session_factory() as s:
            task_id = s.execute(
                text("SELECT id FROM task_run WHERE run_id = :r AND task_key = 'a'"),
                {"r": run.id},
            ).scalar_one()
            s.add(
                TaskAttempt(
                    task_run_id=task_id,
                    attempt_number=1,
                    status=AttemptStatus.SUCCEEDED,
                    worker_id="apitest-worker:1",
                    started_at=datetime.now(UTC),
                    finished_at=datetime.now(UTC),
                )
            )
            s.commit()

        resp = client.get("/api/v1/workers")
        assert resp.status_code == 200
        workers = {w["worker_id"]: w for w in resp.json()}
        assert "apitest-worker:1" in workers
        w = workers["apitest-worker:1"]
        assert w["attempts_total"] >= 1
        assert w["liveness"] in {"active", "idle", "stale"}


class TestFanoutWorkflowShape:
    def test_fanout_spec_produces_correct_edge_count(self, client, session_factory) -> None:
        with session_factory() as s:
            definition = persist_definition(s, fanout_spec("apitest_fanout", shards=3))
            s.commit()
            key = definition.key

        resp = client.get(f"/api/v1/workflows/{key}")
        body = resp.json()
        assert len(body["nodes"]) == 5  # split + 3 shards + merge
        # 3 split->shard edges + 3 shard->merge edges
        assert len(body["edges"]) == 6
