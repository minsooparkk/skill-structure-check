#!/usr/bin/env python3
"""같은 글이 두 벌인 곳을 찾는다(읽기 전용). 틀과 문안은 한 곳만 정본이어야 한다.
한쪽만 고치면 서로 달라지는데 아무도 모르기 때문이다. 파이썬 3.8 이상 표준 라이브러리만 쓴다.

쓰는 법: python3 scripts/copies.py <스킬 폴더 또는 스킬들이 든 폴더> [--min-chars 12] [--json] [--out <작업폴더>] [--strict]
  예: python3 scripts/copies.py ~/.claude/skills --out ~/스킬점검/작업
찾는 세 가지(스킬 폴더 하나 안에서만 본다):
  A 딸린 파일과 문서      assets·references 의 한 줄(JSON 이면 글 값)이 SKILL.md 본문의 어느 줄 안에 그대로 있다
  B 딸린 파일과 스크립트  assets·references 의 한 줄이 scripts 의 코드 줄 안에 그대로 있다
  C 문서와 스크립트      scripts 의 글자열(따옴표 안, 띄어쓰기가 든 글)이 SKILL.md 본문의 어느 줄 안에 그대로 있다
견주는 법: 유니코드 NFC, 이어진 빈칸은 하나로, 앞뒤 빈칸은 떼고 본다. 큰 글자와 작은 글자는 가린다.
표 줄(| 로 시작)은 줄 전체와 칸 하나하나를 따로 견준다(스크립트는 표를 칸마다 따로 들고 있기 쉽다).
세지 않는 것: --min-chars 보다 짧은 글, 글자(낱말 글자)가 넷이 안 되는 줄, 띄어쓰기 없는 이름이나 경로(영문 낱말 하나, / . _ - 가 든 것),
  제목 줄(#), 인용 머리(>), 울타리 줄, 표 가름 줄과 그 바로 위 표 머리 줄, SKILL.md 의 머리(--- 사이),
  스크립트의 주석 줄과 맨 위 설명(docstring),
  UTF-8 로 못 읽는 파일, 200KB 넘는 파일. assets 에 둔 코드 틀(.py, .sh 등)은 스크립트와 견주지 않는다(틀이라 뼈대가 같다).
결과(--out 을 주면 copies.json 도 쓴다): 스킬마다 종류, 양쪽 자리(파일:줄), 겹친 글 앞머리.
하지 않는 것: 고치지 않는다. 어느 쪽이 정본인지 정하지 않는다. 찾은 것은 후보일 뿐이다
  (예시로 일부러 남긴 줄, 지시와 검사가 한 쌍인 값일 수 있다. 고르는 법은 references/두-벌-걷기.md).
종료 코드: 0 = 됨(찾았든 못 찾았든), 1 = --strict 인데 두 벌이 있음, 2 = 인자 문제.
"""
import argparse
import ast
import json
import re
import sys
from pathlib import Path

if sys.version_info < (3, 8):
    sys.exit("파이썬 3.8 이상이 필요합니다(python3 --version 으로 확인).")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inventory import InputError, find_skills, list_files, nfc, parse_front, read_text  # noqa: E402

MAX_BYTES = 200_000
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{2,}")
WORD = re.compile(r"\w", re.UNICODE)
QUOTED = re.compile(r"""(["'])((?:\\.|(?!\1).)*)\1""")
CODE_SUFFIX = {".py", ".js", ".mjs", ".ts", ".sh", ".bash", ".zsh", ".rb", ".go", ".rs", ".java", ".kt", ".php", ".pl", ".ps1",
               ".bat", ".cmd", ".lua", ".swift"}
KIND = {
    "A": ("딸린 파일과 문서", "딸린 파일을 정본으로 두고 SKILL.md 의 사본은 가리키는 말로 바꾼다(move_sections 의 replace)"),
    "B": ("딸린 파일과 스크립트", "스크립트가 그 딸린 파일을 읽게 하고 스크립트 안의 사본을 걷는다"),
    "C": ("문서와 스크립트", "문안이나 표면 assets 한 곳으로 모아 스크립트가 읽게 한다. 지시와 검사가 한 쌍인 값이면 둘이 같은지 보는 시험으로 묶는다"),
}


