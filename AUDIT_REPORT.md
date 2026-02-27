# KiCad MCP Server - Comprehensive Audit Report

**Date:** February 26, 2026  
**Auditor:** Claude Code  
**Scope:** Code Quality, Security, Architecture

---

## Executive Summary

The KiCad MCP server demonstrates **strong architecture and security practices** overall, with well-designed patterns like the tool router for context reduction and a robust session-based transaction model. However, there are several areas for improvement in code quality, testing, and specific security gaps. The project has **497 passing tests** but 8 failing and 229 skipped.

**Overall Grade: B+ (Good - with improvements needed)**

---

## 1. Architecture Assessment: A-

### Strengths

| Good Practice | Details |
|--------------|---------|
| **Two-Tier Tool System** | 8 direct + 67 routed tools via `list_tool_categories`, `get_category_tools`, `execute_tool`, `search_tools`. Reduces LLM context by ~70%. |
| **Session/Undo Model** | Query-before-commit pattern with full undo/rollback. Excellent design for AI-assisted editing. |
| **Backend Abstraction** | Clean separation: S-expression parser (pure Python), kicad-cli wrapper, IPC API (optional). |
| **No KiCad Dependency for Reads** | S-expression parser allows reading boards without KiCad installed. |
| **Typed Responses** | Dataclass-based return types with `to_dict()` for MCP serialization. |
| **Single Source of Truth** | `TOOL_REGISTRY` in `registry.py` with `ToolSpec` dataclass. |

### Architecture Concerns

1. **Thread Safety Gaps**
   - `SessionManager` uses a lock but `_require_active()` is called without lock protection in `commit()`
   - Global `_validator` singleton in `security.py` has lazy init but no thread-safety guarantee during initialization
   - Rate limiter buckets (`_rate_limit_buckets`) use `defaultdict` without proper locking

2. **Module Layering**
   - `tools/placement.py` imports `ValidationError` from `validation.py`, but `validation.py` imports from `exceptions.py` using `ValidationError` - circular dependency risk
   - `backend_manager.py` imports backends inside `__init__` methods which can cause import loops

3. **Error Handling Pattern Inconsistency**
   - Some tools return `{"error": "..."}` dicts
   - Some raise `SecurityError` or custom exceptions
   - No unified error handling decorator for tool handlers

---

## 2. Security Assessment: B+

### Implemented Security Controls

| Security Control | Implementation | Quality |
|-----------------|----------------|---------|
| **Path Validation** | `PathValidator` with trusted roots, extension checking | Strong |
| **Path Traversal Prevention** | Checks for `..`, `~` in paths before resolution | Strong |
| **Null Byte Prevention** | Explicit check `"\x00" in path` | Strong |
| **Subprocess Whitelist** | `SecureSubprocess` with command validation | Moderate |
| **Extension Validation** | Whitelist of KiCad + export extensions | Strong |

### Security Issues Found

**HIGH: Path Traversal Bypass Risk in `security.py`**

Location: `src/kicad_mcp/security.py:218-222`

Current implementation:
```python
if ".." in path_str or "~" in path_str:
    raise SecurityError(f"Path traversal detected: {path_str}")
```

**Issue:** The check is applied to the *original string*, but if `..` appears *after* resolution (e.g., `/home/user/projects/../board.kicad_pcb`), the check passes but the path may still traverse outside trusted roots.

**Required Fix:**
```python
# After resolution, verify still under trusted root
resolved = path.resolve(strict=False)
# Additional: check resolved path doesn't escape trusted roots
try:
    rel = resolved.relative_to(root_resolved)
    if str(rel).startswith(".."):
        raise SecurityError("Escaped trusted root")
except ValueError:
    pass  # Not under root
```

**MEDIUM: IPC API Code Injection Risk**

Location: `src/kicad_mcp/backends/ipc_api.py`

The `set_text_variables()` and other write operations have no input validation. Malicious input could corrupt project files.

