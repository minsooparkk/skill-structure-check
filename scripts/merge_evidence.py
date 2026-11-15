#!/usr/bin/env python3
"""여러 스킬을 나눠 읽은 근거(묶음 파일)를 근거 파일 하나로 합치고, 판정 뒤에는 판정과 읽은 쪽 의견을 나란히 보여 준다.
판단 없음: 합치고 견주기만 한다. 파이썬 3.8 이상 표준 라이브러리만 쓴다.

쓰는 법:
  합치기   python3 scripts/merge_evidence.py <작업폴더>/evidence.json <묶음 파일…> [--only references,assets]
                                             [--skip-skill <이름> …] [--out <작업폴더>]
  견주기   python3 scripts/merge_evidence.py --compare <작업폴더>/result.json <작업폴더>/opinions.json
  예: python3 scripts/merge_evidence.py ~/스킬점검/작업/evidence.json ~/스킬점검/작업/group-*.json --only references,assets
묶음 파일(읽는 쪽 하나가 내는 파일. 틀은 assets/묶음-근거-틀.json):
  {"group": "1", "candidates": [근거를 채운 후보와 손 후보], "opinions": {"<후보 id>": {"opinion": "move" 또는 "keep",
   "why": "한 줄", "op": {옮기기 op 제안}, "ref": {"title": "…", "when": "…"}}}, "notes": ["…"]}
합치기:
  - 묶음의 후보는 id 로 원래 후보를 갈아 끼운다. 원래 없던 id 는 손 후보 꼴(<스킬>#m1)일 때만 더한다.
  - --only 를 주면 suggest 가 그 안에 있는 후보만 남긴다(이번에 볼 범위). --skip-skill 은 그 스킬의 후보를 뺀다.
  - 결과: evidence.merged.json(judge.py 에 넣는다), opinions.json(의견과 메모 모음).
  - 문제로 적는 것: 같은 id 가 두 묶음에 있음, 손 후보 꼴이 아닌 새 id, 근거 칸이 빠진 후보, 후보가 없는 의견.
    문제가 있어도 두 파일은 쓰고 종료 코드 1 로 끝난다(문제를 고쳐 다시 돌린다).
견주기:
  - 판정이 옮김(scripts, references, assets)이거나 의견이 옮김인 후보만 한 줄씩: id, 판정, 의견, 까닭.
  - '판정은 옮김, 의견은 둠'은 계획에서 뺄 후보다(뺀 까닭을 남긴다). '판정은 둠, 의견은 옮김'은 근거를 다시 볼 후보다.
    judge.py 의 판정을 손으로 바꾸지 않는다. 근거를 고쳐 다시 돌리거나, 계획에서 op 를 뺀다.
하지 않는 것: 스킬 파일을 읽거나 고치지 않는다. 근거를 지어 채우지 않는다. 갈 곳을 정하지 않는다.
종료 코드: 0 = 됨, 1 = 합치다 문제가 있음, 2 = 인자나 파일 문제.
"""
import argparse
import json
import sys
from pathlib import Path

if sys.version_info < (3, 8):
    sys.exit("파이썬 3.8 이상이 필요합니다(python3 --version 으로 확인).")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import judge as jd  # noqa: E402

MOVE_FACTS = [f for f, _, _ in jd.MOVE_ORDER]
SCRIPT_FACTS = [f for f, _, _ in jd.SCRIPT_ORDER]
MOVES = ("scripts", "references", "assets")
SAY = {"move": "옮김", "keep": "둠", "": "없음"}


class InputError(Exception):
    """인자나 파일 문제(종료 코드 2)."""


def read_json(path, what):
    p = Path(path)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise InputError(f"{what} 파일이 없습니다: {p}")
    except (UnicodeDecodeError, ValueError, OSError) as e:
        raise InputError(f"{what} 파일을 읽지 못했습니다: {p} ({e})")


def opinion_of(v):
    """느슨하게 읽는다: move·옮김·yes → move, keep·그대로 둠·둠·no → keep, 그 밖 → ''."""
    s = str(v or "").strip().lower()
    if s in ("move", "옮김", "옮긴다", "yes", "y"):
        return "move"
    if s in ("keep", "그대로 둠", "둠", "그대로", "no", "n"):
        return "keep"
    return ""


