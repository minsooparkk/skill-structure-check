# 스킬-구조-점검 (skill-structure-check)

이미 쓰고 있는 AI 스킬(`SKILL.md` 폴더)을 점검해 **판단 없는 단계는 스크립트로, 가끔 읽는 자료와 베껴 쓰는 틀은 딸린 폴더로** 나누는 스킬입니다(Claude Code 등 `SKILL.md` 를 읽는 도구용).

> SKILL.md 는 일할 때마다 통째로 읽힙니다. 정해진 일은 프롬프트가 아니라 스크립트가 해야 같은 입력에 늘 같은 결과가 나옵니다.

## 하는 일

1. 스킬 폴더를 훑어 크기, 절, 코드 블록과 **옮길 후보**를 찾습니다. 저장소를 주면 그 SKILL.md 를 **읽는 프로그램**도 찾습니다.
2. 모델이 후보마다 **근거**(예, 아니오, 모름과 그 까닭, `파일:줄`)만 채웁니다.
3. 스크립트가 정해진 순서로 근거를 읽어 **갈 곳**과 **확신**을 정합니다. 결과는 **확실한 것 · 불확실한 것 · 판단이 필요한 것**으로 나뉩니다.
4. 스크립트로 뺄 것은 틀과 시험 틀로 만들고, 옮길 것은 **임시 폴더에서 줄 대조를 한 뒤에만** 바꿔 끼웁니다.
5. 가리키는 파일이 있는지, 가리키지 않는 파일이 없는지 확인하고 보고합니다.
6. 같은 틀이나 문안이 **두 벌**인 곳(딸린 파일과 문서, 딸린 파일과 스크립트, 문서와 스크립트)을 찾아 한 곳으로 모으게 돕습니다.
7. 스킬이 많으면 **나눠 읽고 한 곳에서 합칩니다.** 읽는 쪽은 읽기만 하고 묶음 파일 하나만 쓰며, 합치기와 옮기기는 스크립트가 합니다.

| 무엇 | 어디로 | 예 |
|---|---|---|
| 판단 없는 단계(명령 잇기, 표 읽기, 날짜 셈, 틀 채우기, 형식 검사) | `scripts/` | 세 명령을 차례로 돌리는 수집 |
| 가끔 읽는 자료(시험 기록, 손 절차, 형식 표, 긴 설명, 옛 메모) | `references/` | 스크립트가 안 될 때의 손 절차 |
| 그대로 베껴 쓰는 틀과 문안, 스크립트가 읽는 재료 | `assets/` | 보고 틀, 답장 머리글 |
| 절차, 판단 기준, 배운 것 | `SKILL.md` 에 남김 | |

## 설치

```
git clone https://github.com/minsooparkk/skill-structure-check ~/.claude/skills/스킬-구조-점검
```

Python 3.8 이상만 있으면 됩니다. 따로 설치할 것은 없습니다. "내 스킬 점검해서 스크립트로 뺄 것 빼줘"라고 말하면 됩니다.

## 손으로 돌려 보기

`examples/` 의 가짜 스킬 두 개로 처음부터 끝까지 돌려 볼 수 있습니다. 이 폴더에서:

```
python3 scripts/inventory.py examples/before --repo examples/before --out /tmp/ssc-연습
python3 scripts/judge.py examples/evidence-예시.json --out /tmp/ssc-연습
cp -R examples/before /tmp/ssc-연습/skills
python3 scripts/move_sections.py examples/옮기기-계획-예시.json --root /tmp/ssc-연습/skills --apply
python3 scripts/check.py /tmp/ssc-연습/skills
```

- 첫 줄은 후보와 빈 근거 파일을 만듭니다. 둘째 줄은 근거를 채운 예시로 `report.md` 를 만듭니다(`examples/report-예시.md` 와 같습니다).
- 넷째 줄에서 `--apply` 를 빼면 대조만 하고 아무것도 바꾸지 않습니다. 바꾼 결과는 `examples/after/` 와 같습니다.

두 벌 찾기와 묶음 합치기도 같은 예시로 돌려 볼 수 있습니다.

```
python3 scripts/copies.py examples/before
python3 scripts/merge_evidence.py examples/evidence-예시.json examples/묶음-근거-예시.json --only references,assets --out /tmp/ssc-연습
python3 scripts/judge.py /tmp/ssc-연습/evidence.merged.json --out /tmp/ssc-연습
python3 scripts/merge_evidence.py --compare /tmp/ssc-연습/result.json /tmp/ssc-연습/opinions.json
```

- 예시 스킬에는 두 벌이 없어 첫 줄은 '두 벌 있는 스킬 0개'로 끝납니다.
- 둘째 줄은 읽는 쪽 하나가 낸 묶음 파일을 근거 파일에 합치고, 넷째 줄은 판정과 읽은 쪽 의견을 나란히 보여 줍니다.

## 구성

