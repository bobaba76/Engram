from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class PathRiskRule:
    hint: str
    predicate: Callable[[str, str], bool]
    high_risk: bool = False
    embedded_sensitive: bool = False


def _endswith(*suffixes: str) -> Callable[[str, str], bool]:
    return lambda normalized, name: normalized.endswith(suffixes)


def _contains_any(*tokens: str) -> Callable[[str, str], bool]:
    return lambda normalized, name: any(token in normalized for token in tokens)


def _name_contains_any(*tokens: str) -> Callable[[str, str], bool]:
    return lambda normalized, name: any(token in name for token in tokens)


def _name_token_contains_any(*tokens: str) -> Callable[[str, str], bool]:
    token_set = set(tokens)

    def predicate(normalized: str, name: str) -> bool:
        name_tokens = set(re.split(r"[^a-z0-9]+", name.lower()))
        non_vector_tokens = token_set - {"vector"}
        if name_tokens & non_vector_tokens:
            return True
        native_like = normalized.endswith((".c", ".h", ".s", ".asm", ".inc", ".ld", ".lds"))
        return native_like and "vector" in token_set and any(token in name_tokens for token in {"vector", "vectors", "vectortable", "vector_table"})

    return predicate


PATH_RISK_RULES = (
    PathRiskRule("embedded/native assembly startup or include path", _endswith(".s", ".asm", ".inc"), high_risk=True, embedded_sensitive=True),
    PathRiskRule("MPLAB embedded project/config path", _endswith(".mcp", ".mcw", ".mptags", ".scl", ".plt"), high_risk=True, embedded_sensitive=True),
    PathRiskRule("device/vendor register header", lambda normalized, name: bool(re.match(r"p\d+[a-z0-9_]*\.h$", name) or name.startswith(("xc", "pic", "dspic"))), high_risk=True, embedded_sensitive=True),
    PathRiskRule("global embedded C contract header", lambda normalized, name: name in {"global.h", "globals.h", "typedefs.h", "sysdefs.h"}, high_risk=True, embedded_sensitive=True),
    PathRiskRule("interrupt/trap/startup path", _name_token_contains_any("trap", "isr", "interrupt", "vector", "reset"), high_risk=True, embedded_sensitive=True),
    PathRiskRule("embedded peripheral/init/flash path", _name_contains_any("uart", "flash", "init", "bootloader"), embedded_sensitive=True),
    PathRiskRule("public/native header surface", _endswith(".h", ".hh", ".hpp", ".hxx"), high_risk=True),
    PathRiskRule("native implementation file", _endswith(".c", ".cc", ".cpp", ".cxx")),
    PathRiskRule("native build target/config path", lambda normalized, name: normalized.endswith((".cmake", "cmakelists.txt", "makefile")) or normalized.endswith((".vcxproj", ".vcxproj.filters")), high_risk=True),
    PathRiskRule("native exported API/ABI surface", lambda normalized, name: normalized.endswith((".def", ".map")) or "/exports/" in normalized, high_risk=True),
    PathRiskRule("C# public route/API path", lambda normalized, name: normalized.endswith(".cs") and any(part in normalized for part in ("/controllers/", "/endpoints/", "/minimalapi", "program.cs")), high_risk=True),
    PathRiskRule("C# DTO/API contract path", lambda normalized, name: normalized.endswith(".cs") and any(token in normalized for token in ("dto", "contract", "request", "response")), high_risk=True),
    PathRiskRule("C# dependency-injection/config path", lambda normalized, name: normalized.endswith(".cs") and any(token in normalized for token in ("startup.cs", "program.cs", "servicecollection", "dependencyinjection")), high_risk=True),
    PathRiskRule("C# database/schema path", lambda normalized, name: normalized.endswith(".cs") and any(part in normalized for part in ("/migrations/", "migration", "dbcontext")), high_risk=True),
    PathRiskRule("Object Pascal project/package path", _endswith(".dpr", ".dpk", ".dproj", ".groupproj", ".lpi", ".lpk"), high_risk=True),
    PathRiskRule("Object Pascal form/resource path", _endswith(".dfm", ".lfm"), high_risk=True),
    PathRiskRule("Object Pascal form event wiring path", _endswith(".dfm", ".lfm")),
    PathRiskRule("Object Pascal unit/source path", _endswith(".pas", ".pp")),
    PathRiskRule("Object Pascal/global include path", _endswith(".inc"), high_risk=True),
    PathRiskRule("auth/security/middleware path", _contains_any("/auth", "/security", "/middleware"), high_risk=True),
    PathRiskRule("public route/API path", _contains_any("/routers/", "/routes/", "/api/")),
    PathRiskRule("database/repository path", _contains_any("/repositories/", "/repository/", "/db", "migration", "schema"), high_risk=True),
    PathRiskRule("shared service/core path", _contains_any("/services/", "/core/", "/shared/", "/utils/", "/config")),
)


def path_risk_hints(file_path: str) -> list[str]:
    normalized = str(file_path or "").replace("\\", "/").lower()
    name = Path(normalized).name
    return [rule.hint for rule in PATH_RISK_RULES if rule.predicate(normalized, name)]


def high_risk_path_hints(hints: list[str]) -> bool:
    high_risk_hints = {rule.hint for rule in PATH_RISK_RULES if rule.high_risk}
    return any(hint in high_risk_hints for hint in hints)


def embedded_sensitive_path_hints(hints: list[str]) -> bool:
    embedded_hints = {rule.hint for rule in PATH_RISK_RULES if rule.embedded_sensitive}
    return any(hint in embedded_hints for hint in hints)


HIGH_RISK_SYMBOL_HINT_TOKENS = (
    "native ABI/layout",
    "native exported symbol",
    "native ABI surface",
    "native layout field",
    "Object Pascal public unit dependency",
    "Object Pascal project ownership",
    "Object Pascal include dependency",
    "Object Pascal conditional compilation",
)


def high_risk_symbol_hints(hints: list[str]) -> bool:
    return any(any(token in hint for token in HIGH_RISK_SYMBOL_HINT_TOKENS) for hint in hints)
