#!/usr/bin/env python3
"""STE-KO 검사기. 기계로 셀 수 있는 규칙만 본다.

  python3 scripts/lint.py README.md --surface 문서
  python3 scripts/lint.py 'copy/**/*.md' --surface UI
  python3 scripts/lint.py --self-test

의존성 없음. 위반이 있으면 종료 코드 1을 낸다.
"""
import argparse
import glob
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 10.2 표면별 상한
SURFACES = {
    "문서": {"eojeol": 25, "para": 6},
    "대화": {"eojeol": 25, "para": 4},
    "코딩": {"eojeol": 20, "para": 4},
    "UI":  {"eojeol": 12, "para": 2},
}

# 어간 뒤에 어미가 붙으면 마지막 음절이 합쳐진다. `되어지` + `-ㅂ니다` 는 `되어집니다` 가
# 되어 문자열 매칭이 뚫린다. 종성 결합과 모음 축약을 음절 단위로 펼쳐서 잡는다.
_CONTRACT = {0: 1, 4: 5, 8: 9, 11: 12, 13: 14, 20: 6}  # ㅏ→ㅐ, ㅓ→ㅔ, ㅗ→ㅘ, ㅚ→ㅙ, ㅜ→ㅝ, ㅣ→ㅕ


def syllable_class(ch):
    """한 음절을 같은 초성 + 원·축약 중성 + 모든 종성의 문자 클래스로 편다."""
    if not ("가" <= ch <= "힣"):
        return re.escape(ch)
    code = ord(ch) - 0xAC00
    cho, jung = code // 588, (code % 588) // 28
    jungs = {jung} | ({_CONTRACT[jung]} if jung in _CONTRACT else set())
    chars = "".join(chr(0xAC00 + cho * 588 + j * 28 + t) for j in sorted(jungs) for t in range(28))
    return f"[{chars}]"


def stem_pattern(stem, open_ended=True):
    """어간 문자열을 활용형까지 덮는 정규식으로 만든다."""
    tokens = stem.split()
    parts = []
    for i, tok in enumerate(tokens):
        last = i == len(tokens) - 1
        body = "".join(
            syllable_class(c) if (last and j == len(tok) - 1 and open_ended) else re.escape(c)
            for j, c in enumerate(tok)
        )
        parts.append(body)
    # 한글에는 \b 가 없다. 앞뒤에 한글이 붙으면 다른 단어다 — `등급` 의 `등` 을 잡지 않는다.
    body = r"\s*".join(parts)
    tail = r"[가-힣]*" if open_ended else r"(?![가-힣])"
    return r"(?<![가-힣])" + body + tail


# 3.2 이중피동 — dictionary.md B절과 같은 목록이다. --no-vocab 에서도 `필수` 규칙은 잡는다.
DOUBLE_PASSIVE = re.compile("|".join(
    stem_pattern(s) for s in (
        "되어지", "보여지", "불려지", "쓰여지", "읽혀지", "잊혀지", "나뉘어지",
        "모여지", "짜여지", "열려지", "닫혀지", "놓여지", "믿겨지", "걸려지", "풀려지",
    )
))
# 8.1 범위 물결표
TILDE_RANGE = re.compile(r"\d\s*~\s*\d")
# 8.5 말줄임표 종결
ELLIPSIS_END = re.compile(r"(?:\.\.\.|…)\s*$")
# 10.4 앞 턴 되풀이 문두 (`대화` 표면)
ECHO_OPEN = re.compile(r"^(좋은 질문|정확한 지적|말씀하신|말씀해 주신|확인해 보겠|살펴보겠|알겠습니다)")


def load_dictionary(path=None):
    """dictionary.md 비승인 어간을 정규식으로 컴파일한다.

    어간 표기 규칙 — `-`로 끝나면 활용형 전체, `다`로 끝나는 기본형도 활용형 전체,
    표시가 없으면 그 형태 그대로다.
    """
    path = Path(path) if path else ROOT / "dictionary.md"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        m = re.match(r"^\|\s*`([^`]+)`\s*\|\s*(.+?)\s*\|", line)
        if not m:
            continue
        term, good = m.group(1), m.group(2)
        stem = term.strip("-").strip()
        if not stem:
            continue
        open_ended = term.endswith("-") or (stem.endswith("다") and len(stem) > 2)
        if stem.endswith("다") and open_ended:
            stem = stem[:-1]
        try:
            out.append((re.compile(stem_pattern(stem, open_ended)), term, good.replace("`", "")))
        except re.error:
            continue
    return out


def strip_noise(line):
    """검사에서 뺄 것 — 인라인 코드, 링크 URL, 마크다운 강조."""
    line = re.sub(r"`[^`]*`", " ", line)
    line = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line)
    line = re.sub(r"[*_#]", "", line)
    return line


def prose_lines(text):
    """산문 줄만 (번호, 원문 문자열)로 낸다. 코드 펜스·표·인용·frontmatter는 건너뛴다."""
    in_fence = in_front = False
    for i, raw in enumerate(text.split("\n"), 1):
        if raw.startswith("```"):
            in_fence = not in_fence
            continue
        if i == 1 and raw.strip() == "---":
            in_front = True
            continue
        if in_front:
            if raw.strip() == "---":
                in_front = False
            continue
        if in_fence or not raw.strip():
            continue
        if raw.lstrip().startswith(("|", ">", "    ", "\t")):
            continue
        yield i, raw


