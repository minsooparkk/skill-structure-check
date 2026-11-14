#!/usr/bin/env python3
"""근거 파일(evidence.json)에 기준을 적용해 후보마다 갈 곳과 확신 정도를 정한다(3단계 판정).
판단 없음: 같은 근거에는 늘 같은 결과가 나온다. 파이썬 3.8 이상 표준 라이브러리만 쓴다.

쓰는 법:  python3 scripts/judge.py <작업폴더>/evidence.json [--out <작업폴더>]
  예: python3 scripts/judge.py ~/스킬점검/작업/evidence.json
결과(--out 이 없으면 evidence.json 옆):
  report.md               사람이 읽는 보고서(수, 확실한 것, 불확실한 것, 판단이 필요한 것, 스킬별 할 일).
                          근거 파일 맨 위에 "label" 글이 있으면 제목 아래에 한 줄로 싣는다
  result.json             후보마다 갈 곳, 확신, 까닭, 쓴 근거
  move-plan.skeleton.json references·assets 로 정해진 후보로 미리 채운 옮기기 계획 뼈대(move_sections.py 의 꼴).
                          "<채울 것>" 자리만 채워 move-plan.json 으로 따로 저장해 쓴다(이 파일은 다시 돌리면 덮인다).
먼저 '그대로 둠'으로 일찍 정하는 근거를 본다. 아래 가운데 하나만 맞아도 앞 근거가 unknown 이어도 그 근거 하나로
'그대로 둠'이 된다(쓴 근거도 그 하나): read_by_program yes, restricted_runner yes, notes_section yes,
irreversible yes, needs_judgment yes, single_command yes, observed no. 맞는 것이 없으면 아래 순서대로 간다.
옮길 후보(references·assets)의 순서. 처음 걸리는 줄대로 정한다:
  read_by_program yes → 그대로 둠 / restricted_runner yes → 그대로 둠 / notes_section yes → 그대로 둠
  / copied_verbatim yes → assets / needed_every_run no → references / needed_every_run yes → 그대로 둠
스크립트 후보의 순서:
  irreversible yes → 그대로 둠(읽기·준비 단계만 따로 뺄 수 있는지 본다) / needs_judgment yes → 그대로 둠
  / single_command yes → 그대로 둠 / observed no → 그대로 둠(처음 실제로 해 본 뒤에) / 그 밖 → scripts
확신:
  확실(정하는 데 쓴 근거마다 why 나 source 가 있음) / 불확실(비어 있음, 다시 확인) / 판단 필요(가다가 unknown 에서 멈춤)
손으로 더한 후보(id 가 <스킬>#m1 꼴, signals ["manual"])도 같은 꼴이면 똑같이 판정하고 뼈대 계획에 넣는다.
값은 느슨하게 읽는다: yes·y·true·예·네·있음 → yes, no·n·false·아니오·아니요·없음 → no, 그 밖 → unknown.
하지 않는 것: 스킬 파일을 읽거나 고치지 않는다. 근거를 지어 채우지 않는다.
종료 코드: 0 = 됨, 2 = 근거 파일 문제(없음, JSON 아님, 맨 위가 객체가 아님, candidates 가 목록이 아님).
"""
import argparse
import json
import re
import sys
from pathlib import Path

if sys.version_info < (3, 8):
    sys.exit("파이썬 3.8 이상이 필요합니다(python3 --version 으로 확인).")

