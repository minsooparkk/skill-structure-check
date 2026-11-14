"""scripts/judge.py 시험. 판정 순서를 못 박는다. 근거는 모두 지어낸 것이다."""
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

EM_DASH = chr(0x2014)   # 엠대시. 글자로 적으면 이 파일도 찾기에 걸린다
ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location("ssc_" + name, ROOT / "scripts" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


judge = load("judge")


def F(status, why="지어낸 까닭", source="SKILL.md:1"):
    return {"status": status, "why": why, "source": source}


def move(**facts):
    base = {k: F("unknown", "", "") for k in judge.LABEL if k in ("read_by_program", "restricted_runner", "notes_section",
                                                                    "copied_verbatim", "needed_every_run")}
    base.update(facts)
    return {"id": "가#c1", "skill": "가", "suggest": "references", "signals": ["title:history"],
            "target": {"kind": "section", "title": "## 시험 기록", "line": 10, "lines": 4}, "facts": base, "note": ""}


def script(**facts):
    base = {k: F("unknown", "", "") for k in ("irreversible", "needs_judgment", "single_command", "observed")}
    base.update(facts)
    return {"id": "가#c2", "skill": "가", "suggest": "scripts", "signals": ["inline-code"],
            "target": {"kind": "block", "title": "## 절차", "line": 20, "lines": 6, "lang": "bash", "before": "아래를 돌린다."},
            "facts": base, "note": ""}


class Norm(unittest.TestCase):
    def test_loose_values(self):
        for v in ("yes", "YES", " y ", "true", True, "예", "네", "있음"):
            self.assertEqual(judge.norm(v), "yes", v)
        for v in ("no", "N", "false", False, "아니오", "아니요", "없음"):
            self.assertEqual(judge.norm(v), "no", v)
        for v in ("", None, "maybe", "모름", 0, 1, "unknown"):
            self.assertEqual(judge.norm(v), "unknown", v)


class MoveOrder(unittest.TestCase):
    def test_program_reading_beats_rarely_needed(self):
        r = judge.judge(move(read_by_program=F("yes"), needed_every_run=F("no"), copied_verbatim=F("yes")))
        self.assertEqual((r["decision"], r["confidence"]), ("keep", "확실"))
        self.assertEqual([f["fact"] for f in r["used"]], ["read_by_program"])

    def test_restricted_runner_beats_copied(self):
        r = judge.judge(move(read_by_program=F("no"), restricted_runner=F("yes"), copied_verbatim=F("yes")))
        self.assertEqual(r["decision"], "keep")

    def test_notes_section_stays(self):
        r = judge.judge(move(read_by_program=F("no"), restricted_runner=F("no"), notes_section=F("yes"), needed_every_run=F("no")))
        self.assertEqual(r["decision"], "keep")
        self.assertIn("배운 것", r["reason"])

    def test_copied_goes_to_assets_then_needed_decides(self):
        base = dict(read_by_program=F("no"), restricted_runner=F("no"), notes_section=F("no"))
        self.assertEqual(judge.judge(move(copied_verbatim=F("yes"), **base))["decision"], "assets")
        self.assertEqual(judge.judge(move(copied_verbatim=F("no"), needed_every_run=F("no"), **base))["decision"], "references")
        self.assertEqual(judge.judge(move(copied_verbatim=F("no"), needed_every_run=F("yes"), **base))["decision"], "keep")

    def test_unknown_stops_and_asks(self):
        r = judge.judge(move(read_by_program=F("no"), copied_verbatim=F("yes")))
        self.assertEqual((r["decision"], r["confidence"]), ("undecided", "판단 필요"))
        self.assertIn("권한이 좁은 실행", r["ask"])
        self.assertEqual([f["fact"] for f in r["used"]], ["read_by_program", "restricted_runner"])

    def test_one_keep_fact_is_enough(self):
        r = judge.judge(move(notes_section=F("yes")))                    # 앞 근거는 모두 unknown
        self.assertEqual((r["decision"], r["confidence"]), ("keep", "확실"))
        self.assertEqual([f["fact"] for f in r["used"]], ["notes_section"])
        r = judge.judge(move(restricted_runner=F("yes", "", "")))
        self.assertEqual((r["decision"], r["confidence"]), ("keep", "불확실"))
        for v in ("no", "unknown"):
            r = judge.judge(move(read_by_program=F(v), notes_section=F("yes")))
            self.assertEqual(r["decision"], "keep")

    def test_copied_and_needed_still_wait_for_earlier_facts(self):
        self.assertEqual(judge.judge(move(copied_verbatim=F("yes")))["decision"], "undecided")
        self.assertEqual(judge.judge(move(needed_every_run=F("yes")))["decision"], "undecided")
        self.assertEqual(judge.judge(move(needed_every_run=F("no")))["decision"], "undecided")
        r = judge.judge(move(read_by_program=F("no"), restricted_runner=F("no"), notes_section=F("no"),
                             copied_verbatim=F("yes"), needed_every_run=F("yes")))
        self.assertEqual(r["decision"], "assets")      # needed_every_run yes 가 먼저 붙잡지 않는다

    def test_empty_why_and_source_is_uncertain(self):
        r = judge.judge(move(read_by_program=F("no", "", ""), restricted_runner=F("no"), notes_section=F("no"),
                             copied_verbatim=F("no"), needed_every_run=F("no")))
        self.assertEqual((r["decision"], r["confidence"]), ("references", "불확실"))
        self.assertEqual(r["missing"], ["read_by_program"])
        only_source = judge.judge(move(read_by_program=F("yes", "", "run.py:3")))
        self.assertEqual(only_source["confidence"], "확실")

    def test_broken_facts_do_not_crash(self):
        c = move()
        c["facts"] = "엉뚱한 값"
        self.assertEqual(judge.judge(c)["confidence"], "판단 필요")
        c["facts"] = {"read_by_program": "yes"}
        self.assertEqual(judge.judge(c)["decision"], "keep")


class ScriptOrder(unittest.TestCase):
    def test_irreversible_first(self):
        r = judge.judge(script(irreversible=F("yes"), needs_judgment=F("no"), single_command=F("no"), observed=F("yes")))
        self.assertEqual(r["decision"], "keep")
        self.assertIn("읽기·준비 단계만 따로 뺄 수 있는지 본다", r["reason"])

    def test_judgment_and_single_command_stay(self):
        self.assertEqual(judge.judge(script(irreversible=F("no"), needs_judgment=F("yes")))["decision"], "keep")
        r = judge.judge(script(irreversible=F("no"), needs_judgment=F("no"), single_command=F("yes"), observed=F("yes")))
        self.assertEqual(r["decision"], "keep")

    def test_not_observed_waits(self):
        r = judge.judge(script(irreversible=F("no"), needs_judgment=F("no"), single_command=F("no"), observed=F("no")))
        self.assertEqual(r["decision"], "keep")
        self.assertIn("처음 실제로 해 본 뒤에", r["reason"])

    def test_all_clear_goes_to_scripts(self):
        r = judge.judge(script(irreversible=F("no"), needs_judgment=F("no"), single_command=F("no"), observed=F("yes")))
        self.assertEqual((r["decision"], r["confidence"]), ("scripts", "확실"))

    def test_one_keep_fact_is_enough_for_scripts(self):
        for k, v in (("irreversible", "yes"), ("needs_judgment", "yes"), ("single_command", "yes"), ("observed", "no")):
            r = judge.judge(script(**{k: F(v)}))
            self.assertEqual((r["decision"], r["confidence"]), ("keep", "확실"), k)
            self.assertEqual([f["fact"] for f in r["used"]], [k])
        self.assertEqual(judge.judge(script(observed=F("yes")))["decision"], "undecided")

    def test_unknown_observed_needs_judgment(self):
        r = judge.judge(script(irreversible=F("no"), needs_judgment=F("no"), single_command=F("no")))
        self.assertEqual(r["confidence"], "판단 필요")


class MainAndFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = judge.main(argv)
        return code, out.getvalue(), err.getvalue()

    def write(self, data, name="evidence.json"):
        p = self.root / name
        p.write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return p

    def evidence(self):
        refs = move(read_by_program=F("no"), restricted_runner=F("no"), notes_section=F("no"), copied_verbatim=F("no"),
                    needed_every_run=F("no"))
        tmpl = move(read_by_program=F("no"), restricted_runner=F("no"), notes_section=F("no"), copied_verbatim=F("yes"))
        tmpl.update(id="가#c3", target={"kind": "block", "title": "### 3. 보고 쓰기", "line": 30, "lines": 5, "lang": "markdown",
                                        "before": "아래 모양 그대로 채운다."})
        return {"root": "/somewhere/skills", "skills": {"가": {}, "나": {}},
                "candidates": [refs, script(irreversible=F("no"), needs_judgment=F("no"), single_command=F("no")), tmpl]}

    def test_same_evidence_same_files(self):
        ev = self.write(self.evidence())
        self.assertEqual(self.run_main([str(ev), "--out", str(self.root / "a")])[0], 0)
        self.assertEqual(self.run_main([str(ev), "--out", str(self.root / "b")])[0], 0)
        for f in ("report.md", "result.json", "move-plan.skeleton.json"):
            self.assertEqual((self.root / "a" / f).read_text(encoding="utf-8"), (self.root / "b" / f).read_text(encoding="utf-8"))

    def test_report_has_three_groups_and_skill_todo(self):
        ev = self.write(self.evidence())
        self.run_main([str(ev)])
        rep = (self.root / "report.md").read_text(encoding="utf-8")
        for h in ("## 확실한 것 (2)", "## 불확실한 것 (0)", "## 판단이 필요한 것 (1)", "## 스킬별 할 일", "### 나", "후보 없음"):
            self.assertIn(h, rep)
        self.assertIn("`SKILL.md:1`", rep)
        self.assertNotIn(EM_DASH, rep)

    def test_skeleton_is_prefilled(self):
        ev = self.write(self.evidence())
        self.run_main([str(ev)])
        plan = json.loads((self.root / "move-plan.skeleton.json").read_text(encoding="utf-8"))
        ops = plan["skills"]["가"]["ops"]
        self.assertEqual(ops[0]["kind"], "section")
        self.assertEqual(ops[0]["head"], "## 시험 기록")
        self.assertEqual(ops[0]["dest"], "references/시험-기록.md")
        self.assertEqual(ops[0]["pointer"], ["<채울 것>"])
        self.assertEqual(ops[1]["kind"], "block")
        self.assertEqual(ops[1]["start"], "아래 모양 그대로 채운다.")
        self.assertTrue(ops[1]["raw"])
        self.assertEqual(ops[1]["dest"], "assets/보고-쓰기.md")
        self.assertIn("references/시험-기록.md", plan["skills"]["가"]["refs"])
        self.assertEqual(plan["root"], "/somewhere/skills")

    def test_manual_candidate_is_judged_and_planned(self):
        ev = self.evidence()
        manual = move(read_by_program=F("no"), restricted_runner=F("no"), notes_section=F("no"), copied_verbatim=F("no"),
                      needed_every_run=F("no"))
        manual.update(id="가#m1", signals=["manual"], suggest="references",
                      target={"kind": "section", "title": "## 처리 흐름", "line": 40, "lines": 12})
        ev["candidates"].append(manual)
        p = self.write(ev)
        self.run_main([str(p)])
        rows = json.loads((self.root / "result.json").read_text(encoding="utf-8"))
        self.assertEqual([r["decision"] for r in rows if r["id"] == "가#m1"], ["references"])
        self.assertIn("신호 manual", (self.root / "report.md").read_text(encoding="utf-8"))
        plan = json.loads((self.root / "move-plan.skeleton.json").read_text(encoding="utf-8"))
        heads = [o.get("head") for o in plan["skills"]["가"]["ops"]]
        self.assertIn("## 처리 흐름", heads)
        self.assertIn("references/처리-흐름.md", plan["skills"]["가"]["refs"])

    def test_bad_files(self):
        self.assertEqual(self.run_main([str(self.root / "none.json")])[0], 2)
        self.assertEqual(self.run_main([str(self.write("[1, 2]"))])[0], 2)
        self.assertEqual(self.run_main([str(self.write("{not json"))])[0], 2)
        self.assertEqual(self.run_main([str(self.write({"candidates": {}}))])[0], 2)
        code, out, _ = self.run_main([str(self.write({"candidates": [1, "x", move()]}))])
        self.assertEqual(code, 0)
        self.assertIn("읽지 못한 후보 2개", out)


if __name__ == "__main__":
    unittest.main()
