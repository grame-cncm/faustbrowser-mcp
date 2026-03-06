#!/usr/bin/env python3
"""Local Faust library documentation lookup helpers for faustbrowser-mcp.

This module ports the reusable lookup logic from the `faustlibraries`
repository's `faust_doc_api.py`, but intentionally keeps only the in-process
Python API needed by this MCP server.

Scope:

- split-layout Faust documentation index only
- lazy loading of detailed module JSON files
- symbol search, lookup, module listing, examples, and goal-oriented explain

This module does not contain a CLI layer. It is meant to be imported directly
by `faust_browser_server.py`.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath


def load_json(path: Path) -> dict[str, object]:
    """Load and decode a JSON document from disk."""

    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def module_doc_relpath_for_source(source_path: str) -> str:
    """Map a `.lib` source path to its split-layout module JSON path."""

    return str(PurePosixPath("modules") / PurePosixPath(source_path).with_suffix(".json"))


def rank_symbol_match(symbol: dict[str, object], query_lower: str) -> int:
    """Score one symbol against a lowercased free-text query."""

    if str(symbol.get("qualifiedName", "")).lower() == query_lower:
        return 120
    if str(symbol.get("name", "")).lower() == query_lower:
        return 110
    if str(symbol.get("id", "")).lower() == query_lower:
        return 105

    score = 0
    haystacks = [
        symbol.get("name", ""),
        symbol.get("qualifiedName", ""),
        symbol.get("summary", ""),
        (symbol.get("source") or {}).get("file", ""),
    ]
    for haystack in haystacks:
        if query_lower in str(haystack).lower():
            score += 20
    return score


def normalize_module_key(module: str) -> str:
    """Normalize a module selector to a lowercase comparable key."""

    return str(module or "").strip().lower()


class FaustDocStore:
    """Access wrapper around the split Faust documentation index layout."""

    def __init__(self, index_path: Path):
        self.index_path = index_path.resolve()
        self.index = load_json(self.index_path)
        if self.index.get("layout") != "split-v1":
            raise ValueError(
                "faustbrowser-mcp expects a split Faust doc index (layout=split-v1). "
                "Generate one with make doc-index-split in faustlibraries."
            )
        self.base_dir = self.index_path.parent
        self._module_cache: dict[str, dict[str, object]] = {}

        libraries = self.index.get("libraries", [])
        self.library_by_path = {
            str(library.get("path", "")): library
            for library in libraries
            if isinstance(library, dict) and library.get("path")
        }

    @classmethod
    def from_candidate(cls, candidate: Path) -> "FaustDocStore":
        """Load a split index from a file or from a directory containing `index.json`."""

        path = candidate.resolve()
        if path.is_dir():
            return cls(path / "index.json")
        return cls(path)

    def compact_symbols(self) -> list[dict[str, object]]:
        """Return the compact top-level symbol list from the split index."""

        return list(self.index.get("symbols", []))

    def _load_module_document(self, relpath: str) -> dict[str, object]:
        """Load one detailed module JSON and cache it in memory."""

        if relpath not in self._module_cache:
            self._module_cache[relpath] = load_json(self.base_dir / relpath)
        return self._module_cache[relpath]

    def get_library(self, module: str) -> dict[str, object] | None:
        """Resolve a module name, path stem, or alias to its library entry."""

        key = normalize_module_key(module)
        for library in self.index.get("libraries", []):
            if not isinstance(library, dict):
                continue
            file_name = str(library.get("file", ""))
            path_name = str(library.get("path", ""))
            file_stem = file_name.lower().removesuffix(".lib")
            path_stem = path_name.lower().removesuffix(".lib")
            aliases = [str(alias).lower() for alias in library.get("aliasHints", [])]
            if key in {file_stem, path_stem} or key in aliases:
                return library
        return None

    def get_library_symbols(
        self, module: str
    ) -> tuple[dict[str, object], list[dict[str, object]]] | tuple[None, list]:
        """Return one library descriptor plus its full symbol entries."""

        library = self.get_library(module)
        if library is None:
            return None, []
        relpath = str(library.get("moduleDoc", ""))
        module_doc = self._load_module_document(relpath)
        return library, list(module_doc.get("symbols", []))

    def get_symbol_by_summary(self, summary_symbol: dict[str, object]) -> dict[str, object]:
        """Expand one compact top-level symbol summary into the full symbol entry."""

        source = summary_symbol.get("source") or {}
        source_path = str(source.get("path", ""))
        library = self.library_by_path.get(source_path)
        if library is not None:
            relpath = str(library.get("moduleDoc", ""))
        else:
            relpath = module_doc_relpath_for_source(source_path)

        module_doc = self._load_module_document(relpath)
        for symbol in module_doc.get("symbols", []):
            if str(symbol.get("id", "")).lower() == str(summary_symbol.get("id", "")).lower():
                return symbol
        raise KeyError(f"Symbol not found in detailed module document: {summary_symbol.get('id')}")

    def find_symbol(self, symbol_input: str) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
        """Find the best symbol match plus alternative compact matches."""

        key = str(symbol_input or "").strip().lower()
        if not key:
            return None, []

        exact_summary = next(
            (
                symbol
                for symbol in self.compact_symbols()
                if str(symbol.get("name", "")).lower() == key
                or str(symbol.get("id", "")).lower() == key
                or str(symbol.get("qualifiedName", "")).lower() == key
            ),
            None,
        )
        if exact_summary is not None:
            return self.get_symbol_by_summary(exact_summary), []

        ranked = [
            {"symbol": symbol, "score": rank_symbol_match(symbol, key)}
            for symbol in self.compact_symbols()
        ]
        ranked = [entry for entry in ranked if entry["score"] > 0]
        ranked.sort(key=lambda entry: entry["score"], reverse=True)
        if not ranked:
            return None, []

        best = self.get_symbol_by_summary(ranked[0]["symbol"])
        alternatives = [entry["symbol"] for entry in ranked[1:6]]
        return best, alternatives


def search_faust_lib(
    store: FaustDocStore, query: str, limit: int = 10, module: str | None = None
) -> dict[str, object]:
    """Search compact symbol summaries by text, optionally restricted to one module."""

    q = str(query or "").strip().lower()
    if not q:
        raise ValueError("Missing query")

    module_key = normalize_module_key(module or "")
    ranked = []
    for symbol in store.compact_symbols():
        if module_key:
            source_file = str((symbol.get("source") or {}).get("file", "")).lower()
            source_path = str((symbol.get("source") or {}).get("path", "")).lower()
            source_mod = source_file.removesuffix(".lib")
            source_path_mod = source_path.removesuffix(".lib")
            qualified = str(symbol.get("qualifiedName", "")).lower()
            if module_key not in {source_mod, source_path_mod} and not qualified.startswith(f"{module_key}."):
                continue
        score = rank_symbol_match(symbol, q)
        if score <= 0:
            continue
        ranked.append({"symbol": symbol, "score": score})

    ranked.sort(key=lambda entry: entry["score"], reverse=True)
    results = []
    for entry in ranked[:limit]:
        symbol = entry["symbol"]
        results.append(
            {
                "id": symbol.get("id"),
                "name": symbol.get("name"),
                "qualifiedName": symbol.get("qualifiedName"),
                "summary": symbol.get("summary"),
                "usage": symbol.get("usage"),
                "source": symbol.get("source"),
            }
        )
    return {"query": query, "module": module or None, "results": results}


def get_faust_symbol(store: FaustDocStore, symbol: str) -> dict[str, object]:
    """Return the full symbol entry plus nearby alternatives."""

    found, alternatives = store.find_symbol(symbol)
    if found is None:
        raise ValueError(f"Symbol not found: {symbol}")
    return {
        "symbol": found,
        "alternatives": [
            {
                "id": alt.get("id"),
                "qualifiedName": alt.get("qualifiedName"),
                "summary": alt.get("summary"),
            }
            for alt in alternatives
        ],
    }


def list_faust_module(store: FaustDocStore, module: str, limit: int = 200) -> dict[str, object]:
    """List lightweight symbol summaries from one module."""

    library, symbols = store.get_library_symbols(module)
    if library is None:
        raise ValueError(f"Module not found: {module}")

    return {
        "module": normalize_module_key(module),
        "file": library.get("file"),
        "aliasHints": library.get("aliasHints", []),
        "symbols": [
            {
                "id": symbol.get("id"),
                "qualifiedName": symbol.get("qualifiedName"),
                "summary": symbol.get("summary"),
                "usage": symbol.get("usage"),
                "source": symbol.get("source"),
            }
            for symbol in symbols[:limit]
        ],
    }


def get_faust_examples(store: FaustDocStore, symbol_or_module: str, limit: int = 10) -> dict[str, object]:
    """Return `testCode` snippets for a module or a symbol."""

    key = str(symbol_or_module or "").strip()
    if not key:
        raise ValueError("Missing symbolOrModule")

    library, symbols = store.get_library_symbols(key)
    if library is not None:
        examples = []
        for symbol in symbols:
            if not symbol.get("testCode"):
                continue
            examples.append(
                {
                    "symbol": symbol.get("qualifiedName"),
                    "code": symbol.get("testCode"),
                    "source": symbol.get("source"),
                }
            )
            if len(examples) >= limit:
                break
        return {"scope": "module", "query": key, "file": library.get("file"), "examples": examples}

    found, _ = store.find_symbol(key)
    if found is not None:
        examples = []
        if found.get("testCode"):
            examples.append(
                {
                    "symbol": found.get("qualifiedName"),
                    "code": found.get("testCode"),
                    "source": found.get("source"),
                }
            )
        return {"scope": "symbol", "query": key, "examples": examples}

    raise ValueError(f"No symbol/module found: {key}")


def explain_faust_symbol_for_goal(store: FaustDocStore, symbol: str, goal: str) -> dict[str, object]:
    """Compose a short action-oriented explanation from one symbol entry."""

    found, _ = store.find_symbol(symbol)
    if found is None:
        raise ValueError(f"Symbol not found: {symbol}")

    goal_text = str(goal or "").strip()
    params = found.get("params", [])
    notes = found.get("notes", [])
    param_hint = (
        "Key params: " + "; ".join(f"{param['name']} ({param['description']})" for param in params)
        if params
        else "No explicit parameter notes found."
    )
    notes_hint = "Notes: " + " ".join(str(note) for note in notes) if notes else None
    usage = f"Usage: {found['usage']}" if found.get("usage") else "Usage not documented."
    parts = [
        f"Use {found['qualifiedName']} when it matches this goal: {goal_text or 'general DSP design'}.",
        str(found.get("summary") or "No summary found in comments."),
        usage,
        param_hint,
    ]
    if notes_hint:
        parts.append(notes_hint)
    parts.append(
        "A test snippet is available via get_faust_examples."
        if found.get("testCode")
        else "No test snippet found."
    )
    recommendation = " ".join(parts)
    return {"symbol": found.get("qualifiedName"), "goal": goal_text, "recommendation": recommendation}
