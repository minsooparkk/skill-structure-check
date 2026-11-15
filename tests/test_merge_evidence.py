"""scripts/merge_evidence.py 시험. 임시 폴더만 쓴다. 스킬 이름과 글은 모두 지어낸 것이다.

못 박는 것: 묶음의 후보는 id 로 갈아 끼우고 손 후보만 새로 더한다, 범위 밖 후보는 뺀다, 판정을 바꾸지 않는다(견주기만 한다).
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


mg = load("merge_evidence")
judge = load("judge")

MOVE = ["read_by_program", "restricted_runner", "notes_section", "copied_verbatim", "needed_every_run"]
SCRIPT = ["irreversible", "needs_judgment", "single_command", "observed"]


def F(status="unknown", why="", source=""):
    return {"status": status, "why": why, "source": source}


def cand(cid, suggest="references", facts=None, **over):
    names = SCRIPT if suggest == "scripts" else MOVE
    c = {"id": cid, "skill": cid.split("#")[0], "suggest": suggest, "signals": ["big-section"],
         "target": {"kind": "section", "title": "## 시험 기록", "line": 10, "lines": 8},
         "facts": {k: F() for k in names}, "note": ""}
    c["facts"].update(facts or {})
    c.update(over)
    return c


def filled(cid, suggest="references", every="no", verbatim="no"):
    facts = {"read_by_program": F("no", "읽는 프로그램 없음", "inventory"), "restricted_runner": F("no", "대화 중에만 씀", "SKILL.md:3"),
             "notes_section": F("no", "기록이다", "SKILL.md:10"), "copied_verbatim": F(verbatim, "틀이 아니다", "SKILL.md:10"),
             "needed_every_run": F(every, "본문이 가리키지 않는다", "SKILL.md:10")}
    return cand(cid, suggest, facts)


BASE = {"_about": "지어낸 근거", "root": "/없는/폴더", "skills": {"가": {}, "나": {}, "다": {}},
        "candidates": [cand("가#c1"), cand("가#c2", "scripts"), cand("나#c1", "assets"), cand("다#c1")]}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def put(self, name, data):
        p = self.root / name
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return str(p)

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = mg.main(list(argv))
        return code, out.getvalue(), err.getvalue()


class Merge(Base):
    def groups(self):
        g1 = {"group": "1", "candidates": [filled("가#c1"), filled("가#m1", every="yes")],
              "opinions": {"가#c1": {"opinion": "옮김", "why": "스크립트가 대신 한다", "op": {"kind": "section", "head": "## 시험 기록"}},
                           "가#m1": {"opinion": "keep", "why": "네 줄이라 나누면 찾아갈 곳만 는다"}},
              "notes": ["가: 끊긴 가리킴 하나"]}
        g2 = {"group": "2", "candidates": [filled("나#c1", "assets", verbatim="yes")], "opinions": {"나#c1": {"opinion": "move", "why": "베껴 쓰는 틀"}}}
        return [("g1.json", g1), ("g2.json", g2)]

    def test_replaces_by_id_adds_manual_and_keeps_order(self):
        merged, ops, problems, st = mg.merge(BASE, self.groups())
        self.assertEqual(problems, [])
        self.assertEqual([c["id"] for c in merged["candidates"]], ["가#c1", "가#c2", "나#c1", "다#c1", "가#m1"])
        self.assertEqual(merged["candidates"][0]["facts"]["needed_every_run"]["status"], "no")     # 묶음이 채운 것으로 갈아 끼움
        self.assertEqual(merged["candidates"][3]["facts"]["needed_every_run"]["status"], "unknown")  # 아무도 안 본 후보는 그대로
        self.assertEqual(st["manual"], 1)
        self.assertEqual(st["blank"], ["가#c2", "다#c1"])
        self.assertEqual(ops["opinions"]["가#c1"]["opinion"], "move")          # 느슨하게 읽어 한 가지로 적는다
        self.assertEqual(ops["opinions"]["가#m1"]["group"], "1")
        self.assertEqual(ops["notes"], ["[1] 가: 끊긴 가리킴 하나"])
        self.assertNotIn("label", merged)
        self.assertEqual(BASE["candidates"][0]["facts"]["needed_every_run"]["status"], "unknown")  # 받은 것은 고치지 않는다

    def test_scope_and_skipped_skills(self):
        merged, _, problems, st = mg.merge(BASE, self.groups(), only=["references", "assets"], skip_skills=["다"])
        self.assertEqual(problems, [])
        self.assertEqual([c["id"] for c in merged["candidates"]], ["가#c1", "나#c1", "가#m1"])
        self.assertEqual((st["dropped_scope"], st["dropped_skill"]), (1, 1))
        self.assertIn("범위: assets, references", merged["label"])
        self.assertIn("뺀 스킬: 다", merged["label"])

    def test_problems_are_listed(self):
        g = {"group": "x", "candidates": [filled("가#c1"), cand("가#새것"), {"skill": "가"},
                                         {"id": "나#m1", "skill": "나", "suggest": "references", "facts": {"notes_section": F("no")}}],
             "opinions": {"없는#c9": {"opinion": "move"}}}
        dup = {"group": "y", "candidates": [filled("가#c1")]}
        _, _, problems, _ = mg.merge(BASE, [("a.json", g), ("b.json", dup), ("c.json", ["목록"])])
        joined = " / ".join(problems)
        for part in ("a.json 가#새것: 원래 후보에 없는 id 인데 손 후보 꼴", "a.json: id 없는 후보", "a.json 나#m1: 근거 칸 없음(read_by_program",
                     "b.json 가#c1: 다른 묶음(a.json)에도 있음", "c.json: 맨 위가 객체가 아님", "의견 없는#c9: 그 id 의 후보가 없음"):
            self.assertIn(part, joined)

    def test_merged_file_goes_straight_into_judge(self):
        merged, _, _, _ = mg.merge(BASE, self.groups(), only=["references", "assets"])
        rows, bad = judge.judge_all(merged)
        got = {r["id"]: r["decision"] for r in rows}
        self.assertEqual(bad, 0)
        self.assertEqual(got["가#c1"], "references")
        self.assertEqual(got["나#c1"], "assets")
        self.assertEqual(got["가#m1"], "keep")


class Compare(Base):
    def test_only_moving_rows_and_three_marks(self):
        rows = [{"id": "가#c1", "decision": "references"}, {"id": "가#m1", "decision": "references"}, {"id": "나#c1", "decision": "keep"},
                {"id": "다#c1", "decision": "keep"}, {"id": "다#c2", "decision": "assets"}, "이상한 줄"]
        ops = {"opinions": {"가#c1": {"opinion": "move", "why": "손 절차"}, "가#m1": {"opinion": "keep", "why": "네 줄"},
                            "나#c1": {"opinion": "옮김", "why": "가끔 본다"}, "다#c1": {"opinion": "keep"}}}
        lines = mg.compare(rows, ops)
        self.assertEqual(len(lines), 5)                                   # 둘 다 '둠'인 다#c1 은 안 나온다
        self.assertIn("가#c1 | 판정 references 로 | 의견 옮김 | 같음 | 손 절차", lines[0])
        self.assertIn("가#m1 | 판정 references 로 | 의견 둠 | 계획에서 뺄 후보 | 네 줄", lines[1])
        self.assertIn("나#c1 | 판정 그대로 둠 | 의견 옮김 | 근거를 다시 볼 후보", lines[2])
        self.assertIn("다#c2 | 판정 assets 로 | 의견 없음 | 의견 없음", lines[3])
        self.assertEqual(lines[4], "판정과 의견이 같은 옮김 1개 · 계획에서 뺄 후보 1개 · 근거를 다시 볼 후보 1개")


class Cli(Base):
    def test_merge_then_judge_then_compare(self):
        ev = self.put("evidence.json", BASE)
        g1 = self.put("group-1.json", {"group": "1", "candidates": [filled("가#c1"), filled("가#m1")],
                                       "opinions": {"가#m1": {"opinion": "keep", "why": "두 줄뿐"}}})
        code, out, _ = self.run_main(ev, g1, "--only", "references,assets", "--out", str(self.root / "work"))
        self.assertEqual(code, 0, out)
        self.assertIn("묶음 1개 · 후보 4개(손 후보 1개) · 의견 1개 · 범위 밖이라 뺀 후보 1개", out)
        self.assertIn("근거가 하나도 안 채워진 후보: 나#c1, 다#c1", out)
        merged = self.root / "work" / "evidence.merged.json"
        data = json.loads(merged.read_text(encoding="utf-8"))
        self.assertEqual(len(data["candidates"]), 4)
        out2, err2 = io.StringIO(), io.StringIO()
        with redirect_stdout(out2), redirect_stderr(err2):
            self.assertEqual(judge.main([str(merged), "--out", str(self.root / "work")]), 0)
        code, out, _ = self.run_main("--compare", str(self.root / "work" / "result.json"), str(self.root / "work" / "opinions.json"))
        self.assertEqual(code, 0)
        self.assertIn("가#m1 | 판정 references 로 | 의견 둠 | 계획에서 뺄 후보 | 두 줄뿐", out)
        self.assertIn("가#c1 | 판정 references 로 | 의견 없음", out)

    def test_problems_exit_1_but_files_are_written(self):
        ev = self.put("evidence.json", BASE)
        g = self.put("g.json", {"candidates": [cand("가#새것")]})
        code, out, _ = self.run_main(ev, g)
        self.assertEqual(code, 1)
        self.assertIn("문제: g.json 가#새것", out)
        self.assertTrue((self.root / "evidence.merged.json").is_file())    # --out 이 없으면 evidence.json 옆

    def test_bad_arguments(self):
        ev = self.put("evidence.json", BASE)
        self.assertEqual(self.run_main(ev)[0], 2)
        self.assertEqual(self.run_main(ev, str(self.root / "없음.json"))[0], 2)
        self.assertEqual(self.run_main(ev, self.put("g.json", {}), "--only", "docs")[0], 2)
        self.assertEqual(self.run_main("--compare", ev)[0], 2)
        bad = self.root / "깨짐.json"
        bad.write_text("{", encoding="utf-8")
        code, _, err = self.run_main(str(bad), ev)
        self.assertEqual(code, 2)
        self.assertIn("입력 문제", err)

    def test_group_template_asset_is_a_valid_empty_group(self):
        tpl = json.loads((ROOT / "assets" / "묶음-근거-틀.json").read_text(encoding="utf-8"))
        merged, ops, problems, st = mg.merge(BASE, [("틀.json", tpl)])
        self.assertEqual((problems, st["opinions"]), ([], 0))
        self.assertEqual(len(merged["candidates"]), 4)


if __name__ == "__main__":
    unittest.main()
