#!/usr/bin/env python3
"""스킬 폴더를 훑어 크기, 머리, 절, 코드 블록, 이미 있는 딸린 파일과 옮길 후보를 모은다(1단계 훑기).
판단 없음, 읽기 전용(쓰는 곳은 --out 폴더뿐). 파이썬 3.8 이상 표준 라이브러리만 쓴다.

쓰는 법:
  python3 scripts/inventory.py <스킬 폴더 | 스킬들이 든 폴더> [--repo <저장소 뿌리>] [--out <작업폴더>]
                               [--max-lines 500] [--max-bytes 20000] [--signals <낱말 파일>]
  예: python3 scripts/inventory.py ~/.claude/skills --repo ~/my-project --out ~/스킬점검/작업
스킬 찾기:
  준 폴더에 SKILL.md 가 있으면 그 하나, 없으면 바로 아래 폴더 가운데 SKILL.md 가 있는 것(바로가기 폴더도 따라간다).
--repo:
  그 저장소의 글 파일(py, js, ts, sh, yaml, json, toml 등. .git, node_modules, __pycache__, 사본 폴더는 뺀다)을 읽어
  '<스킬 이름>/SKILL.md' 가 든 줄을 모은다. 스킬 자신의 scripts/ 안 프로그램도 본다(own_folder: true).
  경로를 나눠 쓴 꼴('"<스킬 이름>" / "SKILL.md"')도 잡는다. 그 줄이나 앞뒤 세 줄, 또는 그 줄에서 값을 받은 이름을
  같은 파일에서 읽는 줄(read_text, open( 등)이 있으면 reads_body: "maybe" 를 붙인다. 정말 읽는지는 모델이 연다.
결과:
  화면: 스킬마다 한 줄 요약과 합계.
  --out: inventory.json(모은 것 전부), evidence.json(후보마다 빈 근거 칸. 이미 있으면 덮지 않고 evidence.new.json).
후보는 신호일 뿐이다. 갈 곳은 근거를 채운 뒤 scripts/judge.py 가 정한다.
낱말은 assets/신호-낱말.json 에서 읽는다(없으면 이 파일의 DEFAULT_SIGNALS).
하지 않는 것: 스킬 파일을 고치지 않는다. 갈 곳을 정하지 않는다. 다른 프로그램을 돌리지 않는다.
종료 코드: 0 = 됨, 1 = 읽지 못한 SKILL.md 가 있음(나머지는 냄), 2 = 스킬을 못 찾음, 인자나 낱말 파일 문제.
"""
import argparse
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

if sys.version_info < (3, 8):
    sys.exit("파이썬 3.8 이상이 필요합니다(python3 --version 으로 확인).")

HERE = Path(__file__).resolve().parent
SIGNALS_FILE = HERE.parent / "assets" / "신호-낱말.json"
KINDS = ("scripts", "references", "assets")
MOVE_FACTS = ("read_by_program", "restricted_runner", "notes_section", "copied_verbatim", "needed_every_run")
SCRIPT_FACTS = ("irreversible", "needs_judgment", "single_command", "observed")
BIG_SECTION_BYTES = 1500
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache", ".tox",
             ".skill-backup", "backup", "backups"}   # 사본 폴더 안의 옛 프로그램은 지금 도는 것이 아니다
CODE_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".sh", ".bash", ".zsh", ".fish", ".yaml", ".yml",
            ".json", ".toml", ".rb", ".go", ".rs", ".java", ".kt", ".php", ".pl", ".ps1", ".bat", ".cmd", ".lua",
            ".swift", ".ini", ".cfg", ".conf", ".plist"}
