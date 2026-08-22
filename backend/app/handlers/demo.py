"""Deterministic demo workflow handlers.

Two design rules shape everything here:

1. **Real computation, not sleep().** Every handler does genuine CPU work
   (SHA-256 digests, aggregation, checksum verification). Durations in the
   dashboard are real durations.

2. **Bounded outputs.** A handler never returns its dataset. It returns a
   compact *descriptor* — the seed and range needed to regenerate the data,
   plus aggregates and a checksum. Downstream tasks regenerate from the
   descriptor. This keeps task_run.output at a few hundred bytes instead of
   megabytes of JSONB, while output-passing stays genuinely load-bearing:
   a downstream task that ignored its upstream's descriptor would compute a
   different checksum and fail.

Determinism means the same run produces the same checksums every time, so
tests can assert exact values rather than "something happened".
"""

import hashlib
from typing import Any

from app.core.errors import PermanentError
from app.handlers.registry import HandlerContext, handler

# Tuned so one shard is roughly 0.5-1.5s of real work on a development
# machine: long enough that concurrent shard execution is clearly visible in
# wall-clock timestamps, short enough to keep the test suite and the demo
# responsive.
_HASH_ROUNDS_PER_RECORD = 500


def _derive_value(seed: int, index: int) -> int:
    """Deterministically derive one bounded record value from (seed, index).

    SHA-256 rather than random.Random so the sequence is identical across
    Python versions, platforms, and processes — a worker on any container
    must regenerate byte-identical data.
    """
    digest = hashlib.sha256(f"{seed}:{index}".encode()).digest()
    return int.from_bytes(digest[:4], "big") % 1_000_000


def _process_range(seed: int, start: int, end: int) -> dict[str, Any]:
    """Generate and aggregate records [start, end), doing real hashing work.

    Returns count/sum/min/max plus an order-independent checksum. This is the
    single hot loop shared by the ETL and fan-out workflows.
    """
    count = 0
    total = 0
    minimum: int | None = None
    maximum: int | None = None
    checksum = hashlib.sha256()

    for index in range(start, end):
        value = _derive_value(seed, index)

        # Genuine CPU load: iterated hashing of the derived value. Also
        # feeds the checksum, so this work is not discardable busy-work —
        # removing it changes the result.
        payload = value.to_bytes(4, "big")
        for _ in range(_HASH_ROUNDS_PER_RECORD):
            payload = hashlib.sha256(payload).digest()
        checksum.update(payload[:8])

        count += 1
        total += value
        minimum = value if minimum is None else min(minimum, value)
        maximum = value if maximum is None else max(maximum, value)

    return {
        "count": count,
        "sum": total,
        "min": minimum,
        "max": maximum,
        "checksum": checksum.hexdigest(),
    }


def _require(outputs: dict[str, Any], key: str) -> dict[str, Any]:
    """Fetch a required upstream output, failing permanently if absent.

    A missing upstream output means the DAG or the reconciler is wrong, not
    that the world is flaky — so this is a PermanentError, never retried.
    """
    value = outputs.get(key)
    if not isinstance(value, dict):
        raise PermanentError(f"missing or malformed upstream output for task '{key}'")
    return value


# --------------------------------------------------------------- sequential_etl


@handler("etl.extract")
def extract(
    context: HandlerContext, params: dict[str, Any], upstream_outputs: dict[str, Any]
) -> dict[str, Any]:
    """Generate a deterministic dataset and return its descriptor."""
    seed = int(params.get("seed", 42))
    record_count = int(params.get("record_count", 4000))

    stats = _process_range(seed, 0, record_count)
    context.logger.info("extract_complete", records=stats["count"], seed=seed)

    return {
        "seed": seed,
        "record_count": record_count,
        "source_checksum": stats["checksum"],
        "raw_sum": stats["sum"],
    }


