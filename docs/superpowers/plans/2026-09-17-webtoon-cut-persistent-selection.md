# Webtoon Cut Persistent Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 컷 분할 이력의 현재 페이지·필터 전체 선택을 페이지 이동과 필터 변경 뒤에도 유지하고, Grok/Batch 재사용 대상은 명시적 확인 후에만 전달한다.

**Architecture:** 화면은 선택된 output ID를 페이지 데이터와 독립된 집합으로 유지한다. 서버는 페이지 제한 없는 필터 결과 ID 조회와 선택 요약을 제공하고, handoff API는 기존 사용 컷이 있으면 `confirmReuse` 없이는 거부한다.

**Tech Stack:** React/TypeScript, FastAPI, SQLAlchemy, Vitest, pytest

**Spec:** 사용자 요청(2026-09-17 컷 분할 이력 선택 및 중복 처리 확인)

## Global Constraints

- 현재 페이지 선택과 필터 결과 전체 선택은 추가/해제 토글이어야 한다.
- 페이지 이동·필터 변경은 기존 선택 집합을 제거하지 않는다.
- 개별 체크박스로 언제든 선택 추가·해제가 가능해야 한다.
- 필터 전체 선택은 서버 페이지 크기 제한을 받지 않는다.
- Grok/Batch 사용 이력이 하나라도 있으면 선택 수와 중복 수를 표시하고 확인 전에는 handoff하지 않는다.
- 기존 API 권한 범위와 작업 소유권 검사를 유지한다.

---

### Task 1: Persistent selection operations

**Files:**
- Create: `frontend/src/features/webtoon-cut/selection.ts`
- Test: `frontend/src/features/webtoon-cut/selection.test.ts`
- Modify: `frontend/src/screens/webtoonCutScreen.tsx`

**Interfaces:**
- Produces: `toggleSelection(current: ReadonlySet<string>, targetIds: Iterable<string>): Set<string>`

- [ ] 현재 페이지 전체 추가/전체 해제와 기존 타 페이지 선택 보존 테스트를 먼저 작성하고 실패를 확인한다.
- [ ] 순수 선택 토글 함수를 구현하고 테스트를 통과시킨다.
- [ ] 출력 새로고침 시 현재 페이지 밖 ID를 제거하는 로직을 삭제하고 현재 페이지 버튼에 토글 함수를 연결한다.

### Task 2: Unlimited filtered selection and reuse summary

**Files:**
- Modify: `backend/app/services/webtoon_cut_service.py`
- Modify: `backend/app/api/v1/webtoon_cuts.py`
- Modify: `backend/tests/test_webtoon_cut_service.py`
- Modify: `frontend/src/api/client.ts`

**Interfaces:**
- Produces: filtered selection response `{outputIds, count}`
- Produces: handoff summary `{selectedCount, usedInPromptCount, usedInBatchCount, duplicateCount}`
- Handoff consumes: `confirmReuse: boolean`

- [ ] 페이지 제한 없는 필터 ID 조회와 중복 확인 강제 테스트를 먼저 작성하고 실패를 확인한다.
- [ ] 기존 필터·중복 제거·읽기 순서를 재사용하는 서비스/API를 구현한다.
- [ ] 기존 사용 컷 handoff는 `confirmReuse=true`일 때만 카운터를 증가시키도록 구현한다.

### Task 3: Confirmation modal and integration

**Files:**
- Modify: `frontend/src/screens/webtoonCutScreen.tsx`
- Modify: `backend/tests/test_frontend_webtoon_cut_contract.py`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Consumes: Task 1 selection helper and Task 2 API responses.

- [ ] 선택 유지·필터 전체 선택·중복 확인 모달 계약 테스트를 먼저 작성하고 실패를 확인한다.
- [ ] 필터 전체 토글을 서버의 전체 ID 결과에 연결한다.
- [ ] Grok/Batch 버튼 클릭 시 요약을 조회하고 선택 건수 및 Grok/Batch 사용 건수를 표시한다.
- [ ] 사용 이력이 없더라도 선택 건수를 표시하는 확인 모달을 거쳐 handoff하고, 사용 이력이 있으면 중복 처리 경고를 추가한다.
- [ ] 전체 검증 스크립트와 프로덕션 프론트 빌드를 실행한다.
