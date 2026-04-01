# DOCX 변경대비표 자동 생성 시스템

## 프로젝트 개요
임상시험 프로토콜 DOCX 2개 버전을 비교하여 **변경대비표(Comparison Table of Change)** DOCX를 자동 생성하는 파이프라인.

## 실행 방법

```bash
# 전체 파이프라인 (Phase 1→2→3→4)
python3 scripts/run_split.py --old "V1.docx" --new "V2.docx" --out work/
python3 scripts/run_diff.py --work-dir work/ --out work/diff/change_candidates.json
python3 scripts/run_rows.py --work-dir work/ --out work/rows/change_rows.json
python3 scripts/run_export.py --work-dir work/ --out-dir work/output/

# 검증 (Phase 5, 선택사항 — 수동 작성 변경대비표와 비교)
python3 scripts/run_validate.py \
  --reference "수동_변경대비표.docx" \
  --generated work/output/generated.docx \
  --out-dir work/validation/
```

또는 Claude Code Skill로: `변경대비표 만들어줘`

## 의존성
- Python 3.8+, `python-docx`, `lxml`, `diff-match-patch`, `docx2pdf`, `PyMuPDF`
- Claude Code CLI (`claude -p`) — Phase 3 행 생성에 필요
- Microsoft Word — DOCX→PDF 변환 (페이지 번호 추출)에 필요

## 핵심 파일
| 파일 | 역할 |
|------|------|
| `scripts/extract_blocks.py` | DOCX → blocks.json (XML 직접 순회, 자동번호 복원) |
| `scripts/extract_pages.py` | DOCX→PDF→페이지 번호 추출 (Microsoft Word 필요) |
| `scripts/split_sections.py` | 블록 → 섹션 분할 (adaptive heading) |
| `scripts/match_sections.py` | old↔new 섹션 매칭 |
| `scripts/diff_text.py` | 텍스트 diff (diff-match-patch) |
| `scripts/diff_tables.py` | 표 셀 단위 diff (vMerge/gridSpan 처리) |
| `scripts/diff_media.py` | 이미지 SHA-256 비교 |
| `scripts/diff_headers.py` | Header/Footer diff |
| `scripts/generate_rows.py` | Claude CLI 병렬 호출 (ThreadPoolExecutor) |
| `scripts/export_docx.py` | 변경대비표 DOCX 생성 |
| `scripts/validate_table.py` | 생성 vs 수동 변경대비표 매칭/점수 산출 |
| `scripts/run_validate.py` | Phase 5: 검증 보고서 생성 |

## 설계 원칙
1. **XML 직접 순회** — python-docx API 아닌 lxml으로 w:body 직계 자식 순회 (혼합 콘텐츠 순서 보존)
2. **로컬 diff + Claude 정리** — 변경 감지는 로컬 Python, Claude는 행 정리만
3. **자동 번호 복원** — numbering.xml 파싱으로 Word 표시 번호와 동일하게 재현 (빈 heading 건너뛰기, numId=0 전문 구분)
4. **참고 양식 준수** — SAMPLE_PROTOCOL 변경대비표 5열 양식(Page|Item|Previous|Current|Note) 매칭

## 참고 파일
- `SAMPLE_PROTOCOL001_...docx` — 변경대비표 참고 양식 (5열 포맷, 페이지 번호 포함)
- `SPONSOR_PROTOCOL001_..._V1.docx` / `V2.docx` — 테스트용 프로토콜 문서

## 중간 산출물 (work/)
```
work/
├── old/          blocks.json, section_index.json, media_inventory.json, headers_footers.json, page_map.json
├── new/          (same)
├── diff/         change_candidates.json
├── rows/         change_rows.json
├── output/       최종 변경대비표 DOCX
└── validation/   validation_report.json (Phase 5)
```

## 주의사항
- `python3` 사용 (`python`은 macOS에서 미설치)
- 원본 DOCX 절대 수정 금지
- Phase 3은 Claude Code 구독 필요 (CLI 호출)
- `scripts/` import 시 프로젝트 루트에서 실행 필요 (`PYTHONPATH` 설정 또는 프로젝트 루트 cd)