def key(s):
    return re.sub(r"\s+", " ", nfc(s)).strip()


def worth(k, min_chars):
    if len(k) < min_chars or len(WORD.findall(k)) < 4:
        return False
    if " " in k:
        return True
    return not k.isascii() and not re.search(r"[/._-]", k)   # 띄어쓰기 없는 영문 낱말, 파일 이름, 경로는 글이 아니다


def doc_lines(text):
    """SKILL.md 본문 줄 → [(줄 번호, 견줄 글)]. 머리, 제목 줄, 울타리 줄은 뺀다."""
    _, body, _ = parse_front(text)
    out = []
    for n, ln in enumerate(text.split("\n"), 1):
        if n <= body or FENCE.match(ln) or ln.lstrip().startswith("#"):
            continue
        k = key(ln)
        if k:
            out.append((n, k))
    return out


def _json_strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for k, v in x.items():
            if not str(k).startswith("_"):      # '_about' 같은 설명 칸은 재료가 아니다
                yield from _json_strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from _json_strings(v)


def side_items(rel, text, min_chars):
    """딸린 파일에서 견줄 글 → [(줄 번호, 글)]. JSON 은 글 값을, 그 밖은 줄을 본다."""
    items = []
    if rel.lower().endswith(".json"):
        try:
            values = list(_json_strings(json.loads(text)))
        except ValueError:
            values = None
        if values is not None:
            raw = text.split("\n")
            for v in values:
                for piece in str(v).split("\n"):
                    k = key(piece)
                    if not worth(k, min_chars):
                        continue
                    line = next((n for n, ln in enumerate(raw, 1) if piece.strip()[:20] and piece.strip()[:20] in ln), 0)
                    items.append((line, k))
            return items
    raw = text.split("\n")
    for n, ln in enumerate(raw, 1):
        s = ln.lstrip()
        if s.startswith("#") or s.startswith(">") or FENCE.match(ln) or TABLE_RULE.match(ln):
            continue
        if s.startswith("|") and n < len(raw) and TABLE_RULE.match(raw[n]):
            continue                          # 표 머리 줄('| 값 | 뜻 |')은 어느 표에나 있다
        k = key(ln)
        if worth(k, min_chars):
            items.append((n, k))
        if s.startswith("|"):                 # 표 줄은 칸마다도 본다
            for cell in s.strip().strip("|").split("|"):
                c = key(cell)
                if c != k and worth(c, min_chars):
                    items.append((n, c))
    return items