def merge(base, groups, only=None, skip_skills=()):
    """→ (합친 근거, 의견 모음, 문제 줄들, 숫자). groups = [(파일 이름, 묶음 dict)]."""
    cands = [c for c in base.get("candidates", []) if isinstance(c, dict) and c.get("id")]
    by_id = {c["id"]: c for c in cands}
    order = [c["id"] for c in cands]
    seen_in, problems, opinions, notes = {}, [], {}, []
    for fname, g in groups:
        if not isinstance(g, dict):
            problems.append(f"{fname}: 맨 위가 객체가 아님")
            continue
        label = str(g.get("group") or fname)
        for c in g.get("candidates") or []:
            if not isinstance(c, dict) or not c.get("id"):
                problems.append(f"{fname}: id 없는 후보")
                continue
            cid = c["id"]
            if cid in seen_in:
                problems.append(f"{fname} {cid}: 다른 묶음({seen_in[cid]})에도 있음")
                continue
            seen_in[cid] = fname
            need = SCRIPT_FACTS if jd.is_script(c) else MOVE_FACTS
            facts = c.get("facts") if isinstance(c.get("facts"), dict) else {}
            miss = [f for f in need if f not in facts]
            if miss:
                problems.append(f"{fname} {cid}: 근거 칸 없음({', '.join(miss)})")
            if cid not in by_id:
                if "#m" not in cid:
                    problems.append(f"{fname} {cid}: 원래 후보에 없는 id 인데 손 후보 꼴(<스킬>#m1)이 아님")
                order.append(cid)
            by_id[cid] = c
        for cid, o in (g.get("opinions") or {}).items():
            o = dict(o) if isinstance(o, dict) else {"why": str(o)}
            o["opinion"] = opinion_of(o.get("opinion"))
            o["group"] = label
            opinions[cid] = o
        notes += [f"[{label}] {n}" for n in g.get("notes") or []]
    for cid in opinions:
        if cid not in by_id:
            problems.append(f"의견 {cid}: 그 id 의 후보가 없음")
    only = set(only or [])
    skip = set(skip_skills or [])
    kept, dropped_scope, dropped_skill = [], 0, 0
    for cid in order:
        c = by_id[cid]
        if c.get("skill") in skip:
            dropped_skill += 1
        elif only and c.get("suggest") not in only:
            dropped_scope += 1
        else:
            kept.append(c)
    blank = [c["id"] for c in kept
             if all(jd.norm((v or {}).get("status") if isinstance(v, dict) else v) == jd.UNK for v in (c.get("facts") or {}).values())]
    merged = dict(base, candidates=kept)
    scope = []
    if only:
        scope.append("범위: " + ", ".join(sorted(only)))
    if skip:
        scope.append("뺀 스킬: " + ", ".join(sorted(skip)))
    if scope:
        merged["label"] = " · ".join(([str(base["label"])] if base.get("label") else []) + scope)
    stats = {"kept": len(kept), "manual": sum("#m" in c["id"] for c in kept), "groups": len(groups), "opinions": len(opinions),
             "dropped_scope": dropped_scope, "dropped_skill": dropped_skill, "blank": blank}
    return merged, {"opinions": opinions, "notes": notes}, problems, stats


def compare(rows, opinions):
    """→ 보여 줄 줄들. 판정이 옮김이거나 의견이 옮김인 후보만."""
    ops = opinions.get("opinions") if isinstance(opinions, dict) else {}
    lines, drop, recheck, agree = [], 0, 0, 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        o = ops.get(r.get("id")) or {}
        op = opinion_of(o.get("opinion"))
        moving = r.get("decision") in MOVES
        if not moving and op != "move":
            continue
        if moving and op == "keep":
            mark, drop = "계획에서 뺄 후보", drop + 1
        elif not moving and op == "move":
            mark, recheck = "근거를 다시 볼 후보", recheck + 1
        elif moving and op == "move":
            mark, agree = "같음", agree + 1
        else:
            mark = "의견 없음"
        lines.append(f"{r.get('id')} | 판정 {jd.DEST.get(r.get('decision'), r.get('decision'))} | 의견 {SAY[op]} | {mark} | {str(o.get('why') or '')[:120]}")
    lines.append(f"판정과 의견이 같은 옮김 {agree}개 · 계획에서 뺄 후보 {drop}개 · 근거를 다시 볼 후보 {recheck}개")
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description="묶음 근거를 합치고, 판정과 의견을 견준다(판단 없음)")
    ap.add_argument("files", nargs="+", help="합치기: evidence.json 과 묶음 파일들 / 견주기: result.json 과 opinions.json")
    ap.add_argument("--compare", action="store_true", help="판정(result.json)과 의견(opinions.json)을 견준다")
    ap.add_argument("--only", help="이번에 볼 범위(쉼표로): scripts, references, assets")
    ap.add_argument("--skip-skill", action="append", default=[], help="후보를 뺄 스킬 이름(여러 번 줄 수 있다)")
    ap.add_argument("--out", help="결과를 둘 작업폴더(없으면 evidence.json 옆)")
    a = ap.parse_args(argv)
    try:
        if a.compare:
            if len(a.files) != 2:
                raise InputError("견주기에는 result.json 과 opinions.json 두 파일을 준다")
            rows = read_json(a.files[0], "판정")
            if isinstance(rows, dict):
                rows = rows.get("results") or rows.get("candidates") or []
            if not isinstance(rows, list):
                raise InputError("판정 파일의 맨 위는 목록이어야 합니다")
            print("\n".join(compare(rows, read_json(a.files[1], "의견"))))
            return 0
        if len(a.files) < 2:
            raise InputError("합치기에는 evidence.json 과 묶음 파일을 하나 이상 준다")
        only = [x.strip() for x in (a.only or "").split(",") if x.strip()]
        bad = [x for x in only if x not in MOVES]
        if bad:
            raise InputError(f"--only 는 {', '.join(MOVES)} 가운데서: {', '.join(bad)}")
        base = jd.load(a.files[0])
        groups = [(Path(f).name, read_json(f, "묶음")) for f in a.files[1:]]
    except (InputError, jd.InputError) as e:
        print(f"입력 문제: {e}", file=sys.stderr)
        return 2
    merged, opinions, problems, st = merge(base, groups, only, a.skip_skill)
    out = Path(a.out) if a.out else Path(a.files[0]).resolve().parent
    out.mkdir(parents=True, exist_ok=True)
    (out / "evidence.merged.json").write_text(json.dumps(merged, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out / "opinions.json").write_text(json.dumps(opinions, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"묶음 {st['groups']}개 · 후보 {st['kept']}개(손 후보 {st['manual']}개) · 의견 {st['opinions']}개"
          f" · 범위 밖이라 뺀 후보 {st['dropped_scope']}개 · 스킬째 뺀 후보 {st['dropped_skill']}개")
    if st["blank"]:
        print("근거가 하나도 안 채워진 후보: " + ", ".join(st["blank"][:20]) + (" …" if len(st["blank"]) > 20 else ""))
    for p in problems:
        print("문제: " + p)
    print(f"→ {out / 'evidence.merged.json'}  ·  {out / 'opinions.json'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
