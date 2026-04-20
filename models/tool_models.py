from dataclasses import dataclass, field


@dataclass(slots=True)
class SearchRequest:
    task: str
    intent: str = "explore"
    limit: int = 5
    scope_paths: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TargetRequest:
    target: str
    target_type: str = "file"
