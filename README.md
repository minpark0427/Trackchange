# 변경대비표 자동 생성기 (DOCX Comparison Table Generator)

임상시험 프로토콜 등 DOCX 문서 2개 버전을 비교하여 **변경대비표(Comparison Table of Change)** DOCX를 자동으로 생성합니다.

## 결과물 예시

입력: V1.docx, V2.docx → 출력: 5열 변경대비표 DOCX (Landscape, 실제 페이지 번호 포함)

| Page | Item | Previous Version | Current Version | Note |
|------|------|------------------|-----------------|------|
| 24 | 1. Introduction<br><br>1.1. Unmet Medical Need | (Karimi-Shah BA., 2015) | (Karimi-Shah BA., Chowdhury BA, 2015) | Added co-author |
| 30 | 2. Study Objectives and Endpoints<br><br>2.2.2. Secondary Endpoints | refer Section 8.1.2 | refer **to** Section 8.1.2 | Grammatical correction |
| 32-36 | 3. Study Plan<br><br>3.1. Description of Overall Study Design | (Not present) | SAD5 (1400 mg) \| 8 \| 6 \| 2 | New highest dose group added |

---

## 빠른 시작

### 1. 의존성 설치

```bash
pip3 install python-docx lxml diff-match-patch docx2pdf PyMuPDF
```

> **참고**: `docx2pdf`는 Microsoft Word가 설치되어 있어야 동작합니다 (페이지 번호 추출용).

### 2. 전체 파이프라인 실행

```bash
# Phase 1: 섹션 분할 + 매칭
python3 scripts/run_split.py \
  --old "이전버전.docx" \
  --new "새버전.docx" \
  --out work/

# Phase 2: 변경 감지 (텍스트/표/이미지/헤더)
python3 scripts/run_diff.py \
  --work-dir work/ \
  --out work/diff/change_candidates.json

# Phase 3: Claude로 변경대비표 행 생성 (Claude Code CLI 필요)
python3 scripts/run_rows.py \
  --work-dir work/ \
  --out work/rows/change_rows.json

# Phase 4: DOCX 출력
python3 scripts/run_export.py \
  --work-dir work/ \
  --out-dir work/output/
```

`work/output/` 에 변경대비표 DOCX가 생성됩니다.

### 3. Claude Code Skill로 사용 (권장)

Skill이 `~/.claude/skills/docx-comparison/`에 설치되어 있으면, Claude Code에서 바로 사용 가능합니다:

```
> 변경대비표 만들어줘
```

Claude가 파일 경로를 물어본 뒤 자동으로 전체 파이프라인을 실행합니다.

---

## 파이프라인 구조

```
DOCX V1 ──┐                                    ┌── change_rows.json
           ├→ Phase 1 → Phase 2 → Phase 3 → Phase 4 → 변경대비표.docx
DOCX V2 ──┘                                    └── (5열 표, Landscape)
```

| Phase | 역할 | 핵심 기술 | 산출물 |
|-------|------|----------|--------|
| **1. Section Split** | DOCX를 Heading 기반 섹션으로 분할 + old↔new 매칭 + 페이지 번호 추출 | lxml XML 순회, 자동번호 복원, docx2pdf+PyMuPDF | `blocks.json`, `section_index.json`, `matched_pairs.json`, `page_map.json` |
| **2. Diff** | 텍스트/표/이미지/헤더 변경 감지 + 페이지 번호 주입 | diff-match-patch, 셀 단위 표 비교 | `change_candidates.json` (286건, page_hint 포함) |
| **3. Claude Rows** | 변경 후보를 5열 양식으로 정리 | Claude Code CLI 병렬 호출 | `change_rows.json` (138행) |
| **4. DOCX Export** | 참고 양식과 동일한 스타일의 DOCX 생성 | python-docx + lxml 테두리 | 최종 `.docx` 파일 |

> Phase 1~2는 Claude 없이 로컬에서 동작합니다. Phase 3만 Claude Code CLI가 필요합니다.

