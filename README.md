# trackchange — DOCX 변경대비표 자동 생성기

임상시험 프로토콜 등 DOCX 문서 2개 버전을 비교하여 **변경대비표(Comparison Table of Change)** DOCX를 자동 생성합니다.

## 결과물 예시

| Page | Item | Previous Version | Current Version | Note |
|------|------|------------------|-----------------|------|
| 14 | 1. Protocol Summary<br><br>1.1.2. Overall Design | 18세 이상 45세 이하 | 만 19세 이상 45세 이하 | 연령 하한 변경 |
| 18-35 | 2. Trial Schema<br><br>2.1. Schedule of Activities | 입원(4박 5일) 1회 | 입원(3박 4일) 1회 | 입원 기간 단축 |

---

## 설치

### 요구 사항

- Python 3.8+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) — Phase 3 행 생성에 필요
- Microsoft Word (macOS) — 페이지 번호 추출에 필요 (선택사항)

### pip install

```bash
git clone https://github.com/minpark0427/Trackchange.git
cd Trackchange
pip install .
```

### Claude Code CLI 설치

```bash
npm install -g @anthropic-ai/claude-code
claude  # 첫 실행 시 로그인
```

---

## 사용법

### 변경대비표 생성 (Phase 1→2→3→4)

```bash
trackchange compare \
  --old "Protocol_V1.docx" \
  --new "Protocol_V2.docx" \
  --out work/
```

출력: `work/output/Comparison_Table_of_Change_*.docx`

### 검증 (Phase 5, 선택사항)

수동 작성된 변경대비표가 있을 때 자동 생성 결과와 비교:

```bash
# 텍스트 유사도 기반
trackchange validate \
  --reference "수동_변경대비표.docx" \
  --generated "work/output/generated.docx" \
  --out-dir work/validation/

# LLM 의미 평가 포함 (권장)
trackchange validate \
  --reference "수동_변경대비표.docx" \
  --generated-json "work/rows/change_rows.json" \
  --out-dir work/validation/ \
  --llm
```

출력: `work/validation/validation_report.json`

### 개별 Phase 실행

```bash
# Phase 1: 섹션 분할 + 매칭
python3 scripts/run_split.py --old V1.docx --new V2.docx --out work/

# Phase 2: Diff 감지
python3 scripts/run_diff.py --work-dir work/ --out work/diff/change_candidates.json

# Phase 3: Claude CLI로 행 생성
python3 scripts/run_rows.py --work-dir work/ --out work/rows/change_rows.json

# Phase 4: DOCX 내보내기
python3 scripts/run_export.py --work-dir work/ --out-dir work/output/

# Phase 5: 검증
python3 scripts/run_validate.py --reference ref.docx --generated-json work/rows/change_rows.json --out-dir work/validation/ --llm
```

---

## 파이프라인 구조

```
Phase 1 (Split)     Phase 2 (Diff)      Phase 3 (Rows)     Phase 4 (Export)    Phase 5 (Validate)
DOCX → blocks    →  text/table/media  →  Claude CLI로     →  5열 변경대비표    →  참조 문서 대비
→ sections          diff 감지            행 생성             DOCX 생성           정확도 평가
→ page numbers                           (병렬 처리)                             (LLM 의미 평가)
```

| Phase | 스크립트 | LLM 필요 | 설명 |
|:-----:|---------|:--------:|------|
| 1 | `run_split.py` | No | DOCX → blocks → sections → matching → page numbers |
| 2 | `run_diff.py` | No | text/table/media/header diff 감지 |
| 3 | `run_rows.py` | **Yes** | Claude CLI로 변경 후보 → 5열 행 생성 |
| 4 | `run_export.py` | No | change_rows.json → 변경대비표 DOCX |
| 5 | `run_validate.py` | Optional | 수동 작성 변경대비표와 비교 검증 |

---

## 중간 산출물

```
work/
├── old/           blocks.json, section_index.json, page_map.json, ...
├── new/           (same)
├── matched_pairs.json
├── diff/          change_candidates.json
├── rows/          change_rows.json
├── output/        Comparison_Table_of_Change_*.docx
└── validation/    validation_report.json, validation_report.md
```

---

## 설계 원칙

1. **XML 직접 순회** — python-docx API 대신 lxml으로 w:body 순회 (혼합 콘텐츠 순서 보존)
2. **로컬 diff + Claude 정리** — 변경 감지는 Python, Claude는 행 정리만 담당
3. **자동 번호 복원** — numbering.xml 파싱으로 Word 표시 번호 재현
4. **테이블 단위 집계** — 셀 단위 diff를 테이블 단위로 집계하여 노이즈 감소
5. **4-pass 매칭** — 섹션 번호 → 페이지 겹침 → 내용 유사도 → 미매칭 순으로 검증

---

## 라이선스

MIT
