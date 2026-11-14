"""scripts/backup.py 시험. 임시 폴더만 쓴다. 날짜와 시각은 인자로 넣는다(오늘에 기대지 않는다)."""
import datetime
import importlib.util
import io
import os
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


bk = load("backup")
NOW = datetime.datetime(2026, 1, 20, 9, 30, 15)


class Backup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.old_cwd = os.getcwd()
        os.chdir(str(self.root))
        self.addCleanup(os.chdir, self.old_cwd)
        self.src = self.root / "skills" / "가" / "SKILL.md"
        self.src.parent.mkdir(parents=True)
        self.src.write_text("처음 글\n", encoding="utf-8")

    def run_main(self, argv, now=NOW):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = bk.main(argv, now=now)
        return code, out.getvalue(), err.getvalue()

    def test_copy_keeps_relative_path_and_prints_undo(self):
        code, out, _ = self.run_main(["나누기", str(self.src), "--date", "2026-01-20"])
        self.assertEqual(code, 0)
        dst = self.root / ".skill-backup" / "2026-01-20" / "나누기" / "skills" / "가" / "SKILL.md"
        self.assertEqual(dst.read_text(encoding="utf-8"), "처음 글\n")
        self.assertEqual(dst.stat().st_mode & 0o777, 0o600)
        self.assertIn("되돌리기:", out)
        self.assertIn(f'cp "{dst}" "{self.src}"', out)

    def test_same_content_is_not_copied_again_and_first_copy_is_kept(self):
        self.run_main(["t", str(self.src), "--date", "2026-01-20"])
        code, out, _ = self.run_main(["t", str(self.src), "--date", "2026-01-20"])
        self.assertIn("이미 있음(같은 내용)", out)
        folder = self.root / ".skill-backup" / "2026-01-20" / "t" / "skills" / "가"
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["SKILL.md"])
        self.src.write_text("고친 글\n", encoding="utf-8")
        self.run_main(["t", str(self.src), "--date", "2026-01-20"])
        self.assertEqual((folder / "SKILL.md").read_text(encoding="utf-8"), "처음 글\n")
        self.assertEqual((folder / "SKILL.md.093015").read_text(encoding="utf-8"), "고친 글\n")
        self.src.write_text("또 고친 글\n", encoding="utf-8")
        self.run_main(["t", str(self.src), "--date", "2026-01-20"])
        self.assertEqual((folder / "SKILL.md.093015-2").read_text(encoding="utf-8"), "또 고친 글\n")

    def test_dest_option(self):
        code, _, _ = self.run_main(["t", str(self.src), "--dest", str(self.root / "사본"), "--date", "2026-01-20"])
        self.assertEqual(code, 0)
        self.assertTrue((self.root / "사본" / "2026-01-20" / "t" / "skills" / "가" / "SKILL.md").is_file())

    def test_bad_arguments(self):
        for argv in (["t", str(self.src), "--date", "2026-13-01"], ["t", str(self.src), "--date", "../../x"],
                     ["a/b", str(self.src)], [".숨김", str(self.src)], [" t", str(self.src)]):
            self.assertEqual(self.run_main(argv)[0], 2, argv)

    def test_default_date_is_from_now(self):
        self.run_main(["t", str(self.src)])
        self.assertTrue((self.root / ".skill-backup" / "2026-01-20" / "t").is_dir())

    def test_new_and_unreadable_files(self):
        code, out, _ = self.run_main(["t", str(self.root / "없는.md"), "--date", "2026-01-20"])
        self.assertEqual(code, 0)
        self.assertIn("새 파일(사본 없음", out)
        code, out, _ = self.run_main(["t", str(self.root / "skills"), "--date", "2026-01-20"])
        self.assertEqual(code, 1)
        self.assertIn("못 읽음", out)


if __name__ == "__main__":
    unittest.main()