YES, NO, UNK = "yes", "no", "unknown"
FILL = "<채울 것>"
SAY = {YES: "예", NO: "아니오", UNK: "모름"}
DEST = {"keep": "그대로 둠", "scripts": "scripts 로", "references": "references 로", "assets": "assets 로", "undecided": "미정"}
DEST_ORDER = ["scripts", "references", "assets", "keep", "undecided"]
CONF_ORDER = ["확실", "불확실", "판단 필요"]
LABEL = {
    "read_by_program": "프로그램이 본문을 읽음",
    "restricted_runner": "좁은 권한 실행이 읽음",
    "notes_section": "배운 것을 적어 가는 자리",
    "copied_verbatim": "그대로 베껴 쓰는 글",
    "needed_every_run": "일할 때마다 필요",
    "irreversible": "되돌릴 수 없는 동작",
    "needs_judgment": "판단이 본체",
    "single_command": "명령 한 줄",
    "observed": "실제로 본 적 있음",
}
# (fact, {값: (갈 곳, 까닭)}, unknown 일 때 확인할 것)
MOVE_ORDER = [
    ("read_by_program", {YES: ("keep", "프로그램이 이 문서 본문을 읽는다. 옮기면 그 프로그램이 이 글을 못 본다")},
     "프로그램(예약 스크립트, 시험)이 이 SKILL.md 본문을 읽는지. evidence 의 consumers 에 적힌 파일을 열어 본다"),
    ("restricted_runner", {YES: ("keep", "도구나 권한이 좁은 실행이 이 글을 보고 일한다. 다른 파일을 못 열 수 있다")},
     "도구나 권한이 좁은 실행(예약 회차, 다른 파일을 못 여는 모델)이 이 글을 보고 일하는지"),
    ("notes_section", {YES: ("keep", "새로 배운 것을 적어 가는 자리다. 일하며 바로 적어야 한다")},
     "새로 배운 것을 날짜와 함께 적어 가는 자리인지"),
    ("copied_verbatim", {YES: ("assets", "산출물에 그대로 베껴 쓰거나 스크립트가 읽는 글이다")},
     "산출물에 그대로 베껴 쓰거나 스크립트가 읽는 글인지"),
    ("needed_every_run", {NO: ("references", "일할 때마다 읽을 필요가 없다"), YES: ("keep", "일할 때마다 읽어야 한다")},
     "일할 때마다 읽어야 하는지. 절차 본문이 이 절을 가리키는지 본다"),
]
SCRIPT_ORDER = [
    ("irreversible", {YES: ("keep", "보내기·지우기·결제처럼 되돌릴 수 없는 동작이 섞였다. 읽기·준비 단계만 따로 뺄 수 있는지 본다")},
     "보내기·지우기·결제처럼 되돌릴 수 없는 동작이 섞였는지"),
    ("needs_judgment", {YES: ("keep", "판단이 본체다(읽고 고르고 쓰는 일)")},
     "판단이 본체인지(읽고 고르고 쓰는 일인지)"),
    ("single_command", {YES: ("keep", "명령 한 줄로 끝난다. 감싸면 관리할 것만 는다")},
     "명령 한 줄로 끝나는지"),
    ("observed", {NO: ("keep", "실제 화면이나 출력을 본 적이 없다. 처음 실제로 해 본 뒤에 뺀다"),
                  YES: ("scripts", "정해진 순서대로 하는 일이고 실제 출력을 본 적이 있다")},
     "그 절차의 실제 화면이나 출력을 본 적이 있는지"),
]


# 하나만 맞아도 '그대로 둠'이 되는 근거. copied_verbatim 과 needed_every_run 은 여기 없다(앞 근거가 모두 no 여야 간다).
EARLY_KEEP = {("read_by_program", YES), ("restricted_runner", YES), ("notes_section", YES),
              ("irreversible", YES), ("needs_judgment", YES), ("single_command", YES), ("observed", NO)}


class InputError(Exception):
    pass


def norm(v):
    v = str(v if v is not None else "").strip().lower()
    return {"예": YES, "네": YES, "있음": YES, "y": YES, "true": YES, "yes": YES,
            "아니오": NO, "아니요": NO, "없음": NO, "n": NO, "false": NO, "no": NO}.get(v, UNK)


def _fact(facts, name):
    f = facts.get(name) if isinstance(facts, dict) else None
    if not isinstance(f, dict):
        f = {"status": f} if isinstance(f, str) else {}
    return {"fact": name, "status": norm(f.get("status")), "why": str(f.get("why") or "").strip(),
            "source": str(f.get("source") or "").strip()}


def is_script(c):
    facts = c.get("facts") if isinstance(c.get("facts"), dict) else {}
    if any(k in facts for k in ("irreversible", "needs_judgment", "single_command", "observed")):
        return True
    if any(k in facts for k in ("read_by_program", "needed_every_run", "copied_verbatim")):
        return False
    return c.get("suggest") == "scripts"


def judge(c):
    """후보 하나 → 결과 dict."""
    order = SCRIPT_ORDER if is_script(c) else MOVE_ORDER
    facts = c.get("facts")
    used = []
    dest, reason, ask = "undecided", "", ""
    # 먼저 '그대로 둠'으로 일찍 정하는 근거를 순서대로 훑는다. 하나만 맞아도 그 근거 하나로 정한다.
    for name, outcomes, question in order:
        f = _fact(facts, name)
        hit = outcomes.get(f["status"])
        if hit and hit[0] == "keep" and (name, f["status"]) in EARLY_KEEP:
            dest, reason = hit
            used = [f]
            break
    for name, outcomes, question in ([] if used else order):
        f = _fact(facts, name)
        used.append(f)
        if f["status"] == UNK:
            ask = question
            reason = f"'{LABEL[name]}' 을 아직 모른다"
            break
        if f["status"] in outcomes:
            dest, reason = outcomes[f["status"]]
            break
    missing = [f["fact"] for f in used if f["status"] != UNK and not (f["why"] or f["source"])]
    if dest == "undecided":
        conf = "판단 필요"
    elif missing:
        conf = "불확실"
    else:
        conf = "확실"
    return {"id": str(c.get("id", "?")), "skill": str(c.get("skill", "?")), "target": c.get("target") if isinstance(c.get("target"), dict) else {},
            "suggest": c.get("suggest", ""), "signals": c.get("signals", []), "kind": "scripts" if is_script(c) else "move",
            "decision": dest, "confidence": conf, "reason": reason, "ask": ask, "used": used, "missing": missing,
            "note": str(c.get("note") or "")}


