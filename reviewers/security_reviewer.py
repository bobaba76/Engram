from __future__ import annotations

import ast
import re
from pathlib import Path

from indexing.symbol_extractor import extract_symbols_with_status
from models.entity_models import SymbolRecord
from models.review_models import ReviewJob, ReviewObservation, ReviewResult
from reviewers.base import BaseReviewer


SENSITIVE_IDENTIFIER_RE = re.compile(
    r"(^|_)(access_)?(auth|bearer|jwt|session|refresh)?_?(token|secret|password|apikey|api_key|credential)s?($|_)",
    re.IGNORECASE,
)
BENIGN_IDENTIFIER_RE = re.compile(r"(design|csrf|color|style|theme|syntax)_?token", re.IGNORECASE)
VERIFY_CALL_RE = re.compile(r"(verify|validate|decode|authenticate|authorize|check|require|guard|jwt|permission|policy)", re.IGNORECASE)
SQL_EXECUTE_RE = re.compile(r"\b(execute|executemany|raw|query|executescript)\s*\(", re.IGNORECASE)


def _symbol_lines(text: str, symbol: SymbolRecord) -> str:
    lines = text.splitlines()
    start = max(0, int(symbol.start_line or 1) - 1)
    end = max(start + 1, int(symbol.end_line or symbol.start_line or 1))
    return "\n".join(lines[start:end])


def _identifier_like(value: str) -> list[str]:
    return re.findall(r"[A-Za-z_][A-Za-z0-9_]*", value or "")


def _sensitive_identifiers(value: str) -> list[str]:
    names = []
    for name in _identifier_like(value):
        if BENIGN_IDENTIFIER_RE.search(name):
            continue
        if SENSITIVE_IDENTIFIER_RE.search(name):
            names.append(name)
    return sorted(set(names))


def _symbol_security_context(symbol: SymbolRecord, text: str) -> dict[str, object]:
    metadata = symbol.metadata if isinstance(symbol.metadata, dict) else {}
    body = _symbol_lines(text, symbol)
    calls = [str(item) for item in metadata.get("calls", []) if str(item)]
    references = [str(item) for item in metadata.get("references", []) if str(item)]
    accesses = [str(item) for item in metadata.get("accesses", []) if str(item)]
    names = [symbol.name, symbol.qualified_name, symbol.signature, *calls, *references, *accesses, body]
    sensitive_names = sorted({name for value in names for name in _sensitive_identifiers(str(value))})
    verification_calls = sorted({call for call in calls if VERIFY_CALL_RE.search(call)})
    return {
        "body": body,
        "calls": calls,
        "references": references,
        "accesses": accesses,
        "sensitive_names": sensitive_names,
        "verification_calls": verification_calls,
        "has_verification_cue": bool(verification_calls or VERIFY_CALL_RE.search(body)),
    }


def _python_sql_concat_lines(text: str) -> list[int]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    risky_lines: set[int] = set()

    class Visitor(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> None:
            func_name = ""
            if isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            elif isinstance(node.func, ast.Name):
                func_name = node.func.id
            if func_name.lower() in {"execute", "executemany", "executescript", "raw", "query"}:
                for arg in node.args[:1]:
                    if isinstance(arg, ast.JoinedStr):
                        risky_lines.add(getattr(arg, "lineno", getattr(node, "lineno", 0)))
                    elif isinstance(arg, ast.BinOp) and isinstance(arg.op, (ast.Add, ast.Mod)):
                        risky_lines.add(getattr(arg, "lineno", getattr(node, "lineno", 0)))
                    elif isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) and arg.func.attr == "format":
                        risky_lines.add(getattr(arg, "lineno", getattr(node, "lineno", 0)))
            self.generic_visit(node)

    Visitor().visit(tree)
    return sorted(line for line in risky_lines if line)


def _text_sql_concat_lines(text: str) -> list[int]:
    lines = text.splitlines()
    risky = []
    for index, line in enumerate(lines, start=1):
        lowered = line.lower()
        if SQL_EXECUTE_RE.search(line) and any(token in lowered for token in ("f\"", "f'", ".format(", " + ", "% ")):
            risky.append(index)
    return risky


class SecurityReviewer(BaseReviewer):
    review_type = "security"

    def _observation(
        self,
        job: ReviewJob,
        *,
        title: str,
        description: str,
        category: str,
        severity: str,
        start_line: int | None = None,
        confidence: float = 0.65,
    ) -> ReviewObservation:
        observation = self.build_observation(job, title=title, description=description, category=category, severity=severity)
        observation.start_line = start_line
        observation.end_line = start_line
        observation.confidence = confidence
        observation.review_model = "ast-graph-heuristic-v2"
        return observation

    def review(self, job: ReviewJob, file_path: Path) -> ReviewResult:
        try:
            text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        symbols, status = extract_symbols_with_status(file_path)
        findings: list[ReviewObservation] = []

        for symbol in symbols:
            context = _symbol_security_context(symbol, text)
            sensitive_names = context["sensitive_names"]
            if sensitive_names and not context["has_verification_cue"]:
                names = ", ".join(str(name) for name in sensitive_names[:4])
                findings.append(
                    self._observation(
                        job,
                        title="Sensitive token handling without verification flow",
                        description=(
                            f"AST context for `{symbol.qualified_name or symbol.name}` references sensitive identifier(s) "
                            f"{names}, but its calls/references do not show an obvious verify, validate, authenticate, authorize, or guard step."
                        ),
                        category="authorization_gap",
                        severity="medium",
                        start_line=symbol.start_line,
                        confidence=0.72,
                    )
                )

        sql_lines = _python_sql_concat_lines(text) if str(status.get("language", "")).lower() == "python" else _text_sql_concat_lines(text)
        for line in sql_lines[:5]:
            findings.append(
                self._observation(
                    job,
                    title="Dynamic SQL execution may need parameter binding",
                    description="AST/text context found a SQL execution call built with interpolation or concatenation. Prefer parameterized queries.",
                    category="injection_risk",
                    severity="medium",
                    start_line=line,
                    confidence=0.7,
                )
            )

        return ReviewResult(job=job, findings=findings, diagnostics=[f"security_review_language={status.get('language', 'unknown')}"])
