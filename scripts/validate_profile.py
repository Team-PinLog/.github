#!/usr/bin/env python3
"""Team-PinLog 공개 조직 프로필 계약을 검증한다 (Python stdlib only)."""

from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REQUIRED_SECTIONS = (
    "## 서비스 가치",
    "## MVP 핵심 흐름",
    "## 핵심 개념",
    "## 아키텍처",
    "## 제품 저장소",
    "## 팀 도구와 지식",
    "## 공식 문서",
)

PRODUCT_REPOS = ("front", "back", "ai", "docs", "infra", "mockup")
TEAM_TOOLS = ("cowork", "pico-agent")
CANONICAL_DOCS = "https://github.com/Team-PinLog/docs/blob/main/README.md"

FORBIDDEN_PATTERNS = (
    (r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])", "IP 주소"),
    (r"(?i)\b(?:localhost|127\.0\.0\.1)\b", "로컬 호스트"),
    (r"(?i)\b[\w.-]+\.ssafy\.io\b", "운영 호스트명"),
    (r"(?i)\b(?:pinlog-(?:prod|dev)|argocd|kube-system)\b", "내부 namespace"),
    (r"(?i)(?:api[_ -]?key|secret|token|password)\s*[:=]", "자격증명 형태"),
    (r"(?i)production[- ]ready|프로덕션[- ]?준비|운영\s*중|정식\s*출시|출시\s*완료", "과도한 제품 상태 주장"),
    (r"(?i)brand-resource|raw\.githubusercontent\.com|private[-_/ ]asset", "비공개/raw 자산"),
)

LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\((https?://[^)\s]+)\)")


def _read(path: Path, errors: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        errors.append(f"필수 파일 없음: {path.as_posix()}")
    except UnicodeDecodeError:
        errors.append(f"UTF-8 아님: {path.as_posix()}")
    return ""


def extract_links(markdown: str) -> list[str]:
    return LINK_RE.findall(markdown)


def github_api_url(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "github.com":
        return None
    parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    owner, repo = parts[:2]
    api = f"https://api.github.com/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}"
    if len(parts) == 2:
        return api
    if len(parts) >= 5 and parts[2] == "blob":
        branch = parts[3]
        file_path = "/".join(parts[4:])
        return (
            f"{api}/contents/{urllib.parse.quote(file_path, safe='/')}"
            f"?ref={urllib.parse.quote(branch)}"
        )
    return None


def broken_links(links: list[str], timeout: float = 15.0) -> list[str]:
    failures: list[str] = []
    for link in sorted(set(links)):
        api_url = github_api_url(link)
        if api_url is None:
            failures.append(f"허용되지 않거나 검증할 수 없는 링크: {link}")
            continue
        request = urllib.request.Request(
            api_url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "team-pinlog-org-profile-validator",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    failures.append(f"링크 응답 {response.status}: {link}")
        except urllib.error.HTTPError as exc:
            if exc.code not in (403, 429):
                failures.append(f"링크 확인 실패: {link} (HTTP {exc.code})")
                continue
            # Anonymous GitHub API rate limit에 걸리면 같은 공개 URL을 HEAD로 확인한다.
            fallback = urllib.request.Request(
                link,
                method="HEAD",
                headers={"User-Agent": "team-pinlog-org-profile-validator"},
            )
            try:
                with urllib.request.urlopen(fallback, timeout=timeout) as response:
                    if response.status != 200:
                        failures.append(f"링크 응답 {response.status}: {link}")
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as fallback_exc:
                failures.append(
                    f"링크 확인 실패: {link} ({type(fallback_exc).__name__})"
                )
        except (urllib.error.URLError, TimeoutError) as exc:
            failures.append(f"링크 확인 실패: {link} ({type(exc).__name__})")
    return failures


def validate_profile(markdown: str) -> list[str]:
    errors: list[str] = []
    lines = markdown.splitlines()

    if not lines or not re.fullmatch(r"#\s+PinLog", lines[0].strip()):
        errors.append("profile/README.md의 첫 줄은 '# PinLog' H1이어야 함")
    if len(lines) < 3 or not lines[2].strip():
        errors.append("H1 다음에 제품 한 줄 가치가 있어야 함")

    for section in REQUIRED_SECTIONS:
        if section not in markdown:
            errors.append(f"필수 섹션 없음: {section}")

    if re.search(r"^\s*\|.*\|\s*$", markdown, re.MULTILINE):
        errors.append("모바일 가독성을 위해 Markdown 표를 사용할 수 없음")

    if "MVP" not in markdown:
        errors.append("제품 상태를 MVP로 명시해야 함")

    for pattern, label in FORBIDDEN_PATTERNS:
        if re.search(pattern, markdown):
            errors.append(f"금지 정보/표현 감지: {label}")

    if re.search(r"!\[[^\]]*\]\([^)]+\)|<img\b", markdown, re.IGNORECASE):
        errors.append("승인된 공개 이미지가 없으므로 이미지 참조를 둘 수 없음")

    links = extract_links(markdown)
    if re.search(r"(?<!https:)//github\.com", markdown):
        errors.append("GitHub 링크는 HTTPS만 허용")
    for link in links:
        if not link.startswith("https://github.com/Team-PinLog/"):
            errors.append(f"Team-PinLog HTTPS GitHub 링크만 허용: {link}")

    for repo in PRODUCT_REPOS:
        expected = f"https://github.com/Team-PinLog/{repo}"
        if expected not in links:
            errors.append(f"제품 저장소 링크 없음: {repo}")
    for repo in TEAM_TOOLS:
        expected = f"https://github.com/Team-PinLog/{repo}"
        if expected not in links:
            errors.append(f"팀 도구 링크 없음: {repo}")
    if CANONICAL_DOCS not in links:
        errors.append("공식 docs canonical README CTA가 없음")

    product_start = markdown.find("## 제품 저장소")
    tools_start = markdown.find("## 팀 도구와 지식")
    docs_start = markdown.find("## 공식 문서")
    if product_start >= 0 and tools_start >= 0:
        product_block = markdown[product_start:tools_start]
        for tool in TEAM_TOOLS:
            if f"Team-PinLog/{tool}" in product_block:
                errors.append(f"팀 도구가 제품 저장소에 섞임: {tool}")
    if tools_start >= 0 and docs_start >= 0:
        tools_block = markdown[tools_start:docs_start]
        for tool in TEAM_TOOLS:
            if f"Team-PinLog/{tool}" not in tools_block:
                errors.append(f"팀 도구 섹션 링크 없음: {tool}")

    if "```mermaid" not in markdown or "flowchart TB" not in markdown:
        errors.append("Mermaid TB 아키텍처가 없음")
    architecture_tokens = (
        "U[사용자] --> FE[Frontend]",
        "FE --> BE[Spring Backend]",
        "BE --> PG[(PostgreSQL + pgvector)]",
        "BE --> R[(Redis)]",
        "BE --> AI[FastAPI AI]",
        "AI --> PG",
        "AI --> EXT[외부 Embedding / LLM API]",
        "k3s",
        "Argo CD",
        "GitOps",
    )
    for token in architecture_tokens:
        if token not in markdown:
            errors.append(f"아키텍처 계약 없음: {token}")
    if re.search(r"FE(?:\[[^\]]*\])?\s*--?>\s*AI", markdown):
        errors.append("Client/Frontend가 AI를 직접 호출할 수 없음")

    mermaid_end = markdown.find("```", markdown.find("```mermaid") + len("```mermaid"))
    fallback_start = markdown.find("### 텍스트 대체 설명")
    if mermaid_end < 0 or fallback_start <= mermaid_end:
        errors.append("Mermaid 뒤에 텍스트 대체 설명이 없음")
    elif "```text" not in markdown[fallback_start:]:
        errors.append("아키텍처 텍스트 fallback 코드 블록이 없음")

    return errors


def validate_repository(root: Path, check_links: bool = True) -> list[str]:
    errors: list[str] = []
    profile_path = root / "profile" / "README.md"
    maintenance_path = root / "README.md"
    profile = _read(profile_path, errors)
    maintenance = _read(maintenance_path, errors)

    if profile:
        errors.extend(validate_profile(profile))
    if maintenance:
        if "조직 공개 프로필" not in maintenance or "profile/README.md" not in maintenance:
            errors.append("README.md에 조직 공개 프로필 maintenance 설명이 없음")
        for pattern, label in FORBIDDEN_PATTERNS:
            if re.search(pattern, maintenance):
                errors.append(f"README.md 금지 정보/표현 감지: {label}")
    if check_links and profile:
        errors.extend(broken_links(extract_links(profile)))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--offline", action="store_true", help="네트워크 링크 확인 생략")
    args = parser.parse_args(argv)

    errors = validate_repository(args.root.resolve(), check_links=not args.offline)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Profile validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
