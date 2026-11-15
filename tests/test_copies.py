"""scripts/copies.py 시험. 임시 폴더만 쓴다. 스킬 이름과 글은 모두 지어낸 것이다.

못 박는 것: 딸린 파일의 글이 문서나 스크립트에 그대로 있으면 잡는다, 문서와 스크립트에 같은 문장이 있으면 잡는다,
제목·머리·주석·맨 위 설명·이름과 경로는 세지 않는다, 아무것도 고치지 않는다.
"""
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location("ssc_" + name, ROOT / "scripts" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cp = load("copies")

FRONT = "---\nname: {name}\ndescription: 지어낸 시험용 스킬. 답장 첫 줄은 정해진 인사말 그대로 쓴다\n---\n\n# {name}\n\n"
DOC = FRONT.format(name="가") + """## 절차

1. 답장 첫 줄은 "안녕하세요, 문의 주셔서 감사합니다." 로 쓴다. 틀은 `assets/답장-틀.txt` 에 있다.
2. 멈춘 까닭을 아래 표로 읽는다.

| 값 | 뜻 | 할 일 |
|---|---|---|
| `locked` | 계정이 잠겨 다시 시도하면 안 됨 | 담당자에게 한 줄로 알린다 |

3. 보고 첫 줄은 `주간 보고 · 날짜` 꼴이다.

## 지난 기록

`references/지난-기록.md` 에 있다. 규칙이 왜 생겼는지 볼 때 읽는다.
"""
ASSET = "안녕하세요, 문의 주셔서 감사합니다.\n<본문 두세 줄>\n<끝 인사>\n"
REF = "# 가 · 지난 기록\n\n> 가 스킬의 딸린 자료다. 규칙이 왜 생겼는지 볼 때 읽는다.\n\n## 지난 기록\n\n- 2026-01-02 처음 돌려 보고 줄 수 한도를 정했다.\n"
SCRIPT = '''#!/usr/bin/env python3
"""멈춘 까닭을 읽어 준다. 답장 첫 줄은 "안녕하세요, 문의 주셔서 감사합니다." 로 쓴다(이 설명은 세지 않는다)."""
# 주석: 계정이 잠겨 다시 시도하면 안 됨 (세지 않는다)
import sys

STOPS = {"locked": ("계정이 잠겨 다시 시도하면 안 됨", "담당자에게 한 줄로 알린다")}
GREETING = "안녕하세요, 문의 주셔서 감사합니다."
STATE_FILE = "작업-상태-기록.json"


def main():
    """계정이 잠겨 다시 시도하면 안 됨 (함수 설명도 세지 않는다)."""
    print(f"멈춤: {STOPS['locked'][0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


class Base(unittest.TestCase):
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

    def skill(self, name="가", doc=DOC, asset=ASSET, ref=REF, script=SCRIPT):
        self.put(f"skills/{name}/SKILL.md", doc)
        if asset is not None:
            self.put(f"skills/{name}/assets/답장-틀.txt", asset)
        if ref is not None:
            self.put(f"skills/{name}/references/지난-기록.md", ref)
        if script is not None:
            self.put(f"skills/{name}/scripts/status.py", script)
        return self.root / "skills" / name

    def kinds(self, res):
        return sorted((f["kind"], f["text"]) for f in res["found"])

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cp.main(list(argv))
        return code, out.getvalue(), err.getvalue()


class Find(Base):
    def test_three_kinds_are_found_once_each(self):
        res = cp.inspect(self.skill())
        self.assertEqual(self.kinds(res), [
            ("A", "안녕하세요, 문의 주셔서 감사합니다."),       # 틀 파일의 첫 줄이 문서 1번 줄 안에 그대로
            ("B", "안녕하세요, 문의 주셔서 감사합니다."),       # 같은 줄이 스크립트의 글자열에도
            ("C", "계정이 잠겨 다시 시도하면 안 됨"),          # 문서 표의 칸과 스크립트의 글자열
            ("C", "담당자에게 한 줄로 알린다"),
            ("C", "안녕하세요, 문의 주셔서 감사합니다."),
        ])
        a = next(f for f in res["found"] if f["kind"] == "A")
        self.assertEqual((a["a"], a["b"]), ("assets/답장-틀.txt:1", "SKILL.md:10"))
        b = next(f for f in res["found"] if f["kind"] == "B")
        self.assertEqual((b["a"], b["b"]), ("assets/답장-틀.txt:1", "scripts/status.py:7"))

    def test_headings_headers_comments_docstrings_and_names_do_not_count(self):
        res = cp.inspect(self.skill(asset="<본문 두세 줄>\n<끝 인사>\n", script=SCRIPT.replace(
            'STOPS = {"locked": ("계정이 잠겨 다시 시도하면 안 됨", "담당자에게 한 줄로 알린다")}\nGREETING = "안녕하세요, 문의 주셔서 감사합니다."\n', "STOPS = {}\n")))
        # 남은 것: 제목 '## 지난 기록'(문서와 딸린 파일 양쪽), 딸린 파일 머리(>), 주석과 설명 속 같은 글, 파일 이름
        self.assertEqual(res["found"], [])

    def test_short_lines_and_single_tokens_do_not_count(self):
        self.assertFalse(cp.worth("주간 보고", 12))
        self.assertFalse(cp.worth("troubleshooting", 12))            # 띄어쓰기 없는 영문 낱말
        self.assertFalse(cp.worth("작업-상태-기록.json", 12))          # 파일 이름
        self.assertFalse(cp.worth("reports/weekly/latest", 12))      # 경로
        self.assertFalse(cp.worth("----------------", 12))           # 낱말 글자가 없음
        self.assertTrue(cp.worth("띄어쓰기없이이어쓴열두글자넘는글", 12))    # 띄어쓰기를 안 하는 말은 센다
        self.assertTrue(cp.worth("주간 보고는 금요일에 올린다", 12))
        res = cp.inspect(self.skill(), min_chars=40)
        self.assertEqual(res["found"], [])

    def test_table_row_in_reference_is_matched_cell_by_cell(self):
        ref = REF + "\n| 값 | 뜻 | 할 일 |\n|---|---|---|\n| `locked` | 계정이 잠겨 다시 시도하면 안 됨 | 담당자에게 한 줄로 알린다 |\n"
        doc = DOC.replace("| `locked` | 계정이 잠겨 다시 시도하면 안 됨 | 담당자에게 한 줄로 알린다 |\n", "표는 `references/지난-기록.md` 에 있다.\n")
        res = cp.inspect(self.skill(doc=doc, ref=ref, asset=None))
        got = self.kinds(res)
        self.assertIn(("B", "계정이 잠겨 다시 시도하면 안 됨"), got)   # 스크립트는 표를 칸마다 따로 들고 있다
        self.assertIn(("B", "담당자에게 한 줄로 알린다"), got)
        self.assertFalse([k for k in got if k[0] == "A"])

    def test_json_asset_values_are_compared_but_notes_are_not(self):
        table = {"_about": "계정이 잠겨 다시 시도하면 안 됨 (설명 칸은 재료가 아니다)",
                 "멈춤": {"locked": {"뜻": "계정이 잠겨 다시 시도하면 안 됨", "알림": "계정이 잠겼어요. 내일 다시 로그인해 주세요."}}}
        d = self.skill(asset=None)
        self.put("skills/가/assets/멈춤-표.json", json.dumps(table, ensure_ascii=False, indent=1))
        doc = (d / "SKILL.md").read_text(encoding="utf-8") + '\n알릴 말: "계정이 잠겼어요. 내일 다시 로그인해 주세요."\n'
        (d / "SKILL.md").write_text(doc, encoding="utf-8")
        got = self.kinds(cp.inspect(d))
        self.assertIn(("A", "계정이 잠겼어요. 내일 다시 로그인해 주세요."), got)
        self.assertIn(("A", "계정이 잠겨 다시 시도하면 안 됨"), got)
        self.assertEqual(len([k for k in got if k == ("A", "계정이 잠겨 다시 시도하면 안 됨")]), 1)   # _about 의 같은 글은 한 번 더 세지 않는다

    def test_code_template_in_assets_is_not_compared_with_scripts(self):
        d = self.skill(asset=None)
        self.put("skills/가/assets/스크립트-틀.py", "import sys\n\n\ndef main():\n    return 0\n\n\nif __name__ == \"__main__\":\n    sys.exit(main())\n")
        self.assertFalse([f for f in cp.inspect(d)["found"] if f["kind"] == "B"])

    def test_non_python_script_and_broken_python_use_quoted_strings(self):
        d = self.skill(script=None, asset=None)
        self.put("skills/가/scripts/notify.sh", '#!/bin/sh\n# 계정이 잠겨 다시 시도하면 안 됨\necho "담당자에게 한 줄로 알린다"\n')
        self.put("skills/가/scripts/broken.py", 'def f(:\n    x = "계정이 잠겨 다시 시도하면 안 됨"\n')
        got = self.kinds(cp.inspect(d))
        self.assertEqual(got, [("C", "계정이 잠겨 다시 시도하면 안 됨"), ("C", "담당자에게 한 줄로 알린다")])

    def test_unreadable_and_huge_files_are_skipped(self):
        d = self.skill(asset=None)
        self.put("skills/가/assets/그림.png", b"\x89PNG\xff\xfe\x00")
        self.put("skills/가/assets/큰-파일.txt", "안녕하세요, 문의 주셔서 감사합니다.\n" + "가" * 210000)
        res = cp.inspect(d)
        self.assertFalse([f for f in res["found"] if f["kind"] == "A"])
        self.assertTrue(any("200KB" in n for n in res["notes"]))

    def test_clean_skill_and_missing_document(self):
        d = self.skill(doc=FRONT.format(name="가") + "## 절차\n\n1. 틀은 `assets/답장-틀.txt` 에 있다.\n", script=None)
        self.assertEqual(cp.inspect(d)["found"], [])
        (d / "SKILL.md").write_bytes(b"\xff\xfe")
        self.assertTrue(cp.inspect(d)["notes"])


class Cli(Base):
    def test_text_json_out_and_strict(self):
        self.skill()
        self.skill("나", doc=FRONT.format(name="나") + "## 절차\n\n1. 그냥 한다.\n", asset=None, ref=None, script=None)
        before = {p: p.read_bytes() for p in (self.root / "skills").rglob("*") if p.is_file()}
        code, out, _ = self.run_main(str(self.root / "skills"), "--out", str(self.root / "work"))
        self.assertEqual(code, 0)
        self.assertIn("가: 두 벌 5곳", out)
        self.assertIn("[A 딸린 파일과 문서] assets/답장-틀.txt:1 = SKILL.md:10", out)
        self.assertIn("스킬 2개 · 두 벌 있는 스킬 1개(A 1 · B 1 · C 3)", out)
        self.assertNotIn("나:", out)
        saved = json.loads((self.root / "work" / "copies.json").read_text(encoding="utf-8"))
        self.assertEqual([s["name"] for s in saved["skills"]], ["가", "나"])
        self.assertEqual(len(saved["skills"][0]["found"]), 5)
        code, out, _ = self.run_main(str(self.root / "skills"), "--json", "--strict")
        self.assertEqual(code, 1)
        self.assertEqual(len(json.loads(out)), 2)
        self.assertEqual(self.run_main(str(self.root / "skills" / "나"), "--strict")[0], 0)
        self.assertEqual({p: p.read_bytes() for p in (self.root / "skills").rglob("*") if p.is_file()}, before)   # 읽기만 한다

    def test_bad_arguments(self):
        code, _, err = self.run_main(str(self.root / "없는-폴더"))
        self.assertEqual(code, 2)
        self.assertIn("입력 문제", err)
        self.skill()
        self.assertEqual(self.run_main(str(self.root / "skills"), "--min-chars", "2")[0], 2)

    def test_this_repository_keeps_its_own_tables_in_one_place(self):
        """이 저장소 자신: assets·references 의 글이 SKILL.md 나 scripts 에 한 벌 더 있지 않다(A, B 0)."""
        res = cp.inspect(ROOT)
        self.assertEqual([f for f in res["found"] if f["kind"] in ("A", "B")], [])


if __name__ == "__main__":
    unittest.main()
