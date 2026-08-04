"""Одноразовый трансформер: обернуть кириллические строковые литералы в _().

Использует ast: узлы Constant(str) с кириллицей оборачиваются в _(...).
Неявная конкатенация ("a" "b") парсится в один Constant, поэтому
оборачивается корректно как единое целое. Пропускаются:
  * f-строки (ast.JoinedStr) — обрабатываются вручную;
  * докстринги (первый оператор модуля/функции/класса);
  * уже обёрнутые строки (родитель — вызов _()).

Замена выполняется по координатам исходника с конца к началу, чтобы не
сдвигать смещения. Запуск: python3 tools/wrap_i18n.py <файл.py> ...
"""

import ast
import re
import sys

CYR = re.compile(r"[А-Яа-яЁё]")


def _docstring_nodes(tree):
    """Множество id() строковых узлов-докстрингов."""
    ds = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef,
                             ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                ds.add(id(body[0].value))
    return ds


def _fstring_constants(tree):
    """id() строковых Constant-узлов, находящихся внутри f-строк."""
    inside = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for child in ast.walk(node):
                if isinstance(child, ast.Constant):
                    inside.add(id(child))
    return inside


def _wrapped_nodes(tree):
    """id() строковых узлов, уже являющихся аргументом вызова _()."""
    wrapped = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "_" and node.args:
            a = node.args[0]
            if isinstance(a, ast.Constant):
                wrapped.add(id(a))
    return wrapped


def transform(src: str) -> str:
    tree = ast.parse(src)
    docs = _docstring_nodes(tree)
    wrapped = _wrapped_nodes(tree)
    fstr = _fstring_constants(tree)

    # ВАЖНО: ast col_offset — это смещение в БАЙТАХ UTF-8, поэтому работаем
    # с байтовым представлением исходника.
    data = src.encode("utf-8")
    lines = data.splitlines(keepends=True)
    line_start = [0]
    for ln in lines:
        line_start.append(line_start[-1] + len(ln))

    def off(lineno, col):
        return line_start[lineno - 1] + col

    targets = []  # (start, end) в байтах
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docs or id(node) in wrapped or id(node) in fstr:
                continue
            if not CYR.search(node.value):
                continue
            if node.end_lineno is None:
                continue
            s = off(node.lineno, node.col_offset)
            e = off(node.end_lineno, node.end_col_offset)
            targets.append((s, e))

    targets.sort(reverse=True)
    for s, e in targets:
        data = data[:s] + b"_(" + data[s:e] + b")" + data[e:]
    return data.decode("utf-8")


def main(argv):
    for path in argv:
        src = open(path, encoding="utf-8").read()
        open(path, "w", encoding="utf-8").write(transform(src))
        print("обработан:", path)


if __name__ == "__main__":
    main(sys.argv[1:])
