#!/usr/bin/env python3
"""옮기기 계획(JSON)대로 SKILL.md 의 일부를 references·assets 로 글자 그대로 옮기고 그 자리에 가리키는 줄을 둔다(5단계).
먼저 임시 폴더에 새 SKILL.md 와 딸린 파일을 만들고 줄 대조를 한다. --apply 를 줄 때만 실제 스킬 폴더를 바꾼다.
파이썬 3.8 이상 표준 라이브러리만 쓴다.

쓰는 법:
  python3 scripts/move_sections.py <계획.json> [--root <스킬들이 든 폴더>] [--stage <임시 폴더>]
                                    [--apply] [--backup-dir <폴더>] [--force]
  예: python3 scripts/move_sections.py ~/스킬점검/작업/move-plan.json --root ~/.claude/skills          (대조만)
      python3 scripts/move_sections.py ~/스킬점검/작업/move-plan.json --root ~/.claude/skills --apply  (바꿈)
계획의 op(고르는 자리는 그 SKILL.md 에서 정확히 한 번 나와야 한다):
  section  head 와 똑같은 제목 줄(코드 블록 밖)부터 같거나 높은 단계의 다음 제목 앞까지. keep_heading 이면 제목 줄을 남긴다.
  to       start 가 든 줄부터 end 가 든 줄 앞까지(end 가 없으면 끝까지).
  block    start 가 든 줄 바로 다음의 코드 블록(+ 뒤 extra 줄). start 줄은 남는다. raw 이면 울타리 줄(```)을 뺀다.
  insert   anchor 가 든 줄 앞(where: before) 이나 뒤(after, 기본)에 text 줄들을 넣는다.
  replace  anchor 가 든 줄에서 old(그 줄에 한 번) 를 new 로 바꾼다.
references 로 가는 글 맨 위 머리: "# <스킬> · <title>" / "> <스킬> 스킬의 딸린 자료다. <when>." / "> <note>". raw 이면 머리 없이.
줄 대조: 원래 SKILL.md 의 빈 줄 아닌 모든 줄(울타리 줄, 올린 version 줄 빼고)이 새 SKILL.md 나 딸린 파일(이미 있는
  references·assets 포함) 어딘가에 그대로 있어야 한다. 빠진 줄 수가 replace 수 + allow_lost 를 넘으면 그 스킬은 실패.
  고른 자리끼리 겹치거나, 코드 블록을 반만 골라 새 SKILL.md 에 닫히지 않은 블록이 생겨도 그 스킬은 만들지 않는다.
--apply: 하나라도 실패면 아무것도 바꾸지 않는다. 스킬마다 ① 만들 때 읽은 원본과 지금 원본의 해시를 견주고(다르면 건너뜀)
  ② 원본을 사본 폴더(기본 <root>/.skill-backup/<날짜-시각>/<스킬>/SKILL.md)에 두고 ③ 딸린 파일을 쓰고(같은 이름이
  이미 있으면 --force 없이는 그 스킬을 건너뜀) ④ SKILL.md 를 임시 파일에 쓴 뒤 바꿔 끼운다(권한은 원래 파일 그대로,
  새 파일은 보통 새 파일 권한). --stage 없이 돌려 스스로 만든 임시 폴더는 --apply 가 모두 성공하면 지운다
  (대조만 했거나 실패했으면 남기고 자리를 찍는다).
하지 않는 것: 옮길 글을 고쳐 쓰지 않는다. 계획에 없는 곳을 건드리지 않는다. git 을 쓰지 않는다.
종료 코드: 0 = 됨, 1 = 못 만든 스킬, 대조 실패, 건너뛴 스킬이 있음, 2 = 계획 파일이나 인자 문제.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

if sys.version_info < (3, 8):
    sys.exit("파이썬 3.8 이상이 필요합니다(python3 --version 으로 확인).")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inventory import code_mask, headings, nfc, parse_front  # noqa: E402

FILL = "<채울 것"
KINDS = ("section", "to", "block", "insert", "replace")
FENCE_ONLY = re.compile(r"^\s*(`{3,}|~{3,})[\w+-]*\s*$")
VERSION = re.compile(r'^(\s*version:\s*)(["\']?)(\d+)\.(\d+)\.(\d+)(["\']?)\s*$')


class PlanError(Exception):
    """계획 파일 문제(종료 코드 2)."""


class BuildError(Exception):
    """그 스킬을 만들 수 없음(자리가 없거나 두 번, 겹침 등)."""


# ------------------------------------------------------------------ 계획 읽기

def _dest_ok(dest):
    d = str(dest or "")
    parts = d.split("/")
    return (parts[0] in ("references", "assets") and len(parts) >= 2 and all(p and p not in (".", "..") for p in parts)
            and "\\" not in d and not d.startswith("/"))


def unfilled(x, path="plan"):
    """'<채울 것' 이 남은 자리. '_' 로 시작하는 열쇠(설명)는 보지 않는다."""
    if isinstance(x, dict):
        return [p for k, v in x.items() if not str(k).startswith("_") for p in unfilled(v, f"{path}.{k}")]
    if isinstance(x, list):
        return [p for n, v in enumerate(x) for p in unfilled(v, f"{path}[{n}]")]
    return [path] if isinstance(x, str) and FILL in x else []


def check_plan(plan):
    """계획의 꼴을 본다. 문제가 있으면 PlanError."""
    if not isinstance(plan, dict):
        raise PlanError("계획의 맨 위는 객체여야 합니다")
    skills = plan.get("skills")
    if not isinstance(skills, dict) or not skills:
        raise PlanError("계획에 skills 객체가 없습니다")
    left = unfilled(plan)
    if left:
        raise PlanError(f"계획에 '<채울 것>' 자리가 남아 있습니다: {', '.join(left[:5])}")
    for name, sk in skills.items():
        if not isinstance(sk, dict) or not isinstance(sk.get("ops"), list):
            raise PlanError(f"{name}: ops 목록이 없습니다")
        refs = sk.get("refs", {})
        if not isinstance(refs, dict):
            raise PlanError(f"{name}: refs 는 객체여야 합니다")
        if not isinstance(sk.get("allow_lost", 0), int) or sk.get("allow_lost", 0) < 0:
            raise PlanError(f"{name}: allow_lost 는 0 이상의 정수여야 합니다")
        raw_of = {}
        for n, op in enumerate(sk["ops"], 1):
            if not isinstance(op, dict) or op.get("kind") not in KINDS:
                raise PlanError(f"{name} op{n}: kind 는 {', '.join(KINDS)} 가운데 하나")
            k = op["kind"]
            need = {"section": ["head", "dest"], "to": ["start", "dest"], "block": ["start", "dest"],
                    "insert": ["anchor", "text"], "replace": ["anchor", "old", "new"]}[k]
            for f in need:
                if f not in op or (f != "new" and not op[f]):
                    raise PlanError(f"{name} op{n}({k}): {f} 가 비었습니다")
            if k in ("section", "to", "block"):
                if not _dest_ok(op["dest"]):
                    raise PlanError(f"{name} op{n}: dest 는 references/… 나 assets/… 꼴의 상대 경로여야 합니다: {op['dest']}")
                raw = bool(op.get("raw"))
                if raw_of.setdefault(op["dest"], raw) != raw:
                    raise PlanError(f"{name}: 같은 dest 에 raw 와 raw 아님이 섞였습니다: {op['dest']}")
                p = op.get("pointer", [])
                if isinstance(p, str):
                    op["pointer"] = [p]
                elif not isinstance(p, list) or not all(isinstance(x, str) for x in p):
                    raise PlanError(f"{name} op{n}: pointer 는 글 줄의 목록이어야 합니다")
            if k == "insert":
                if isinstance(op["text"], str):
                    op["text"] = [op["text"]]
                if op.get("where", "after") not in ("after", "before"):
                    raise PlanError(f"{name} op{n}: where 는 after 나 before")
            if k == "block" and (not isinstance(op.get("extra", 0), int) or op.get("extra", 0) < 0):
                raise PlanError(f"{name} op{n}: extra 는 0 이상의 정수")
    return plan


# ------------------------------------------------------------------ 고르기

def find_once(lines, needle, what):
    hits = [i for i, ln in enumerate(lines) if needle in ln]
    if len(hits) != 1:
        raise BuildError(f"{what} 자리가 {len(hits)}번 나옴: {needle[:60]}")
    return hits[0]


def trim(lines, a, b):
    while b > a + 1 and not lines[b - 1].strip():
        b -= 1
    return a, b


def sel_section(lines, mask, body, head):
    hs = headings(lines, mask, body)
    hit = [(i, lv) for i, lv, t in hs if t.strip() == head.strip()]
    if len(hit) != 1:
        raise BuildError(f"제목이 {len(hit)}번 나옴(코드 블록 밖): {head[:60]}")
    i, lv = hit[0]
    end = next((j for j, l2, _ in hs if j > i and l2 <= lv), len(lines))
    return trim(lines, i, end)


def sel_to(lines, start, end=None):
    a = find_once(lines, start, "start")
    b = len(lines)
    if end:
        b = find_once(lines, end, "end")
        if b <= a:
            raise BuildError(f"end 가 start 보다 앞에 있음: {end[:60]}")
    return trim(lines, a, b)


def sel_block(lines, blocks, start, extra=0):
    a = find_once(lines, start, "start")
    j = a + 1
    while j < len(lines) and not lines[j].strip():
        j += 1
    blk = next((b for b in blocks if b["open"] == j), None)
    if blk is None:
        raise BuildError(f"start 줄 바로 뒤에 코드 블록이 없음: {start[:60]}")
    if not blk["closed"]:
        raise BuildError(f"코드 블록이 닫히지 않음: {start[:60]}")
    end = blk["close"] + 1 + extra
    if end > len(lines):
        raise BuildError(f"extra 줄이 문서 끝을 넘음: {start[:60]}")
    return j, end


def bump(lines, body):
    """머리 안의 version: "a.b.c" 가운데 자리를 하나 올린다. → (바꿨는지, 옛 줄)"""
    for i in range(1, max(1, body - 1)):
        m = VERSION.match(lines[i])
        if m and m.group(2) == m.group(6):
            old = lines[i]
            lines[i] = f"{m.group(1)}{m.group(2)}{m.group(3)}.{int(m.group(4)) + 1}.0{m.group(6)}"
            return True, old
    return False, ""


def header(skill, title, when, note):
    L = [f"# {skill} · {title}", ""]
    w = str(when or "").strip()
    L.append(f"> {skill} 스킬의 딸린 자료다." + (f" {w}" + ("" if w.endswith(".") else ".") if w else ""))
    if str(note or "").strip():
        L.append(f"> {str(note).strip()}")
    return L + [""]


def build(skill, text, spec, note=""):
    """→ (새 SKILL.md 글, {딸린 파일: 글}, 옛 version 줄 또는 ""). 자리가 맞지 않으면 BuildError."""
    lines = text.split("\n")
    _, body, _ = parse_front(text)
    blocks, mask = code_mask(lines, body)
    todo = []
    for op in spec["ops"]:
        k = op["kind"]
        if k == "section":
            a, b = sel_section(lines, mask, body, op["head"])
        elif k == "to":
            a, b = sel_to(lines, op["start"], op.get("end"))
        elif k == "block":
            a, b = sel_block(lines, blocks, op["start"], op.get("extra", 0))
        elif k == "insert":
            i = find_once(lines, op["anchor"], "anchor")
            a = b = i + 1 if op.get("where", "after") == "after" else i
        else:
            i = find_once(lines, op["anchor"], "anchor")
            if lines[i].count(op["old"]) != 1:
                raise BuildError(f"old 가 그 줄에 {lines[i].count(op['old'])}번: {op['old'][:40]}")
            a, b = i, i + 1
        todo.append((a, b, op))
    spans = sorted((a, b) for a, b, op in todo if op["kind"] != "insert")
    for (a1, b1), (a2, b2) in zip(spans, spans[1:]):
        if a2 < b1:
            raise BuildError(f"옮길 자리가 겹침: {a1 + 1}-{b1}줄 · {a2 + 1}-{b2}줄")
    for a, b, op in todo:
        if op["kind"] == "insert" and any(s < a < e for s, e in spans):
            raise BuildError(f"넣을 자리가 옮길 자리 안에 있음: {op['anchor'][:40]}")
    out = list(lines)
    moved = {}
    raw_of = {}
    for a, b, op in sorted(todo, key=lambda t: (t[0], 0 if t[2]["kind"] == "insert" else 1), reverse=True):
        k = op["kind"]
        if k == "insert":
            out[a:a] = list(op["text"])
            continue
        if k == "replace":
            out[a] = lines[a].replace(op["old"], op["new"])
            continue
        chunk = lines[a:b]
        raw = bool(op.get("raw"))
        if k == "block" and raw:
            close = next(bl["close"] for bl in blocks if bl["open"] == a)
            chunk = lines[a + 1:close] + lines[close + 1:b]
        moved.setdefault(op["dest"], []).append((a, chunk))
        raw_of[op["dest"]] = raw
        pointer = list(op.get("pointer", []))
        if k == "section" and op.get("keep_heading"):
            out[a:b] = [lines[a]] + ([""] + pointer if pointer else [])
        else:
            out[a:b] = pointer
    files = {}
    refs = spec.get("refs", {})
    for dest, chunks in moved.items():
        body_text = "\n\n".join("\n".join(c) for _, c in sorted(chunks, key=lambda x: x[0])).rstrip()
        if raw_of[dest]:
            files[dest] = body_text + "\n"
            continue
        info = refs.get(dest) if isinstance(refs.get(dest), dict) else {}
        title = info.get("title") or Path(dest).stem.replace("-", " ")
        files[dest] = "\n".join(header(skill, title, info.get("when", ""), note)) + "\n" + body_text + "\n"
    if all(bl["closed"] for bl in blocks):
        new_blocks, _ = code_mask(out, body)
        if not all(bl["closed"] for bl in new_blocks):
            raise BuildError("옮긴 뒤 SKILL.md 에 닫히지 않은 코드 블록이 생김(코드 블록을 반만 고름)")
    old_version = ""
    if spec.get("bump_version"):
        _, front_end, ferr = parse_front("\n".join(out))
        if not ferr:
            changed, old_version = bump(out, front_end)
    return "\n".join(out), files, old_version


def key(ln):
    return re.sub(r"\s+", " ", nfc(ln).strip())


def lost_lines(old, new, files, extra=(), skip=()):
    """원래 문서의 줄 가운데 새 SKILL.md·딸린 파일·이미 있는 딸린 파일 어디에도 없는 줄."""
    have = set()
    for t in [new] + list(files.values()) + list(extra):
        have.update(key(ln) for ln in t.split("\n"))
    skip = set(key(s) for s in skip)
    return [ln for ln in old.split("\n") if key(ln) and key(ln) not in have and key(ln) not in skip and not FENCE_ONLY.match(ln)]


def existing_extra(skill_dir):
    out = []
    for kind in ("references", "assets"):
        base = skill_dir / kind
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file() and not p.name.startswith("."):
                try:
                    out.append(p.read_text(encoding="utf-8"))
                except (UnicodeDecodeError, OSError):
                    pass
    return out


def skill_dir_of(root, name):
    want = nfc(name)
    p = root / name
    if (p / "SKILL.md").is_file():
        return p
    for child in root.iterdir() if root.is_dir() else []:
        if nfc(child.name) == want and (child / "SKILL.md").is_file():
            return child
    return None


def kb(n):
    return f"{n / 1000:.1f}KB"


def new_file_mode():
    """보통 새 파일 권한: 0o666 에서 umask 를 뺀 값."""
    mask = os.umask(0)
    os.umask(mask)
    return 0o666 & ~mask


def write_atomic(path, text):
    """임시 파일에 쓴 뒤 바꿔 끼운다. 이미 있는 파일이면 그 권한을, 새 파일이면 보통 새 파일 권한을 쓴다
    (mkstemp 는 600 으로 만들어서 그대로 두면 권한이 바뀐다)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = os.stat(str(path)).st_mode & 0o7777
    except OSError:
        mode = new_file_mode()
    fd, tmp = tempfile.mkstemp(prefix=".move-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, str(path))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def inside(child, parent):
    try:
        Path(child).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False


def main(argv=None, now=None):
    ap = argparse.ArgumentParser(description="계획대로 references·assets 로 옮긴다(먼저 대조만, --apply 로 바꿈)")
    ap.add_argument("plan")
    ap.add_argument("--root", help="스킬들이 든 폴더(없으면 계획의 root)")
    ap.add_argument("--stage", help="새 문서를 먼저 만들 임시 폴더(없으면 새 임시 폴더)")
    ap.add_argument("--apply", action="store_true", help="대조가 모두 맞으면 실제로 바꾼다")
    ap.add_argument("--backup-dir", help="원본 사본을 둘 폴더(기본 <root>/.skill-backup/<날짜-시각>)")
    ap.add_argument("--force", action="store_true", help="같은 이름의 딸린 파일이 있어도 덮는다(덮기 전 사본을 뜬다)")
    a = ap.parse_args(argv)
    now = now or datetime.now()
    try:
        try:
            plan = json.loads(Path(a.plan).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as e:
            raise PlanError(f"계획 파일을 읽지 못했습니다: {e}")
        check_plan(plan)
        root_s = a.root or plan.get("root")
        if not root_s:
            raise PlanError("--root 도 계획의 root 도 없습니다")
        root = Path(os.path.expanduser(str(root_s)))
        if not root.is_dir():
            raise PlanError(f"root 폴더가 없습니다: {root}")
        own_stage = not a.stage           # 스스로 만든 임시 폴더만 지운다(--stage 로 받은 폴더는 두고)
        stage = Path(a.stage) if a.stage else Path(tempfile.mkdtemp(prefix="skill-move-"))
        if inside(stage, root) or inside(root, stage):
            raise PlanError("--stage 는 root 와 겹치지 않는 폴더여야 합니다")
        backup = Path(a.backup_dir) if a.backup_dir else root / ".skill-backup" / now.strftime("%Y-%m-%d-%H%M%S")
    except PlanError as e:
        print(f"계획 문제: {e}", file=sys.stderr)
        return 2

    note = str(plan.get("note") or "")
    ok, done = True, []
    for name, spec in plan["skills"].items():
        sdir = skill_dir_of(root, name)
        if sdir is None:
            print(f"못 만듦  {name}: {root} 아래에 이 스킬 폴더가 없음")
            ok = False
            continue
        path = sdir / "SKILL.md"
        try:
            old = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(f"못 만듦  {name}: SKILL.md 를 읽지 못함({e.__class__.__name__})")
            ok = False
            continue
        digest = hashlib.sha256(old.encode("utf-8")).hexdigest()
        try:
            new, files, old_version = build(nfc(name), old, spec, note)
        except BuildError as e:
            print(f"못 만듦  {name}: {e}")
            ok = False
            continue
        lost = lost_lines(old, new, files, existing_extra(sdir), [old_version] if old_version else [])
        allowed = sum(1 for op in spec["ops"] if op["kind"] == "replace") + spec.get("allow_lost", 0)
        d = stage / nfc(name)
        write_atomic(d / "SKILL.md", new)
        for rel, txt in files.items():
            write_atomic(d / rel, txt)
        clash = [rel for rel in files if (sdir / rel).exists()]
        state = "맞음" if len(lost) <= allowed else f"빠진 줄 {len(lost)}개(허용 {allowed})"
        print(f"{name}: SKILL.md {kb(len(old.encode('utf-8')))}({old.count(chr(10))}줄) → {kb(len(new.encode('utf-8')))}({new.count(chr(10))}줄)"
              f" · 딸린 파일 {len(files)}개 · 줄 대조 {state}" + (f" · 이미 있는 파일 {len(clash)}개" if clash else ""))
        if len(lost) > allowed:
            ok = False
            for ln in lost[:10]:
                print(f"    빠짐: {ln.strip()[:100]}")
            continue
        done.append((name, sdir, path, digest, new, files, clash))
    print(f"만든 곳: {stage}")
    if not ok:
        print("못 만들었거나 대조가 안 맞는 스킬이 있어 아무것도 바꾸지 않음")
        return 1
    if not a.apply:
        print("대조만 했다. 바꾸려면 --apply 를 붙여 다시 돌린다.")
        return 0

    undo = []
    for name, sdir, path, digest, new, files, clash in done:
        now_text = path.read_text(encoding="utf-8")
        if hashlib.sha256(now_text.encode("utf-8")).hexdigest() != digest:
            print(f"건너뜀  {name}: 그 사이 원본이 바뀜")
            ok = False
            continue
        if clash and not a.force:
            print(f"건너뜀  {name}: 같은 이름의 딸린 파일이 이미 있음({', '.join(clash)}). 덮으려면 --force")
            ok = False
            continue
        bdir = backup / nfc(name)
        bfile = bdir / "SKILL.md"
        n = 1
        while bfile.exists():
            n += 1
            bfile = bdir / f"SKILL.md.{n}"
        bfile.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(path), str(bfile))
        for rel in clash:
            shutil.copyfile(str(sdir / rel), str(bdir / rel.replace("/", "__")))
        for rel, txt in files.items():
            write_atomic(sdir / rel, txt)
        write_atomic(path, new)
        print(f"바꿔 끼움  {name}  (사본 {bfile})")
        undo.append((bfile, path, [sdir / rel for rel in files if rel not in clash]))
    if undo:
        print("되돌리기:")
        for bfile, path, made in undo:
            print(f'  cp "{bfile}" "{path}"')
            for m in made:
                print(f'  rm "{m}"')
    if ok and own_stage:
        shutil.rmtree(str(stage), ignore_errors=True)
        print(f"임시 폴더를 지웠다: {stage}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
