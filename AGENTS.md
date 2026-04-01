# Agent 가이드 — 변경대비표 자동화

## 이 프로젝트에서 코드 수정 시 규칙

### 반드시 지킬 것
- XML 레벨 순회 유지 (`lxml` 직접 사용, `doc.paragraphs` 단독 사용 금지)
- 원본 DOCX 파일 수정 금지
- 변경대비표 5열 양식 준수: Page | Item | Previous Version | Current Version | Note
- Page 열에는 실제 페이지 번호 기입 (섹션 경로 아님)
- Item 열에는 `"상위섹션번호. 상위섹션명\n\n하위섹션번호. 하위항목명"` 형태
- 섹션 번호는 Word에서 표시되는 번호와 반드시 일치
  - 빈 텍스트 heading은 번호 카운트 제외 (Word도 건너뜀)
  - `numId=0` → 전문(front-matter), 번호 없음
  - `numId≠0`이고 heading 스타일 numbering과 같은 abstractNum → 본문 heading, 번호 있음
- `as any`, `@ts-ignore` 등 타입 억제 금지
- `shell=True` in subprocess 금지

### 참고 양식
변경대비표 참고 양식 DOCX를 기준으로:
- Page 열: 실제 페이지 번호 (예: "12-14", "37-40", "54, 56, 57", "전체")
- Item 열: 섹션 계층 포함 (예: "5. 임상시험 디자인\n\n5.1. 디자인 설명")
- Previous/Current: 핵심 변경 내용 원문 인용
- Note: 변경 사유 (추정 시 "추정: ..." 접두어)

### 파이프라인 구조
```
Phase 1 (로컬): DOCX → blocks.json → section_index.json → matched_pairs.json
Phase 2 (로컬): → change_candidates.json (텍스트/표/이미지/헤더 diff)
Phase 3 (Claude CLI): → change_rows.json (5열 양식 행)
Phase 4 (로컬): → 변경대비표.docx
```

### 페이지 번호 추출
- `scripts/extract_pages.py`가 처리
- Microsoft Word 앱으로 DOCX→PDF 변환 (`docx2pdf`)
- PDF에서 heading 텍스트(font size > 13)와 페이지 번호 매핑 (`PyMuPDF`)
- 매칭 안 되는 하위 섹션은 상위/이전 섹션 페이지를 상속
- 결과: `page_map.json` (section_id → page_start/page_end/page_str)
- `run_diff.py`에서 change_candidates에 `page_hint` 필드로 주입

### 테스트
- 테스트용 프로토콜 DOCX (V1, V2)로 검증
- 참고 양식과 비교하여 Page/Item 열 형태가 일치하는지 확인
- 변경대비표 참고 양식의 행은 다른 프로토콜의 예시임 — 내용 대조 대상 아님
