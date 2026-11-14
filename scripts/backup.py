#!/usr/bin/env python3
"""고치기 전 사본 뜨기(0단계 준비). 판단 없음. 원본은 읽기만 한다. 파이썬 3.8 이상 표준 라이브러리만 쓴다.

쓰는 법:  python3 scripts/backup.py <주제> <파일…> [--dest <폴더>] [--date YYYY-MM-DD]
  예: python3 scripts/backup.py 주간-보고-나누기 ~/.claude/skills/주간-보고/SKILL.md
자리: <--dest, 없으면 지금 폴더의 .skill-backup>/<날짜>/<주제>/<원래 상대 경로>
  원래 상대 경로는 지금 폴더 안이면 지금 폴더 기준, 홈 안이면 홈 기준, 그 밖은 맨 앞 / 만 뗀 경로다.
- 같은 내용의 사본이 이미 있으면 다시 뜨지 않는다. 내용이 다르면 첫 사본('고치기 전' 판)을 덮지 않고 이름 끝에 .HHMMSS 를 붙인다.
- 폴더는 700, 사본은 600 으로 둔다(남이 못 읽게). 없는 파일은 '새 파일(사본 없음)'으로 적고 넘어간다.
- 날짜는 YYYY-MM-DD 꼴의 실제 날짜만 받는다. 주제에는 / 와 \\ 를 쓰지 않고 . 으로 시작하지 않는다(사본 폴더 밖으로 못 나가게).
- 끝에 되돌리는 명령을 한 줄씩 찍는다(cp 사본 원본).
하지 않는 것: 원본을 고치거나 지우지 않는다. 폴더를 통째로 뜨지 않는다(파일만).
종료 코드: 0 = 됨, 1 = 읽지 못한 파일이 있음, 2 = 인자 문제.
"""
import argparse
import hashlib
import os
import re
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

if sys.version_info < (3, 8):
    sys.exit("파이썬 3.8 이상이 필요합니다(python3 --version 으로 확인).")


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rel_of(path, cwd=None, home=None):
    """→ (원본 절대 경로, 사본 폴더 안의 상대 경로)"""
    p = Path(os.path.abspath(os.path.expanduser(str(path))))
    for base in (Path(cwd or os.getcwd()).resolve(), Path(home or Path.home()).resolve()):
        try:
            return p, p.relative_to(base)
        except ValueError:
            try:
                return p, p.resolve().relative_to(base)
            except ValueError:
                continue
    return p, Path(*p.parts[1:])


def mkdirs(folder):
    made = []
    cur = folder
    while not cur.exists():
        made.append(cur)
        cur = cur.parent
    folder.mkdir(parents=True, exist_ok=True)
    for d in made:
        try:
            os.chmod(str(d), 0o700)
        except OSError:
            pass


def copy_one(src, folder, now, cwd=None, home=None):
    """→ (상태, 사본 경로 또는 None). 상태: 떴음 · 이미있음 · 새파일 · 못읽음"""
    p, rel = rel_of(src, cwd, home)
    if not p.exists():
        return "새파일", None
    if not p.is_file():
        return "못읽음", None
    dst = folder / rel
    try:
        if dst.exists():
            if digest(dst) == digest(p):
                return "이미있음", dst
            stamp = dst.with_name(dst.name + "." + now.strftime("%H%M%S"))
            n = 1
            while stamp.exists():
                if digest(stamp) == digest(p):
                    return "이미있음", stamp
                n += 1
                stamp = dst.with_name(f"{dst.name}.{now.strftime('%H%M%S')}-{n}")
            dst = stamp
        mkdirs(dst.parent)
        shutil.copyfile(str(p), str(dst))
        os.chmod(str(dst), 0o600)
    except OSError:
        return "못읽음", None
    return "떴음", dst


def valid_day(s):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s or ""):
        return False
    try:
        date(int(s[:4]), int(s[5:7]), int(s[8:]))
    except ValueError:
        return False
    return True


def main(argv=None, now=None):
    ap = argparse.ArgumentParser(description="고치기 전 사본 뜨기(.skill-backup/<날짜>/<주제>/)")
    ap.add_argument("topic", help="주제(폴더 이름). / 없이")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--dest", help="사본 뿌리(기본: 지금 폴더의 .skill-backup)")
    ap.add_argument("--date", help="YYYY-MM-DD (없으면 오늘)")
    a = ap.parse_args(argv)
    topic = a.topic.strip()
    if not topic or "/" in topic or "\\" in topic or topic.startswith(".") or topic != a.topic:
        print("주제에는 / 와 \\ 를 쓰지 않고, . 으로 시작하거나 앞뒤에 빈칸을 두지 않는다", file=sys.stderr)
        return 2
    now = now or datetime.now()
    day = a.date or now.date().isoformat()
    if not valid_day(day):
        print("--date 는 YYYY-MM-DD 꼴의 실제 날짜로(사본 폴더 밖으로 나가는 값은 받지 않는다)", file=sys.stderr)
        return 2
    root = Path(os.path.expanduser(a.dest)) if a.dest else Path(os.getcwd()) / ".skill-backup"
    folder = root / day / topic
    bad = 0
    undo = []
    for f in a.files:
        state, dst = copy_one(f, folder, now)
        src = rel_of(f)[0]
        if state == "떴음":
            print(f"사본 떴음  {src}  →  {dst}")
            undo.append((dst, src))
        elif state == "이미있음":
            print(f"이미 있음(같은 내용)  {src}  →  {dst}")
            undo.append((dst, src))
        elif state == "새파일":
            print(f"새 파일(사본 없음, 되돌리기는 지우기)  {src}")
        else:
            print(f"못 읽음  {src}")
            bad += 1
    if undo:
        print("되돌리기:")
        for dst, src in undo:
            print(f'  cp "{dst}" "{src}"')
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
