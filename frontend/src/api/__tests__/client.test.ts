import { describe, expect, it } from "vitest";
import { ApiError } from "../client";

describe("ApiError", () => {
  it("carries the structured error envelope through to the UI", () => {
    const error = new ApiError("one or more run parameters are invalid", "invalid_parameters", 422, [
      { param: "records", code: "above_maximum", message: "'records' must be <= 200000" },
    ]);

    expect(error.status).toBe(422);
    expect(error.code).toBe("invalid_parameters");
    expect(error.message).toBe("one or more run parameters are invalid");
    expect(error.details).toHaveLength(1);
  });

  it("is a real Error, so it survives throw/catch and instanceof checks", () => {
    const error = new ApiError("too many active runs", "too_many_active_runs", 429);

    expect(error).toBeInstanceOf(Error);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.name).toBe("ApiError");
  });

  it("exposes the codes the public-safety rejections use", () => {
    // These are the four the backend can return to an ordinary visitor;
    // the UI surfaces `message` for each rather than a generic failure.
    const codes = [
      new ApiError("", "invalid_parameters", 422),
      new ApiError("", "workflow_not_publicly_triggerable", 403),
      new ApiError("", "rate_limited", 429),
      new ApiError("", "too_many_active_runs", 429),
    ];

    expect(codes.map((e) => e.status)).toEqual([422, 403, 429, 429]);
  });
});