| 파일 | 내용 |
|---|---|
| `SKILL.md` | 절차, 지켜야 할 선, 근거 채우는 법 |
| `scripts/inventory.py` | 훑기: 크기, 머리, 절, 코드 블록, 후보, 본문을 읽는 프로그램(판단 없음, 읽기 전용) |
| `scripts/judge.py` | 근거 파일에 기준을 적용해 갈 곳과 확신을 정함(판단 없음) |
| `scripts/move_sections.py` | 계획대로 references·assets 로 옮김(임시 폴더 → 줄 대조 → `--apply`). 이미 있는 딸린 파일 끝에 붙이기(`append`), 되돌리기 명령을 파일로 남기기(`--undo-file`) |
| `scripts/copies.py` | 같은 글이 두 벌인 곳 찾기(판단 없음, 읽기 전용) |
| `scripts/merge_evidence.py` | 나눠 읽은 묶음 근거를 하나로 합치고, 판정과 읽은 쪽 의견을 견줌(판단 없음) |
| `scripts/check.py` | 끝난 뒤 확인(양쪽 가리킴, 빈 폴더, 크기, 머리, 있으면 `skills-ref validate`). 결과는 문제(실패)와 주의(찍기만)로 나뉨 |
| `scripts/backup.py` | 고치기 전 사본 |
| `references/` | 스크립트로 뺄 것의 기준, references 와 assets 의 기준, 두 벌 걷기, 여러 스킬을 한꺼번에 점검하기, 함정, 검토 기준 |
| `assets/` | 후보 낱말 목록, 스크립트 틀, 시험 틀, 검토 맡기는 글, 근거 채우기를 나눠 맡기는 글, 묶음 근거 틀, 보고 틀 |
| `examples/` | 가짜 스킬 두 개의 나누기 전·후, 근거 파일, 묶음 근거 파일, 옮기기 계획, 보고서 |
| `tests/` | 시험(`python3 -m unittest discover -s tests -v`) |

## 설계에서 지킨 것

- **추상화**: 특정 저장소의 이름이나 경로에 기대지 않습니다. 스킬 폴더 하나든 여러 개가 든 폴더든, 한글이나 빈칸이 든 이름이든, 바로가기 폴더든 돕니다. 후보를 고르는 낱말은 파일(`assets/신호-낱말.json`)로 빼 두어 언어나 제목 꼴이 달라도 낱말만 더하면 됩니다.
- **검토 구조**: 결과는 확실한 것(근거마다 까닭이나 자리가 있음), 불확실한 것(근거 칸이 빔), 판단이 필요한 것(모름에서 멈춤)으로 나뉩니다.
- **셋팅 내재**: 파이썬 표준 라이브러리만 씁니다. 머리(frontmatter)도 작은 읽개로 읽어 PyYAML 이 필요 없습니다.
- **결정론 분리**: 갈 곳은 모델이 정하지 않습니다. 모델은 근거 칸만 채우고 `scripts/judge.py` 가 정합니다. 같은 근거에는 늘 같은 결과가 나옵니다.
- '프로그램이 본문을 읽는가'를 가장 먼저 봅니다. 예약 스크립트가 문서를 통째로 프롬프트에 넣는다면 거기서 글을 옮기지 않습니다.
- 옮기기는 글자 그대로이고, 원래 문서의 모든 줄이 어딘가에 남는지 대조한 뒤에만, 그 사이 원본이 안 바뀐 스킬만 바꿉니다.
- 틀과 문안은 한 곳만 정본으로 둡니다. 스크립트가 쓰는 틀은 스크립트가 그 파일을 읽고, 파일이 깨졌으면 옛 글로 몰래 찍지 않고 멈춰서 알리게 합니다.
- 판정은 근거대로만 나옵니다. 몇 줄 안 되는 조각까지 옮기지 않도록, 계획에서 뺀 것은 까닭을 남깁니다.

## 알아 둘 점

- 예시의 스킬, 프로그램, 이름은 모두 가짜입니다.
- 후보 낱말은 한국어와 영어만 들어 있습니다. 제목 묶음은 지난 기록, 손 절차, 형식, 배운 것, 긴 설명(구성, 구조, 운영, 설계 등)과 틀입니다. 다른 언어는 `assets/신호-낱말.json` 의 묶음마다 낱말을 더하면 됩니다. 낱말로 못 잡는 후보는 모델이 근거 파일에 손으로 더합니다(`signals: ["manual"]`).
- `--apply` 는 원본 사본을 `<root>/.skill-backup/` 에 둡니다. 스킬을 git 으로 관리한다면 `.gitignore` 에 넣습니다. 그 폴더를 다른 프로그램이 훑는다면 `--backup-dir` 로 밖에 둡니다.
- `copies.py` 가 찾은 것은 후보일 뿐입니다. 명령 한 줄이나, 문서는 시키고 스크립트는 검사하는 한 쌍의 값도 같이 나옵니다. 이 저장소 자신에 돌리면 `SKILL.md` 의 근거 표와 `judge.py` 의 물음 몇 줄이 그렇게 나옵니다(이름이 서로 맞는지는 시험이 봅니다).
- `check.py` 의 '주의'는 다른 폴더 기준으로 쓴 경로이거나 다른 파일만 가리키는 자료일 수 있다는 뜻이고, 실패가 아닙니다. 종료 코드는 '문제'가 있을 때만 2 입니다.
- 본문을 읽는 프로그램 찾기는 글자로 찾습니다. 스킬 이름을 변수로 짜 맞춰 경로를 만드는 프로그램은 잡지 못합니다. `reads_body: "maybe"` 는 신호일 뿐이고, 정말 읽는지는 모델이 파일을 열어 확인합니다.
- 실제로 확인한 환경: macOS 의 파이썬 3.9 와 3.11. Windows 와 Linux 에서는 돌려 보지 않았습니다.

## 라이선스

MIT

## English

An Agent Skill that audits existing `SKILL.md` skills and splits them up: deterministic steps go to `scripts/`, rarely needed material to `references/`, verbatim templates to `assets/`.
A script finds candidates and the programs that read each `SKILL.md`; the model only fills in evidence; another script decides where each candidate goes (sure, unsure, needs a decision).
It also finds text that lives in two places (a template in `assets/` that is still pasted into `SKILL.md` or hard-coded in a script), and merges evidence filled in by several readers when there are many skills.
Moves are verbatim, staged in a temp folder and line-checked before anything is replaced. Python 3.8+ standard library only. Docs and output are in Korean; title keywords cover Korean and English.

```
git clone https://github.com/minsooparkk/skill-structure-check ~/.claude/skills/스킬-구조-점검
```
