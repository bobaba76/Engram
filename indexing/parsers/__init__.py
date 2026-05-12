from __future__ import annotations

from indexing.parser_registry import ParserRegistry


def register_all(registry: ParserRegistry) -> None:
    from indexing.parsers import c_family, csharp, generic, object_pascal, project_files, python, typescript

    python.register(registry)
    typescript.register(registry)
    c_family.register(registry)
    csharp.register(registry)
    object_pascal.register(registry)
    generic.register(registry)
    project_files.register(registry)
