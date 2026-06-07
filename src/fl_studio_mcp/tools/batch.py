"""Strict batch tool for v1.2 operation-registry reads and grouped writes."""

from __future__ import annotations

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from .. import operations as operation_registry
from .. import safety
from ..connection import FLCommandFailed, FLNotRunning, FLTimeout, get_bridge

MAX_BATCH_OPERATIONS = 50
_RAW_OR_SCRIPT_KEYS = {
    "code",
    "command",
    "protocol",
    "pyscript",
    "raw",
    "raw_command",
    "script",
    "script_text",
}


def _read_only_whitelist() -> frozenset[tuple[str, str]]:
    return frozenset(
        (spec.domain, spec.action)
        for spec in operation_registry.list_operations()
        if (
            spec.batch_eligible
            and spec.batch_category == "read_only"
            and spec.safety_class == "read-only"
        )
    )


def _persistent_write_whitelist() -> frozenset[tuple[str, str]]:
    return frozenset(
        (spec.domain, spec.action)
        for spec in operation_registry.list_operations()
        if (
            spec.batch_eligible
            and spec.batch_category == "persistent_write"
            and spec.safety_class == "write-safe"
        )
    )


READ_ONLY_BATCH_WHITELIST = _read_only_whitelist()
PERSISTENT_WRITE_BATCH_WHITELIST = _persistent_write_whitelist()


