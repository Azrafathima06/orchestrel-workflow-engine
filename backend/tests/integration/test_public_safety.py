"""Protections for an unauthenticated, publicly reachable trigger endpoint.

The deployed demo has no login by design — a recruiter should be able to run
a workflow without signing up. These tests pin the controls that make that
safe: nobody may inject undeclared handler arguments, size a workload
arbitrarily, run fault-injection workflows, or saturate a shared free-tier
instance.

Every assertion here is about the HTTP contract, so a regression shows up as
a changed status code rather than as a silently accepted abusive request.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_dispatcher
from app.config import get_settings
from app.core.states import WorkflowStatus
from app.main import app
from app.orchestration.dispatch import RecordingDispatcher
from tests.integration.factories import (
    TEST_KEY_PREFIX,
    linear_spec,
    make_spec,
    persist_definition,
)

settings = get_settings()


@pytest.fixture
def client():
    app.dependency_overrides[get_dispatcher] = lambda: RecordingDispatcher()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_dispatcher, None)


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Clear the in-process rate-limit window between tests.

    The middleware instance lives on the module-level `app`, so counts would
    otherwise leak across tests and make ordering significant.
    """
    from app.api.middleware import TriggerRateLimitMiddleware

    def _clear() -> None:
        current = app.middleware_stack
        # Walk the built middleware chain looking for our instance.
        seen = set()
        stack = [current]
        while stack:
            node = stack.pop()
            if node is None or id(node) in seen:
                continue
            seen.add(id(node))
            if isinstance(node, TriggerRateLimitMiddleware):
                node._hits.clear()
            for attr in ("app", "_app"):
                stack.append(getattr(node, attr, None))

    _clear()
    yield
    _clear()


def _bounded_spec(key: str = "bounded"):
    """A definition whose single declared parameter carries real bounds."""
    doc = make_spec(
        key,
        [
            {
                "key": "a",
                "handler": "test.noop",
                "params": {"size": 10},
                "depends_on": [],
            }
        ],
    )
    doc["params_schema"] = {
        "size": {"type": "integer", "default": 10, "minimum": 1, "maximum": 100}
    }
    return doc


class TestParameterValidation:
    def test_value_above_maximum_is_rejected(self, client, session_factory) -> None:
        """The CPU-exhaustion vector: an unbounded workload size."""
        definition = _persist(session_factory, _bounded_spec())

        resp = client.post(
            f"/api/v1/workflows/{definition.key}/runs", json={"params": {"size": 99_999_999}}
        )

        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "invalid_parameters"
        assert body["error"]["details"][0]["code"] == "above_maximum"

    def test_value_below_minimum_is_rejected(self, client, session_factory) -> None:
        definition = _persist(session_factory, _bounded_spec())

        resp = client.post(
            f"/api/v1/workflows/{definition.key}/runs", json={"params": {"size": 0}}
        )

        assert resp.status_code == 422
        assert resp.json()["error"]["details"][0]["code"] == "below_minimum"

    def test_wrong_type_is_rejected(self, client, session_factory) -> None:
        definition = _persist(session_factory, _bounded_spec())

        resp = client.post(
            f"/api/v1/workflows/{definition.key}/runs", json={"params": {"size": "big"}}
        )

        assert resp.status_code == 422
        assert resp.json()["error"]["details"][0]["code"] == "invalid_type"

    def test_undeclared_parameter_is_rejected(self, client, session_factory) -> None:
        """A caller must not be able to inject arbitrary handler arguments."""
        definition = _persist(session_factory, _bounded_spec())

        resp = client.post(
            f"/api/v1/workflows/{definition.key}/runs",
            json={"params": {"__class__": "evil", "size": 5}},
        )

        assert resp.status_code == 422
        codes = {d["code"] for d in resp.json()["error"]["details"]}
        assert "unknown_parameter" in codes

    def test_workflow_without_schema_rejects_any_parameter(self, client, session_factory) -> None:
        definition = _persist(session_factory, linear_spec())

        resp = client.post(
            f"/api/v1/workflows/{definition.key}/runs", json={"params": {"seed": 1}}
        )

        assert resp.status_code == 422

    def test_valid_parameter_still_starts_a_run(self, client, session_factory) -> None:
        """The guard must not break the ordinary path."""
        definition = _persist(session_factory, _bounded_spec())

        resp = client.post(
            f"/api/v1/workflows/{definition.key}/runs", json={"params": {"size": 50}}
        )

        assert resp.status_code == 202
        assert resp.json()["params"] == {"size": 50}

    def test_rejected_request_creates_no_run(self, client, session_factory) -> None:
        """Validation happens before persistence, so a refusal leaves no trace."""
        definition = _persist(session_factory, _bounded_spec())

        client.post(
            f"/api/v1/workflows/{definition.key}/runs", json={"params": {"size": 10**9}}
        )

        listing = client.get("/api/v1/runs", params={"workflow": definition.key})
        assert listing.json()["items"] == []


