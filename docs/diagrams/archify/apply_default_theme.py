#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 Archify 生成的 HTML 的**默认主题**固定下来（默认浅色）。

## 为什么需要这个脚本

Archify 生成器会把 ``<html data-theme="dark" ...>`` 写死，而产物运行时解析主题的顺序是：

    ?theme= 查询参数  →  浏览器本地存储(archify-theme)  →  操作系统浅/深色偏好  →  深色

也就是说 Archify **没有提供“默认主题”选项**：在深色系统的机器上双击打开这张图，
看到的就是深色，需要手动点一次工具栏的浅/深色切换按钮才会变成浅色。

本脚本对生成产物做一次**确定性的后处理**，把“用户没有显式选择”时的兜底结果固定为
指定主题（默认 ``light``），改动六处：

1. ``<html ... data-theme="...">`` 静态属性（脚本被禁用时的首屏外观）；
2. 首屏渲染前的内联兜底脚本；
3. 工具栏脚本 ``resolveInitial()`` 的兜底分支；
4. 跟随操作系统主题变化的监听器（改为始终应用固定主题，避免阅读过程中被系统切走）；
5. 深色变量块的选择器：由 ``:root, [data-theme="dark"]`` 收窄为 ``[data-theme="dark"]``；
6. 浅色变量块的选择器：改为 ``:root:not([data-theme="dark"]), [data-theme="light"]``。

第 5、6 条让**浅色成为 CSS 底座**：变量块原来是“深色打底、浅色覆盖”，任何把
``data-theme`` 属性丢掉或没跑脚本的渲染路径（缩略图、预览快照、被清洗过的 HTML）
都会退回深色；改完之后，只要不是显式 ``data-theme="dark"``，渲染出来就是浅色。
深色模式本身不受影响（``?theme=dark`` 与工具栏切换仍然正常）。

**显式选择仍然优先**：``?theme=dark`` 查询参数、以及工具栏的切换按钮（写入浏览器本地
存储）都会覆盖这里的默认值。切换按钮依旧可用，只是“没选过”的时候默认是浅色。

## 用法

在仓库根目录执行：

    python docs/diagrams/archify/apply_default_theme.py                    # 默认 light，处理同目录所有 *.architecture.html
    python docs/diagrams/archify/apply_default_theme.py --theme dark       # 改成深色默认
    python docs/diagrams/archify/apply_default_theme.py <某个.architecture.html> ...

## 顺序要求

必须在 ``archify deliver`` **之后**执行；任何一次重新生成 HTML 都需要重跑本脚本。
脚本是幂等的：重复执行不会重复改动，只在文件缺少该主题标记时改写。
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
THEMES = ("light", "dark")
MARKER_NAME = "archify-default-theme"

# 每条：(说明, 匹配“原始形态或已改写形态”的正则, 替换模板)；每条必须恰好命中 1 次。
PATCHES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "<html> 静态 data-theme 属性",
        re.compile(r'(<html\b[^>]*?)\bdata-theme="(?:dark|light)"'),
        r'\g<1>data-theme="{theme}"',
    ),
    (
        "首屏内联兜底脚本",
        re.compile(
            r"\btheme = (?:window\.matchMedia\('\(prefers-color-scheme: light\)'\)"
            r"\.matches \? 'light' : 'dark'|'light'|'dark');"
        ),
        "theme = '{theme}';",
    ),
    (
        "工具栏 resolveInitial() 兜底",
        re.compile(
            r"\breturn (?:window\.matchMedia\('\(prefers-color-scheme: light\)'\)"
            r"\.matches \? 'light' : 'dark'|'light'|'dark');"
        ),
        "return '{theme}';",
    ),
    (
        "跟随系统主题的监听器",
        re.compile(r"\bapply\((?:e\.matches \? 'light' : 'dark'|'light'|'dark')\);"),
        "apply('{theme}');",
    ),
    (
        "深色变量块（改为只认显式 data-theme=\"dark\"）",
        re.compile(
            "|".join(
                re.escape(part)
                for part in (
                    '\n    :root,\n    [data-theme="dark"] {\n',
                    '\n    [data-theme="dark"] {\n',
                )
            )
        ),
        '\n    [data-theme="dark"] {\n',
    ),
    (
        "浅色变量块（改为 :root 兜底，任何缺少 data-theme 的渲染都是浅色）",
        re.compile(
            "|".join(
                re.escape(part)
                for part in (
                    '\n    :root:not([data-theme="dark"]),\n    [data-theme="light"] {\n',
                    '\n    [data-theme="light"] {\n',
                )
            )
        ),
        '\n    :root:not([data-theme="dark"]),\n    [data-theme="light"] {\n',
    ),
)