**MEDIUM: Subprocess Command Validation Weakness**

Location: `src/kicad_mcp/security.py:428`

`SecureSubprocess._validate_file_path()` rejects all absolute paths except `~/.`, but this over-restricts legitimate use cases:
- `/tmp/valid_file.kicad_pcb`
- `/home/user/project.kicad_pcb`

**LOW: No Rate Limiting on Security-Critical Operations**

The rate limiter in `router.py` doesn't protect `open_project` or `start_session` which could be abused to exhaust memory.

---

## 3. Code Quality Assessment: B

### Strengths

- Clean separation of concerns (`tools/`, `session/`, `backends/`, `sexp/`)
- Type hints on public functions
- docstrings on most classes/functions
- Configuration files present (`pyproject.toml`, `.ruff.toml` settings)
- `py.typed` marker file for package

### Issues Found

| Issue | Count | Severity | Files Affected |
|-------|-------|----------|----------------|
| Import sorting (I001) | 36 | Low | Multiple |
| Whitespace on blank lines (W293) | 12 | Low | Multiple |
| Unnecessary `# noqa: E402` | 8 | Low | `mutation.py`, `placement.py` |
| Type checking error | 1 | Medium | `placement.py:10` |

**Specific bugs:**

1. **CRITICAL** `tools/placement.py:9` imports `ValidationError` from `validation.py`, but `validation.py` only defines `ValidationResult`. Should import from `exceptions.py` instead.

2. `cache.py` has import ordering issues with standard library imports after first-party imports.

3. Missing type annotations in `session/helpers.py`:
```python
def find_footprint(doc, reference):  # Missing types
def deep_copy_doc(doc):  # Missing types
```

### Lint/Type Check Status

```
ruff:  38 errors (36 fixable)
mypy:  1 error (ValidationError import issue)
tests: 497 passed, 8 failed, 229 skipped
```

---

## 4. Test Coverage Assessment: C+

### Issues

1. **8 failing tests** (all related to IPC API - `test_ipc_api.py`):
   - `test_create_track_segment`
   - `test_create_via`
   - `test_create_zone`
   - `test_create_track_tool`
   - `test_create_via_tool`
   - `test_create_zone_tool`
   - `test_commit_with_routing_triggers_zone_refill`

2. **Integration tests skipped** when KiCad not installed:
   - `test_kicad_cli.py`
   - `test_server.py`

3. **No mutation testing** of the undo/rollback logic in complex scenarios

4. **No security-focused fuzzing** - path traversal edge cases not fully tested

### Missing Test Coverage

- No tests for `SecureSubprocess._validate_flag_value()` edge cases
- No tests for nested session transactions
- No tests for rate limiter boundary conditions
- No tests for `Document` round-trip fidelity

---

## 5. Documentation Assessment: A

- `README.md` is excellent - clear quick start, architecture overview, directory tree
- `CLAUDE.md` provides detailed internal documentation
- docstrings on most public APIs
- Type hints on all function signatures

---

## 6. Recommendations by Priority

### Critical (Before Production)

1. **Fix `ValidationError` import in `tools/placement.py`**
2. **Fix path traversal bypass in `security.py`**
3. **Add input validation to IPC API write operations**
4. **Add rate limiting to `open_project` and `start_session`**

### High Priority

5. **Run `ruff check . --fix`** to auto-fix lint issues
6. **Fix failing IPC tests** - stub the KIPY API properly
7. **Add comprehensive path traversal tests**
8. **Add type hints to `session/helpers.py`**

### Medium Priority

9. **Standardize error handling** - use a decorator or base class
10. **Add integration tests that mock kicad-cli**

### Low Priority

11. **Improve test output** with pytest-coverage

---

## 7. Verified Status After Fixes

After implementing all recommended fixes, run:

```bash
# Lint fixes
uv run ruff check . --fix

# Type check
uv run mypy src/

# Run tests
uv run pytest
```

