#!/usr/bin/env python3
"""스킬 폴더가 제 모양인지 본다(6단계 확인). 판단 없음, 읽기 전용. 파이썬 3.8 이상 표준 라이브러리만 쓴다.

쓰는 법:  python3 scripts/check.py <스킬 폴더 | 스킬들이 든 폴더> [--max-lines 500] [--max-bytes 20000] [--skills-ref]
  예: python3 scripts/check.py ~/.claude/skills
보는 것(스킬마다):
  1) SKILL.md 가 가리키는 scripts/…, references/…, assets/… 파일이 실제로 있는가
     (스킬 폴더 기준 상대 경로와 '<무엇>/<스킬 이름>/references/…' 꼴. 다른 스킬 이름이 앞에 붙으면 그 스킬 폴더에서 찾는다.
      <…>, {…}, *, … 가 든 경로는 보기로 쓴 것이라 보지 않는다)
     이 스킬 폴더에 없을 때: 같은 부모 아래 다른 스킬 폴더나 위쪽 폴더(부모부터 4단계까지, .git 이 있는 폴더에서 멈춤)의
     같은 상대 경로에 있으면 주의(그 폴더 기준으로 쓴 명령으로 보임), 어디에도 없으면 문제.
  2) 그 세 폴더의 파일(숨김 파일, __pycache__ 제외)을 누가 가리키는가
     scripts·assets: 상대 경로, 파일 이름, 코드 파일이면 확장자 뗀 이름이 낱말로(앞뒤가 영숫자·밑줄이 아님) SKILL.md 나
       그 스킬 폴더의 다른 글 파일(예약 파일, 다른 스크립트의 import 등)에 나오면 통과. 아무 데도 없으면 문제(고아).
     references: SKILL.md 에 나오면 통과, 다른 파일에만 나오면 주의, 아무 데도 없으면 문제.
     시험 파일(test_*.py, *_test.py, conftest.py)과 __init__.py 는 고아로 보지 않는다.
  3) 빈 폴더가 없는가, references 의 .md 가 비어 있지 않은가
  4) SKILL.md 가 한도(줄 수, 바이트) 안인가, 머리에 name 과 description 이 있는가
  5) --skills-ref 이고 skills-ref 명령이 있으면 'skills-ref validate' 결과(없으면 건너뜀. 명령은 SKILLS_REF_BIN 으로 바꿀 수 있다)
결과: 스킬마다 한 줄(통과 | 통과(주의 n개) | 문제 n개)과 목록, 끝에 합계. 주의는 찍기만 하고 종료 코드에 넣지 않는다.
하지 않는 것: 파일을 고치거나 지우지 않는다. 문서 내용이 옳은지 보지 않는다.
종료 코드: 0 = 문제 없음(주의는 있어도 됨), 2 = 문제 있음(또는 스킬을 못 찾음).
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

if sys.version_info < (3, 8):
    sys.exit("파이썬 3.8 이상이 필요합니다(python3 --version 으로 확인).")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inventory import InputError, find_skills, list_files, nfc, parse_front, read_text  # noqa: E402

KINDS = ("scripts", "references", "assets")
REF = re.compile(r"(?P<pre>[^\s`'\"()\[\]<>|*]*)(?P<path>(?:scripts|references|assets)/[^\s`'\"()\[\]<>|,;]*?\.[A-Za-z0-9]{1,10})"
                 r"(?![A-Za-z0-9]|\.[A-Za-z0-9])")
EXAMPLE = re.compile(r"[<>{}*…]|\.\.\.")
CODE_EXT = {".py", ".sh", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl", ".ps1", ".bash", ".zsh"}
SKIP_DIRS = {"__pycache__", ".skill-backup", ".git", "node_modules"}
MAX_TEXT = 1000000
UP_LEVELS = 4


def is_test_file(name):
    return name == "conftest.py" or name == "__init__.py" or (name.startswith("test_") and name.endswith(".py")) \
        or name.endswith("_test.py")


def has_name(text, name):
    """name 이 낱말로 나오는가. 앞뒤 글자가 ASCII 영숫자나 밑줄이 아니면 된다(\\b 는 한글을 낱말 글자로 봐서 쓰지 않는다)."""
    if not name:
        return False
    rx = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])")
    return rx.search(text) is not None


def names_of(rel):
    """파일을 가리키는 이름들: 상대 경로, 파일 이름, 코드 파일이면 확장자 뗀 이름."""
    p = Path(rel)
    out = [rel, p.name]
    if p.suffix.lower() in CODE_EXT and p.stem:
        out.append(p.stem)
    return out


def other_texts(skill_dir):
    """스킬 폴더 안의 글 파일(SKILL.md 제외) → {스킬 폴더 기준 경로: 글}"""
    out = {}
    for root, dirs, files in os.walk(skill_dir):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS)
        for f in sorted(files):
            if f.startswith(".") or f.endswith(".pyc"):
                continue
            p = Path(root) / f
            rel = nfc(p.relative_to(skill_dir).as_posix())
            if rel == "SKILL.md":
                continue
            try:
                if p.stat().st_size > MAX_TEXT:
                    continue
                out[rel] = nfc(p.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
    return out


def sibling(skill_dir, owner):
    p = skill_dir.parent / owner
    if (p / "SKILL.md").is_file():
        return p
    for c in skill_dir.parent.iterdir():
        if nfc(c.name) == owner and (c / "SKILL.md").is_file():
            return c
    return None


def referenced(text, skill_dir):
    """SKILL.md 가 가리키는 파일 → [(찾을 폴더, 상대 경로, 줄 번호)]"""
    name = nfc(skill_dir.name)
    out = []
    for n, ln in enumerate(nfc(text).split("\n"), 1):
        for m in REF.finditer(ln):
            pre, rel = m.group("pre"), m.group("path")
            if pre and not pre.endswith("/"):
                continue          # myscripts/… 처럼 다른 낱말의 끝
            if EXAMPLE.search(rel) or (pre and EXAMPLE.search(pre)):
                continue
            owner = pre.rstrip("/").split("/")[-1] if pre.strip("/") else ""
            if owner in ("", ".", name):
                base = skill_dir
            else:
                base = sibling(skill_dir, owner)
                if base is None:
                    continue      # 스킬이 아닌 다른 곳의 경로
            out.append((base, rel, n))
    return out


def find_elsewhere(skill_dir, rel):
    """이 스킬 폴더에 없는 rel 을 옆 스킬 폴더, 위쪽 폴더에서 찾는다 → 주의 글 또는 ''"""
    parent = skill_dir.parent
    try:
        kids = sorted(parent.iterdir(), key=lambda p: nfc(p.name))
    except OSError:
        kids = []
    for c in kids:
        if c != skill_dir and c.is_dir() and (c / "SKILL.md").is_file() and (c / rel).is_file():
            return f"다른 스킬 폴더 {nfc(c.name)} 에 있음. 그 폴더 기준으로 쓴 경로로 보임"
    up = parent
    for level in range(1, UP_LEVELS + 1):
        if (up / rel).is_file():
            return f"위 폴더 {'../' * level} 에 있음. 그 폴더 기준으로 쓴 경로로 보임"
        if (up / ".git").exists() or up.parent == up:
            break
        up = up.parent
    return ""


def empty_dirs(skill_dir):
    out = []
    for kind in KINDS:
        base = skill_dir / kind
        if not base.is_dir():
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            here = Path(root)
            has = any(not f.startswith(".") and not f.endswith(".pyc") for _, _, fs in os.walk(here) for f in fs)
            if not has:
                out.append(nfc(here.relative_to(skill_dir).as_posix()) + "/")
                dirs[:] = []
    return out


def skills_ref(skill_dir):
    """→ (상태, 글). 상태: 통과 · 문제 · 건너뜀"""
    exe = os.environ.get("SKILLS_REF_BIN") or shutil.which("skills-ref")
    if not exe:
        return "건너뜀", "skills-ref 명령이 없음"
    try:
        r = subprocess.run([exe, "validate", str(skill_dir)], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return "건너뜀", f"skills-ref 를 돌리지 못함({e.__class__.__name__})"
    msg = (r.stdout + r.stderr).strip().split("\n")
    first = next((x.strip() for x in msg if x.strip()), "")
    if r.returncode == 0:
        return "통과", first
    return "문제", " / ".join(x.strip() for x in msg if x.strip())[:300]


def check_skill(skill_dir, max_lines=500, max_bytes=20000, use_skills_ref=False):
    """→ (문제 목록, 주의 목록, 알림 목록). 문제만 종료 코드에 들어간다."""
    skill_dir = Path(skill_dir)
    problems, warnings, notes = [], [], []
    text, err = read_text(skill_dir / "SKILL.md")
    if err:
        return [f"SKILL.md 를 {err}"], warnings, notes
    if not text.strip():
        problems.append("SKILL.md 가 비어 있음")
    front, _, ferr = parse_front(text)
    if ferr:
        problems.append(f"머리: {ferr}")
    else:
        for k in ("name", "description"):
            v = front.get(k)
            if not (isinstance(v, str) and v.strip()):
                problems.append(f"머리에 {k} 가 없음")
    n_lines = len(text.split("\n")) - (1 if text.endswith("\n") else 0)
    n_bytes = len(text.encode("utf-8"))
    if n_lines > max_lines:
        problems.append(f"SKILL.md 가 {n_lines}줄(한도 {max_lines})")
    if n_bytes > max_bytes:
        problems.append(f"SKILL.md 가 {n_bytes}바이트(한도 {max_bytes})")

    seen = set()
    for base, rel, line in referenced(text, skill_dir):
        if (base, rel) in seen:
            continue
        seen.add((base, rel))
        if (base / rel).is_file():
            continue
        if base == skill_dir:
            where = find_elsewhere(skill_dir, rel)
            if where:
                warnings.append(f"이 폴더에 없는 파일: {rel} (SKILL.md:{line}). {where}")
                continue
            problems.append(f"가리키는 파일이 없음: {rel} (SKILL.md:{line})")
        else:
            problems.append(f"가리키는 파일이 없음: {nfc(base.name)}/{rel} (SKILL.md:{line})")

    doc = nfc(text)
    others = other_texts(skill_dir)
    for kind in KINDS:
        for rel in list_files(skill_dir, kind):
            name = Path(rel).name
            if kind == "references" and rel.endswith(".md"):
                body, e2 = read_text(skill_dir / rel)
                if e2 or not body.strip():
                    problems.append(f"references 파일이 비었거나 읽히지 않음: {rel}")
            if is_test_file(name):
                continue
            keys = names_of(rel) if kind != "references" else [rel, name]
            if any(has_name(doc, k) for k in keys):
                continue
            by = [o for o, t in others.items() if o != rel and any(has_name(t, k) for k in keys)]
            if by and kind == "references":
                warnings.append(f"SKILL.md 가 직접 가리키지 않음: {rel} ({by[0]} 가 가리킴)")
            elif not by:
                problems.append(f"아무도 가리키지 않는 파일(고아): {rel}")
    for d in empty_dirs(skill_dir):
        problems.append(f"빈 폴더: {d}")
    if use_skills_ref:
        state, msg = skills_ref(skill_dir)
        if state == "문제":
            problems.append(f"skills-ref validate: {msg}")
        else:
            notes.append(f"skills-ref: {state}" + (f" ({msg})" if msg and state == "건너뜀" else ""))
    return problems, warnings, notes


def main(argv=None):
    ap = argparse.ArgumentParser(description="스킬 폴더가 제 모양인지 본다(읽기 전용)")
    ap.add_argument("target")
    ap.add_argument("--max-lines", type=int, default=500)
    ap.add_argument("--max-bytes", type=int, default=20000)
    ap.add_argument("--skills-ref", action="store_true", help="skills-ref validate 도 돌린다(있을 때만)")
    a = ap.parse_args(argv)
    try:
        dirs = find_skills(a.target)
    except InputError as e:
        print(str(e), file=sys.stderr)
        return 2
    if not dirs:
        print(f"SKILL.md 가 든 폴더를 찾지 못했습니다: {a.target}", file=sys.stderr)
        return 2
    passed = total = warned = 0
    for d in dirs:
        problems, warnings, notes = check_skill(d, a.max_lines, a.max_bytes, a.skills_ref)
        name = nfc(d.name)
        tail = (" · " + " · ".join(notes)) if notes else ""
        if problems:
            print(f"{name}: 문제 {len(problems)}개" + (f", 주의 {len(warnings)}개" if warnings else "") + tail)
        else:
            passed += 1
            print(f"{name}: 통과" + (f"(주의 {len(warnings)}개)" if warnings else "") + tail)
        for p in problems:
            print(f"  - 문제: {p}")
        for w in warnings:
            print(f"  - 주의: {w}")
        total += len(problems)
        warned += len(warnings)
    print(f"스킬 {len(dirs)}개 · 통과 {passed} · 문제 있음 {len(dirs) - passed} (문제 {total}개, 주의 {warned}개)")
    return 0 if passed == len(dirs) else 2


if __name__ == "__main__":
    sys.exit(main())
