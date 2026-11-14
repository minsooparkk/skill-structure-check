#!/usr/bin/env python3
"""<무엇을 보는지 한 줄>(판단 없음, 읽기만). <언제 먼저 돌리는지: 예 "○○ 왜 안 돼" 에 먼저 돌린다>.

쓰는 법:  python3 scripts/<이름>.py [--since YYYY-MM-DD] [--json]
  예: python3 scripts/<이름>.py --since 2026-01-01
보는 것:
  1) <첫째로 보는 것>
  2) <둘째로 보는 것>
판정(스킬 문서의 기준 그대로): <어떤 값이면 어떤 줄을 내는지>. 사람이 정할 것은 정하지 않고 사실만 붙인다.
글에는 이름, 주소, 본문을 싣지 않는다(수와 시각만).
하지 않는 것: 보내기, 지우기, 고치기. 바꾸는 일이 꼭 있으면 --apply 를 줄 때만 한다.
종료 코드: 0 = 살펴볼 것 없음, 2 = 살펴볼 것 있음, 1 = 읽지 못함(명령이 없거나 실패).

이 파일은 스킬-구조-점검 의 틀이다. <…> 자리를 채우고, 쓰지 않는 칸은 지운다.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import date

if sys.version_info < (3, 8):
    sys.exit("파이썬 3.8 이상이 필요합니다(python3 --version 으로 확인).")

# 바깥 명령은 환경변수로 바꿔 끼울 수 있게 둔다(시험에서는 가짜 명령을 넣는다).
TOOL = os.environ.get("MY_SKILL_TOOL_BIN") or "<명령 이름>"
TIMEOUT = 60


def run(argv, timeout=TIMEOUT):
    """→ (종료 코드, 표준 출력). 명령이 없거나 시간을 넘기면 (1, "")."""
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def parse(text):
    """명령 출력 → 줄마다의 값. 판단 없이 꼴만 바꾼다(순수 함수라 시험에서 바로 부른다)."""
    rows = []
    for ln in text.splitlines():
        ln = ln.strip()
        if ln:
            rows.append(ln)
    return rows


def verdict(rows, since):
    """→ 살펴볼 것 목록. 스킬 문서의 기준을 그대로 옮긴다(since 는 날짜 인자로 받아 오늘에 기대지 않는다)."""
    return [r for r in rows if r.startswith("ERROR")]


def render(rows, issues):
    lines = [f"모두 {len(rows)}건 · 살펴볼 것 {len(issues)}건"]
    for n, _ in enumerate(issues, 1):
        lines.append(f"  - 살펴볼 것 {n}")       # 내용 대신 번호와 수만
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="<무엇을 보는지 한 줄>(읽기만)")
    ap.add_argument("--since", help="YYYY-MM-DD (없으면 오늘)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        since = date.fromisoformat(a.since) if a.since else date.today()
    except ValueError:
        ap.error("--since 는 YYYY-MM-DD 꼴로")
    code, out = run([TOOL, "list"])
    if code != 0:
        print(f"읽지 못함: {TOOL} (종료 코드 {code})")
        return 1
    rows = parse(out)
    issues = verdict(rows, since)
    if a.json:
        print(json.dumps({"rows": len(rows), "issues": len(issues)}, ensure_ascii=False))
    else:
        print(render(rows, issues))
    return 2 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