---

## 요구사항

- **Python 3.8+**
- **Microsoft Word** — DOCX→PDF 변환으로 페이지 번호 추출에 필요
- **Claude Code CLI** (`claude --version`으로 확인) — Phase 3에 필요
- 패키지: `python-docx`, `lxml`, `diff-match-patch`, `docx2pdf`, `PyMuPDF`

---

## 개별 스크립트 사용

각 스크립트는 독립 실행 가능합니다:

```bash
# 블록 추출만
python3 scripts/extract_blocks.py --docx "문서.docx" --out work/new

# 섹션 분할만
python3 scripts/split_sections.py --blocks work/new/blocks.json --out work/new/section_index.json

# 텍스트 diff만
python3 scripts/diff_text.py --work-dir work/ --out work/diff/text_candidates.json

# 표 diff만
python3 scripts/diff_tables.py --work-dir work/ --out work/diff/table_candidates.json

# 이미지 해시 비교만
python3 scripts/diff_media.py --old-media work/old/media_inventory.json --new-media work/new/media_inventory.json --out work/diff/media_candidates.json
```

---

## 설계 원칙

1. **XML 직접 순회** — python-docx 상위 API가 아닌 lxml으로 `w:body` 자식을 직접 순회하여 문단-표 혼합 순서를 보존
2. **자동 번호 복원** — `numbering.xml`의 abstractNum 패턴을 파싱하여 Word 표시 번호와 동일하게 재현. 빈 heading은 번호 카운트에서 제외. `numId=0`(전문)과 `numId≠0`(본문) 구분
3. **실제 페이지 번호** — DOCX→PDF 변환(Microsoft Word) 후 PyMuPDF로 heading 위치 → 페이지 번호 매핑
4. **로컬 diff + Claude 정리** — 변경 감지는 로컬 Python(재현 가능, 감사 가능), Claude는 사람이 읽기 좋은 형태로 정리만
5. **셀 단위 표 비교** — vMerge/gridSpan 병합 셀을 정규 그리드로 풀어서 좌표 단위 비교
6. **적응형 분할** — H1-H3 기본, 30블록 초과 시 H4/H5 추가 분할

---

## 파일 구조

```
Trackchange/
├── scripts/
│   ├── extract_blocks.py    # DOCX → blocks.json (XML 순회 + 자동번호 복원)
│   ├── extract_pages.py     # DOCX→PDF→페이지 번호 추출 (Word 필요)
│   ├── split_sections.py    # blocks → section_index.json
│   ├── match_sections.py    # old↔new 섹션 매칭
│   ├── run_split.py         # Phase 1 오케스트레이터 (페이지 추출 포함)
│   ├── schema.py            # 변경 후보 스키마
│   ├── diff_text.py         # 텍스트 diff (diff-match-patch)
│   ├── diff_tables.py       # 표 셀 단위 diff
│   ├── diff_media.py        # 이미지 SHA-256 비교
│   ├── diff_headers.py      # Header/Footer diff
│   ├── run_diff.py          # Phase 2 오케스트레이터 (페이지 번호 주입)
│   ├── detect_language.py   # 한/영 자동 감지
│   ├── generate_rows.py     # Claude CLI 병렬 호출
│   ├── run_rows.py          # Phase 3 오케스트레이터
│   ├── export_docx.py       # 변경대비표 DOCX 생성
│   └── run_export.py        # Phase 4 오케스트레이터
├── prompts/
│   ├── change_row_system.txt    # Claude system prompt
│   └── change_row_schema.json   # 5열 JSON Schema
├── work/                    # 실행 시 생성되는 중간 산출물
│   ├── old/                 # V1 blocks, sections, media, page_map
│   ├── new/                 # V2 blocks, sections, media, page_map
│   ├── diff/                # change_candidates.json
│   ├── rows/                # change_rows.json
│   └── output/              # 최종 DOCX
└── requirements.txt
```
