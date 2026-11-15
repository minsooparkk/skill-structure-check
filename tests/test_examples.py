"""examples/ 끝에서 끝까지: before 를 임시 폴더에 복사해 inventory → judge → move_sections(대조, --apply) → check 를 돌리고
결과가 examples 의 report-예시.md, after/ 와 글자 그대로 같은지 본다. 예시는 모두 지어낸 것이다."""
import ast
import importlib.util
import io
import json
import re
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

EM_DASH = chr(0x2014)   # 엠대시. 글자로 적으면 이 파일도 찾기에 걸린다
ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "examples"


def load(name):
    spec = importlib.util.spec_from_file_location("ssc_" + name, ROOT / "scripts" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


inv, judge, mv, chk = load("inventory"), load("judge"), load("move_sections"), load("check")


def quiet(fn, *a, **kw):
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(io.StringIO()):
        code = fn(*a, **kw)
    return code, out.getvalue()


def tree(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*"))
            if p.is_file() and ".skill-backup" not in p.parts and "__pycache__" not in p.parts}


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.skills = self.root / "skills"
        shutil.copytree(str(EX / "before"), str(self.skills))
        self.work = self.root / "work"

    def test_pipeline_matches_examples(self):
        code, out = quiet(inv.main, [str(self.skills), "--repo", str(self.skills), "--out", str(self.work)])
        self.assertEqual(code, 0, out)
        made = json.loads((self.work / "evidence.json").read_text(encoding="utf-8"))
        sample = json.loads((EX / "evidence-예시.json").read_text(encoding="utf-8"))
        shape = lambda ev: [(c["id"], c["target"], c["suggest"], c["signals"], sorted(c["facts"])) for c in ev["candidates"]]
        self.assertEqual(shape(made), shape(sample))
        reads = [c["reads_body"] for c in made["skills"]["문의-답장"]["consumers"]]
        self.assertEqual(reads, ["maybe"])

        code, _ = quiet(judge.main, [str(EX / "evidence-예시.json"), "--out", str(self.work)])
        self.assertEqual(code, 0)
        self.assertEqual((self.work / "report.md").read_text(encoding="utf-8"), (EX / "report-예시.md").read_text(encoding="utf-8"))

        plan = EX / "옮기기-계획-예시.json"
        before = tree(self.skills)
        code, out = quiet(mv.main, [str(plan), "--root", str(self.skills), "--stage", str(self.root / "stage")])
        self.assertEqual(code, 0, out)
        self.assertEqual(tree(self.skills), before)                 # 대조만 하면 아무것도 바뀌지 않는다
        code, out = quiet(mv.main, [str(plan), "--root", str(self.skills), "--stage", str(self.root / "stage2"),
                                    "--apply", "--backup-dir", str(self.root / "bk")])
        self.assertEqual(code, 0, out)
        self.assertEqual(tree(self.skills), tree(EX / "after"))
        self.assertEqual((self.root / "bk" / "주간-보고" / "SKILL.md").read_bytes(), before["주간-보고/SKILL.md"])

        code, out = quiet(chk.main, [str(self.skills)])
        self.assertEqual(code, 0, out)

    def test_skeleton_from_example_lines_up_with_the_filled_plan(self):
        quiet(judge.main, [str(EX / "evidence-예시.json"), "--out", str(self.work)])
        skel = json.loads((self.work / "move-plan.skeleton.json").read_text(encoding="utf-8"))
        filled = json.loads((EX / "옮기기-계획-예시.json").read_text(encoding="utf-8"))
        pick = lambda p: [(o["kind"], o.get("head") or o.get("start")) for o in p["skills"]["주간-보고"]["ops"]]
        self.assertEqual(pick(skel), pick(filled))
        self.assertEqual(quiet(mv.main, [str(self.work / "move-plan.skeleton.json"), "--root", str(self.skills)])[0], 2)


class Files(unittest.TestCase):
    def test_examples_say_they_are_fake(self):
        for p in ("before/주간-보고/SKILL.md", "before/문의-답장/SKILL.md", "before/run_daily.py",
                  "after/주간-보고/SKILL.md", "evidence-예시.json", "옮기기-계획-예시.json", "report-예시.md", "묶음-근거-예시.json"):
            self.assertIn("가짜", (EX / p).read_text(encoding="utf-8"), p)

    def test_templates_are_valid_python(self):
        for p in ("assets/스크립트-틀.py", "assets/시험-틀.py"):
            ast.parse((ROOT / p).read_text(encoding="utf-8"))

    def test_commands_in_docs_point_to_real_scripts(self):
        rx = re.compile(r"python3? (scripts/[\w-]+\.py)")
        seen = 0
        for doc in ("SKILL.md", "README.md"):
            for rel in rx.findall((ROOT / doc).read_text(encoding="utf-8")):
                seen += 1
                self.assertTrue((ROOT / rel).is_file(), f"{doc} 가 가리키는 {rel} 가 없음")
        self.assertGreater(seen, 8)

    def test_skill_document_names_every_fact_the_judge_uses(self):
        """문서의 근거 표(모델에게 주는 지시)와 judge.py 의 근거 이름(판정)은 한 쌍이다. 한쪽에만 있는 이름이 없어야 한다."""
        doc = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        rows = set(re.findall(r"^\| `(\w+)` \|", doc, re.M))
        used = {f for f, _, _ in judge.MOVE_ORDER} | {f for f, _, _ in judge.SCRIPT_ORDER}
        self.assertEqual(rows, used)

    def test_example_group_file_merges_into_example_evidence(self):
        mg = load("merge_evidence")
        base = json.loads((EX / "evidence-예시.json").read_text(encoding="utf-8"))
        group = json.loads((EX / "묶음-근거-예시.json").read_text(encoding="utf-8"))
        merged, ops, problems, st = mg.merge(base, [("묶음-근거-예시.json", group)], only=["references", "assets"])
        self.assertEqual(problems, [])
        self.assertEqual(st["manual"], 1)
        rows, _ = judge.judge_all(merged)
        got = {r["id"]: r["decision"] for r in rows}
        self.assertEqual(got["문의-답장#m1"], "keep")              # 프로그램이 본문을 읽는 문서라 문안 한 줄도 그대로 둔다
        self.assertEqual(ops["opinions"]["문의-답장#m1"]["opinion"], "keep")

    def test_no_em_dash_anywhere(self):
        for p in ROOT.rglob("*"):
            if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts:
                self.assertNotIn(EM_DASH, p.read_text(encoding="utf-8", errors="replace"), p)


if __name__ == "__main__":
    unittest.main()