MAX_SCAN_BYTES = 1000000
PLACEHOLDER = re.compile(r"<[^<>\n]{1,40}>|\{[^{}\n]{1,40}\}|○○|YYYY")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})\s*([^`\s]*)")
HEADING = re.compile(r"^(#{2,4})\s+\S")
NUMBERED = re.compile(r"^\s*\d+[.)]\s+")
TICK = re.compile(r"`([^`\n]+)`")
ASSIGN = re.compile(r"^\s*(?:export\s+|const\s+|let\s+|var\s+|final\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*:?=")

# assets/신호-낱말.json 이 없을 때만 쓴다. 두 곳이 같은지는 tests/test_inventory.py 가 본다.
DEFAULT_SIGNALS = {
    "title_groups": {
        "history": ["시험 기록", "지난 기록", "옛 메모", "변경 기록", "이력", "changelog", "history", "test log", "test notes"],
        "fallback": ["손 절차", "손으로", "안 될 때", "안될 때", "문제 해결", "troubleshooting", "manual", "fallback"],
        "format": ["모양", "형식", "스키마", "schema", "format"],
        "notes": ["배운 것", "알게 된 것", "lessons", "learned", "notes"],
        "background": ["구성", "구조", "배경", "원리", "설계", "운영", "architecture", "background", "internals",
                       "rationale", "operations", "runbook"],
    },
    "template_titles": ["틀", "양식", "문안", "서명", "template", "boilerplate", "signature"],
    "table_meaning_words": ["뜻", "할 일", "대응", "조치", "의미", "meaning", "action", "todo", "next", "fix"],
    "calc_words": ["계산", "셈", "며칠", "기간 계산", "날짜 계산", "며칠 전", "며칠 뒤", "남은 날", "글자 수", "형식 검사",
                   "형식이 맞는지", "정규식", "calculate", "compute", "validate", "regex", "checksum", "word count", "date math"],
    "command_words": ["python", "python3", "node", "npm", "npx", "pip", "uv", "git", "gh", "curl", "wget", "bash", "sh", "zsh",
                      "cd", "ls", "cat", "grep", "sed", "awk", "jq", "find", "echo", "make", "docker", "kubectl", "brew",
                      "ffmpeg", "sqlite3", "psql", "ssh", "scp", "rsync", "cp", "mv", "mkdir", "open", "pwsh"],
    "code_langs": ["bash", "sh", "shell", "zsh", "console", "terminal", "python", "py", "python3", "js", "javascript", "ts",
                   "typescript", "node", "powershell", "ps1", "pwsh", "bat", "cmd", "sql", "ruby", "go"],
    "read_words": ["read_text", "read_bytes", "open(", "readFile", "readFileSync", "readlines", ".read()", "cat ",
                   "Get-Content", "fs.read", "File.read", "ReadFile"],
}


class InputError(Exception):
    """인자나 입력 파일 문제(종료 코드 2)."""


def nfc(s):
    return unicodedata.normalize("NFC", str(s))


# ------------------------------------------------------------------ 읽기

def find_skills(target):
    """→ 스킬 폴더 목록(이름 순). 준 폴더에 SKILL.md 가 있으면 그 하나."""
    target = Path(os.path.abspath(os.path.expanduser(str(target))))   # "." 도 이름이 서게(바로가기는 풀지 않는다)
    if not target.is_dir():
        raise InputError(f"폴더가 아닙니다: {target}")
    if (target / "SKILL.md").is_file():
        return [target]
    found = []
    for child in target.iterdir():
        if child.name.startswith(".") or not child.is_dir():   # is_dir 는 바로가기를 따라간다
            continue
        if (child / "SKILL.md").is_file():
            found.append(child)
    return sorted(found, key=lambda p: nfc(p.name))


def read_text(path):
    """→ (글, 오류). UTF-8 로 읽고, 못 읽으면 이유를 낸다."""
    try:
        return Path(path).read_text(encoding="utf-8"), ""
    except UnicodeDecodeError:
        return "", "UTF-8 로 읽지 못함"
    except OSError as e:
        return "", f"읽지 못함({e.__class__.__name__})"


def _scalar(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    return v


def parse_front(text):
    """머리(--- 사이)를 읽는다. '열쇠: 값' 과 한 단계 들여쓴 묶음, > 나 | 로 이어 쓴 값만 안다(PyYAML 을 쓰지 않는다).
    → (머리 dict, 본문이 시작하는 줄 번호(0부터), 오류 글)"""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, 0, "머리 없음"
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, 0, "머리가 닫히지 않음"
    front, key, mode, buf = {}, None, None, []

    def flush():
        if key is not None and mode == "text":
            front[key] = " ".join(x.strip() for x in buf if x.strip())

    for ln in lines[1:end]:
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        if not ln[0].isspace():
            flush()
            k, sep, v = ln.partition(":")
            if not sep:
                key, mode, buf = None, None, []
                continue
            key, v = k.strip(), v.strip()
            if v in (">", "|", ">-", "|-", ">+", "|+"):
                mode, buf = "text", []
                front[key] = ""
            elif v == "":
                mode, buf = "map", []
                front[key] = {}
            else:
                mode, buf = None, []
                front[key] = _scalar(v)
        elif key is not None:
            if mode == "text":
                buf.append(ln)
            elif mode == "map":
                k, sep, v = ln.strip().partition(":")
                if sep and isinstance(front.get(key), dict):
                    front[key][k.strip()] = _scalar(v)
                else:   # 들여쓴 줄이 '열쇠: 값' 이 아니면 이어 쓴 글로 본다
                    mode, buf = "text", [ln]
            else:
                front[key] = (str(front[key]) + " " + ln.strip()).strip()
    flush()
    return front, end + 1, ""


def code_mask(lines, start=0):
    """→ (코드 블록 목록, 줄마다 코드 블록 안(울타리 포함)인지). 울타리는 ``` 와 ~~~ 를 안다."""
    mask = [False] * len(lines)
    blocks = []
    i = start
    while i < len(lines):
        m = FENCE.match(lines[i])
        if not m:
            i += 1
            continue
        mark = m.group(1)
        lang = m.group(2).strip().lower()
        j = i + 1
        while j < len(lines):
            c = re.match(r"^\s*(`{3,}|~{3,})\s*$", lines[j])
            if c and c.group(1)[0] == mark[0] and len(c.group(1)) >= len(mark):
                break
            j += 1
        closed = j < len(lines)
        last = j if closed else len(lines) - 1
        for k in range(i, last + 1):
            mask[k] = True
        blocks.append({"open": i, "close": last, "closed": closed, "lang": lang,
                       "content": lines[i + 1:j] if closed else lines[i + 1:]})
        i = last + 1
    return blocks, mask


def headings(lines, mask, start=0):
    """코드 블록 밖의 ##~#### 제목 → [(줄 번호(0부터), 단계, 제목 줄)]"""
    out = []
    for i in range(start, len(lines)):
        if mask[i]:
            continue
        m = HEADING.match(lines[i])
        if m:
            out.append((i, len(m.group(1)), lines[i].rstrip()))
    return out


def section_spans(lines, heads):
    """제목마다 (시작, 끝) 끝은 같거나 높은 단계의 다음 제목 앞(뒤쪽 빈 줄은 뺀다)."""
    spans = []
    for n, (i, lv, title) in enumerate(heads):
        end = next((j for j, l2, _ in heads[n + 1:] if l2 <= lv), len(lines))
        while end > i + 1 and not lines[end - 1].strip():
            end -= 1
        spans.append((i, end, lv, title))
    return spans


def list_files(skill_dir, kind):
    """scripts·references·assets 안의 파일(숨김 파일, __pycache__ 제외) → 스킬 폴더 기준 경로."""
    base = Path(skill_dir) / kind
    if not base.is_dir():
        return []
    out = []
    for root, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "__pycache__")
        for f in sorted(files):
            if f.startswith(".") or f.endswith(".pyc"):
                continue
            out.append(nfc(Path(root, f).relative_to(skill_dir).as_posix()))
    return sorted(out)


# ------------------------------------------------------------------ 낱말

def load_signals(path=None):
    p = Path(path) if path else SIGNALS_FILE
    if not p.is_file():
        if path:
            raise InputError(f"낱말 파일이 없습니다: {p}")
        return DEFAULT_SIGNALS
    text, err = read_text(p)
    if err:
        raise InputError(f"낱말 파일을 {err}: {p}")
    try:
        data = json.loads(text)
    except ValueError as e:
        raise InputError(f"낱말 파일이 JSON 이 아닙니다: {e}")
    if not isinstance(data, dict):
        raise InputError("낱말 파일의 맨 위는 객체여야 합니다")
    merged = {}
    for k, v in DEFAULT_SIGNALS.items():
        got = data.get(k, v)
        if isinstance(v, dict) and not isinstance(got, dict) or isinstance(v, list) and not isinstance(got, list):
            raise InputError(f"낱말 파일의 '{k}' 꼴이 다릅니다")
        merged[k] = got
    return merged


def has_word(text, word):
    """영어(ASCII) 낱말은 낱말 경계로, 그 밖은 글자 그대로. 파이썬의 \\b 는 한글도 낱말 글자로 봐서 쓰지 않는다."""
    text, word = nfc(text).lower(), nfc(word).lower()
    if not word:
        return False
    if word.isascii():
        return re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", text) is not None
    return word in text


def any_word(text, words):
    return [w for w in words if has_word(text, w)]


def is_command(text, sig):
    """글 한 줄(백틱 안 글, 코드 블록 첫 줄)이 명령으로 보이는가.
    ① 첫 토큰(앞의 $, >, 경로를 뗀 것)이 흔한 명령(command_words)이거나 .py·.sh 같은 스크립트 이름이면 명령.
    ② 제 손으로 만든 명령: 토큰이 둘 이상이고, 첫 토큰이 ASCII 소문자로 시작하는 이름(영숫자, -, _, . 만)이며,
       [첫 토큰에 - 나 _ 가 있거나, 첫 토큰이 ./ ~/ / 로 시작하는 경로였거나, 뒤 토큰 가운데 - 로 시작하는 것이 있으면] 명령.
    'status unknown' 처럼 낱말 둘인 값은 명령이 아니다."""
    t = re.sub(r"^[$>]\s*", "", str(text).strip())
    toks = t.split()
    if not toks:
        return False
    first = toks[0]
    pathy = first.startswith(("./", "~/", "/"))
    name = first.rstrip("/").split("/")[-1] if "/" in first else first
    if name in sig["command_words"] or re.search(r"\.(py|sh|js|ts|rb)$", name):
        return True
    if len(toks) >= 2 and re.fullmatch(r"[a-z][A-Za-z0-9._-]*", name):
        return "-" in name or "_" in name or pathy or any(x.startswith("-") for x in toks[1:])
    return False


def looks_like_command(block, sig):
    if block["lang"] in sig["code_langs"]:
        return True
    first = next((ln.strip() for ln in block["content"] if ln.strip()), "")
    first = re.sub(r"^#\s+", "", first)
    return is_command(first, sig)


def command_in(text, sig):
    return any(is_command(span, sig) for span in TICK.findall(text))


MOVED_PATH = re.compile(r"(?:references|assets)/[^\s`'\"()<>]+")


def already_moved(lines, a, b):
    """이미 옮긴 자리: 제목을 뺀 본문의 빈 줄 아닌 줄이 3줄 이하이고 그 안에 references/… 나 assets/… 경로가 있다."""
    rest = [ln for ln in lines[a + 1:b] if ln.strip()]
    return len(rest) <= 3 and any(MOVED_PATH.search(ln) for ln in rest)


# ------------------------------------------------------------------ 후보

def blank_facts(names):
    return {n: {"status": "unknown", "why": "", "source": ""} for n in names}


def _section_of(spans, i):
    """줄 i 를 품은 가장 안쪽 절 제목."""
    best = None
    for a, b, lv, title in spans:
        if a <= i < max(b, a + 1) and (best is None or lv >= best[0]):
            best = (lv, title)
    return best[1] if best else "(머리말)"


def _nonblank_before(lines, i, stop):
    j = i - 1
    while j >= stop and not lines[j].strip():
        j -= 1
    return lines[j].strip() if j >= stop else ""


def find_candidates(lines, body, sig, max_lines, max_bytes):
    """→ 후보 목록(문서 순서). 줄 번호는 1부터."""
    blocks, mask = code_mask(lines, body)
    heads = headings(lines, mask, body)
    spans = section_spans(lines, heads)
    found = {}

    def add(kind, i, n, title, suggest, signal, **extra):
        key = (kind, i)
        if key in found:
            c = found[key]
            if signal not in c["signals"]:
                c["signals"].append(signal)
            if suggest == "assets":
                c["suggest"] = "assets"
            return
        t = {"kind": kind, "title": title, "line": i + 1, "lines": n}
        t.update(extra)
        found[key] = {"target": t, "suggest": suggest, "signals": [signal]}

    # 절: 제목 낱말, 큰 절
    sizes = {}
    for a, b, lv, title in spans:
        sizes[a] = len("\n".join(lines[a:b]).encode("utf-8"))
    notes_word = {}
    for a, b, lv, title in spans:
        if already_moved(lines, a, b):
            continue
        name = title.lstrip("#").strip()
        hit = any_word(name, sig["title_groups"].get("notes", []))
        if hit:
            notes_word[a + 1] = hit[0]
        if any_word(name, sig["template_titles"]):
            add("section", a, b - a, title, "assets", "title:template")
        for group, words in sorted(sig["title_groups"].items()):
            if any_word(name, words):
                add("section", a, b - a, title, "references", "title:" + group)
        if sizes[a] > BIG_SECTION_BYTES:
            inner_big = any(a < a2 < b and sizes[a2] > BIG_SECTION_BYTES for a2, _, _, _ in spans)
            if not inner_big:
                add("section", a, b - a, title, "references", "big-section", bytes=sizes[a])

    # 코드 블록
    for blk in blocks:
        n = len(blk["content"])
        text = "\n".join(blk["content"])
        title = _section_of(spans, blk["open"])
        before = _nonblank_before(lines, blk["open"], body)
        if looks_like_command(blk, sig):
            if n > 3:
                add("block", blk["open"], n, title, "scripts", "inline-code", lang=blk["lang"], before=before)
        elif PLACEHOLDER.search(text):
            add("block", blk["open"], n, title, "assets", "template-block", lang=blk["lang"], before=before)

    # 번호 목록: 명령이 든 항목이 세 개 이상 이어지면
    items = []          # (시작 줄, 끝 줄, 명령 있음)
    runs = []

    def close_run():
        streak = []
        for it in items + [None]:
            if it is not None and it[2]:
                streak.append(it)
                continue
            if len(streak) >= 3:
                runs.append((streak[0][0], streak[-1][1]))
            streak = []
        items.clear()

    in_item = {}         # 들여쓴 코드 블록(목록 항목에 딸린 것)의 줄
    for blk in blocks:
        if lines[blk["open"]][:1].isspace():
            for k in range(blk["open"], blk["close"] + 1):
                in_item[k] = True
    cur = None
    for i in range(body, len(lines)):
        ln = lines[i]
        if not mask[i] and NUMBERED.match(ln):
            if cur:
                items.append(tuple(cur))
            cur = [i, i, command_in(ln, sig)]
        elif cur and (in_item.get(i) or (not mask[i] and (not ln.strip() or ln[:1].isspace()))):
            if ln.strip():          # 항목에 딸린 줄(들여쓴 줄, 코드 블록)
                cur[1] = i
                cur[2] = cur[2] or mask[i] or command_in(ln, sig)
        elif cur:
            items.append(tuple(cur))
            cur = None
            close_run()
    if cur:
        items.append(tuple(cur))
    close_run()
    for a, b in runs:
        add("lines", a, b - a + 1, _section_of(spans, a), "scripts", "command-sequence")

    # 표: 머리 줄에 뜻·할 일 꼴 낱말이 있고 본문 줄이 2줄 이상이면
    i = body
    while i < len(lines):
        if mask[i] or not lines[i].lstrip().startswith("|"):
            i += 1
            continue
        j = i
        while j < len(lines) and not mask[j] and lines[j].lstrip().startswith("|"):
            j += 1
        if j - i >= 4 and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            if any_word(lines[i], sig["table_meaning_words"]):
                add("lines", i, j - i, _section_of(spans, i), "scripts", "lookup-table")
        i = j

    # 셈·날짜·형식 검사 낱말이 든 줄(절마다 하나로 묶는다)
    by_sec = {}
    for i in range(body, len(lines)):
        if mask[i] or HEADING.match(lines[i]):
            continue
        if any_word(lines[i], sig["calc_words"]):
            by_sec.setdefault(_section_of(spans, i), []).append(i)
    for title, hits in by_sec.items():
        add("lines", hits[0], hits[-1] - hits[0] + 1, title, "scripts", "calc-or-check", hits=[h + 1 for h in hits])

    # 문서 전체가 한도를 넘으면
    size = len("\n".join(lines).encode("utf-8"))
    if len(lines) > max_lines or size > max_bytes:
        add("lines", 0, len(lines), "(문서 전체)", "references", "over-budget", bytes=size)

    order = {"section": 0, "block": 1, "lines": 2}
    out = sorted(found.values(), key=lambda c: (c["target"]["line"], order[c["target"]["kind"]], c["signals"][0]))
    for c in out:
        c["facts"] = blank_facts(SCRIPT_FACTS if c["suggest"] == "scripts" else MOVE_FACTS)
        c["note"] = ""
        t = c["target"]
        if t["kind"] == "section" and "title:notes" in c["signals"] and t["line"] in notes_word:
            c["facts"]["notes_section"] = {
                "status": "yes", "source": f"SKILL.md:{t['line']}",
                "why": f"제목에 '{notes_word[t['line']]}' 이 있음(inventory 가 미리 채움. 배운 것을 적어 가는 자리가 아니면 no 로 고친다)"}
    return out


# ------------------------------------------------------------------ 본문을 읽는 프로그램

def _scan_files(repo, skip):
    for root, dirs, files in os.walk(repo):
        rp = Path(root)
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and (rp / d).resolve() not in skip)
        for f in sorted(files):
            p = rp / f
            ext = p.suffix.lower()
            try:
                if p.is_symlink() or not p.is_file() or p.stat().st_size > MAX_SCAN_BYTES:
                    continue
                if ext not in CODE_EXT:
                    if ext or f in ("README", "LICENSE"):
                        continue
                    with open(p, "rb") as fh:
                        if fh.read(2) != b"#!":
                            continue
            except OSError:
                continue
            yield p


def find_consumers(repo, skills, sig, skip=()):
    """skills: {이름: 폴더}. → {이름: [{where, text, reads_body, read_at}]}"""
    repo = Path(repo).resolve()
    names = {nfc(n): Path(p).resolve() for n, p in skills.items()}
    skip_dirs = set(Path(s).resolve() for s in skip)
    pats = {n: re.compile(r"(?<![\w-])" + re.escape(n) + r"[\s\"'/\\,+()]{0,12}SKILL\.md") for n in names}
    out = {n: [] for n in names}
    reads = sig["read_words"]
    for p in _scan_files(repo, skip_dirs):
        try:
            text = nfc(p.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, OSError):
            continue
        if "SKILL.md" not in text:
            continue
        lines = text.split("\n")
        rp = p.resolve()
        try:
            rel = nfc(rp.relative_to(repo).as_posix())
        except ValueError:
            rel = nfc(p.relative_to(repo).as_posix()) if p.is_absolute() else nfc(p.as_posix())
        for i, ln in enumerate(lines):
            if "SKILL.md" not in ln:
                continue
            for n, rx in pats.items():
                if not rx.search(ln):
                    continue
                own = str(rp).startswith(str(names[n]) + os.sep)
                read_at = ""
                for k in range(max(0, i - 3), min(len(lines), i + 4)):
                    if any(w in lines[k] for w in reads):
                        read_at = f"{rel}:{k + 1}"
                        break
                m = ASSIGN.match(ln)
                if not read_at and m:
                    var = re.compile(r"(?<![\w.])" + re.escape(m.group(1)) + r"(?!\w|\.md)")
                    for k, other in enumerate(lines):
                        if k != i and var.search(other) and any(w in other for w in reads):
                            read_at = f"{rel}:{k + 1}"
                            break
                out[n].append({"where": f"{rel}:{i + 1}", "text": ln.strip()[:160], "own_folder": own,
                               "reads_body": "maybe" if read_at else "no_sign", "read_at": read_at})
    return out


# ------------------------------------------------------------------ 모으기

def inspect_skill(skill_dir, sig, max_lines, max_bytes):
    skill_dir = Path(skill_dir)
    name = nfc(skill_dir.name)
    info = {"name": name, "path": str(skill_dir.resolve()), "link": skill_dir.is_symlink(), "error": "",
            "lines": 0, "bytes": 0, "front": {}, "front_error": "", "files": {k: list_files(skill_dir, k) for k in KINDS},
            "sections": [], "blocks": [], "candidates": []}
    text, err = read_text(skill_dir / "SKILL.md")
    if err:
        info["error"] = err
        return info
    lines = text.split("\n")
    front, body, ferr = parse_front(text)
    desc = front.get("description", "")
    meta = front.get("metadata") if isinstance(front.get("metadata"), dict) else {}
    info.update({
        "lines": len(lines) - (1 if text.endswith("\n") else 0),
        "bytes": len(text.encode("utf-8")),
        "front": {"name": front.get("name", ""), "description_chars": len(desc) if isinstance(desc, str) else 0,
                  "version": meta.get("version", "") or front.get("version", ""), "keys": sorted(front)},
        "front_error": ferr,
    })
    blocks, mask = code_mask(lines, body)
    for a, b, lv, title in section_spans(lines, headings(lines, mask, body)):
        info["sections"].append({"title": title, "level": lv, "line": a + 1, "lines": b - a,
                                 "bytes": len("\n".join(lines[a:b]).encode("utf-8"))})
    for blk in blocks:
        info["blocks"].append({"line": blk["open"] + 1, "lines": len(blk["content"]), "lang": blk["lang"], "closed": blk["closed"]})
    cands = find_candidates(lines, body, sig, max_lines, max_bytes)
    for n, c in enumerate(cands, 1):
        c["id"] = f"{name}#c{n}"
        c["skill"] = name
    info["candidates"] = [dict([("id", c["id"]), ("skill", name)] + [(k, c[k]) for k in ("target", "suggest", "signals", "facts", "note")])
                          for c in cands]
    return info


def run(target, repo=None, sig=None, max_lines=500, max_bytes=20000, skip=()):
    sig = sig or DEFAULT_SIGNALS
    dirs = find_skills(target)
    if not dirs:
        raise InputError(f"SKILL.md 가 든 폴더를 찾지 못했습니다: {target}")
    skills = [inspect_skill(d, sig, max_lines, max_bytes) for d in dirs]
    if repo:
        cons = find_consumers(repo, {s["name"]: s["path"] for s in skills}, sig, skip)
        for s in skills:
            s["consumers"] = cons.get(s["name"], [])
    else:
        for s in skills:
            s["consumers"] = None
    return skills


def evidence_of(skills, root):
    return {
        "_about": "후보마다 facts 의 status(yes, no, unknown), why, source(파일:줄)만 채운다. 갈 곳은 scripts/judge.py 가 정한다.",
        "root": str(root),
        "skills": {s["name"]: {"path": s["path"], "consumers": s["consumers"]} for s in skills},
        "candidates": [c for s in skills for c in s["candidates"]],
    }


def render(skills, max_lines, max_bytes):
    L = ["| 스킬 | 줄 | 바이트 | 머리 | 딸린 파일(s·r·a) | 후보(s·r·a) | 본문 읽는 곳 |", "|---|---|---|---|---|---|---|"]
    tot = {"scripts": 0, "references": 0, "assets": 0}
    over = reading = bad = 0
    for s in skills:
        if s["error"]:
            bad += 1
            L.append(f"| {s['name']} | - | - | {s['error']} | - | - | - |")
            continue
        head = s["front_error"] or ("있음" if s["front"]["name"] and s["front"]["description_chars"] else "name·description 빠짐")
        files = "·".join(str(len(s["files"][k])) for k in KINDS)
        cnt = {k: sum(1 for c in s["candidates"] if c["suggest"] == k) for k in tot}
        for k in tot:
            tot[k] += cnt[k]
        if s["lines"] > max_lines or s["bytes"] > max_bytes:
            over += 1
        if s["consumers"] is None:
            cons = "안 봄"
        else:
            maybe = sum(1 for c in s["consumers"] if c["reads_body"] == "maybe")
            reading += 1 if maybe else 0
            cons = f"{len(s['consumers'])}곳(읽는 듯 {maybe})" if s["consumers"] else "없음"
        L.append(f"| {s['name']}{' (바로가기)' if s['link'] else ''} | {s['lines']} | {s['bytes']} | {head} | {files} | "
                 f"{cnt['scripts']}·{cnt['references']}·{cnt['assets']} | {cons} |")
    n = sum(tot.values())
    L.append("")
    L.append(f"스킬 {len(skills)}개 · 후보 {n}개(scripts {tot['scripts']} · references {tot['references']} · assets {tot['assets']})"
             f" · 본문을 읽는 듯한 프로그램이 잡힌 스킬 {reading}개 · 한도 넘은 스킬 {over}개"
             + (f" · 읽지 못한 스킬 {bad}개" if bad else ""))
    return "\n".join(L)


def write_out(out, skills, root):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "inventory.json").write_text(json.dumps(skills, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    ev = out / "evidence.json"
    if ev.exists():
        ev = out / "evidence.new.json"
    ev.write_text(json.dumps(evidence_of(skills, root), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out / "inventory.json", ev


def main(argv=None):
    ap = argparse.ArgumentParser(description="스킬 폴더를 훑어 옮길 후보와 빈 근거 파일을 만든다(읽기 전용)")
    ap.add_argument("target", help="스킬 폴더 또는 스킬들이 든 폴더")
    ap.add_argument("--repo", help="SKILL.md 본문을 읽는 프로그램을 찾을 저장소 뿌리")
    ap.add_argument("--out", help="inventory.json, evidence.json 을 둘 작업폴더")
    ap.add_argument("--max-lines", type=int, default=500)
    ap.add_argument("--max-bytes", type=int, default=20000)
    ap.add_argument("--signals", help="낱말 파일(기본 assets/신호-낱말.json)")
    a = ap.parse_args(argv)
    if a.max_lines <= 0 or a.max_bytes <= 0:
        print("--max-lines, --max-bytes 는 0 보다 커야 합니다", file=sys.stderr)
        return 2
    if a.repo and not Path(a.repo).is_dir():
        print(f"--repo 폴더가 없습니다: {a.repo}", file=sys.stderr)
        return 2
    try:
        sig = load_signals(a.signals)
        skills = run(a.target, a.repo, sig, a.max_lines, a.max_bytes, skip=[a.out] if a.out else [])
    except InputError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(render(skills, a.max_lines, a.max_bytes))
    if a.out:
        t = Path(a.target)
        root = (t if not (t / "SKILL.md").is_file() else t.parent).resolve()
        inv, ev = write_out(a.out, skills, root)
        print(f"→ {inv}  ·  {ev}")
    return 1 if any(s["error"] for s in skills) else 0


if __name__ == "__main__":
    sys.exit(main())