class TestFaultInjectionWorkflows:
    def test_non_public_workflow_cannot_be_triggered(self, client, session_factory) -> None:
        doc = make_spec(
            "faultinj", [{"key": "a", "handler": "test.noop", "params": {}, "depends_on": []}]
        )
        doc["is_public"] = False
        definition = _persist(session_factory, doc)

        resp = client.post(f"/api/v1/workflows/{definition.key}/runs", json={"params": {}})

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "workflow_not_publicly_triggerable"

    def test_non_public_workflow_stays_visible(self, client, session_factory) -> None:
        """Hidden from triggering, never hidden from inspection."""
        doc = make_spec(
            "faultinj2", [{"key": "a", "handler": "test.noop", "params": {}, "depends_on": []}]
        )
        doc["is_public"] = False
        definition = _persist(session_factory, doc)

        detail = client.get(f"/api/v1/workflows/{definition.key}")

        assert detail.status_code == 200
        assert detail.json()["is_public"] is False
        assert len(detail.json()["nodes"]) == 1

    def test_seeded_crash_recovery_definition_is_not_public(self) -> None:
        """Guards the shipped definition itself, not just the mechanism."""
        from pathlib import Path

        spec = json.loads(
            (Path(__file__).resolve().parents[2] / "workflows" / "crash_recovery.json").read_text()
        )

        assert spec["is_public"] is False
        assert spec["params_schema"]["records"]["maximum"] == 200000

    def test_ordinary_workflows_remain_public(self, client, session_factory) -> None:
        definition = _persist(session_factory, linear_spec())

        resp = client.post(f"/api/v1/workflows/{definition.key}/runs", json={"params": {}})

        assert resp.status_code == 202


class TestRequestBodyLimit:
    def test_oversized_body_is_rejected(self, client, session_factory) -> None:
        definition = _persist(session_factory, linear_spec())
        huge = {"params": {"blob": "x" * (settings.max_request_body_bytes + 1024)}}

        resp = client.post(f"/api/v1/workflows/{definition.key}/runs", json=huge)

        assert resp.status_code == 413
        assert resp.json()["error"]["code"] == "request_too_large"

    def test_normal_body_passes(self, client, session_factory) -> None:
        definition = _persist(session_factory, linear_spec())

        resp = client.post(f"/api/v1/workflows/{definition.key}/runs", json={"params": {}})

        assert resp.status_code == 202

    def test_get_requests_are_unaffected(self, client) -> None:
        assert client.get("/api/v1/workflows").status_code == 200


class TestRateLimit:
    def test_repeated_triggers_are_eventually_rejected(self, client, session_factory) -> None:
        definition = _persist(session_factory, linear_spec())
        limit = settings.public_trigger_rate_per_minute

        statuses = [
            client.post(
                f"/api/v1/workflows/{definition.key}/runs", json={"params": {}}
            ).status_code
            for _ in range(limit + 3)
        ]

        assert 429 in statuses
        assert statuses[-1] == 429
        rejected = client.post(
            f"/api/v1/workflows/{definition.key}/runs", json={"params": {}}
        )
        assert rejected.json()["error"]["code"] == "rate_limited"

    def test_reads_are_never_rate_limited(self, client) -> None:
        """Dashboard polling must never be throttled."""
        for _ in range(settings.public_trigger_rate_per_minute + 10):
            assert client.get("/api/v1/workflows").status_code == 200


class TestActiveRunCap:
    def test_cap_rejects_further_triggers(self, client, session_factory) -> None:
        definition = _persist(session_factory, linear_spec())

        # Create exactly the cap's worth of RUNNING runs directly, so this
        # test measures the cap rather than the rate limit.
        from sqlalchemy import select, text

        from app.core.states import TriggerType
        from app.db.models import WorkflowDefinition
        from app.orchestration.materialize import create_run

        with session_factory() as s:
            fresh = s.execute(
                select(WorkflowDefinition).where(WorkflowDefinition.key == definition.key)
            ).scalar_one()
            for _ in range(settings.max_active_runs):
                run = create_run(s, fresh, params={}, trigger_type=TriggerType.MANUAL)
                s.flush()
                s.execute(
                    text("UPDATE workflow_run SET status = :st WHERE id = :i"),
                    {"st": WorkflowStatus.RUNNING.value, "i": run.id},
                )
            s.commit()

        resp = client.post(f"/api/v1/workflows/{definition.key}/runs", json={"params": {}})

        assert resp.status_code == 429
        assert resp.json()["error"]["code"] == "too_many_active_runs"


class TestErrorHygiene:
    def test_invalid_uuid_is_a_clean_error_with_no_traceback(self, client) -> None:
        resp = client.get("/api/v1/runs/not-a-uuid")

        assert resp.status_code in (404, 422)
        assert "Traceback" not in resp.text
        assert "/app/" not in resp.text

    def test_unknown_workflow_is_a_clean_404(self, client) -> None:
        resp = client.get("/api/v1/workflows/does-not-exist")

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "workflow_not_found"
        assert "Traceback" not in resp.text

    def test_pagination_limit_is_bounded(self, client) -> None:
        resp = client.get("/api/v1/runs", params={"limit": 100000})

        assert resp.status_code == 422
        assert "Traceback" not in resp.text


class TestCors:
    def test_configured_origin_is_allowed(self, client) -> None:
        allowed = settings.cors_origins_list[0]

        resp = client.get("/api/v1/workflows", headers={"Origin": allowed})

        assert resp.headers.get("access-control-allow-origin") == allowed

    def test_unknown_origin_gets_no_permissive_header(self, client) -> None:
        resp = client.get(
            "/api/v1/workflows", headers={"Origin": "https://evil.example"}
        )

        header = resp.headers.get("access-control-allow-origin")
        assert header != "*"
        assert header != "https://evil.example"

    def test_credentials_are_not_allowed(self, client) -> None:
        """No cookies or browser-managed auth, so credentials add risk for nothing."""
        allowed = settings.cors_origins_list[0]

        resp = client.get("/api/v1/workflows", headers={"Origin": allowed})

        assert resp.headers.get("access-control-allow-credentials") is None


def _persist(session_factory, spec_doc):
    """Persist a definition through a real committing session.

    Not `db_session`: that fixture joins an external transaction which is
    rolled back at teardown, so its writes are never visible to the separate
    connection the API request handler uses.
    """
    with session_factory() as s:
        definition = persist_definition(s, spec_doc)
        s.commit()
        assert definition.key.startswith(TEST_KEY_PREFIX)
        return definition
