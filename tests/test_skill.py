"""SKILL.md가 STE-KO 규칙을 스스로 지키는지 검사한다."""
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "ste-ko" / "SKILL.md"
OPENAI_YAML = ROOT / "skills" / "ste-ko" / "agents" / "openai.yaml"
SPEC = ROOT / "SPEC.md"
DICT = ROOT / "dictionary.md"


def prose_lines(text):
    """표, 인용(예문), 코드, 제목, 목록을 뺀 산문 줄만 남긴다."""
    for line in text.split("\n"):
        if line.startswith(("|", ">", "```", "#", "-", "1.", "2.", "3.", "4.",
                            "5.", "6.", "7.", "8.", "9.", "10.")):
            continue
        if line.strip():
            yield line


class SteKoSkillTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = SKILL.read_text(encoding="utf-8")
        cls.body = cls.skill.split("---", 2)[2]

    def test_frontmatter_is_discoverable(self):
        self.assertRegex(self.skill, r"(?m)^name: ste-ko$")
        self.assertRegex(self.skill, r"(?m)^description: .+")
        self.assertNotIn("TODO", self.skill)

    def test_all_four_surfaces_present(self):
        for surface in ("`대화`", "`문서`", "`코딩`", "`UI`"):
            self.assertIn(surface, self.skill)

    def test_release_conditions_survive_compression(self):
        """9.4와 9.3이 스킬에서 빠지면 안전 규칙이 통째로 사라진다."""
        for phrase in ("되돌릴 수 없는", "안전 경고", "부정과 한정"):
            self.assertIn(phrase, self.skill)

    def test_no_sentence_over_25_eojeol(self):
        """4.1 설명문 상한."""
        over = []
        for line in prose_lines(self.body):
            for sentence in re.split(r"(?<=다[.])\s+", line):
                if len(sentence.split()) > 25:
                    over.append(sentence)
        self.assertEqual(over, [], f"25어절 초과: {over}")

    def test_no_tilde_range(self):
        """8.1 물결표 금지. 인라인 코드로 인용한 나쁨 예시는 1.4에 따라 원문을 보존한다."""
        stripped = re.sub(r"`[^`]*`", "", self.body)
        hits = [l for l in stripped.split("\n") if "~" in l]
        self.assertEqual(hits, [], f"8.1 위반: {hits}")

    def test_no_double_passive(self):
        """3.2 이중피동 금지. 예문의 나쁨 항목만 예외다."""
        clean = re.sub(r"`[^`]*`", "", self.body)
        hits = re.findall(r"[가-힣]*(?:보여지|되어지|불려지|짜여지)[가-힣]*",
                          "\n".join(l for l in clean.split("\n") if "나쁨" not in l))
        self.assertEqual(hits, [], f"3.2 위반: {hits}")

    def test_spec_links_resolve(self):
        self.assertTrue(SPEC.exists())
        self.assertTrue(DICT.exists())
        self.assertIn("SPEC.md", self.skill)
        self.assertIn("dictionary.md", self.skill)

    def test_lint_self_test_passes(self):
        """검사기가 스스로 만든 위반 샘플을 잡는지 본다."""
        import subprocess
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "lint.py"), "--self-test"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_repo_docs_pass_lint(self):
        """규격 문서가 자기 검사를 통과해야 한다."""
        import subprocess
        targets = [str(ROOT / f) for f in ("README.md", "SPEC.md", "dictionary.md")]
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "lint.py"), *targets,
                            "--surface", "문서"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_openai_interface_exists(self):
        self.assertIn("$ste-ko", OPENAI_YAML.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
