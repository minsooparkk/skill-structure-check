"""scripts/move_sections.py 시험. 임시 폴더만 쓴다. 스킬 이름과 글은 모두 지어낸 것이다.

못 박는 세 가지: 코드 블록 안의 '## ' 줄은 제목이 아니다, 자리가 두 번 나오면 고르지 않는다, 줄 대조 없이 적용하지 않는다.
"""
import datetime
import hashlib
import importlib.util
import io
import json
import os
import tempfile
import unicodedata
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


mv = load("move_sections")
NOW = datetime.datetime(2026, 1, 20, 9, 30, 0)

DOC = """---
name: 가
description: 지어낸 시험용 스킬
metadata:
  version: "1.2.3"
---

# 가

## 절차

1. 자료를 모은다.

예시 출력:
```text
## 시험 기록
OK 3건
```

답장 틀:
```
<이름>님, 안녕하세요.
{내용}
```
틀 끝 설명 한 줄.

## 시험 기록

- 2026-01-01 처음 돌림.

### 시험 기록 안쪽

- 2026-01-02 두 번째.

## 배운 것

- 2026-01-03 하나 배움.
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.skills = self.root / "skills"
        self.doc = self.put("skills/가/SKILL.md", DOC)

    def put(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def plan(self, ops, **kw):
        sk = {"refs": {"references/시험-기록.md": {"title": "시험 기록", "when": "출력이 달라진 것 같을 때 읽는다"}},
              "ops": ops, "allow_lost": 0, "bump_version": True}
        sk.update(kw)
        p = self.root / "plan.json"
        p.write_text(json.dumps({"note": "2026-01-20 글자 그대로 옮김(시험)", "skills": {"가": sk}}, ensure_ascii=False), encoding="utf-8")
        return p

    def run_main(self, plan, *extra):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = mv.main([str(plan), "--root", str(self.skills), "--stage", str(self.root / "stage"), *extra], now=NOW)
        return code, out.getvalue(), err.getvalue()

    def spec(self, ops, **kw):
        s = {"refs": {}, "ops": ops}
        s.update(kw)
        return mv.check_plan({"skills": {"가": s}})["skills"]["가"]


SECTION = {"kind": "section", "head": "## 시험 기록", "dest": "references/시험-기록.md", "keep_heading": True,
           "pointer": ["지난 기록은 `references/시험-기록.md` 에 있다."]}
BLOCK = {"kind": "block", "start": "답장 틀:", "dest": "assets/답장-틀.txt", "raw": True, "pointer": ["틀은 `assets/답장-틀.txt`."]}


class Select(Base):
    def test_heading_inside_code_block_is_not_chosen(self):
        lines = DOC.split("\n")
        _, body, _ = mv.parse_front(DOC)
        _, mask = mv.code_mask(lines, body)
        a, b = mv.sel_section(lines, mask, body, "## 시험 기록")
        self.assertEqual(lines[a], "## 시험 기록")
        self.assertTrue(a > 20)                       # 코드 블록 안(15줄쯤)의 같은 글자가 아니라 진짜 제목
        self.assertIn("- 2026-01-02 두 번째.", lines[a:b])   # 낮은 단계 제목은 품는다
        self.assertNotIn("## 배운 것", lines[a:b])

    def test_code_block_line_does_not_end_a_section(self):
        new, files, _ = mv.build("가", DOC, self.spec([{"kind": "section", "head": "## 절차", "dest": "references/절차.md"}]))
        body = files["references/절차.md"]
        self.assertIn("## 시험 기록\nOK 3건", body)
        self.assertIn("틀 끝 설명 한 줄.", body)
        self.assertIn("## 시험 기록\n\n- 2026-01-01", new)

    def test_anchor_twice_is_refused(self):
        with self.assertRaises(mv.BuildError) as e:
            mv.build("가", DOC, self.spec([{"kind": "to", "start": "2026-01-0", "dest": "references/x.md"}]))
        self.assertIn("3번", str(e.exception))
        with self.assertRaises(mv.BuildError):
            mv.build("가", DOC, self.spec([{"kind": "section", "head": "## 없는 제목", "dest": "references/x.md"}]))

    def test_overlap_is_refused(self):
        ops = [SECTION, {"kind": "to", "start": "- 2026-01-02", "dest": "references/y.md"}]
        with self.assertRaises(mv.BuildError) as e:
            mv.build("가", DOC, self.spec(ops))
        self.assertIn("겹침", str(e.exception))

    def test_half_a_code_block_is_refused(self):
        with self.assertRaises(mv.BuildError) as e:
            mv.build("가", DOC, self.spec([{"kind": "to", "start": "예시 출력:", "end": "OK 3건", "dest": "references/x.md"}]))
        self.assertIn("닫히지 않은 코드 블록", str(e.exception))

    def test_block_needs_a_block_right_after(self):
        with self.assertRaises(mv.BuildError):
            mv.build("가", DOC, self.spec([{"kind": "block", "start": "1. 자료를 모은다.", "dest": "assets/x.txt"}]))


class Build(Base):
    def test_section_moves_verbatim_with_header_and_pointer(self):
        new, files, old_v = mv.build("가", DOC, self.spec([SECTION], bump_version=True,
                                                            refs={"references/시험-기록.md": {"title": "시험 기록", "when": "필요할 때 읽는다"}}),
                                     note="옮긴 날 메모")
        ref = files["references/시험-기록.md"]
        self.assertTrue(ref.startswith("# 가 · 시험 기록\n\n> 가 스킬의 딸린 자료다. 필요할 때 읽는다.\n> 옮긴 날 메모\n\n## 시험 기록\n"))
        self.assertIn("### 시험 기록 안쪽\n\n- 2026-01-02 두 번째.\n", ref)
        self.assertIn("## 시험 기록\n\n지난 기록은 `references/시험-기록.md` 에 있다.\n\n## 배운 것", new)
        self.assertEqual(old_v, '  version: "1.2.3"')
        self.assertIn('  version: "1.3.0"', new)

    def test_raw_block_drops_fences_and_keeps_anchor(self):
        new, files, _ = mv.build("가", DOC, self.spec([BLOCK]))
        self.assertEqual(files["assets/답장-틀.txt"], "<이름>님, 안녕하세요.\n{내용}\n")
        self.assertIn("답장 틀:\n틀은 `assets/답장-틀.txt`.\n틀 끝 설명 한 줄.", new)

    def test_block_with_extra_and_not_raw_keeps_fences(self):
        op = {"kind": "block", "start": "답장 틀:", "extra": 1, "dest": "references/틀.md", "pointer": []}
        new, files, _ = mv.build("가", DOC, self.spec([op]))
        self.assertIn("```\n<이름>님, 안녕하세요.\n{내용}\n```\n틀 끝 설명 한 줄.\n", files["references/틀.md"])
        self.assertNotIn("틀 끝 설명 한 줄.", new)

    def test_same_dest_joins_in_document_order(self):
        ops = [{"kind": "to", "start": "### 시험 기록 안쪽", "end": "## 배운 것", "dest": "references/모음.md"},
               {"kind": "block", "start": "예시 출력:", "dest": "references/모음.md"}]
        _, files, _ = mv.build("가", DOC, self.spec(ops))
        body = files["references/모음.md"]
        self.assertLess(body.index("OK 3건"), body.index("두 번째"))
        self.assertEqual(body.count("# 가 · "), 1)

    def test_insert_and_replace(self):
        ops = [{"kind": "insert", "anchor": "1. 자료를 모은다.", "text": ["2. 새 줄."]},
               {"kind": "insert", "anchor": "## 배운 것", "where": "before", "text": "앞에 넣음"},
               {"kind": "replace", "anchor": "1. 자료를 모은다.", "old": "모은다", "new": "모아 둔다"}]
        new, _, _ = mv.build("가", DOC, self.spec(ops, bump_version=False))
        self.assertIn("1. 자료를 모아 둔다.\n2. 새 줄.", new)
        self.assertIn("앞에 넣음\n## 배운 것", new)
        self.assertIn('version: "1.2.3"', new)

    def test_no_version_line_is_left_alone(self):
        doc = "---\nname: 가\ndescription: x\n---\n\n## 시험 기록\n\n- 하나\n"
        new, _, old_v = mv.build("가", doc, self.spec([SECTION], bump_version=True))
        self.assertEqual(old_v, "")
        self.assertTrue(new.startswith("---\nname: 가\ndescription: x\n---"))

    def test_lost_lines_ignores_fences_and_bumped_version(self):
        old = 'version: "1.0.0"\n```bash\n남는 줄\n사라진 줄\n```\n'
        self.assertEqual(mv.lost_lines(old, "남는 줄\n", {}, skip=['version: "1.0.0"']), ["사라진 줄"])


class Plan(Base):
    def test_unfilled_skeleton_is_refused(self):
        p = self.plan([dict(SECTION, pointer=["<채울 것>"])])
        code, _, err = self.run_main(p)
        self.assertEqual(code, 2)
        self.assertIn("채울 것", err)

    def test_underscore_keys_are_notes_only(self):
        p = self.plan([dict(SECTION, _from="가#c1 [확실]")])
        data = json.loads(p.read_text(encoding="utf-8"))
        data["_about"] = "\"<채울 것>\" 을 모두 채운다"
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(self.run_main(p)[0], 0)

    def test_bad_plans(self):
        for bad in ("[1]", "{}", '{"skills": {"가": {"ops": [{"kind": "move"}]}}}',
                    '{"skills": {"가": {"ops": [{"kind": "section", "head": "## x", "dest": "../x.md"}]}}}',
                    '{"skills": {"가": {"ops": [{"kind": "section", "head": "## x", "dest": "notes/x.md"}]}}}',
                    '{"skills": {"가": {"ops": [], "allow_lost": -1}}}', "{not json"):
            p = self.root / "bad.json"
            p.write_text(bad, encoding="utf-8")
            self.assertEqual(self.run_main(p)[0], 2, bad)

    def test_stage_inside_root_is_refused(self):
        p = self.plan([SECTION])
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = mv.main([str(p), "--root", str(self.skills), "--stage", str(self.skills / "tmp"), "--apply"], now=NOW)
        self.assertEqual(code, 2)
        self.assertEqual(self.doc.read_text(encoding="utf-8"), DOC)


class Apply(Base):
    def test_dry_run_changes_nothing(self):
        code, out, _ = self.run_main(self.plan([SECTION, BLOCK]))
        self.assertEqual(code, 0)
        self.assertIn("줄 대조 맞음", out)
        self.assertEqual(self.doc.read_text(encoding="utf-8"), DOC)
        self.assertFalse((self.skills / "가" / "references").exists())
        self.assertTrue((self.root / "stage" / "가" / "references" / "시험-기록.md").is_file())

    def test_apply_writes_and_backs_up(self):
        code, out, _ = self.run_main(self.plan([SECTION, BLOCK]), "--apply")
        self.assertEqual(code, 0, out)
        self.assertIn("바꿔 끼움", out)
        self.assertIn("되돌리기:", out)
        backup = self.skills / ".skill-backup" / "2026-01-20-093000" / "가" / "SKILL.md"
        self.assertEqual(backup.read_text(encoding="utf-8"), DOC)
        self.assertTrue((self.skills / "가" / "assets" / "답장-틀.txt").is_file())
        self.assertIn("`references/시험-기록.md`", self.doc.read_text(encoding="utf-8"))

    def test_lost_line_blocks_apply(self):
        real = mv.build

        def drop(skill, text, spec, note=""):
            new, files, v = real(skill, text, spec, note)
            return new.replace("- 2026-01-03 하나 배움.\n", ""), files, v

        with patch.object(mv, "build", drop):
            code, out, _ = self.run_main(self.plan([SECTION]), "--apply")
        self.assertEqual(code, 1)
        self.assertIn("빠진 줄 1개(허용 0)", out)
        self.assertIn("빠짐: - 2026-01-03 하나 배움.", out)
        self.assertIn("아무것도 바꾸지 않음", out)
        self.assertEqual(self.doc.read_text(encoding="utf-8"), DOC)

    def test_allow_lost_and_replace_count(self):
        ops = [{"kind": "replace", "anchor": "1. 자료를 모은다.", "old": "모은다", "new": "모아 둔다"}]
        code, out, _ = self.run_main(self.plan(ops))
        self.assertEqual(code, 0, out)

    def test_one_failure_stops_every_skill(self):
        self.put("skills/나/SKILL.md", DOC.replace("name: 가", "name: 나"))
        p = self.plan([SECTION])
        data = json.loads(p.read_text(encoding="utf-8"))
        data["skills"]["나"] = {"ops": [{"kind": "section", "head": "## 없음", "dest": "references/x.md"}]}
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        code, out, _ = self.run_main(p, "--apply")
        self.assertEqual(code, 1)
        self.assertIn("못 만듦  나", out)
        self.assertEqual(self.doc.read_text(encoding="utf-8"), DOC)

    def test_source_changed_in_between_is_skipped(self):
        real = mv.build

        def change_after(skill, text, spec, note=""):
            got = real(skill, text, spec, note)
            self.doc.write_text(DOC + "\n- 다른 세션이 더한 줄\n", encoding="utf-8")
            return got

        with patch.object(mv, "build", change_after):
            code, out, _ = self.run_main(self.plan([SECTION]), "--apply")
        self.assertEqual(code, 1)
        self.assertIn("그 사이 원본이 바뀜", out)
        self.assertIn("다른 세션이 더한 줄", self.doc.read_text(encoding="utf-8"))
        self.assertFalse((self.skills / "가" / "references" / "시험-기록.md").exists())

    def test_existing_file_needs_force(self):
        old = self.put("skills/가/references/시험-기록.md", "# 옛 파일\n\n전부터 있던 글\n")
        code, out, _ = self.run_main(self.plan([SECTION]), "--apply")
        self.assertEqual(code, 1)
        self.assertIn("이미 있음", out)
        self.assertEqual(self.doc.read_text(encoding="utf-8"), DOC)
        code, out, _ = self.run_main(self.plan([SECTION]), "--apply", "--force", "--backup-dir", str(self.root / "bk"))
        self.assertEqual(code, 0, out)
        self.assertIn("2026-01-01 처음 돌림", old.read_text(encoding="utf-8"))
        self.assertEqual((self.root / "bk" / "가" / "references__시험-기록.md").read_text(encoding="utf-8"), "# 옛 파일\n\n전부터 있던 글\n")
        self.assertEqual(hashlib.sha256((self.root / "bk" / "가" / "SKILL.md").read_bytes()).hexdigest(),
                         hashlib.sha256(DOC.encode("utf-8")).hexdigest())

    def test_file_modes_are_kept(self):
        old_mask = os.umask(0o022)
        self.addCleanup(os.umask, old_mask)
        self.doc.chmod(0o644)
        code, out, _ = self.run_main(self.plan([SECTION, BLOCK]), "--apply")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.doc.stat().st_mode & 0o777, 0o644)
        ref = self.skills / "가" / "references" / "시험-기록.md"
        self.assertEqual(ref.stat().st_mode & 0o777, 0o644)
        self.assertTrue(ref.stat().st_mode & 0o004)         # 남도 읽을 수 있다
        self.doc.chmod(0o640)
        p = self.root / "p3.json"
        p.write_text(json.dumps({"skills": {"가": {"ops": [{"kind": "insert", "anchor": "## 배운 것", "text": ["더함"]}]}}},
                                ensure_ascii=False), encoding="utf-8")
        self.assertEqual(self.run_main(p, "--apply")[0], 0)
        self.assertEqual(self.doc.stat().st_mode & 0o777, 0o640)

    def test_own_temp_stage_is_removed_after_full_success(self):
        def count():
            return len(list(Path(tempfile.gettempdir()).glob("skill-move-*")))
        before = count()
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = mv.main([str(self.plan([SECTION])), "--root", str(self.skills), "--apply",
                            "--backup-dir", str(self.root / "bk")], now=NOW)
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("임시 폴더를 지웠다", out.getvalue())
        self.assertEqual(count(), before)

    def test_given_stage_and_dry_run_stage_are_kept(self):
        code, out, _ = self.run_main(self.plan([SECTION]), "--apply")
        self.assertEqual(code, 0)
        self.assertTrue((self.root / "stage" / "가" / "SKILL.md").is_file())     # --stage 로 받은 폴더는 두고
        self.assertNotIn("임시 폴더를 지웠다", out)

    def test_append_adds_to_an_existing_file_and_can_be_undone(self):
        """전에 옮기다 남은 줄을 이미 있는 딸린 파일 끝에 붙인다. 머리는 다시 붙이지 않고, 옛 파일은 사본으로 남는다."""
        old_ref = "# 가 · 시험 기록\n\n> 가 스킬의 딸린 자료다. 전에 옮긴 글.\n\n- 2025-12-31 전에 옮긴 줄.\n"
        ref = self.put("skills/가/references/시험-기록.md", old_ref)
        op = {"kind": "to", "start": "- 2026-01-01 처음 돌림.", "end": "### 시험 기록 안쪽", "dest": "references/시험-기록.md", "append": True,
              "pointer": []}
        code, out, _ = self.run_main(self.plan([op]))
        self.assertEqual(code, 0, out)
        self.assertIn("덧붙이는 파일 1개", out)
        self.assertNotIn("이미 있는 파일", out)                 # 덧붙이기는 '이미 있음'으로 막지 않는다
        self.assertEqual(ref.read_text(encoding="utf-8"), old_ref)   # 대조만 했을 때는 그대로
        undo = self.root / "undo.sh"
        code, out, _ = self.run_main(self.plan([op]), "--apply", "--backup-dir", str(self.root / "bk"), "--undo-file", str(undo))
        self.assertEqual(code, 0, out)
        self.assertEqual(ref.read_text(encoding="utf-8"), old_ref + "\n- 2026-01-01 처음 돌림.\n")
        self.assertEqual(ref.read_text(encoding="utf-8").count("# 가 · "), 1)
        self.assertNotIn("- 2026-01-01 처음 돌림.", self.doc.read_text(encoding="utf-8"))
        kept = self.root / "bk" / "가" / "references__시험-기록.md"
        self.assertEqual(kept.read_text(encoding="utf-8"), old_ref)
        script = undo.read_text(encoding="utf-8")
        self.assertTrue(script.startswith("#!/bin/sh\n"))
        self.assertIn(f'cp "{kept}" "{ref}"', script)
        self.assertIn(f'cp "{self.root / "bk" / "가" / "SKILL.md"}" "{self.doc}"', script)
        self.assertNotIn("rm ", script)                         # 새로 만든 파일이 없으니 지울 것도 없다
        self.assertIn("되돌리기 파일:", out)

    def test_append_needs_the_file_and_does_not_mix(self):
        op = {"kind": "to", "start": "- 2026-01-01 처음 돌림.", "end": "### 시험 기록 안쪽", "dest": "references/없는-파일.md", "append": True}
        code, out, _ = self.run_main(self.plan([op]), "--apply")
        self.assertEqual(code, 1)
        self.assertIn("append 로 덧붙일 파일을 읽지 못함", out)
        self.assertEqual(self.doc.read_text(encoding="utf-8"), DOC)
        mixed = [dict(op, dest="references/x.md"), {"kind": "section", "head": "## 배운 것", "dest": "references/x.md"}]
        code, _, err = self.run_main(self.plan(mixed))
        self.assertEqual(code, 2)
        self.assertIn("append 와 새로 쓰기가 섞였습니다", err)
        code, _, err = self.run_main(self.plan([dict(op, append="예")]))
        self.assertEqual(code, 2)

    def test_appended_file_changed_in_between_is_skipped(self):
        ref = self.put("skills/가/references/시험-기록.md", "# 옛 글\n")
        op = {"kind": "to", "start": "- 2026-01-01 처음 돌림.", "end": "### 시험 기록 안쪽", "dest": "references/시험-기록.md", "append": True}
        real = mv.lost_lines

        def touch(*a, **k):                                     # 만든 뒤, 바꾸기 전에 누가 그 파일을 고친 경우
            ref.write_text("# 옛 글\n누가 그 사이에 더한 줄\n", encoding="utf-8")
            return real(*a, **k)

        with patch.object(mv, "lost_lines", touch):
            code, out, _ = self.run_main(self.plan([op]), "--apply", "--undo-file", str(self.root / "undo.sh"))
        self.assertEqual(code, 1)
        self.assertIn("그 사이 덧붙일 파일이 바뀜", out)
        self.assertEqual(self.doc.read_text(encoding="utf-8"), DOC)
        self.assertEqual(ref.read_text(encoding="utf-8"), "# 옛 글\n누가 그 사이에 더한 줄\n")
        self.assertFalse((self.root / "undo.sh").exists())        # 바꾼 것이 없으면 되돌리기 파일도 없다

    def test_undo_file_lists_new_files_to_remove(self):
        undo = self.root / "되돌리기.sh"
        code, out, _ = self.run_main(self.plan([SECTION, BLOCK]), "--apply", "--undo-file", str(undo))
        self.assertEqual(code, 0, out)
        script = undo.read_text(encoding="utf-8")
        self.assertIn(f'rm "{self.skills / "가" / "references" / "시험-기록.md"}"', script)
        self.assertIn(f'rm "{self.skills / "가" / "assets" / "답장-틀.txt"}"', script)
        self.assertEqual(script.count("cp "), 1)

    def test_nfd_folder_name_is_found(self):
        nfd = unicodedata.normalize("NFD", "다라")
        self.put(f"skills/{nfd}/SKILL.md", DOC.replace("name: 가", "name: 다라"))
        p = self.root / "p2.json"
        p.write_text(json.dumps({"skills": {"다라": {"ops": [SECTION]}}}, ensure_ascii=False), encoding="utf-8")
        code, out, _ = self.run_main(p)
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
