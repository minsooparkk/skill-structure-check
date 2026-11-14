"""scripts/inventory.py 시험. 임시 폴더만 쓴다. 스킬 이름과 글은 모두 지어낸 것이다."""
import importlib.util
import io
import json
import os
import tempfile
import unicodedata
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location("ssc_" + name, ROOT / "scripts" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


inv = load("inventory")


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = inv.main(argv)
    return code, out.getvalue(), err.getvalue()


FRONT = '---\nname: {name}\ndescription: 지어낸 시험용 스킬\nmetadata:\n  author: tester\n  version: "1.0.0"\n---\n\n'

ENGLISH = """---
name: release-notes
description: Fake skill for tests. Writes weekly release notes.
metadata:
  version: "2.1.0"
---

# Release notes

## Steps

1. `git fetch --tags` to sync.
2. `python3 tools/collect.py --since last` to collect.
3. `python3 tools/render.py notes.json` to render.
4. `gh release create v1 -F notes.md` to publish.

```bash
python3 - <<'PY'
import json
print(json.load(open("notes.json"))["count"])
PY
```

```bash
echo short
```

Validate that every line matches the regex before sending.

| Status | Meaning | Action |
|---|---|---|
| ok | all good | stop |
| fail | broken | rerun |

## Email template

```
Hello {name},
the release {version} is out.
```

## Troubleshooting

If the tool fails, do the manual steps.

## Changelog

- 2026-01-01 first run.

## Information

Nothing here.

## Architecture

How the pieces fit.
"""


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def put(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            p.write_bytes(text)
        else:
            p.write_text(text, encoding="utf-8")
        return p

    def cands(self, text, **kw):
        lines = text.split("\n")
        _, body, _ = inv.parse_front(text)
        return inv.find_candidates(lines, body, inv.DEFAULT_SIGNALS, kw.get("max_lines", 500), kw.get("max_bytes", 20000))


class Signals(Tmp):
    def test_signals_file_matches_defaults(self):
        data = json.loads((ROOT / "assets" / "신호-낱말.json").read_text(encoding="utf-8"))
        data.pop("_about")
        self.assertEqual(data, inv.DEFAULT_SIGNALS)
        self.assertNotIn("기간", data["calc_words"])
        self.assertIn("background", data["title_groups"])

    def test_bad_signals_file(self):
        self.put("skills/가/SKILL.md", FRONT.format(name="가"))
        self.put("sig.json", "[1, 2]")
        code, _, err = run_main([str(self.root / "skills"), "--signals", str(self.root / "sig.json")])
        self.assertEqual(code, 2)
        self.assertIn("객체", err)

    def test_word_boundary_for_ascii_and_plain_for_korean(self):
        self.assertTrue(inv.has_word("## Output format", "format"))
        self.assertFalse(inv.has_word("## Information", "format"))
        self.assertTrue(inv.has_word("## 원문 모양을 남기는 법", "모양"))
        self.assertTrue(inv.has_word("## 시험기록", "시험기록"))


class FindSkills(Tmp):
    def test_single_folder(self):
        self.put("one/SKILL.md", FRONT.format(name="one"))
        self.assertEqual([p.name for p in inv.find_skills(self.root / "one")], ["one"])

    def test_parent_folder_with_korean_space_symlink_and_hidden(self):
        self.put("skills/주간 보고/SKILL.md", FRONT.format(name="주간 보고"))
        self.put("skills/b-skill/SKILL.md", FRONT.format(name="b-skill"))
        self.put("skills/.hidden/SKILL.md", FRONT.format(name="hidden"))
        self.put("skills/no-doc/README.md", "x")
        self.put("elsewhere/linked/SKILL.md", FRONT.format(name="linked"))
        os.symlink(str(self.root / "elsewhere/linked"), str(self.root / "skills/linked"))
        names = [p.name for p in inv.find_skills(self.root / "skills")]
        self.assertEqual(names, ["b-skill", "linked", "주간 보고"])

    def test_not_a_folder(self):
        with self.assertRaises(inv.InputError):
            inv.find_skills(self.root / "none")


class Front(unittest.TestCase):
    def test_nested_quoted_and_folded(self):
        text = '---\nname: "가-나"\ndescription: >\n  첫 줄\n  둘째 줄\nlicense: MIT\nmetadata:\n  author: someone\n  version: "1.2.3"\n---\n# 본문\n'
        front, body, err = inv.parse_front(text)
        self.assertEqual(err, "")
        self.assertEqual(front["name"], "가-나")
        self.assertEqual(front["description"], "첫 줄 둘째 줄")
        self.assertEqual(front["metadata"], {"author": "someone", "version": "1.2.3"})
        self.assertEqual(text.split("\n")[body], "# 본문")

    def test_missing_and_unclosed(self):
        self.assertEqual(inv.parse_front("# 제목만\n")[2], "머리 없음")
        self.assertEqual(inv.parse_front("---\nname: x\n")[2], "머리가 닫히지 않음")
        self.assertEqual(inv.parse_front("")[2], "머리 없음")


class Structure(Tmp):
    def test_heading_inside_code_block_is_not_a_heading(self):
        text = FRONT.format(name="x") + "## 진짜\n\n```\n## 가짜 제목\n```\n\n### 안쪽\n\n글\n"
        lines = text.split("\n")
        _, body, _ = inv.parse_front(text)
        blocks, mask = inv.code_mask(lines, body)
        titles = [t for _, _, t in inv.headings(lines, mask, body)]
        self.assertEqual(titles, ["## 진짜", "### 안쪽"])
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["content"], ["## 가짜 제목"])

    def test_tilde_fence_and_unclosed_block(self):
        lines = ["~~~text", "```", "## 안", "~~~", "## 밖", "```", "끝"]
        blocks, mask = inv.code_mask(lines)
        self.assertEqual([(b["open"], b["closed"]) for b in blocks], [(0, True), (5, False)])
        self.assertEqual([t for _, _, t in inv.headings(lines, mask)], ["## 밖"])


class Candidates(Tmp):
    def by_signal(self, cands):
        out = {}
        for c in cands:
            for s in c["signals"]:
                out.setdefault(s, []).append(c)
        return out

    def test_english_skill_gets_every_kind(self):
        got = self.by_signal(self.cands(ENGLISH))
        self.assertEqual(len(got["command-sequence"]), 1)
        self.assertEqual(got["command-sequence"][0]["target"]["lines"], 4)
        self.assertEqual(len(got["inline-code"]), 1)          # 세 줄 이하 블록(echo short)은 빼고
        self.assertEqual(got["inline-code"][0]["target"]["lang"], "bash")
        self.assertEqual(len(got["lookup-table"]), 1)
        self.assertEqual(len(got["calc-or-check"]), 1)
        self.assertEqual(got["template-block"][0]["suggest"], "assets")
        self.assertEqual(got["title:template"][0]["target"]["title"], "## Email template")
        self.assertEqual(got["title:fallback"][0]["target"]["title"], "## Troubleshooting")
        self.assertEqual(got["title:history"][0]["target"]["title"], "## Changelog")
        self.assertNotIn("title:format", got)                 # Information 은 format 이 아니다
        self.assertEqual(got["title:background"][0]["target"]["title"], "## Architecture")
        for c in self.cands(ENGLISH):
            names = inv.SCRIPT_FACTS if c["suggest"] == "scripts" else inv.MOVE_FACTS
            self.assertEqual(sorted(c["facts"]), sorted(names))
            for f in c["facts"].values():
                self.assertEqual(f, {"status": "unknown", "why": "", "source": ""})

    def test_two_commands_are_not_a_sequence_three_are(self):
        text = FRONT.format(name="x") + "## 순서\n\n1. `git pull`\n2. `make`\n3. 결과를 읽는다\n"
        self.assertNotIn("command-sequence", self.by_signal(self.cands(text)))
        text = FRONT.format(name="x") + "## 순서\n\n1. `git pull`\n2. `make`\n3. `make test`\n4. 결과를 읽는다\n"
        self.assertEqual(self.by_signal(self.cands(text))["command-sequence"][0]["target"]["lines"], 3)

    def test_home_made_commands_count_but_plain_values_do_not(self):
        text = (FRONT.format(name="x") + "## 순서\n\n1. `mytool-hub pending --json` 로 남은 것을 본다.\n"
                "2. `./bin/sync all` 로 맞춘다.\n3. `report make --week` 로 표를 만든다.\n")
        self.assertIn("command-sequence", self.by_signal(self.cands(text)))
        values = FRONT.format(name="x") + "## 값\n\n1. `status unknown` 이면 묻는다.\n2. `key value` 꼴.\n3. `mode fast` 로 둔다.\n"
        self.assertNotIn("command-sequence", self.by_signal(self.cands(values)))
        sig = inv.DEFAULT_SIGNALS
        for t in ("mytool-hub pending --json", "./bin/sync all", "~/x/run now", "report make --week", "$ git status", "deploy.sh"):
            self.assertTrue(inv.is_command(t, sig), t)
        for t in ("status unknown", "key value", "Hello world", "references/x.md", "OK", "-- 없음"):
            self.assertFalse(inv.is_command(t, sig), t)

    def test_table_needs_meaning_word_and_two_rows(self):
        two = FRONT.format(name="x") + "## 표\n\n| 보이는 것 | 할 일 |\n|---|---|\n| 가 | 나 |\n| 다 | 라 |\n"
        one = FRONT.format(name="x") + "## 표\n\n| 보이는 것 | 할 일 |\n|---|---|\n| 가 | 나 |\n"
        plain = FRONT.format(name="x") + "## 표\n\n| 이름 | 쓰는 곳 |\n|---|---|\n| 가 | 나 |\n| 다 | 라 |\n"
        self.assertIn("lookup-table", self.by_signal(self.cands(two)))
        self.assertNotIn("lookup-table", self.by_signal(self.cands(one)))
        self.assertNotIn("lookup-table", self.by_signal(self.cands(plain)))

    def test_calc_words_are_specific(self):
        noisy = FRONT.format(name="x") + "## 가\n\n보관 기간은 1년이다. 합계 칸은 비운다. 8바이트.\n"
        self.assertNotIn("calc-or-check", self.by_signal(self.cands(noisy)))
        real = FRONT.format(name="x") + "## 가\n\n마감까지 남은 날을 센다.\n"
        self.assertIn("calc-or-check", self.by_signal(self.cands(real)))

    def test_background_titles(self):
        text = FRONT.format(name="x") + "## 구성\n\n글\n\n## 운영 (예약 쪽)\n\n글\n"
        titles = [c["target"]["title"] for c in self.by_signal(self.cands(text))["title:background"]]
        self.assertEqual(titles, ["## 구성", "## 운영 (예약 쪽)"])

    def test_notes_title_prefills_notes_section(self):
        text = FRONT.format(name="x") + "## 배운 것\n\n- 하나\n"
        c = self.by_signal(self.cands(text))["title:notes"][0]
        f = c["facts"]["notes_section"]
        self.assertEqual(f["status"], "yes")
        self.assertIn("제목에 '배운 것' 이 있음(inventory 가 미리 채움", f["why"])
        self.assertEqual(f["source"], "SKILL.md:9")
        self.assertEqual(c["facts"]["read_by_program"]["status"], "unknown")
        judge = load("judge")
        r = judge.judge(dict(c, id="x#c1", skill="x"))
        self.assertEqual((r["decision"], r["confidence"]), ("keep", "확실"))

    def test_already_moved_section_is_not_a_candidate_again(self):
        def sections(folder):
            text = (ROOT / "examples" / folder / "주간-보고" / "SKILL.md").read_text(encoding="utf-8")
            return [c["target"]["title"] for c in self.cands(text) if c["target"]["kind"] == "section"]
        self.assertIn("## 시험 기록", sections("before"))
        self.assertNotIn("## 시험 기록", sections("after"))
        self.assertIn("## 배운 것", sections("after"))
        long_ = FRONT.format(name="x") + "## 시험 기록\n\n- 1\n- 2\n- 3\n- 4 `references/a.md`\n"
        self.assertIn("## 시험 기록", [c["target"]["title"] for c in self.cands(long_)])

    def test_korean_titles_big_section_and_over_budget(self):
        big = "가" * 600
        text = (FRONT.format(name="x") + "## 시험 기록\n\n- 한 번\n\n## 보고 틀\n\n글\n\n## 배운 것\n\n- 하나\n\n"
                "## 큰 절\n\n" + big + "\n\n### 안쪽 작은 절\n\n짧다\n")
        got = self.by_signal(self.cands(text, max_lines=10))
        self.assertEqual(got["title:history"][0]["target"]["title"], "## 시험 기록")
        self.assertEqual(got["title:template"][0]["suggest"], "assets")
        self.assertEqual(got["title:notes"][0]["target"]["title"], "## 배운 것")
        self.assertEqual(got["big-section"][0]["target"]["title"], "## 큰 절")
        self.assertEqual(got["over-budget"][0]["target"]["title"], "(문서 전체)")

    def test_block_before_line_is_recorded(self):
        text = FRONT.format(name="x") + "## 답\n\n아래 틀을 쓴다.\n\n```\n<이름>님 안녕하세요.\n```\n"
        c = self.by_signal(self.cands(text))["template-block"][0]
        self.assertEqual(c["target"]["before"], "아래 틀을 쓴다.")
        self.assertEqual(c["target"]["kind"], "block")

    def test_empty_and_frontless_documents_do_not_crash(self):
        self.assertEqual(self.cands(""), [])
        self.assertEqual(self.cands("그냥 글\n"), [])


class Consumers(Tmp):
    def test_finds_programs_that_read_the_body(self):
        skills = self.root / "skills"
        self.put("skills/my-skill/SKILL.md", FRONT.format(name="my-skill"))
        self.put("skills/my-skill/scripts/own.py", 'DOC = HERE.parent / "SKILL.md"\np = "my-skill/SKILL.md"\nopen(p).read()\n')
        self.put("jobs/daily.py", 'from pathlib import Path\nSKILL = ROOT / "my-skill" / "SKILL.md"\n\n\n\n\n'
                                   'def go():\n    text = SKILL.read_text(encoding="utf-8")\n')
        self.put("jobs/mention.yaml", "# 설명: skills/my-skill/SKILL.md 를 보라\n")
        self.put("jobs/other.py", 'X = "old-my-skill/SKILL.md"\nopen(X)\n')
        self.put("node_modules/pkg/a.js", 'readFile("my-skill/SKILL.md")\n')
        self.put(".skill-backup/2026-01-01/a.py", 'open("my-skill/SKILL.md")\n')
        cons = inv.find_consumers(self.root, {"my-skill": skills / "my-skill"}, inv.DEFAULT_SIGNALS)["my-skill"]
        where = {c["where"]: c for c in cons}
        self.assertEqual(sorted(where), ["jobs/daily.py:2", "jobs/mention.yaml:1", "skills/my-skill/scripts/own.py:2"])
        self.assertEqual(where["jobs/daily.py:2"]["reads_body"], "maybe")
        self.assertEqual(where["jobs/daily.py:2"]["read_at"], "jobs/daily.py:8")
        self.assertEqual(where["jobs/mention.yaml:1"]["reads_body"], "no_sign")
        self.assertTrue(where["skills/my-skill/scripts/own.py:2"]["own_folder"])
        self.assertEqual(where["skills/my-skill/scripts/own.py:2"]["reads_body"], "maybe")

    def test_nfd_names_in_code_still_match(self):
        name = "주간-보고"
        self.put(f"skills/{name}/SKILL.md", FRONT.format(name=name))
        self.put("run.py", 'open("' + unicodedata.normalize("NFD", name) + '/SKILL.md")\n')
        cons = inv.find_consumers(self.root, {name: self.root / "skills" / name}, inv.DEFAULT_SIGNALS)[name]
        self.assertEqual([c["reads_body"] for c in cons], ["maybe"])


class Main(Tmp):
    def test_out_writes_files_and_never_overwrites_evidence(self):
        self.put("skills/가/SKILL.md", FRONT.format(name="가") + "## 시험 기록\n\n- 하나\n")
        out = self.root / "work"
        code, text, _ = run_main([str(self.root / "skills"), "--repo", str(self.root), "--out", str(out)])
        self.assertEqual(code, 0)
        self.assertIn("스킬 1개", text)
        ev = json.loads((out / "evidence.json").read_text(encoding="utf-8"))
        self.assertEqual(ev["candidates"][0]["id"], "가#c1")
        self.assertEqual(ev["skills"]["가"]["consumers"], [])
        (out / "evidence.json").write_text('{"filled": true}', encoding="utf-8")
        code, _, _ = run_main([str(self.root / "skills"), "--out", str(out)])
        self.assertEqual(code, 0)
        self.assertEqual((out / "evidence.json").read_text(encoding="utf-8"), '{"filled": true}')
        self.assertTrue((out / "evidence.new.json").is_file())
        inv_data = json.loads((out / "inventory.json").read_text(encoding="utf-8"))
        self.assertEqual(inv_data[0]["front"]["version"], "1.0.0")

    def test_unreadable_skill_gives_1_and_others_still_listed(self):
        self.put("skills/a/SKILL.md", FRONT.format(name="a"))
        self.put("skills/b/SKILL.md", b"\xff\xfe\x00bad")
        self.put("skills/c/SKILL.md", "")
        code, text, _ = run_main([str(self.root / "skills")])
        self.assertEqual(code, 1)
        self.assertIn("UTF-8 로 읽지 못함", text)
        self.assertIn("| c |", text)
        self.assertIn("머리 없음", text)

    def test_no_skills_and_bad_numbers(self):
        (self.root / "empty").mkdir()
        self.assertEqual(run_main([str(self.root / "empty")])[0], 2)
        self.put("one/SKILL.md", FRONT.format(name="one"))
        self.assertEqual(run_main([str(self.root / "one"), "--max-lines", "0"])[0], 2)
        self.assertEqual(run_main([str(self.root / "one"), "--repo", str(self.root / "nope")])[0], 2)


if __name__ == "__main__":
    unittest.main()
