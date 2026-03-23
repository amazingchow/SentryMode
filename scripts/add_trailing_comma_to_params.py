"""
Ensure every function / async def / lambda has a trailing comma on its last parameter.

After running, `ruff format` expands the parameter list to one name per line (magic comma).

Usage (repo root):
    uv run python scripts/add_trailing_comma_to_params.py src tests
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import libcst as cst
from libcst import Comma, Param, Parameters


def _last_parameter(params: Parameters) -> Param | None:
    if params.star_kwarg is not None:
        return params.star_kwarg
    if params.kwonly_params:
        return params.kwonly_params[-1]
    star = params.star_arg
    if isinstance(star, Param):
        return star
    if params.params:
        return params.params[-1]
    if params.posonly_params:
        return params.posonly_params[-1]
    return None


def _replace_last_param(params: Parameters, fixed: Param) -> Parameters:
    if params.star_kwarg is not None:
        return params.with_changes(star_kwarg=fixed)
    if params.kwonly_params:
        kws = list(params.kwonly_params)
        kws[-1] = fixed
        return params.with_changes(kwonly_params=kws)
    if isinstance(params.star_arg, Param):
        return params.with_changes(star_arg=fixed)
    if params.params:
        ps = list(params.params)
        ps[-1] = fixed
        return params.with_changes(params=ps)
    if params.posonly_params:
        ps = list(params.posonly_params)
        ps[-1] = fixed
        return params.with_changes(posonly_params=ps)
    return params


def ensure_parameters_trailing_comma(params: Parameters) -> Parameters:
    last = _last_parameter(params)
    if last is None:
        return params
    if isinstance(last.comma, Comma):
        return params
    fixed = last.with_changes(comma=Comma())
    return _replace_last_param(params, fixed)


class _TrailingCommaParams(cst.CSTTransformer):
    def leave_FunctionDef(self, original: cst.FunctionDef, updated: cst.FunctionDef) -> cst.FunctionDef:
        new_params = ensure_parameters_trailing_comma(updated.params)
        if new_params is updated.params:
            return updated
        return updated.with_changes(params=new_params)

    def leave_AsyncFunctionDef(
        self,
        original: cst.AsyncFunctionDef,
        updated: cst.AsyncFunctionDef,
    ) -> cst.AsyncFunctionDef:
        new_params = ensure_parameters_trailing_comma(updated.params)
        if new_params is updated.params:
            return updated
        return updated.with_changes(params=new_params)

    def leave_Lambda(self, original: cst.Lambda, updated: cst.Lambda) -> cst.Lambda:
        new_params = ensure_parameters_trailing_comma(updated.params)
        if new_params is updated.params:
            return updated
        return updated.with_changes(params=new_params)


def transform_source(src: str) -> str:
    module = cst.parse_module(src)
    return module.visit(_TrailingCommaParams()).code


def collect_py_files(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if p.is_file() and p.suffix == ".py":
            out.append(p)
        elif p.is_dir():
            out.extend(sorted(p.rglob("*.py")))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Files or directories of Python sources",
    )
    args = parser.parse_args()
    files = collect_py_files(args.paths)
    changed = 0
    for path in files:
        text = path.read_text(encoding="utf-8")
        new_text = transform_source(text)
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            changed += 1
            print(f"updated {path}", file=sys.stderr)
    print(f"done: {changed} file(s) modified", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