MARKER_RE = re.compile(
    r'[ \t]*<meta name="' + re.escape(MARKER_NAME) + r'" content="(?:light|dark)">\r?\n'
)
GENERATOR_RE = re.compile(r'([ \t]*<meta name="generator"[^>]*>\r?\n)')


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def apply_theme(html: str, theme: str, *, name: str) -> tuple[str, list[str]]:
    """返回 (改写后的 HTML, 改动说明列表)；锚点缺失或重复命中时直接报错。"""
    notes: list[str] = []
    for label, pattern, replacement in PATCHES:
        hits = pattern.findall(html)
        if len(hits) != 1:
            raise SystemExit(
                f"{name}: 锚点「{label}」命中 {len(hits)} 次（期望 1 次）——"
                f"生成器可能已升级，请核对 archify 产物后更新本脚本。"
            )
        # 用 str.replace 而不是 str.format：CSS 替换串里含有字面量花括号。
        html = pattern.sub(
            lambda m: m.expand(replacement.replace("{theme}", theme)), html, count=1
        )
        notes.append(label)

    marker = f'  <meta name="{MARKER_NAME}" content="{theme}">\n'
    if MARKER_RE.search(html):
        html = MARKER_RE.sub(lambda _m: marker, html, count=1)
        notes.append(f"默认主题标记（更新为 {theme}）")
    else:
        generator = GENERATOR_RE.search(html)
        if not generator or GENERATOR_RE.findall(html).__len__() != 1:
            raise SystemExit(f"{name}: 找不到唯一的 generator meta，无法写入默认主题标记。")
        html = GENERATOR_RE.sub(lambda m: m.group(1) + marker, html, count=1)
        notes.append(f"默认主题标记（新增为 {theme}）")
    return html, notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="固定 Archify 产物的默认主题")
    parser.add_argument("--theme", choices=THEMES, default="light", help="默认主题（默认 light）")
    parser.add_argument(
        "targets",
        nargs="*",
        help="待处理的 .architecture.html；缺省时处理本脚本同目录下的全部 *.architecture.html",
    )
    args = parser.parse_args(argv)

    if args.targets:
        files = [Path(t) for t in args.targets]
    else:
        files = sorted(HERE.glob("*.architecture.html"))
    if not files:
        print("没有找到待处理的 *.architecture.html", file=sys.stderr)
        return 2

    failed = False
    for path in files:
        if not path.is_file():
            print(f"[跳过] {path}：文件不存在", file=sys.stderr)
            failed = True
            continue
        original = path.read_text(encoding="utf-8")
        updated, notes = apply_theme(original, args.theme, name=path.name)
        before, after = sha256(original), sha256(updated)
        if updated == original:
            print(f"[不变] {path.name}：已是默认 {args.theme}")
        else:
            path.write_text(updated, encoding="utf-8")
            print(f"[改写] {path.name}：默认主题 -> {args.theme}")
        for note in notes:
            print(f"         - {note}")
        before_bytes = len(original.encode("utf-8"))
        after_bytes = len(updated.encode("utf-8"))
        print(f"         sha256 {before[:12]} -> {after[:12]}  bytes {before_bytes} -> {after_bytes}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
