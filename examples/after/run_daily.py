"""(가짜 예시) 매일 아침 스킬 문의-답장의 SKILL.md 를 통째로 읽어 프롬프트에 넣는 예약 스크립트.

skill-structure-check 의 예시로 지어낸 것이다. 모델을 부르지 않고, 실제로 돌리지도 않는다.
inventory.py --repo 가 이런 프로그램을 '본문을 읽는 곳'으로 잡는지 보여 주려고 둔다.
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE / "문의-답장" / "SKILL.md"


def build_prompt(inbox_text):
    doc = SKILL.read_text(encoding="utf-8")
    return doc + "\n\n오늘 들어온 문의:\n" + inbox_text