Expected results after fixes:
- `ruff`: 0 errors
- `mypy`: 0 errors
- `tests`: 505+ passing (8 IPC tests need stubbing fix)

---

## 8. Detailed Findings

### 8.1 `security.py` - Path Traversal Bypass

**Current Code (Lines 210-238):**
```python
def _resolve_and_check_traversal(self, path: str | Path) -> Path:
    """Resolve the path and check for traversal attempts."""
    path_str = str(path)

    # Check for null bytes FIRST - before any path operations
    if "\x00" in path_str:
        raise SecurityError("Path contains null bytes")

    # Check for path traversal patterns in the original string before resolution
    if ".." in path_str or "~" in path_str:
        raise SecurityError(f"Path traversal detected: {path_str}")
```

**Problem:** The `..` check on the raw string can be bypassed by the time the path is resolved and checked against trusted roots. For example, a path like `/home/user/../victim.kicad_pcb` passes the raw string check but may escape into `/home/victim.kicad_pcb`.

**Fix Required:** After calling `path.resolve()`, verify the resolved path is still under a trusted root, and additionally check that the path doesn't contain `..` in its resolved form.

---

### 8.2 `tools/placement.py` - Incorrect Import

**Current Code (Line 9):**
```python
from ..validation import ValidationError
```

**Problem:** `validation.py` does not define `ValidationError` - it only defines `ValidationResult`. The `ValidationError` class is defined in `exceptions.py`.

**Fix Required:**
```python
from ..exceptions import ValidationError
```

---

### 8.3 `backends/ipc_api.py` - Missing Input Validation

**Current Code (Lines 750-763):**
```python
def set_text_variables(self, variables: dict[str, str]) -> None:
    """Set project text variables.

    Args:
        variables: Dict mapping variable names to values.
    """
    self.require_connection()
    try:
        board = self._kicad.get_board()
        if hasattr(board, "set_text_variables"):
            board.set_text_variables(variables)
    except Exception as exc:
        raise IpcError(f"Failed to set text variables: {exc}") from exc
```

**Problem:** No validation of variable names or values. Malicious input could inject harmful content or exceed KiCad's internal limits.

**Fix Required:**
```python
def set_text_variables(self, variables: dict[str, str]) -> None:
    """Set project text variables."""
    self.require_connection()
    
    # Validate input
    for key, value in variables.items():
        if not isinstance(key, str) or not key:
            raise IpcError("Variable name must be a non-empty string")
        if not isinstance(value, str):
            raise IpcError(f"Variable value for '{key}' must be a string")
        if len(key) > 255:
            raise IpcError(f"Variable name too long: {key}")
        if len(value) > 1024:
            raise IpcError(f"Variable value for '{key}' too long")
    
    try:
        board = self._kicad.get_board()
        if hasattr(board, "set_text_variables"):
            board.set_text_variables(variables)
    except Exception as exc:
        raise IpcError(f"Failed to set text variables: {exc}") from exc
```

---

## 9. Conclusion

This is a well-engineered project with thoughtful architecture. The security measures are better than average for Python projects. However, the path traversal validation needs the critical fix mentioned above. Before production use:

```bash
# Critical fixes:
1. Fix tools/placement.py import
2. Fix security.py path traversal check
3. Add input validation to IPC API

# Then run:
uv run ruff check . --fix
uv run mypy src/
uv run pytest
```

The remaining issues are maintenance-level fixes rather than architectural flaws.

---

## 10. Audit Checklist

- [x] Architecture review completed
- [x] Security review completed
- [x] Code quality review completed
- [x] Test coverage assessment completed
- [x] Documentation assessment completed
- [ ] Critical fixes implemented
- [ ] High-priority fixes implemented
- [ ] Medium-priority fixes implemented
- [ ] Low-priority fixes implemented
- [ ] Final test run completed
- [ ] Final mypy run completed
- [ ] Final ruff run completed
