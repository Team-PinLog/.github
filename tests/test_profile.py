from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "scripts" / "validate_profile.py"

spec = importlib.util.spec_from_file_location("validate_profile", VALIDATOR_PATH)
assert spec is not None and spec.loader is not None
validator = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = validator
spec.loader.exec_module(validator)


class OrganizationProfileContractTests(unittest.TestCase):
    def test_profile_and_maintenance_contract(self) -> None:
        errors = validator.validate_repository(ROOT, check_links=False)
        self.assertEqual([], errors, "\n".join(errors))

    def test_documented_repository_and_docs_links_resolve(self) -> None:
        profile_path = ROOT / "profile" / "README.md"
        self.assertTrue(profile_path.is_file(), "profile/README.md가 아직 구현되지 않음")
        links = validator.extract_links(profile_path.read_text(encoding="utf-8"))
        failures = validator.broken_links(links)
        self.assertEqual([], failures, "\n".join(failures))

    def test_validator_rejects_direct_frontend_to_ai_call(self) -> None:
        invalid = """# PinLog

MVP 소개

```mermaid
flowchart TB
    FE[Frontend] --> AI[FastAPI AI]
```
"""
        errors = validator.validate_profile(invalid)
        self.assertTrue(any("직접 호출" in error for error in errors), errors)

    def test_github_link_mapper_supports_canonical_docs_path(self) -> None:
        mapped = validator.github_api_url(validator.CANONICAL_DOCS)
        self.assertEqual(
            "https://api.github.com/repos/Team-PinLog/docs/contents/README.md?ref=main",
            mapped,
        )


if __name__ == "__main__":
    unittest.main()
