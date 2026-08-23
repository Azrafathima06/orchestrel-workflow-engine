"""Parameter validation is the public trigger endpoint's trust boundary.

These tests exercise the pure rules directly — no database, no HTTP — so a
regression in the bounds logic is caught here rather than only in an
integration test that might not enumerate every case.
"""

from app.core.params import validate_params

CRASH_SCHEMA = {
    "records": {
        "type": "integer",
        "default": 70000,
        "minimum": 1000,
        "maximum": 200000,
    }
}


class TestAcceptance:
    def test_value_inside_bounds_is_accepted(self) -> None:
        assert validate_params({"records": 50000}, CRASH_SCHEMA) == []

    def test_bounds_are_inclusive(self) -> None:
        assert validate_params({"records": 1000}, CRASH_SCHEMA) == []
        assert validate_params({"records": 200000}, CRASH_SCHEMA) == []

    def test_empty_params_are_always_valid(self) -> None:
        assert validate_params({}, CRASH_SCHEMA) == []
        assert validate_params({}, {}) == []


class TestRejection:
    def test_above_maximum_is_rejected(self) -> None:
        """The exact CPU-exhaustion vector the pre-deployment audit found."""
        errors = validate_params({"records": 100_000_000}, CRASH_SCHEMA)

        assert len(errors) == 1
        assert errors[0].param == "records"
        assert errors[0].code == "above_maximum"

    def test_below_minimum_is_rejected(self) -> None:
        errors = validate_params({"records": 0}, CRASH_SCHEMA)

        assert [e.code for e in errors] == ["below_minimum"]

    def test_wrong_type_is_rejected(self) -> None:
        errors = validate_params({"records": "lots"}, CRASH_SCHEMA)

        assert [e.code for e in errors] == ["invalid_type"]

    def test_undeclared_parameter_is_rejected(self) -> None:
        errors = validate_params({"admin": True}, CRASH_SCHEMA)

        assert [e.code for e in errors] == ["unknown_parameter"]

    def test_workflow_without_schema_accepts_no_parameters(self) -> None:
        """sequential_etl and fanout_join declare no params_schema at all."""
        errors = validate_params({"anything": 1}, {})

        assert [e.code for e in errors] == ["unknown_parameter"]

    def test_bool_is_not_accepted_as_an_integer(self) -> None:
        """`True == 1` in Python, so a bool would otherwise pass a bounds check."""
        errors = validate_params({"records": True}, CRASH_SCHEMA)

        assert [e.code for e in errors] == ["invalid_type"]

    def test_every_problem_is_reported_not_just_the_first(self) -> None:
        errors = validate_params(
            {"records": 999_999_999, "nope": 1}, CRASH_SCHEMA
        )

        assert {e.code for e in errors} == {"above_maximum", "unknown_parameter"}

    def test_malformed_schema_entry_refuses_the_value(self) -> None:
        errors = validate_params({"records": 5}, {"records": "not-a-dict"})

        assert [e.code for e in errors] == ["invalid_parameter_schema"]


class TestTypes:
    def test_number_accepts_int_and_float(self) -> None:
        schema = {"scale": {"type": "number", "minimum": 0, "maximum": 10}}

        assert validate_params({"scale": 3}, schema) == []
        assert validate_params({"scale": 3.5}, schema) == []

    def test_string_type_is_enforced(self) -> None:
        schema = {"label": {"type": "string"}}

        assert validate_params({"label": "ok"}, schema) == []
        assert [e.code for e in validate_params({"label": 7}, schema)] == ["invalid_type"]

    def test_boolean_type_accepts_only_bool(self) -> None:
        schema = {"strict": {"type": "boolean"}}

        assert validate_params({"strict": False}, schema) == []
        assert [e.code for e in validate_params({"strict": 1}, schema)] == ["invalid_type"]

    def test_error_serializes_for_the_api_envelope(self) -> None:
        errors = validate_params({"records": -1}, CRASH_SCHEMA)

        assert errors[0].as_dict() == {
            "param": "records",
            "code": "below_minimum",
            "message": "'records' must be >= 1000, got -1",
        }
