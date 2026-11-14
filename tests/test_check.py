"""scripts/check.py 시험. 임시 폴더와 가짜 skills-ref 명령만 쓴다. 스킬 이름과 글은 모두 지어낸 것이다."""
import importlib.util
import io
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location("ssc_" + name, ROOT / "scripts" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


chk = load("check")
FRONT = "---\nname: {name}\ndescription: 지어낸 시험용 스킬\n---\n\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def put(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def skill(self, name, body):
        self.put(f"skills/{name}/SKILL.md", FRONT.format(name=name) + body)
        return self.root / "skills" / name

    def problems(self, d, **kw):
        return chk.check_skill(d, **kw)[0]

    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = chk.main(argv)
        return code, out.getvalue()


class Links(Base):
    def test_good_skill_passes(self):
        d = self.skill("가", "`python3 scripts/run.py` 로 돌린다. 기록은 references/기록.md를 본다. 틀은 assets/틀.txt.\n")
        self.put("skills/가/scripts/run.py", "print(1)\n")
        self.put("skills/가/references/기록.md", "# 기록\n\n있음\n")
        self.put("skills/가/assets/틀.txt", "<이름>\n")
        self.put("skills/가/scripts/__pycache__/run.cpython-39.pyc", "x")
        self.put("skills/가/assets/.DS_Store", "x")
        self.assertEqual(self.problems(d), [])

    def test_missing_file_and_orphan(self):
        d = self.skill("가", "1줄\n`scripts/없는.py` 를 돌린다.\n")
        self.put("skills/가/assets/고아.txt", "x")
        got = self.problems(d)
        self.assertIn("가리키는 파일이 없음: scripts/없는.py (SKILL.md:7)", got)
        self.assertIn("아무도 가리키지 않는 파일(고아): assets/고아.txt", got)

    def test_name_only_mention_is_not_orphan(self):
        d = self.skill("가", "`helper.py` 는 run 이 읽는다. scripts/run.py\n")
        self.put("skills/가/scripts/run.py", "")
        self.put("skills/가/scripts/helper.py", "")
        self.assertEqual(self.problems(d), [])

    def test_example_paths_and_other_words_are_ignored(self):
        d = self.skill("가", "`scripts/<이름>.py`, references/…, assets/*.json, {x}/scripts/a.py, myscripts/b.py, references/\n")
        self.assertEqual(self.problems(d), [])

    def test_sibling_skill_path(self):
        self.skill("나", "`assets/나-틀.txt`\n")
        self.put("skills/나/assets/나-틀.txt", "x")
        d = self.skill("가", "틀은 `skills/나/assets/나-틀.txt` 와 `skills/나/assets/없음.txt`. 남의 것 `tools/x/scripts/y.py`.\n")
        got = self.problems(d)
        self.assertEqual(got, ["가리키는 파일이 없음: 나/assets/없음.txt (SKILL.md:6)"])

    def test_own_name_prefix_counts_as_own(self):
        d = self.skill("가", "`~/.agents/skills/가/scripts/run.py`\n")
        self.assertEqual(self.problems(d), ["가리키는 파일이 없음: scripts/run.py (SKILL.md:6)"])

    def test_sentence_end_and_dotted_names(self):
        d = self.skill("가", "references/a.b.md. 그리고 scripts/x.py에서.\n")
        self.put("skills/가/references/a.b.md", "# a\n\n글\n")
        self.put("skills/가/scripts/x.py", "")
        self.assertEqual(self.problems(d), [])


class Orphans(Base):
    def test_file_run_by_a_schedule_file_is_not_orphan(self):
        d = self.skill("가", "글\n")
        self.put("skills/가/schedule.yaml", "every_hour:\n  run: python3 scripts/hourly_job.py --quiet\n")
        self.put("skills/가/scripts/hourly_job.py", "print(1)\n")
        self.assertEqual(chk.check_skill(d)[:2], ([], []))

    def test_imported_helper_module_is_not_orphan(self):
        d = self.skill("가", "`scripts/main_tool.py` 를 돌린다.\n")
        self.put("skills/가/scripts/main_tool.py", "from shared_bits import load\n")
        self.put("skills/가/scripts/shared_bits.py", "def load():\n    pass\n")
        self.assertEqual(chk.check_skill(d)[:2], ([], []))

    def test_stem_must_be_a_whole_word(self):
        d = self.skill("가", "`scripts/main_tool.py`\n")
        self.put("skills/가/scripts/main_tool.py", "import bitsy_extra\n")
        self.put("skills/가/scripts/bits.py", "")
        self.assertEqual(self.problems(d), ["아무도 가리키지 않는 파일(고아): scripts/bits.py"])

    def test_korean_name_with_particle_is_found(self):
        d = self.skill("가", "틀은 assets/보고-틀.md를 베낀다.\n")
        self.put("skills/가/assets/보고-틀.md", "<이름>\n")
        self.assertEqual(chk.check_skill(d)[:2], ([], []))

    def test_reference_pointed_only_by_another_file_is_a_warning(self):
        d = self.skill("가", "`references/목차.md` 를 본다.\n")
        self.put("skills/가/references/목차.md", "# 목차\n\n자세한 것은 references/깊이.md\n")
        self.put("skills/가/references/깊이.md", "# 깊이\n\n글\n")
        probs, warns, _ = chk.check_skill(d)
        self.assertEqual(probs, [])
        self.assertEqual(warns, ["SKILL.md 가 직접 가리키지 않음: references/깊이.md (references/목차.md 가 가리킴)"])

    def test_test_files_are_never_orphans(self):
        d = self.skill("가", "글\n")
        for name in ("test_a.py", "b_test.py", "conftest.py", "__init__.py"):
            self.put(f"skills/가/scripts/{name}", "")
        self.assertEqual(self.problems(d), [])

    def test_real_orphan_still_fails_main(self):
        d = self.skill("가", "글\n")
        self.put("skills/가/assets/버린-틀.txt", "x")
        code, out = self.run_main([str(d)])
        self.assertEqual(code, 2)
        self.assertIn("문제: 아무도 가리키지 않는 파일(고아): assets/버린-틀.txt", out)


class Elsewhere(Base):
    def test_script_in_sibling_skill_is_a_warning(self):
        self.skill("나", "`scripts/fetch_all.py`\n")
        self.put("skills/나/scripts/fetch_all.py", "")
        d = self.skill("가", "그 폴더에서: `python3 scripts/fetch_all.py`\n")
        probs, warns, _ = chk.check_skill(d)
        self.assertEqual(probs, [])
        self.assertEqual(warns, ["이 폴더에 없는 파일: scripts/fetch_all.py (SKILL.md:6). 다른 스킬 폴더 나 에 있음. 그 폴더 기준으로 쓴 경로로 보임"])

    def test_script_in_upper_folder_is_a_warning(self):
        (self.root / ".git").mkdir()
        self.put("scripts/collect_all.py", "")
        d = self.skill("가", "저장소 뿌리에서 `python3 scripts/collect_all.py`\n")
        probs, warns, _ = chk.check_skill(d)
        self.assertEqual(probs, [])
        self.assertIn("위 폴더 ../../ 에 있음", warns[0])

    def test_search_stops_at_git_root(self):
        (self.root / "repo" / ".git").mkdir(parents=True)
        self.put("scripts/outside.py", "")
        self.put("repo/skills/가/SKILL.md", FRONT.format(name="가") + "`scripts/outside.py`\n")
        probs, warns, _ = chk.check_skill(self.root / "repo" / "skills" / "가")
        self.assertEqual(probs, ["가리키는 파일이 없음: scripts/outside.py (SKILL.md:6)"])

    def test_missing_everywhere_is_a_problem_and_warning_alone_passes(self):
        self.skill("나", "`references/표.md`\n")
        self.put("skills/나/references/표.md", "# 표\n\n글\n")
        d = self.skill("가", "`references/표.md` 와 `assets/없는-틀.txt`\n")
        probs, warns, _ = chk.check_skill(d)
        self.assertEqual(probs, ["가리키는 파일이 없음: assets/없는-틀.txt (SKILL.md:6)"])
        self.assertEqual(len(warns), 1)
        (self.root / "skills" / "가" / "SKILL.md").write_text(FRONT.format(name="가") + "`references/표.md`\n", encoding="utf-8")
        code, out = self.run_main([str(self.root / "skills")])
        self.assertEqual(code, 0, out)
        self.assertIn("가: 통과(주의 1개)", out)
        self.assertIn("(문제 0개, 주의 1개)", out)


class Shape(Base):
    def test_empty_dir_and_empty_reference(self):
        d = self.skill("가", "references/빈.md\n")
        self.put("skills/가/references/빈.md", "  \n")
        (d / "scripts" / "안쪽").mkdir(parents=True)
        got = self.problems(d)
        self.assertIn("references 파일이 비었거나 읽히지 않음: references/빈.md", got)
        self.assertIn("빈 폴더: scripts/", got)

    def test_size_and_front(self):
        d = self.skill("가", "줄\n" * 30)
        got = self.problems(d, max_lines=20, max_bytes=50)
        self.assertTrue(any("줄(한도 20)" in p for p in got))
        self.assertTrue(any("바이트(한도 50)" in p for p in got))
        self.put("skills/나/SKILL.md", "# 머리 없음\n")
        self.assertEqual(self.problems(self.root / "skills" / "나"), ["머리: 머리 없음"])
        self.put("skills/다/SKILL.md", "---\nname: 다\n---\n")
        self.assertEqual(self.problems(self.root / "skills" / "다"), ["머리에 description 가 없음"])
        self.put("skills/라/SKILL.md", "")
        self.assertIn("SKILL.md 가 비어 있음", self.problems(self.root / "skills" / "라"))


class SkillsRef(Base):
    def fake(self, code):
        p = self.put(f"bin/fake-{code}", f"#!/bin/sh\necho 'fake result {code}'\nexit {code}\n")
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
        return str(p)

    def test_pass_fail_and_skip(self):
        d = self.skill("가", "글\n")
        with patch.dict(os.environ, {"SKILLS_REF_BIN": self.fake(0)}):
            probs, _, notes = chk.check_skill(d, use_skills_ref=True)
        self.assertEqual((probs, notes), ([], ["skills-ref: 통과"]))
        with patch.dict(os.environ, {"SKILLS_REF_BIN": self.fake(1)}):
            probs, _, _ = chk.check_skill(d, use_skills_ref=True)
        self.assertEqual(probs, ["skills-ref validate: fake result 1"])
        with patch.dict(os.environ, {"SKILLS_REF_BIN": ""}), patch.object(chk.shutil, "which", return_value=None):
            probs, _, notes = chk.check_skill(d, use_skills_ref=True)
        self.assertEqual(probs, [])
        self.assertIn("건너뜀", notes[0])


class Main(Base):
    def test_exit_codes(self):
        self.skill("가", "글\n")
        self.assertEqual(self.run_main([str(self.root / "skills")])[0], 0)
        self.put("skills/나/SKILL.md", "")
        code, out = self.run_main([str(self.root / "skills")])
        self.assertEqual(code, 2)
        self.assertIn("스킬 2개 · 통과 1 · 문제 있음 1", out)
        (self.root / "none").mkdir()
        self.assertEqual(self.run_main([str(self.root / "none")])[0], 2)

    def test_this_skill_passes_its_own_check(self):
        code, out = self.run_main([str(ROOT)])
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
