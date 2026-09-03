#!/usr/bin/env python3
"""Build the canonical Grok instruction JSON set from Markdown rule files.

The admin screen supports importing one Markdown file at a time. This utility
is for creating or rebuilding a complete baseline set without introducing a
database dependency.
"""
from __future__ import annotations

import argparse
import json
import re
import uuid
from pathlib import Path


CORE_PROMPT = """# Wan2.2 i2v 프롬프트 변환기

너는 웹툰 원고 컷을 Wan2.2 image-to-video 프롬프트로 바꾸는 변환기다.
입력은 이미지 1장이고, 여러 장이면 각 이미지를 순서대로 독립 처리한다.
서론, 후기, 조언, 질문을 쓰지 않는다. 아래 규칙 문서를 오름차순으로 읽고,
이미지에 맞는 규칙만 적용한다.

## 앱 응답 계약 (최우선)

다른 문서의 출력 형식 지시와 무관하게, 반드시 다음 키만 가진 JSON 객체 하나만
반환한다. Markdown 코드 펜스, 설명, 제목을 덧붙이지 않는다.

```json
{"positivePrompt":"...","imageType":"background|indoor_background|static_character|dynamic_image","warnings":[]}
```

positivePrompt는 Wan2.2 I2V에 전달할 영어 문장이고, warnings는 경고 코드 배열이다.
"""

DOCUMENTS = (
    ("rule_00_type_router", "규칙 00 · 유형 판정", "ROUTER", 20),
    ("rule_01_background", "규칙 01 · 배경 이미지", "GUIDE", 30),
    ("rule_02_static_character", "규칙 02 · 정적 캐릭터", "GUIDE", 40),
    ("rule_03_dynamic_image", "규칙 03 · 동적 이미지", "GUIDE", 50),
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rule-00", type=Path, required=True)
    parser.add_argument("--rule-01", type=Path, required=True)
    parser.add_argument("--rule-02", type=Path, required=True)
    parser.add_argument("--rule-03", type=Path, required=True)
    parser.add_argument("--workflow-id", required=True, help="Workflow file name receiving this instruction set")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source_paths = (args.rule_00, args.rule_01, args.rule_02, args.rule_03)

    documents = [
        {
            "id": _id_for("core_wan_i2v_transformer"),
            "code": "core_wan_i2v_transformer",
            "title": "Wan2.2 i2v 프롬프트 변환기",
            "role": "CORE",
            "contentMarkdown": CORE_PROMPT,
            "source": "DOBEDUB Studio system instruction",
            "sortOrder": 10,
            "version": 1,
            "isActive": True,
        }
    ]
    for (code, title, role, sort_order), source_path in zip(DOCUMENTS, source_paths, strict=True):
        if not source_path.is_file():
            raise SystemExit(f"Markdown file does not exist: {source_path}")
        documents.append(
            {
                "id": _id_for(code),
                "code": code,
                "title": _heading_or(title, source_path.read_text(encoding="utf-8")),
                "role": role,
                "contentMarkdown": source_path.read_text(encoding="utf-8").strip(),
                "source": source_path.name,
                "sortOrder": sort_order,
                "version": 1,
                "isActive": True,
            }
        )
    document_set = {
        "schemaVersion": "2.0",
        "setCode": "grok_wan_i2v_transformer",
        "responseContract": {
            "format": "json_object",
            "fields": ["positivePrompt", "imageType", "warnings"],
            "instruction": "Return exactly one JSON object with these fields and no Markdown fence or commentary.",
        },
        "workflowInstructionSets": [{
            "workflowId": args.workflow_id,
            "version": 1,
            "documents": documents,
        }],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document_set, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(documents)} documents to {args.output}")


def _heading_or(fallback: str, markdown: str) -> str:
    for line in markdown.splitlines():
        heading = re.sub(r"^\s*#+\s*", "", line).strip()
        if heading:
            return heading[:191]
    return fallback


def _id_for(code: str) -> str:
    return f"grok_instruction_{uuid.uuid5(uuid.NAMESPACE_URL, code).hex[:16]}"


if __name__ == "__main__":
    main()