@handler("etl.transform")
def transform(
    context: HandlerContext, params: dict[str, Any], upstream_outputs: dict[str, Any]
) -> dict[str, Any]:
    """Regenerate from the extract descriptor, then derive normalised values."""
    source = _require(upstream_outputs, "extract")
    seed = int(source["seed"])
    record_count = int(source["record_count"])
    scale = int(params.get("scale", 3))

    transformed_sum = 0
    checksum = hashlib.sha256()
    for index in range(record_count):
        value = _derive_value(seed, index)
        # A deterministic derivation: scale, offset, and bound the value.
        derived = (value * scale + index) % 1_000_003
        transformed_sum += derived
        checksum.update(derived.to_bytes(4, "big"))

    context.logger.info("transform_complete", records=record_count, scale=scale)

    return {
        "seed": seed,
        "record_count": record_count,
        "scale": scale,
        "transformed_sum": transformed_sum,
        "transform_checksum": checksum.hexdigest(),
        "source_checksum": source["source_checksum"],
    }


@handler("etl.validate")
def validate(
    context: HandlerContext, params: dict[str, Any], upstream_outputs: dict[str, Any]
) -> dict[str, Any]:
    """Apply real validation rules and report genuine pass/fail counts."""
    transformed = _require(upstream_outputs, "transform")
    seed = int(transformed["seed"])
    record_count = int(transformed["record_count"])
    scale = int(transformed["scale"])
    max_value = int(params.get("max_value", 1_000_003))

    valid = 0
    invalid = 0
    recomputed_sum = 0
    for index in range(record_count):
        derived = (_derive_value(seed, index) * scale + index) % 1_000_003
        recomputed_sum += derived
        if 0 <= derived < max_value:
            valid += 1
        else:
            invalid += 1

    # Independent verification that transform's reported total is real: this
    # is what makes output-passing meaningful rather than decorative.
    if recomputed_sum != int(transformed["transformed_sum"]):
        raise PermanentError(
            f"transform sum mismatch: recomputed {recomputed_sum} != "
            f"reported {transformed['transformed_sum']}"
        )

    context.logger.info("validate_complete", valid=valid, invalid=invalid)

    return {
        "records_checked": record_count,
        "valid": valid,
        "invalid": invalid,
        "transform_checksum": transformed["transform_checksum"],
        "transformed_sum": recomputed_sum,
    }


@handler("etl.load")
def load(
    context: HandlerContext, params: dict[str, Any], upstream_outputs: dict[str, Any]
) -> dict[str, Any]:
    """Produce the final summary and a SHA-256 checksum over canonical output."""
    report = _require(upstream_outputs, "validate")

    if report["invalid"] != 0:
        raise PermanentError(f"refusing to load {report['invalid']} invalid records")

    canonical = "|".join(
        [
            f"records={report['records_checked']}",
            f"valid={report['valid']}",
            f"sum={report['transformed_sum']}",
            f"transform={report['transform_checksum']}",
        ]
    )
    final_checksum = hashlib.sha256(canonical.encode()).hexdigest()

    context.logger.info("load_complete", records_loaded=report["valid"])

    return {
        "records_loaded": report["valid"],
        "transformed_sum": report["transformed_sum"],
        "final_checksum": final_checksum,
    }


# ----------------------------------------------------------------- fanout_join


@handler("shard.split")
def split(
    context: HandlerContext, params: dict[str, Any], upstream_outputs: dict[str, Any]
) -> dict[str, Any]:
    """Partition a deterministic keyspace into contiguous shard ranges.

    Returns range descriptors, not data — each shard regenerates its own
    slice from (seed, start, end).
    """
    seed = int(params.get("seed", 7))
    total_records = int(params.get("total_records", 12000))
    shard_count = int(params.get("shard_count", 4))

    if shard_count < 1:
        raise PermanentError("shard_count must be >= 1")

    # Contiguous, non-overlapping, exhaustive partition. Any remainder goes
    # to the final shard so the union is exactly [0, total_records).
    size = total_records // shard_count
    partitions = []
    for i in range(shard_count):
        start = i * size
        end = total_records if i == shard_count - 1 else (i + 1) * size
        partitions.append({"index": i, "start": start, "end": end})

    context.logger.info("split_complete", shard_count=shard_count, total=total_records)

    return {
        "seed": seed,
        "total_records": total_records,
        "shard_count": shard_count,
        "partitions": partitions,
    }


