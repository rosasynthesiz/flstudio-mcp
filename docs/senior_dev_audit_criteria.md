# Senior Developer Audit Criteria: FL Studio MCP

This repository is not intended to merely function. It is intended to demonstrate the level of engineering discipline expected from experienced software engineers working with unsafe host APIs, AI-generated code, and difficult-to-test environments.

A Staff or Principal Engineer therefore evaluates the project primarily through the following lens:

> **Is the system robust, understandable, testable, and resilient against both human and AI-generated mistakes?**

---

## 1. Architecture & Responsibility Boundaries

**Goal:** No business logic inside the FL Studio sandbox.

**Expected State:**

* The FL Studio controller acts as a **Thin Controller**.
* It only reads and writes raw host data.
* Planning, orchestration, diagnostics, validation, and decision-making occur exclusively on the MCP server.
* AST-based audits prevent sandbox escape attempts such as `import os`, `open()`, network access, or other unauthorized side effects.

**Definition of Done:**

* No orchestration logic exists inside the controller.
* No complex search, planning, or diagnostic functionality runs in the FL Studio sandbox.
* `audit_anti_vibe.py` blocks dangerous imports and prohibited APIs.

---

## 2. State Mutation & Safety

**Goal:** No write operation without a guaranteed recovery path.

**Expected State:**

* Every mutating operation follows the pattern:

```text
snapshot -> write -> readback -> validate -> rollback on failure
```

* All write operations pass through `safety.safe_write`.
* Multi-step changes use `safe_write_group`.
* AST-based audits detect direct FL API write operations that bypass the safety layer.

**Definition of Done:**

* No blind writes.
* Every tool-level mutation is rollback-capable.
* `audit_tool_safety.py --fail-on-gaps` runs in CI and blocks unsafe changes.

---

## 3. Code Hygiene & Anti-Vibe Coding

**Goal:** The codebase must never resemble trial-and-error development or AI-generated clutter.

**Expected State:**

* Strict Ruff configuration and enforcement.
* No unused imports, variables, or debugging artifacts.
* No comments such as `TODO: fix later`, `HACK`, `quick fix`, or `print("here")`.
* API boundaries are strongly typed.
* Pydantic models define explicit contracts.

**Definition of Done:**

* CI passes with zero linting violations.
* `from __future__ import annotations` is the default standard.
* Pre-commit hooks block common vibe-coding patterns.
* All public tool interfaces are fully typed.

---

## 4. Testability Without FL Studio

**Goal:** The project must remain verifiable even without a live FL Studio instance.

**Expected State:**

* A mock bridge simulates communication with FL Studio.
* Protocol behavior, timeouts, and error mapping can be tested independently.
* Static meta-tests replace live end-to-end testing where FL Studio cannot be integrated into CI.
* Tool registration and public APIs are locked through baselines.

**Definition of Done:**

* `tests/test_bridge_mock.py` validates bridge behavior and failure scenarios.
* `FLCommandFailed` is consistently generated from host-side failures.
* `check_tool_registration_baseline.py` prevents unnoticed API changes.

---

## 5. Knowledge Management & Agent Discipline

**Goal:** Knowledge must never exist only in a developer’s head or an AI model’s context window.

**Expected State:**

* FL Studio quirks, limitations, and discoveries are documented in `knowledgebase/`.
* `AGENTS.md` defines mandatory rules for both human contributors and AI agents.
* Knowledge entries contain fields such as `confidence_level`, `tested_values`, `source`, and `last_verified`.
* Unverified assumptions cannot be promoted to repository knowledge.

**Definition of Done:**

* New host-specific discoveries are recorded as Markdown or JSON entries.
* `audit_anti_vibe.py` validates knowledge base structure and completeness.
* Undocumented workarounds are rejected.

---

## 6. Protocol & Error Handling

**Goal:** Communication and failures must be explicit, structured, and observable.

**Expected State:**

* The server and FL Studio communicate through a structured JSON-based protocol.
* `protocol.py` defines stable request, response, and error schemas.
* Host-side failures are never silently ignored.
* Errors are translated into explicit exception types such as `FLCommandFailed`.

**Definition of Done:**

* No `except Exception: pass`.
* Errors contain actionable context, tool names, and meaningful messages.
* MCP clients receive clear and actionable failure information.

---

## Senior-Level Assessment

An experienced reviewer should ultimately conclude:

> This project integrates with a proprietary and difficult-to-test host application, yet it does not rely on hope or manual discipline. Safety is enforced through architecture, AST audits, safety layers, pre-commit hooks, and clearly defined API boundaries. Most notably, the repository is designed to be AI-resilient: it systematically rejects vibe coding, treats host knowledge as a first-class asset, and makes state mutations auditable and verifiable.