def load(path):
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise InputError(f"근거 파일이 없습니다: {p}")
    except (UnicodeDecodeError, ValueError, OSError) as e:
        raise InputError(f"근거 파일을 읽지 못했습니다: {e}")
    if not isinstance(data, dict):
        raise InputError("근거 파일의 맨 위는 객체여야 합니다")
    if not isinstance(data.get("candidates"), list):
        raise InputError("근거 파일에 candidates 목록이 없습니다")
    return data


def judge_all(data):
    rows, bad = [], 0
    for c in data["candidates"]:
        if not isinstance(c, dict):
            bad += 1
            continue
        rows.append(judge(c))
    return rows, bad


# ------------------------------------------------------------------ 보고서

def where(t):
    line, n = t.get("line", "?"), t.get("lines", "?")
    kind = t.get("kind")
    if kind == "section":
        return f"절 \"{t.get('title', '')}\" (SKILL.md:{line}, {n}줄)"
    if kind == "block":
        lang = f" {t['lang']}" if t.get("lang") else ""
        return f"코드 블록{lang} (SKILL.md:{line}, {n}줄, \"{t.get('title', '')}\" 안)"
    return f"줄 묶음 (SKILL.md:{line}, {n}줄, \"{t.get('title', '')}\" 안)"


def evid(f):
    tail = " · ".join(x for x in (f["why"], f"`{f['source']}`" if f["source"] else "") if x)
    return f"{LABEL.get(f['fact'], f['fact'])} = {SAY[f['status']]}" + (f" · {tail}" if tail else " · (근거 비어 있음)")


def skill_names(data, rows):
    names = list(data.get("skills", {}).keys()) if isinstance(data.get("skills"), dict) else []
    for r in rows:
        if r["skill"] not in names:
            names.append(r["skill"])
    return names


def report(data, rows, bad=0):
    names = skill_names(data, rows)
    label = str(data.get("label") or "").strip()
    L = ["# 스킬 구조 점검 결과", ""] + ([f"> {label}", ""] if label else []) + [f"스킬 {len(names)}개 · 후보 {len(rows)}개" + (f" · 읽지 못한 후보 {bad}개" if bad else ""), ""]
    L += ["| 갈 곳 | 수 |", "|---|---|"]
    for d in DEST_ORDER:
        L.append(f"| {DEST[d]} | {sum(1 for r in rows if r['decision'] == d)} |")
    L += ["", "| 확신 | 수 |", "|---|---|"]
    for c in CONF_ORDER:
        L.append(f"| {c} | {sum(1 for r in rows if r['confidence'] == c)} |")
    heads = {"확실": ("확실한 것", ""), "불확실": ("불확실한 것", ": 비어 있는 근거를 채워 다시 판정"),
             "판단 필요": ("판단이 필요한 것", ": 확인할 것을 보고 근거를 채워 다시 판정")}
    for conf in CONF_ORDER:
        xs = [r for r in rows if r["confidence"] == conf]
        L += ["", f"## {heads[conf][0]} ({len(xs)}){heads[conf][1]}", ""]
        if not xs:
            L.append("- 없음")
        for r in xs:
            L.append(f"### {r['id']} · {DEST[r['decision']]}")
            L.append(f"- 대상: {where(r['target'])} · 신호 {', '.join(map(str, r['signals']))}")
            L.append(f"- 까닭: {r['reason']}")
            for f in r["used"]:
                if f["status"] != UNK:
                    L.append(f"- 근거: {evid(f)}")
            for m in r["missing"]:
                L.append(f"- 비어 있는 근거: {LABEL.get(m, m)} (why 와 source 가 모두 비어 있음)")
            if r["ask"]:
                L.append(f"- 확인할 것: {r['ask']}")
            if r["note"]:
                L.append(f"- 메모: {r['note']}")
            L.append("")
        if L[-1] == "":
            L.pop()
    L += ["", "## 스킬별 할 일"]
    verb = {"scripts": "스크립트로 만들기", "references": "references 로 옮기기", "assets": "assets 로 옮기기"}
    for name in names:
        xs = [r for r in rows if r["skill"] == name]
        L += ["", f"### {name}", ""]
        if not xs:
            L.append("- 후보 없음. 손대지 않는다.")
            continue
        for d in ("scripts", "references", "assets"):
            for r in xs:
                if r["decision"] == d:
                    L.append(f"- [ ] {verb[d]}: {r['id']} {where(r['target'])} [{r['confidence']}]")
        for r in xs:
            if r["decision"] == "undecided":
                L.append(f"- [ ] 정하기: {r['id']} {r['ask']}")
        keep = [r for r in xs if r["decision"] == "keep"]
        if keep:
            L.append("- 그대로 둠: " + ", ".join(f"{r['id']}({r['reason'].split('.')[0]})" for r in keep))
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ 옮기기 계획 뼈대