def register(mcp: FastMCP) -> None:
    """Attach the strict batch tool to the given FastMCP instance."""

    @mcp.tool(
        annotations={
            "title": "Batch FL operations",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
            "safetyClass": "write-safe",
        },
    )
    def fl_batch(
        operations: Annotated[
            list[dict],
            Field(
                description=(
                    "Read-only operations or persistent writes, max 50. Each item must be "
                    "{domain: str, action: str, params?: object}. Raw protocol "
                    "commands and script/code text are rejected. Persistent writes must "
                    "not be mixed with reads, transient controls, external writes, or "
                    "Piano Roll generated-script actions."
                )
            ),
        ],
        continue_on_error: Annotated[
            bool,
            Field(
                description=(
                    "When true, keep executing later read-only operations after a "
                    "runtime FL read failure. Validation and whitelist failures "
                    "reject the whole batch before execution. Persistent write batches "
                    "must leave this false."
                )
            ),
        ] = False,
    ) -> dict:
        """Execute a strict batch of operation-registry actions.

        Every operation validates before any bridge call is made. Read-only
        batches execute registry-built protocol reads directly and may use
        ``continue_on_error`` for runtime read failures. Persistent write
        batches must be homogeneous, reject ``continue_on_error``, and route
        through ``safety.safe_write_group`` as one named rollback unit. Transient
        runtime controls, external writes, raw protocol commands, generated
        script/code text, and Piano Roll generated-script actions are rejected.

        Safety: Write-Safe with Rollback for persistent writes; Read-Only for
        read batches.
        """
        prepared = _prepare_batch(operations)
        batch_category = _prepared_batch_category(prepared)

        if batch_category == "persistent_write":
            if continue_on_error:
                raise ValueError("continue_on_error is only allowed for read-only batches")
            bridge = get_bridge()
            return _execute_persistent_write_batch(bridge, prepared)

        bridge = get_bridge()
        results = []
        for index, item in enumerate(prepared):
            try:
                data = _bridge_call(bridge, item.command.command, item.command.params)
                results.append(
                    {
                        "index": index,
                        "ok": True,
                        "domain": item.domain,
                        "action": item.action,
                        "result": data,
                    }
                )
            except Exception as exc:
                row = {
                    "index": index,
                    "ok": False,
                    "domain": item.domain,
                    "action": item.action,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                results.append(row)
                if not continue_on_error:
                    return {
                        "ok": False,
                        "count": len(prepared),
                        "completed": len(results) - 1,
                        "failed_index": index,
                        "results": results,
                    }

        return {
            "ok": all(row["ok"] for row in results),
            "count": len(prepared),
            "completed": sum(1 for row in results if row["ok"]),
            "results": results,
        }


def _prepare_batch(raw_operations: Any) -> list[operation_registry.PreparedOperation]:
    if not isinstance(raw_operations, list):
        raise ValueError("operations must be a list")
    if len(raw_operations) > MAX_BATCH_OPERATIONS:
        raise ValueError(f"operations length must be <= {MAX_BATCH_OPERATIONS}")

    prepared = []
    for index, raw in enumerate(raw_operations):
        if not isinstance(raw, dict):
            raise ValueError(f"operation {index} must be an object")
        forbidden = sorted(set(raw) & _RAW_OR_SCRIPT_KEYS)
        if forbidden:
            raise ValueError(
                f"operation {index} uses unsupported raw/script field(s): {', '.join(forbidden)}"
            )
        unknown = sorted(set(raw) - {"domain", "action", "params"})
        if unknown:
            raise ValueError(f"operation {index} has unknown field(s): {', '.join(unknown)}")
        domain = raw.get("domain")
        action = raw.get("action")
        if not isinstance(domain, str) or not domain:
            raise ValueError(f"operation {index} domain must be a non-empty string")
        if not isinstance(action, str) or not action:
            raise ValueError(f"operation {index} action must be a non-empty string")
        params = raw.get("params", {})
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise ValueError(f"operation {index} params must be an object")

        try:
            item = operation_registry.prepare_operation(domain, action, params)
        except operation_registry.OperationValidationError as exc:
            raise ValueError(f"operation {index}: {exc}") from exc

        _validate_batch_whitelist(item, index)
        prepared.append(item)
    _reject_mixed_batch(prepared)
    return prepared


def _prepare_read_only_batch(raw_operations: Any) -> list[operation_registry.PreparedOperation]:
    prepared = _prepare_batch(raw_operations)
    if _prepared_batch_category(prepared) != "read_only":
        raise ValueError("batch contains persistent writes; use fl_batch execution instead")
    return prepared


def _validate_batch_whitelist(item: operation_registry.PreparedOperation, index: int) -> None:
    key = (item.domain, item.action)
    if key in READ_ONLY_BATCH_WHITELIST or key in PERSISTENT_WRITE_BATCH_WHITELIST:
        return
    if item.safety_class == "transient":
        raise ValueError(f"operation {index} is transient and is not allowed in fl_batch")
    if item.safety_class == "write-safe":
        raise ValueError(f"operation {index} is not whitelisted for persistent write batching")
    raise ValueError(f"operation {index} is not whitelisted for fl_batch")


def _reject_mixed_batch(prepared: list[operation_registry.PreparedOperation]) -> None:
    categories = {_batch_category(item) for item in prepared}
    if len(categories) > 1:
        raise ValueError(
            "fl_batch cannot mix read-only operations with persistent writes, "
            "transient controls, external writes, or Piano Roll actions"
        )


def _prepared_batch_category(prepared: list[operation_registry.PreparedOperation]) -> str:
    if not prepared:
        return "read_only"
    return _batch_category(prepared[0])


def _batch_category(item: operation_registry.PreparedOperation) -> str:
    if (item.domain, item.action) in READ_ONLY_BATCH_WHITELIST:
        return "read_only"
    if (item.domain, item.action) in PERSISTENT_WRITE_BATCH_WHITELIST:
        return "persistent_write"
    return "excluded"


def _execute_persistent_write_batch(
    bridge, prepared: list[operation_registry.PreparedOperation]
) -> dict:
    writes = [item.safe_write_group_entry() for item in prepared]
    result = safety.safe_write_group(
        bridge,
        tool="fl_batch",
        scope="operation_batch:persistent_write",
        writes=writes,
        rollback_unit="fl_batch_persistent",
    )
    if result.get("dry_run"):
        return {
            **result,
            "count": len(prepared),
            "completed": 0,
            "results": [
                {
                    "index": index,
                    "ok": True,
                    "domain": item.domain,
                    "action": item.action,
                    "planned": item.command.as_dict(),
                }
                for index, item in enumerate(prepared)
            ],
        }
    return {
        **result,
        "count": len(prepared),
        "completed": len(prepared),
        "results": [
            {
                "index": index,
                "ok": True,
                "domain": item.domain,
                "action": item.action,
                "before": result["before"][index],
                "after": result["after"][index],
            }
            for index, item in enumerate(prepared)
        ],
    }


def _bridge_call(bridge, command: str, params: dict | None = None) -> dict:
    """Call the bridge and translate FL errors into consistent Python exceptions."""
    try:
        return bridge.call(command, params or {})
    except FLNotRunning as e:
        raise RuntimeError(str(e)) from e
    except FLTimeout as e:
        raise RuntimeError(
            f"{e}. Try fl_transport(action='ping') to confirm the controller is alive."
        ) from e
    except FLCommandFailed as e:
        raise RuntimeError(f"FL Studio rejected the command: {e}") from e
