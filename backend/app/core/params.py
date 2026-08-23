"""Validation of caller-supplied run parameters against a workflow's params_schema.

This is the trust boundary for the public trigger endpoint. A workflow's
`params_schema` is the *complete* list of knobs a caller may turn; anything
else is rejected rather than ignored, so a caller always knows whether the
run they got is the run they asked for.

Pure and framework-independent by design: the API layer turns the returned
errors into HTTP 422, and the test suite exercises the rules directly
without a database or a web server.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# JSON Schema-ish type names accepted in a params_schema entry, mapped to
# the Python types we will accept for a supplied value.
_TYPE_MAP: dict[str, tuple[type, ...]] = {
    "integer": (int,),
    "number": (int, float),
    "string": (str,),
    "boolean": (bool,),
}


@dataclass(frozen=True)
class ParamError:
    """One rejected parameter, shaped for the API error envelope's `details`."""

    param: str
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"param": self.param, "code": self.code, "message": self.message}


def validate_params(
    params: dict[str, Any], params_schema: dict[str, Any]
) -> list[ParamError]:
    """Check `params` against `params_schema`. Returns every problem found.

    Rules, in order of evaluation per key:

    1. **Undeclared parameters are rejected.** A workflow with no
       `params_schema` therefore accepts no parameters at all.
    2. **Type must match** the declared `type`, when one is declared.
       `bool` is explicitly excluded from the numeric types: Python treats
       `True` as `1`, which would let `{"records": true}` slip past an
       integer bound check.
    3. **`minimum` / `maximum` are inclusive bounds**, applied to numeric
       values only.

    An empty result means the parameters are safe to apply.
    """
    errors: list[ParamError] = []

    for key, value in params.items():
        spec = params_schema.get(key)
        if spec is None:
            errors.append(
                ParamError(
                    param=key,
                    code="unknown_parameter",
                    message=(
                        f"'{key}' is not a declared parameter of this workflow"
                        if params_schema
                        else f"this workflow accepts no parameters, but '{key}' was supplied"
                    ),
                )
            )
            continue

        if not isinstance(spec, dict):
            # A malformed schema entry is a definition bug, not a caller
            # bug. Refuse the value rather than guessing what it meant.
            errors.append(
                ParamError(
                    param=key,
                    code="invalid_parameter_schema",
                    message=f"the schema for '{key}' is malformed",
                )
            )
            continue

        declared_type = spec.get("type")
        if declared_type in _TYPE_MAP:
            allowed = _TYPE_MAP[declared_type]
            # bool is a subclass of int; only accept it where explicitly asked for.
            is_bool = isinstance(value, bool)
            type_ok = isinstance(value, allowed) and (
                declared_type == "boolean" if is_bool else True
            )
            if not type_ok:
                errors.append(
                    ParamError(
                        param=key,
                        code="invalid_type",
                        message=(
                            f"'{key}' must be of type {declared_type}, "
                            f"got {type(value).__name__}"
                        ),
                    )
                )
                continue

        if isinstance(value, int | float) and not isinstance(value, bool):
            minimum = spec.get("minimum")
            maximum = spec.get("maximum")
            if isinstance(minimum, int | float) and value < minimum:
                errors.append(
                    ParamError(
                        param=key,
                        code="below_minimum",
                        message=f"'{key}' must be >= {minimum}, got {value}",
                    )
                )
            if isinstance(maximum, int | float) and value > maximum:
                errors.append(
                    ParamError(
                        param=key,
                        code="above_maximum",
                        message=f"'{key}' must be <= {maximum}, got {value}",
                    )
                )

    return errors
