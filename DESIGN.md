# Design

## Goal

Remove submodule-based dependencies and make `pywowlib` self-contained inside this repository.

## Decisions

### 1. Remove MPQ / StormLib

- Drop support for WoW clients older than `WOD`.
- Remove `StormLib` and all `MPQ`-specific build/runtime paths.
- Keep only the `CASC`-based asset path.

### 2. Replace `pyCASCLib` with `pycasc`

- Use vendored `pycasc` under `archives/pycasc`.
- Stop depending on `archives/casc` as a submodule.
- Refactor `archives/wow_filesystem.py` to call `pycasc` directly instead of the old `pyCASCLib` API.

### 3. Make `wdbx` self-contained

- Remove the external `wdbx/dbd` submodule dependency.
- Keep the parser and wrapper inside `wdbx`.
- Move DBD definition data into repository-managed assets.
- `DBDefinition` should load definitions only from local repository sources.

## Target Structure

- `archives/wow_filesystem.py`
  - CASC-only code path
  - no `MPQFile` import
  - no `FileOpenFlags` compatibility layer from old `pyCASCLib`
- `archives/pycasc/`
  - vendored runtime implementation
- `archives/mpq/`
  - removed
- `archives/casc/`
  - removed
- `wdbx/`
  - parser, wrapper, and local definition source only
- `.gitmodules`
  - removed or empty

## Migration Plan

1. Remove `MPQ` runtime and build integration.
2. Switch CASC access from `pyCASCLib` to vendored `pycasc`.
3. Replace `wdbx/dbd` external source with repository-local definition data.
4. Remove submodule metadata and dead paths.
5. Update docs to state `WOD+` support only.

## `wdbx` Design Rule

- Runtime behavior must not require cloning `WoWDBDefs`.
- Definitions may be stored as vendored `.dbd` files, built-in Python tables, or both.
- The repository is the only required source of truth at runtime.

## Non-Goals

- Preserve pre-`WOD` client support.
- Keep API compatibility with `StormLib` / `MPQ`.
- Keep submodule-based dependency management.

## Done When

- Fresh clone works without `git submodule update --init --recursive`.
- Asset reading uses only `pycasc` for supported clients.
- `wdbx` resolves DB definitions without external repositories.