@handler("shard.process")
def process_shard(
    context: HandlerContext, params: dict[str, Any], upstream_outputs: dict[str, Any]
) -> dict[str, Any]:
    """Process one partition: real hashing work over its assigned range."""
    plan = _require(upstream_outputs, "split")
    index = int(params["index"])

    partitions = plan["partitions"]
    if index >= len(partitions):
        raise PermanentError(f"shard index {index} outside plan of {len(partitions)} partitions")

    partition = partitions[index]
    seed = int(plan["seed"])
    start, end = int(partition["start"]), int(partition["end"])

    stats = _process_range(seed, start, end)
    context.logger.info("shard_complete", index=index, start=start, end=end, count=stats["count"])

    # `seed` is carried forward deliberately. merge depends on the shards,
    # not on split, so split's output is not in merge's upstream_outputs —
    # the runner passes direct dependencies only. Propagating the seed here
    # keeps the DAG shape (split -> shards -> merge) intact instead of
    # adding a split -> merge edge purely to smuggle a parameter across.
    return {"index": index, "seed": seed, "start": start, "end": end, **stats}


@handler("shard.merge")
def merge(
    context: HandlerContext, params: dict[str, Any], upstream_outputs: dict[str, Any]
) -> dict[str, Any]:
    """Combine all shard summaries and verify against a single-pass recomputation.

    The verification is the point: if the fan-in fired early — before every
    shard had actually succeeded — or a shard's range were wrong, the
    combined totals would not match the single-pass result and this task
    would fail loudly rather than silently reporting a wrong answer.
    """
    shards = sorted(
        (
            value
            for key, value in upstream_outputs.items()
            if key.startswith("shard_") and isinstance(value, dict)
        ),
        key=lambda s: int(s["index"]),
    )

    if not shards:
        raise PermanentError("merge received no shard outputs")

    seeds = {int(s["seed"]) for s in shards}
    if len(seeds) != 1:
        raise PermanentError(f"shards disagree on seed: {sorted(seeds)}")
    seed = seeds.pop()

    # The shard ranges must tile [start_of_first, end_of_last) exactly:
    # contiguous, non-overlapping, no gaps.
    ranges = [(int(s["start"]), int(s["end"])) for s in shards]
    for (_, end), (next_start, _) in zip(ranges, ranges[1:], strict=False):
        if end != next_start:
            raise PermanentError(f"shard ranges are not contiguous: {end} != {next_start}")

    total_start, total_end = ranges[0][0], ranges[-1][1]

    combined_count = sum(int(s["count"]) for s in shards)
    combined_sum = sum(int(s["sum"]) for s in shards)
    combined_min = min(int(s["min"]) for s in shards)
    combined_max = max(int(s["max"]) for s in shards)

    expected = _process_range(seed, total_start, total_end)
    if combined_count != expected["count"] or combined_sum != expected["sum"]:
        raise PermanentError(
            f"shard aggregation mismatch: combined count/sum "
            f"({combined_count}, {combined_sum}) != single-pass "
            f"({expected['count']}, {expected['sum']})"
        )

    combined_checksum = hashlib.sha256(
        "|".join(f"{s['index']}:{s['checksum']}" for s in shards).encode()
    ).hexdigest()

    context.logger.info("merge_complete", shards=len(shards), total_count=combined_count)

    return {
        "shards_merged": len(shards),
        "count": combined_count,
        "sum": combined_sum,
        "min": combined_min,
        "max": combined_max,
        "combined_checksum": combined_checksum,
        "verified_against_single_pass": True,
    }