def slug(title, fallback):
    t = re.sub(r"^#+\s*", "", str(title or "")).strip()
    t = re.sub(r"\([^)]*\)", "", t)
    t = re.sub(r"^\d+[.)]\s*", "", t).strip()
    t = re.sub(r"[^\w\s-]", "", t, flags=re.UNICODE)
    t = re.sub(r"[\s_]+", "-", t).strip("-").lower()
    return t[:40].strip("-") or fallback


EXT = {"md": ".md", "markdown": ".md", "html": ".html", "json": ".json", "yaml": ".yaml", "yml": ".yaml", "csv": ".csv"}


def skeleton(data, rows):
    plan = {"_about": "\"<채울 것>\" 을 모두 채우고 move-plan.json 으로 저장한 뒤 scripts/move_sections.py 로 먼저 대조만 한다. 맞지 않는 op 는 지운다.",
            "root": str(data.get("root", "")) or FILL, "note": FILL + ": 언제 왜 옮겼는지 한 줄", "skills": {}}
    for r in rows:
        if r["decision"] not in ("references", "assets"):
            continue
        t = r["target"]
        sk = plan["skills"].setdefault(r["skill"], {"refs": {}, "ops": [], "allow_lost": 0, "bump_version": True})
        name = slug(t.get("title"), r["id"].split("#")[-1])
        raw = r["decision"] == "assets"
        if t.get("kind") == "section":
            dest = f"{r['decision']}/{name}.md"
            op = {"kind": "section", "head": t.get("title", FILL), "dest": dest, "pointer": [FILL], "keep_heading": True}
        elif t.get("kind") == "block":
            dest = f"{r['decision']}/{name}{EXT.get(t.get('lang', ''), '.txt') if raw else '.md'}"
            op = {"kind": "block", "start": t.get("before") or FILL, "extra": 0, "dest": dest, "pointer": [FILL]}
        else:
            dest = f"{r['decision']}/{name}.md"
            op = {"kind": "to", "start": FILL, "end": FILL + "(선택. 없으면 이 열쇠를 지운다)", "dest": dest, "pointer": [FILL]}
        if raw:
            op["raw"] = True
        else:
            sk["refs"].setdefault(dest, {"title": re.sub(r"^#+\s*", "", str(t.get("title", ""))).strip() or FILL, "when": FILL + ": 언제 읽는지"})
        op["_from"] = f"{r['id']} [{r['confidence']}]"
        sk["ops"].append(op)
    return plan


def main(argv=None):
    ap = argparse.ArgumentParser(description="근거 파일에 기준을 적용해 갈 곳과 확신을 정한다(판단 없음)")
    ap.add_argument("evidence")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    try:
        data = load(a.evidence)
    except InputError as e:
        print(str(e), file=sys.stderr)
        return 2
    rows, bad = judge_all(data)
    out = Path(a.out) if a.out else Path(a.evidence).parent
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out / "report.md").write_text(report(data, rows, bad), encoding="utf-8")
    (out / "move-plan.skeleton.json").write_text(json.dumps(skeleton(data, rows), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    conf = " · ".join(f"{c} {sum(1 for r in rows if r['confidence'] == c)}" for c in CONF_ORDER)
    dest = " · ".join(f"{DEST[d]} {sum(1 for r in rows if r['decision'] == d)}" for d in DEST_ORDER)
    print(f"후보 {len(rows)}개 판정 → {out / 'report.md'}")
    print(f"  {conf}")
    print(f"  {dest}" + (f"  (읽지 못한 후보 {bad}개)" if bad else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