def sentences(line):
    return [s.strip() for s in re.split(r"(?<=다[.!?])\s+|(?<=[.!?])\s+", line) if s.strip()]


def check(path, surface, vocab):
    limit = SURFACES[surface]
    text = Path(path).read_text(encoding="utf-8")
    hits = []
    tails, tail_lines = [], []

    for lineno, raw in prose_lines(text):
        clean = strip_noise(raw)
        is_heading = raw.lstrip().startswith("#")
        is_list = bool(re.match(r"\s*(?:[-*+]|\d+\.)\s", raw))
        stripped = re.sub(r"^\s*(?:[-*+]|\d+\.)\s+", "", clean)

        for sent in sentences(stripped):
            n = len(sent.split())
            if n > limit["eojeol"]:
                hits.append((lineno, "4.1", f"{n}어절 (상한 {limit['eojeol']}) — {sent[:34]}…"))
            # 4.8 은 산문에서만 센다. 제목과 목록은 같은 형태로 끝나는 것이 자연스럽다.
            words = sent.split()
            if words and not is_heading and not is_list:
                tails.append(words[-1].rstrip(".!?"))
                tail_lines.append(lineno)

        for m in DOUBLE_PASSIVE.finditer(clean):
            hits.append((lineno, "3.2", f"이중피동 `{m.group()}`"))
        if TILDE_RANGE.search(clean):
            hits.append((lineno, "8.1", "범위에 물결표 — 마크다운이 취소선으로 읽는다"))
        if ELLIPSIS_END.search(clean.rstrip()):
            hits.append((lineno, "8.5", "말줄임표로 문장을 끝냈다"))
        if surface == "대화" and ECHO_OPEN.match(clean.strip()):
            hits.append((lineno, "10.4", "앞 턴을 되풀이하며 시작한다"))
        for pat, bad, good in vocab:
            m = pat.search(clean)
            if m:
                hits.append((lineno, "1.3", f"비승인 `{m.group()}` ({bad}) → {good}"))
                break

    # 4.8 같은 종결어절 3연속
    run = 1
    for i in range(1, len(tails)):
        run = run + 1 if tails[i] == tails[i - 1] else 1
        if run >= 3:
            hits.append((tail_lines[i], "4.8", f"`{tails[i]}`가 {run}문장 연속"))

    # 4.7 문단 문장 수
    for block in re.split(r"\n\s*\n", text):
        if re.match(r"\s*(?:```|\||>|#|[-*+]\s|\d+\.\s)", block):
            continue
        joined = " ".join(l for _, l in prose_lines(block))
        n = len(sentences(strip_noise(joined)))
        if n > limit["para"]:
            first = block.strip().split("\n")[0][:28]
            hits.append((0, "4.7", f"문단에 {n}문장 (상한 {limit['para']}) — {first}…"))

    return sorted(hits)


def self_test():
    import tempfile
    bad = """긴 문장이 하나 있다.
이 문장은 어절을 아주 많이 넣어서 상한을 넘기려고 일부러 아주 길게 늘여 쓴 문장이고 그래서 스물다섯 어절을 확실하게 넘어가도록 단어를 계속 하나씩 더 붙여 나가고 있는 중이다.
결과가 좋아 보여집니다.
항목은 3~5개다.
좋은 질문입니다.
"""
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(bad)
        p = f.name
    got = {rule for _, rule, _ in check(p, "대화", [])}
    for want in ("4.1", "3.2", "8.1", "10.4"):
        assert want in got, f"{want}를 못 잡았다: {got}"
    clean = "짧게 쓴다.\n검사를 통과해야 한다.\n"
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(clean)
        q = f.name
    assert check(q, "대화", []) == [], check(q, "대화", [])
    print("self-test OK")


def main():
    ap = argparse.ArgumentParser(description="STE-KO 검사기")
    ap.add_argument("paths", nargs="*", help="검사할 마크다운 파일")
    ap.add_argument("--surface", default="문서", choices=list(SURFACES), help="적용 표면 (기본 문서)")
    ap.add_argument("--dictionary", help="dictionary.md 경로")
    ap.add_argument("--no-vocab", action="store_true", help="1.3 비승인 어휘 검사를 끈다")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()

    if a.self_test:
        self_test()
        return 0
    if not a.paths:
        ap.error("검사할 파일이 없다")

    vocab = [] if a.no_vocab else load_dictionary(a.dictionary)
    files = [f for p in a.paths for f in (glob.glob(p, recursive=True) or [p])]
    total = 0
    for f in files:
        if not Path(f).is_file():
            print(f"{f}: 파일이 없다", file=sys.stderr)
            continue
        for lineno, rule, msg in check(f, a.surface, vocab):
            loc = f"{f}:{lineno}" if lineno else f
            print(f"{loc}\t{rule}\t{msg}")
            total += 1
    print(f"\n{len(files)}개 파일, 위반 {total}건 (표면 {a.surface})", file=sys.stderr)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
