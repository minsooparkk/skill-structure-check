"""<스크립트 이름> 시험. 임시 폴더와 가짜 명령만 쓴다. 값은 모두 지어낸 것이다.

이 파일은 스킬-구조-점검 의 틀이다. <…> 자리를 채워 tests/test_<이름>.py 로 둔다.
돌리기: python3 -m unittest discover -s tests -v
"""
import importlib.util
import io
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "<이름>.py"
TODAY = date(2026, 1, 20)        # 오늘에 기대지 않도록 날짜를 넣는다


def load(path):
    spec = importlib.util.spec_from_file_location("under_test", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def fake_command(self, stdout, code=0):
        """가짜 명령 파일을 만들어 경로를 돌려준다. 스크립트는 환경변수로 이 명령을 쓴다."""
        p = self.root / "fake-tool"
        p.write_text("#!/bin/sh\ncat <<'EOF'\n" + stdout + "\nEOF\nexit " + str(code) + "\n", encoding="utf-8")
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
        return str(p)

    def run_main(self, mod, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = mod.main(argv)
        return code, buf.getvalue()


class Behaviour(Base):
    def test_ok_output_gives_0(self):
        with patch.dict(os.environ, {"MY_SKILL_TOOL_BIN": self.fake_command("하나\n둘")}):
            mod = load(SCRIPT)                     # 환경변수를 읽은 뒤에 불러온다
            code, out = self.run_main(mod, ["--since", TODAY.isoformat()])
        self.assertEqual(code, 0)
        self.assertIn("모두 2건", out)

    def test_issue_gives_2_and_hides_content(self):
        with patch.dict(os.environ, {"MY_SKILL_TOOL_BIN": self.fake_command("ERROR 가짜 고객 이름")}):
            mod = load(SCRIPT)
            code, out = self.run_main(mod, ["--since", TODAY.isoformat()])
        self.assertEqual(code, 2)
        self.assertNotIn("고객", out)              # 출력에 내용을 싣지 않는다

    def test_missing_command_gives_1(self):
        with patch.dict(os.environ, {"MY_SKILL_TOOL_BIN": str(self.root / "없는-명령")}):
            mod = load(SCRIPT)
            code, _ = self.run_main(mod, [])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