def _docstring_nodes(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                out.add(id(first.value))
    return out


def script_parts(rel, text):
    """스크립트 → (코드 줄 [(줄 번호, 글)], 글자열 [(줄 번호, 글)]). 주석 줄과 맨 위 설명은 뺀다."""
    lines = text.split("\n")
    skip = set()
    strings = []
    parsed = False
    if rel.endswith(".py"):
        try:
            tree = ast.parse(text)
            parsed = True
        except (SyntaxError, ValueError):
            tree = None
        if tree is not None:
            docs = _docstring_nodes(tree)
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                    continue
                first = getattr(node, "lineno", 0)
                last = getattr(node, "end_lineno", first) or first
                if id(node) in docs:
                    skip.update(range(first, last + 1))
                    continue
                for off, piece in enumerate(node.value.split("\n")):
                    strings.append((first + off if last > first else first, piece))
    if not parsed:
        for n, ln in enumerate(lines, 1):
            if ln.lstrip().startswith(("#", "//")):
                continue
            for m in QUOTED.finditer(ln):
                strings.append((n, m.group(2)))
    code = []
    for n, ln in enumerate(lines, 1):
        if n in skip or ln.lstrip().startswith(("#", "//")):
            continue
        k = key(ln)
        if k:
            code.append((n, k))
    return code, strings


def _hit(items, hay):
    """items 의 글이 hay 의 어느 줄 안에 그대로 있는 것 → [(item 줄, hay 줄, 글)] (같은 글은 한 번만)."""
    out, seen = [], set()
    for n, k in items:
        if k in seen:
            continue
        m = next((hn for hn, hk in hay if k in hk), None)
        if m is not None:
            seen.add(k)
            out.append((n, m, k))
    return out


def inspect(skill_dir, min_chars=12):
    """→ {name, found: [{kind, text, a, b}], notes: […]}"""
    skill_dir = Path(skill_dir)
    name = nfc(skill_dir.name)
    res = {"name": name, "found": [], "notes": []}
    doc, err = read_text(skill_dir / "SKILL.md")
    if err:
        res["notes"].append(f"SKILL.md {err}")
        return res
    dlines = doc_lines(doc)
    sides = {}
    for kind in ("assets", "references"):
        for rel in list_files(skill_dir, kind):
            p = skill_dir / rel
            try:
                if p.stat().st_size > MAX_BYTES:
                    res["notes"].append(f"{rel}: 200KB 를 넘어 보지 않음")
                    continue
            except OSError:
                continue
            text, e = read_text(p)
            if e:
                continue                      # 그림 같은 글이 아닌 파일
            sides[rel] = side_items(rel, text, min_chars)
    scripts = {}
    for rel in list_files(skill_dir, "scripts"):
        p = skill_dir / rel
        try:
            if p.stat().st_size > MAX_BYTES:
                continue
        except OSError:
            continue
        text, e = read_text(p)
        if not e:
            scripts[rel] = script_parts(rel, text)
    for rel, items in sides.items():
        for n, m, k in _hit(items, dlines):
            res["found"].append({"kind": "A", "text": k, "a": f"{rel}:{n}", "b": f"SKILL.md:{m}"})
        if Path(rel).suffix.lower() in CODE_SUFFIX:
            continue                          # 코드 틀은 스크립트와 뼈대가 같다
        for srel, (code, _) in scripts.items():
            for n, m, k in _hit(items, code):
                res["found"].append({"kind": "B", "text": k, "a": f"{rel}:{n}", "b": f"{srel}:{m}"})
    for srel, (_, strings) in scripts.items():
        items = [(n, key(s)) for n, s in strings]
        items = [(n, k) for n, k in items if worth(k, min_chars)]
        for n, m, k in _hit(items, dlines):
            res["found"].append({"kind": "C", "text": k, "a": f"{srel}:{n}", "b": f"SKILL.md:{m}"})
    return res


def run(target, min_chars=12):
    return [inspect(d, min_chars) for d in find_skills(target)]


def render(results):
    lines = []
    total = {"A": 0, "B": 0, "C": 0}
    for r in results:
        if not r["found"] and not r["notes"]:
            continue
        lines.append(f"{r['name']}: 두 벌 {len(r['found'])}곳" if r["found"] else f"{r['name']}: 두 벌 없음")
        for f in r["found"]:
            total[f["kind"]] += 1
            lines.append(f"  [{f['kind']} {KIND[f['kind']][0]}] {f['a']} = {f['b']} · {f['text'][:60]}")
        lines += [f"  (참고) {n}" for n in r["notes"]]
    with_any = sum(1 for r in results if r["found"])
    lines.append(f"스킬 {len(results)}개 · 두 벌 있는 스킬 {with_any}개(A {total['A']} · B {total['B']} · C {total['C']})")
    for k in ("A", "B", "C"):
        if total[k]:
            lines.append(f"  {k} {KIND[k][0]}: {KIND[k][1]}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="같은 글이 두 벌인 곳을 찾는다(읽기 전용)")
    ap.add_argument("target", help="스킬 폴더 또는 스킬들이 든 폴더")
    ap.add_argument("--min-chars", type=int, default=12, help="이보다 짧은 글은 견주지 않는다(기본 12)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", help="copies.json 을 둘 작업폴더")
    ap.add_argument("--strict", action="store_true", help="두 벌이 있으면 종료 코드 1")
    a = ap.parse_args(argv)
    if a.min_chars < 4:
        print("--min-chars 는 4 이상", file=sys.stderr)
        return 2
    try:
        results = run(a.target, a.min_chars)
    except InputError as e:
        print(f"입력 문제: {e}", file=sys.stderr)
        return 2
    if a.out:
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "copies.json").write_text(json.dumps({"min_chars": a.min_chars, "skills": results}, ensure_ascii=False, indent=1) + "\n",
                                         encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=1) if a.json else render(results))
    return 1 if a.strict and any(r["found"] for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
