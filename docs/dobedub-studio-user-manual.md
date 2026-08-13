# DOBEDUB STUDIO 사용자 매뉴얼

작성일: 2026년 8월 13일

대상 앱: DOBEDUB STUDIO v4 (v3 디자인 토큰 기반 라우트형 UI)

운영 목적: ComfyUI WAN Image-to-Video workflow 실행, 프롬프트 생성/재사용, 작업 이력·자산·운영 관리

주요 연동: RunPod Serverless ComfyUI, RunPod vLLM Qwen, DB 기반 작업/자산/프롬프트 관리, Sandbox Pod

## 수정 이력

| 일자 | 변경 전 | 변경 후 | 비고 |
| --- | --- | --- | --- |
| 2026-08-05 | 구버전 캡처 이미지 사용 | v3 현재 화면 14장 신규 캡처 후 전면 재작성 | 당시 문서 기준 |
| ~2026-08-11 | (여러 차례 부분 수정) | Sandbox Pod, Node Config Seed, 해상도/영상길이 등 개별 반영 | 이전 개정 이력 |
| 2026-08-12 | 모달 기반 UI(Admin Console/Prompt Builder/Metadata View 등) 설명, 구버전(v3 이전) 화면 캡처 다수 잔존 | **전면 재작성.** GNB·모달이 모두 사라지고 좌측 사이드바 + 라우트 기반 화면으로 전환된 현재 구조(v4)를 기준으로 목차·화면 설명·캡처 이미지를 새로 작성 | 아래 내용부터 현재 앱과 1:1로 대응 |
| 2026-08-12 | 영상 생성 화면이 한 작업이 끝날 때까지 잠겨 연속 제출을 할 수 없음 | **다중 Task 운영으로 변경.** 제출 직후 Task History로 이동하고, 활성 작업은 서버 모니터가 계속 갱신한다. Admin의 독립 Task Policy 메뉴에서 사용자별/전체 동시 작업 한도를 관리 | 4.3, 4.4, 5, 10 |
| 2026-08-12 | 생성 진행/결과 전용 화면과 Task History의 기능이 겹침 | **Task History를 단일 작업 관리 화면으로 확정.** 이전 진행/결과 주소는 작업 이력으로 이동하며, 제출·진행·완료·실패·다운로드·재작업·평가를 한 화면에서 처리 | 사용자 업무 매뉴얼 4~7 |
| 2026-08-12 | 새로고침 시 로그인 세션 삭제 | 같은 탭의 새로고침은 세션을 유지하고, 명시 로그아웃 또는 탭/브라우저 종료 시에만 세션이 정리되도록 수정 | 2, 21 |
| 2026-08-12 | v4 화면 전환과 업무 간 연결 설명이 간략함 | **v3 수준의 업무 매뉴얼로 확장.** 사용자 업무와 관리자 운영 업무를 분리하고, 이미지 업로드부터 다중 Task 제출·검수·프롬프트 재사용까지의 전체 흐름과 화면별 판단 기준을 추가 | 전체 업무 흐름, 4~20 |
| 2026-08-12 | 목차가 평면 목록으로 보이고, 세그먼트 설정 화면의 실제 예시가 부족함 | **계층형 목차 렌더링과 화면 캡처 보강.** 사용자/관리자 업무군과 하위 기능을 트리 형태로 표시하고, 빈 설정·완성 설정 상태의 실제 세그먼트 화면을 추가 | 목차, 4.2 |
| 2026-08-13 | 브라우저 기본 확인창이 떠서 화면 흐름과 위치가 일관되지 않음 | **v4 확인 모달로 통일.** 카테고리·서브 카테고리·Key word 비활성화는 화면 중앙의 확인 모달에서 취소 또는 비활성화를 선택 | 17. Prompt Catalog 관리 |
| 2026-08-13 | 실행 전 화면에서 Positive Prompt와 일부 노드 값만 확인 가능 | **최종 Negative Prompt와 출력 설정을 추가.** 세그먼트별 Positive/Negative Prompt, 해상도, 프레임/FPS, 인코딩, 예상 길이와 서버 자동 Seed 방식을 제출 전에 확인 | 4.3 |
| 2026-08-13 | Prompt Library에서 선택한 프롬프트가 현재 세그먼트에 반영되지 않거나, 이미지 업로드 방식이 파일 선택에 한정됨 | **프롬프트 재사용 적용 대상을 명시적으로 보존하고 직접 반영.** Keyframe Slot은 클릭 파일 선택과 이미지 파일 끌어놓기를 모두 지원 | 4.1, 4.2, 6 |
| 2026-08-13 | 단일 이미지 workflow 실행 전 확인에 존재하지 않는 끝 Keyframe이 표시되고, 재사용 후 Prompt 결과 패널이 비어 보임 | **단일 이미지 I2V는 시작 Keyframe만 표시.** 프롬프트 재사용 후에도 세그먼트에 적용된 Positive/Negative Prompt를 생성 결과 패널에서 즉시 확인 | 4.2, 4.3, 6 |
| 2026-08-13 | Assets 화면의 새 컬렉션 입력이 상단 헤더에 섞여 눈에 잘 띄지 않음 | **자산 목록 직전의 독립 `컬렉션 관리` 영역으로 이동.** 현재 컬렉션 수, 새 컬렉션 이름 입력, 생성 버튼을 한 영역에서 제공 | 7 |

## 목차

1. [서비스 개요](#1-서비스-개요)
2. [로그인](#2-로그인)
3. [화면 공통 구조](#3-화면-공통-구조)
4. [전체 업무 흐름](#전체-업무-흐름)
5. [사용자 업무 매뉴얼](#사용자-업무-매뉴얼)
   - [영상 생성 흐름](#4-영상-생성-흐름-generate)
     - [STEP 1 · 이미지 로드](#41-step-1--이미지-로드)
     - [STEP 2 · 세그먼트 설정](#42-step-2--세그먼트-설정-프롬프트--노드-컨피그)
     - [Scene Detail 작성법](#자연스러운-scene-detail-작성법)
     - [Prompt 적용 순서](#prompt-적용-순서)
     - [STEP 3 · 실행 전 확인 및 다중 Task 제출](#43-step-3--실행-전-확인-및-다중-task-제출)
     - [STEP 4 · Task History에서 진행·결과 관리](#44-task-history에서-진행결과-관리)
   - [Task History · 작업 이력](#5-task-history--작업-이력)
     - [상태별 사용자 조치](#상태별-사용자-조치)
   - [Prompt Library · 프롬프트 재사용](#6-prompt-library--프롬프트-재사용)
   - [Assets · 자산 관리](#7-assets--자산-관리)
   - [사용자 매뉴얼 화면](#8-사용자-매뉴얼-화면)
6. [관리자 운영 매뉴얼](#관리자-운영-매뉴얼)
   - [운영 업무 흐름](#관리자-업무-흐름-예시)
   - [관리자 콘솔 전환](#9-관리자-콘솔-전환)
   - [역할 & 권한 / 기능 리소스 매핑](#10-역할--권한--기능-리소스-매핑)
   - [사용자 관리](#11-사용자-관리)
   - [프롬프트 카탈로그 관리](#12-프롬프트-카탈로그-관리)
   - [워크플로 정의 관리](#13-워크플로-정의-관리)
   - [Sandbox Pod](#14-sandbox-pod)
   - [Task Policy](#15-task-policy)
   - [System Status](#16-system-status)
   - [Metadata](#17-metadata)
   - [감사 로그](#18-감사-로그)
7. [권한 코드 요약표](#19-권한-코드-요약표)
8. [운영 시 주의사항](#20-운영-시-주의사항)
9. [문제 해결](#21-문제-해결)

## 1. 서비스 개요

DOBEDUB STUDIO는 이미지를 영상으로 변환하는 ComfyUI WAN Image-to-Video workflow를 웹 UI에서 실행하는 사내 도구입니다. 사용자는 ComfyUI 화면을 직접 열지 않고 다음을 수행합니다.

- workflow 선택과 키프레임 이미지 업로드
- 세그먼트(구간)별 Positive/Negative 프롬프트 작성 — 직접 입력, 키워드 카탈로그 조합, Qwen 프롬프트 자동 생성, 과거 프롬프트 재사용 중 선택
- Wan Node Config(FPS, Frames, Steps, CFG Scale, Motion Shift 등) 조정
- RunPod Serverless ComfyUI로 작업 제출과 진행 상태 확인
- 작업 이력, 결과 영상, 입력/출력 자산 조회 및 프롬프트 재사용 등록
- (관리자) 사용자, 역할·권한, 워크플로, 프롬프트 카탈로그, Sandbox Pod, 감사 로그 관리

v4는 기존 모달 중심 UI(Admin Console 모달, Prompt Builder 모달, Metadata View 모달 등)를 걷어내고, **좌측 사이드바 + 상단 헤더 + 우측 정보 패널**로 구성된 라우트 기반 화면으로 전면 재구성되었습니다. 화면마다 고유 URL이 있고(`/studio/create/load`, `/studio/admin/roles` 등), 브라우저 새로고침이나 뒤로가기도 정상 동작합니다.

## 2. 로그인

앱 접속 시 로그인 화면이 먼저 표시됩니다. 로그인은 `ID`와 `Password`만 사용하며, 사내 전용으로 외부 SSO는 없습니다.

![로그인 화면](v4-00-login.jpg)

로그인 절차:

1. `ID` 입력란에 사번 또는 계정 ID를 입력합니다.
2. `Password` 입력란에 비밀번호를 입력합니다.
3. `접속하기` 버튼을 클릭합니다.

로그인 화면 우측 하단의 "시스템 상태" 카드에서 ComfyUI Serverless·Qwen LLM의 공개 헬스체크 상태를 로그인 전에도 미리 확인할 수 있습니다.

세션은 브라우저 탭에 종속됩니다. **같은 탭에서 새로고침해도 로그인 상태는 유지**되며, 명시적으로 `로그아웃`하거나 탭/브라우저를 종료하면 세션이 정리됩니다. 만료 5분 전부터 화면 상단에 남은 시간 배너가 표시되며, 배너의 "세션 연장" 버튼으로 재로그인 없이 세션을 갱신할 수 있습니다.

권한이 없는 화면 URL로 직접 진입하면 403(접근 거부) 화면으로 이동합니다. 이 화면은 필요한 권한, 내 현재 역할, 요청한 경로를 함께 보여줍니다.

## 3. 화면 공통 구조

로그인 후 모든 화면은 아래 3단 레이아웃을 공유합니다(공통 컴포넌트 `AppShell`).

- **좌측 사이드바** — 상단에 로고, 그 아래 GENERATE/ADMIN 전환 버튼, `GENERATE`(또는 `ADMIN`) 대분류 라벨과 1차 메뉴 목록, 화면별 하위 정보(2차 메뉴·필터·트리 등)가 이어집니다. 하위 정보 영역은 항상 상단 메뉴와 구분선으로 분리되어 있고, `LABEL · 건수` 형식의 라벨(예: `SEGMENTS · 3`, `FILTER · 20`)로 시작합니다.
- **상단 헤더** — 현재 위치(eyebrow 텍스트)와 화면 제목, 우측에 화면별 주요 액션 버튼이 있습니다.
- **본문** — 화면의 핵심 콘텐츠(표, 카드, 폼 등).
- **우측 정보 패널** — 있는 화면에서는 요약 정보, 검증 상태, 보조 액션을 보여줍니다(모든 화면에 있는 것은 아닙니다).

권한이 없는 메뉴 항목은 사이드바에서 아예 보이지 않습니다. 로그인한 사용자 이름·역할은 사이드바 하단(GENERATE 영역) 또는 화면 우측 상단(ADMIN 영역)에 표시되며, 로그아웃 버튼도 같은 위치에 있습니다.

![Workspace(이미지 로드) 화면 — 공통 레이아웃 예시](v4-01-workspace.jpg)

### GENERATE ↔ ADMIN 전환

권한이 있는 사용자는 사이드바 최상단(로고 바로 아래, GENERATE/ADMIN 라벨 위)의 전환 버튼으로 두 영역을 오갈 수 있습니다.

- GENERATE 영역에서: `관리자 콘솔 →` 버튼 → ADMIN 영역으로 이동
- ADMIN 영역에서: `← 스튜디오` 버튼 → GENERATE 영역(Workspace)으로 이동

## 전체 업무 흐름

v4는 "한 화면에서 생성이 끝날 때까지 대기"하는 방식이 아닙니다. **작업을 제출하고, Task History에서 여러 작업을 함께 관리**하는 흐름입니다. 아래 순서를 기본 업무 절차로 사용하세요.

| 단계 | 사용하는 화면 | 사용자가 하는 일 | 시스템이 관리하는 일 |
| --- | --- | --- | --- |
| 1. 접속 | 로그인 | ID와 비밀번호로 로그인하고 ComfyUI/Qwen 상태를 확인 | 권한과 세션을 확인하고 메뉴를 구성 |
| 2. 작업 설계 | Workspace · 이미지 로드 | workflow를 선택하고 요구된 Keyframe 슬롯을 모두 채움 | workflow의 입력 수·세그먼트·기본 Prompt/Node Config를 불러옴 |
| 3. 장면 설정 | Workspace · 세그먼트 설정 | 세그먼트별 Prompt와 Wan Node Config를 검토·수정 | Prompt 검증, Negative 기본값 유지, 유효 범위 검증 |
| 4. 제출 | Workspace · 실행 전 확인 | payload와 검증 결과를 확인한 뒤 `Run` 클릭 | Task/입력 Asset/Prompt/Node Config를 DB에 기록하고 RunPod에 제출 |
| 5. 병렬 작업 | Task History | 진행 Task를 확인하면서 Workspace에서 다음 작업을 준비·제출 | 서버 모니터가 로그인 여부와 무관하게 RunPod 상태를 갱신 |
| 6. 결과 검수 | Task History | Final 영상, 입력/출력 Asset, Node Config를 확인 | 완료·실패·취소 상태와 결과 Asset을 작업에 연결 |
| 7. 지식화 | Prompt Review / Prompt Library | 품질 등급·코멘트·재사용 사유를 저장하고 좋은 Prompt를 재사용 후보로 등록 | 재사용 가능 Prompt를 검색 가능한 라이브러리로 관리 |

**가장 중요한 원칙은 Task 단위 관리입니다.** 이미 제출한 작업은 현재 Workspace에서 다른 workflow를 선택하거나 브라우저를 닫아도 사라지지 않습니다. 생성 결과, 입력 이미지, 프롬프트, 노드 설정, 리뷰 정보는 모두 Task ID에 연결되어 Task History에서 다시 확인합니다.

### 사용자 업무 흐름 예시

1. `Workspace`에서 `3-images` workflow를 선택하고 이미지 3장을 업로드합니다.
2. Segment 1과 Segment 2에서 키워드/Scene Detail 또는 직접 입력으로 Positive Prompt를 작성하고, 필요한 Negative 키워드를 더합니다.
3. `프롬프트 생성 · Qwen`을 사용했다면 Draft를 검토한 뒤 `Apply Generated Prompt`로 세그먼트에 적용합니다.
4. Frames, FPS, Steps, CFG, Motion Shift, 해상도와 출력 포맷을 확인합니다.
5. 실행 전 확인 화면의 경고를 해소하고 `Run`을 누릅니다.
6. 자동으로 이동한 `Task History`에서 상태가 `COMPLETED`가 될 때까지 확인합니다. 이 사이에 Workspace로 돌아가 두 번째 작업을 별도로 제출할 수 있습니다.
7. 완료된 작업의 Final 영상을 검수하고, 우수한 Prompt는 Prompt Review에서 재사용 가능으로 등록합니다.

### 관리자 업무 흐름 예시

1. `Admin`으로 전환해 사용자·역할·권한이 업무에 맞게 설정되었는지 확인합니다.
2. `워크플로 정의`에서 활성 workflow와 자동 생성된 Param Config/Metadata를 검토합니다.
3. `프롬프트 카탈로그`에서 Positive/Negative 키워드 트리를 정비합니다.
4. `Task Policy`에서 사용자당/전체 활성 Task 한도를 운영 여건에 맞게 조정합니다.
5. 장애가 의심되면 `System Status`, `Metadata`, `Sandbox Pod`, `감사 로그`를 순서대로 확인합니다.

## 사용자 업무 매뉴얼

이 장은 영상을 생성하는 사용자의 실제 업무 순서입니다. 작업을 제출한 뒤에는 생성 화면을 붙잡고 기다리지 않습니다. 제출된 모든 Task는 **Task History**에서 같은 방식으로 관리합니다.

## 4. 영상 생성 흐름 (GENERATE)

좌측 사이드바 `Workspace` 메뉴에서 시작하는 4단계 마법사입니다. 진행 중에는 사이드바에 `PROGRESS · N/4` 라벨과 함께 1~4단계 체크리스트가 표시됩니다.

### 4.1 STEP 1 — 이미지 로드

1. 상단 `Workflow` 카드 목록에서 workflow를 선택합니다(예: `1-images`, `3-images`, `Blowbang1` 등 — 카드에 필요 키프레임 수·세그먼트 수가 함께 표시됩니다).
2. 선택한 workflow가 요구하는 `Keyframe Slots` 개수만큼 슬롯이 생성됩니다. 슬롯을 클릭해 이미지를 선택하거나, 이미지 파일을 해당 슬롯 위로 끌어놓아 업로드합니다.
3. 모든 슬롯이 채워지면 우측 상단 `세그먼트 설정으로 →` 버튼이 활성화됩니다.

세그먼트는 이미지 사이의 전환 구간이며, workflow가 자동으로 계산합니다(사용자가 개수를 바꿀 수 없습니다).

입력 이미지 체크:

| 확인 항목 | 기준 | 미충족 시 |
| --- | --- | --- |
| workflow 선택 | 사용하려는 workflow가 활성 상태 | 목록에 없다면 관리자에게 활성화를 요청 |
| Keyframe 수 | 모든 고정 슬롯이 채워짐 | 다음 단계로 진행할 수 없음 |
| 파일 연결 | 각 슬롯에 썸네일과 Asset ID가 표시됨 | 업로드를 다시 시도하거나 슬롯을 제거 후 재선택 |
| I2V 조건 | 최소 1개의 이미지가 있어야 함 | `입력파일을 업로드하세요. 이 워크플로우는 i2v 전용 입니다. t2i,t2v는지원하지 않습니다.` 안내 후 제출 차단 |

이미지를 다시 고르면 해당 슬롯만 교체됩니다. 한 번에 여러 이미지를 선택하거나 끌어놓으면, 선택한 슬롯부터 남은 슬롯 순서대로 채워집니다. 이미지 형식이 아닌 파일은 업로드되지 않습니다. workflow를 바꾸면 **현재 Workspace의 임시 이미지·Prompt·Node Config만** 새 workflow 기본값으로 초기화됩니다. 이미 제출한 Task는 취소되지 않으며 Task History에 남습니다.

### 4.2 STEP 2 — 세그먼트 설정 (프롬프트 & 노드 컨피그)

![세그먼트 설정 화면 — 초기 상태](v4-02-segment-config-empty.png)

위 초기 화면은 키워드·Scene Detail·Prompt가 아직 없는 상태입니다. 좌측에는 현재 세그먼트와 키프레임 쌍이, 중앙에는 Keyword Builder/Scene Detail, 우측에는 생성 Draft와 세그먼트별 Wan Node Config가 보입니다.

![세그먼트 설정 화면 — Prompt와 Node Config를 완료한 상태](v4-02-segment-config-complete.png)

완성 상태에서는 선택한 키워드와 Scene Detail로 만든 Draft를 우측 패널에서 검토하고 현재 세그먼트에 적용합니다. 같은 화면에서 Width/Height/Frames/FPS 등 workflow가 노출한 값도 함께 확인합니다.

세그먼트가 여럿이어도 화면 전환 없이 좌측 사이드바에서 세그먼트를 선택하며 같은 화면 안에서 프롬프트와 노드 컨피그를 함께 편집합니다. 본문은 좌우 2컬럼입니다.

**왼쪽 — 프롬프트 작성.** 상단 `Keyword Builder` / `System Prompt 편집` 두 탭이 있습니다.

- **Keyword Builder**: 카탈로그 트리(그룹 → 서브카테고리, 기본 접힘)에서 키워드 칩을 선택하거나, `Scene Detail`에 장면을 직접 씁니다. 자연스러운 결과를 위해 **대상/관계 → 주요 동작 → 보조 동작·상호작용 → 카메라 앵글·구도 → 조명·분위기** 순서로 입력합니다.
- **Scene Detail만 사용**: 키워드를 선택하지 않아도 Scene Detail에 동작·카메라·표현을 입력하면 `프롬프트 생성 · Qwen`과 `Apply Keyword / Scene Draft`를 사용할 수 있습니다. 둘 다 비어 있을 때만 버튼이 비활성화됩니다.
- **Qwen 생성 결과**: `프롬프트 생성 · Qwen`은 선택 키워드, Scene Detail, 세그먼트와 입력 이미지의 보존 제약을 바탕으로 영문 Positive Prompt를 만듭니다. 생성 후 반드시 Draft 영역에서 문장을 확인하고 `Apply Generated Prompt`를 눌러야 현재 세그먼트에 반영됩니다.
- **Negative Prompt**: 워크플로에 내장된 기본 Negative Prompt는 유지됩니다. 사용자가 선택한 Negative 키워드는 기본값을 지우지 않고 추가됩니다.
- **System Prompt 편집**: Qwen 프롬프트 생성에 사용되는 System Prompt 원문을 직접 확인·수정할 수 있습니다. 이 값은 관리자 화면의 시스템 프롬프트 설정과 같은 레코드를 공유합니다 — 어느 화면에서 고쳐도 전역에 반영됩니다.

#### 자연스러운 Scene Detail 작성법

Scene Detail은 자유 입력이지만, Qwen이 장면의 우선순위를 안정적으로 해석하도록 아래 순서를 권장합니다.

1. **대상/관계**: 누가 등장하는지, 인물 사이 관계나 대상 위치
2. **주요 동작**: 가장 먼저 보여야 하는 움직임 또는 자세
3. **보조 동작/표정**: 시선, 손동작, 감정, 상호작용
4. **카메라**: 측면/정면, 아이레벨/로우 앵글, 구도, 움직임
5. **표현**: 조명, 분위기, 배경 안정성, 원하는 스타일

예시: `woman and man, the woman turns toward the man and raises her head, both keep a calm expression, side view, eye-level angle, soft indoor lighting`.

문장 완성도보다 **대상과 동작의 주종 관계를 먼저 쓰는 것**이 중요합니다. 키워드를 쓰지 않고 Scene Detail만 입력해도 Qwen 생성과 초안 적용은 가능합니다. 다만 Positive 키워드와 Scene Detail이 모두 비어 있으면 현재 세그먼트에 적용할 내용이 없으므로 두 버튼은 비활성화됩니다.

#### Prompt 적용 순서

1. `Keyword Builder`에서 Positive/Negative 키워드를 선택합니다. 선택 값은 각각의 박스에 콤마로 이어서 표시됩니다.
2. 필요하면 Scene Detail을 입력합니다.
3. 빠른 초안이 필요하면 `Apply Keyword / Scene Draft`를, 자연스러운 영문 문장이 필요하면 `프롬프트 생성 · Qwen`을 사용합니다.
4. Qwen 응답은 즉시 적용되지 않습니다. Draft의 Positive/Negative 내용을 읽고 `Apply Generated Prompt`를 눌러야 현재 세그먼트 값이 바뀝니다.
5. 적용된 Prompt는 세그먼트 전환 전에도 유지되며, 실행 전 확인 단계에서 전체 세그먼트별로 다시 볼 수 있습니다.

키워드/Scene Detail을 입력한 뒤 우측 패널에서 `Apply Keyword / Scene Draft`(또는 Qwen 생성 결과가 있으면 `Apply Generated Prompt`)를 눌러 해당 세그먼트에 프롬프트를 적용합니다. 경고(Warning)가 있으면 심각도별로 상단에 모아 보여주며, `BLOCK` 등급 경고가 있으면 적용 버튼이 비활성화됩니다.

**오른쪽 — Wan Node Config.** FPS·Frames·Steps·CFG Scale·Motion Shift 등을 슬라이더/드롭다운으로 조정합니다(Seed는 이 화면에서 설정하지 않습니다 — 아래 참조). Format/Codec 선택은 워크플로 실데이터와 연동됩니다.

| 항목 | 의미 | 사용 시 유의점 |
| --- | --- | --- |
| Sampling Steps | 생성 반복 횟수 | 높을수록 세부 표현은 늘 수 있으나 생성 시간이 길어질 수 있음 |
| CFG Scale | Prompt 반영 강도 | 지나치게 높이면 부자연스러운 결과가 생길 수 있음 |
| Motion Shift | 움직임 변화 강도 | workflow와 이미지 특성에 맞춰 조정 |
| Frames / Video Length | 생성할 프레임 또는 길이 | workflow에 따라 VAE/연결 노드 값으로 전달됨 |
| FPS | 최종 재생 프레임 속도 | Frames/Length와 함께 영상 길이를 결정 |
| Width / Height | workflow별 출력 해상도 | 입력 이미지 비율과 GPU 자원을 함께 고려 |
| Final Format / Codec | 최종 저장 포맷과 코덱 | 선택 가능한 값만 workflow SaveVideo 노드로 전달 |

우측 패널 또는 헤더의 `프롬프트 재사용` 버튼으로 [Prompt Library](#6-prompt-library--프롬프트-재사용)를 열어 과거 프롬프트를 현재 세그먼트에 적용할 수도 있습니다.

프롬프트를 재사용해 적용한 직후에는 우측 `생성 결과` 패널의 POSITIVE/NEGATIVE 영역에 적용된 최종 문장이 `적용됨` 상태로 표시됩니다. 새 키워드 또는 Scene Detail을 입력해 Draft를 만들기 전에도 적용 결과를 바로 확인할 수 있습니다.

모든 세그먼트에 프롬프트가 적용되면 헤더의 `실행 전 확인으로 →` 버튼이 활성화됩니다.

> **Seed 안내**: Seed 값은 이 화면에서 직접 입력하지 않습니다. 영상 생성 제출 시 서버가 세그먼트별로 자동 적용하고, Task History의 Overview에서 실제 적용된 값만 확인할 수 있습니다.

### 4.3 STEP 3 — 실행 전 확인 및 다중 Task 제출

STEP 1 화면의 오른쪽 `Run Summary`와 좌측 진행 체크리스트에서 `실행 전 확인`으로 이동해 여는 제출 전용 화면입니다. 실제 실행 요청이 발생하는 유일한 단계이므로, 앞 단계에서 적용한 Prompt·Node Config·입력 이미지를 수정 없이 집계하여 보여줍니다.

제출 전 전체 구성을 한 번에 검토하는 화면입니다.

- 상단에 워크플로/키프레임/세그먼트 요약 타일과, 세그먼트별 시작→끝 키프레임 쌍을 축소 썸네일로 나열한 카드(각 쌍에 프롬프트 적용 여부 배지)가 있습니다.
- 세그먼트별 표에서 **최종 Positive Prompt와 최종 Negative Prompt**를 함께 비교합니다. Negative 값은 워크플로 기본값과 사용자가 추가한 Negative 키워드를 합친 실행 값입니다.
- `출력 설정` 카드에서 세그먼트별 해상도, 프레임/FPS, 포맷·코덱을 확인합니다. 값이 보이지 않는 항목은 해당 워크플로의 기본값으로 실행됩니다.
- 오른쪽 `제출 요약`에는 총 프레임, 계산 가능한 경우 예상 길이, 그리고 서버가 자동으로 생성하는 Seed 방식을 표시합니다.
- `제출 검증` 카드는 키프레임 슬롯 충족, 세그먼트 프롬프트 전체 적용, 노드 구성값 범위, 세그먼트별 최종 Negative Prompt 포함 여부 4가지를 체크합니다.
- 제출 안내 영역은 Task 1건으로 보존되는 입력 이미지, 최종 Prompt, 노드 설정, 결과 영상을 명확히 안내합니다.
- 실제 RunPod 제출 payload(JSON)를 `PAYLOAD` 카드에서 그대로 확인할 수 있습니다.

모든 검증을 통과하면 헤더 또는 우측 패널의 `Run` 버튼으로 영상을 **제출**합니다. 키프레임, Positive Prompt 또는 최종 Negative Prompt가 하나라도 누락되면 `Run`은 활성화되지 않습니다. 제출 성공 시 곧바로 [Task History](#5-task-history--작업-이력)로 이동합니다. 브라우저가 완료까지 기다리지 않으며 워크스페이스는 다음 작업을 위한 빈 상태로 돌아갑니다.

다중 Task 운영 규칙:

1. 하나의 작업을 제출하면 Task History의 최상단 행에 `QUEUED` 또는 `IN_QUEUE` 상태로 추가됩니다.
2. `Workspace`로 돌아가 다음 이미지·프롬프트·노드 설정을 준비해 별도 작업으로 제출할 수 있습니다.
3. 기본 정책은 **사용자당 활성 Task 3개, 전체 활성 Task 10개**입니다. `QUEUED`, `IN_QUEUE`, `IN_PROGRESS`, `RUNNING`만 활성으로 계산합니다.
4. 한도에 도달하면 새 작업은 생성되지 않으며 안내 메시지가 표시됩니다. 진행 중 작업을 취소하거나 종료될 때까지 기다린 뒤 다시 제출합니다.
5. 제출 뒤 로그아웃하거나 탭을 닫아도 작업은 취소되지 않습니다. 서버 모니터가 DB의 작업 상태를 RunPod에서 계속 갱신합니다.

제출 직후에는 Workspace가 새 작업을 위한 초기 상태로 돌아갑니다. 이는 이전 작업이 지워졌다는 뜻이 아닙니다. 생성 화면 우측의 일회성 결과 영역을 유지하지 않고 Task History로 관리 기준을 통일했기 때문에, 제출한 작업은 반드시 Task History 최상단 행에서 확인합니다.

### 4.4 Task History에서 진행·결과 관리

진행과 결과는 별도 화면이 아니라 **Task History의 같은 목록**에서 관리합니다. 상태 값은 `QUEUED`, `IN_QUEUE`, `IN_PROGRESS`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`, `TIMED_OUT`이며, 활성 상태인 작업은 목록 상단에서 3초 간격으로 갱신됩니다.

브라우저 탭을 닫거나 로그아웃해도 제출된 작업은 DB에 남습니다. 다시 로그인하면 같은 Task History에서 이어서 확인할 수 있습니다. 예전 `/studio/create/progress`, `/studio/create/result` 주소로 들어가도 Task History로 자동 이동합니다.

## 5. Task History · 작업 이력

좌측 사이드바 `Task History` 메뉴입니다.

![Task History 화면](v4-03-task-history.jpg)

- 왼쪽 목록: No / Timestamp / Worker / Positive Prompt / Negative Prompt / Status / 삭제 컬럼. `필터` 사이드바에서 전체/진행/완료/실패로 좁힐 수 있습니다. 진행 필터에는 아직 종료되지 않은 Task만 표시됩니다.
- 행을 선택하면 오른쪽 패널에 Run 상세가 열립니다: 항상 펼쳐진 **Overview**(workflow, Task ID, runpod_job_id, 실행자·시각, 세그먼트·seed)와, 접었다 펼 수 있는 **Assets**(입력/출력 미디어), **Node Config**, **Prompt Review**(품질 평가·코멘트·재사용 등록) 아코디언.
- 활성 Task는 Overview에 진행률과 `작업 취소` 버튼이 표시됩니다. 완료 Task는 `Final 다운로드`, `재작업`(같은 설정으로 새 작업 시작)을 이 패널에서 바로 사용할 수 있습니다. 실패/취소 Task는 `전체 재실행`을 제공합니다.
- **성공 결과 확인 순서**: 완료 행 선택 → 오른쪽 `Assets` 아코디언 열기 → Final 영상 재생 → `Final 다운로드` 또는 `재작업`을 선택합니다. 세그먼트 출력은 전환 품질 검수용이고, 배포/공유할 결과는 Final 출력입니다.
- **실패 처리 순서**: 실패 행 선택 → Overview와 Assets의 실패 안내 확인 → Node Config와 Prompt Review에서 입력값 확인 → `전체 재실행` 또는 `재작업`으로 생성 화면에 복원합니다.
- **재작업**은 원래 작업의 워크플로, 입력 Asset, 세그먼트 프롬프트, Wan Node Config를 생성 화면으로 불러옵니다. 일부만 수정한 뒤 새 Task로 제출할 수 있습니다.
- 목록의 `삭제`는 소프트 삭제입니다. 삭제된 작업은 목록·재사용 후보에서 즉시 제외되지만 결과 파일은 Assets에 남아 있을 수 있습니다. 삭제는 되돌릴 수 없다는 확인창이 함께 표시됩니다.

### 상태별 사용자 조치

| 상태 | 의미 | 사용자가 할 일 |
| --- | --- | --- |
| `QUEUED` / `IN_QUEUE` | 서버리스 큐 또는 worker 할당 대기 | 잠시 기다리거나, 더 이상 필요 없으면 작업 취소 |
| `IN_PROGRESS` / `RUNNING` | RunPod에서 실행 중 | Overview 진행 정보 확인, 필요 시 작업 취소 |
| `COMPLETED` | 최종 결과가 저장됨 | Assets에서 Final 영상 재생·다운로드·재작업·Prompt Review |
| `FAILED` | 실행 또는 결과 저장 실패 | 오류 정보와 Node Config를 검토한 뒤 전체 재실행/재작업 |
| `CANCELLED` / `TIMED_OUT` | 사용자가 취소했거나 시간 제한으로 종료 | 실패 작업처럼 원인을 점검하고 필요 시 새 Task로 다시 제출 |

`IN_PROGRESS`는 최종 결과가 아닙니다. RunPod에서 끝났더라도 결과 Asset 저장 또는 상태 확인이 완료되기 전까지 표시될 수 있습니다. 모니터는 최종적으로 `COMPLETED`, `FAILED`, `CANCELLED`, `TIMED_OUT` 중 하나로 정리합니다.

## 6. Prompt Library · 프롬프트 재사용

좌측 사이드바 `Prompt Library` 메뉴입니다. 과거 세그먼트 프롬프트를 검색해 현재 편집 중인 세그먼트에 그대로 적용할 때 사용합니다.

![Prompt Library 화면](v4-04-prompt-reuse.jpg)

- 목록 컬럼: 워크플로, 시작→다음 이미지 썸네일, 프롬프트(Positive/Negative, 스크롤 가능), 재사용 사유, 코멘트, 레이팅, 생성자, 모델명, `프롬프트 재사용` 버튼.
- 상단 검색창에 프롬프트·코멘트·사유·task ID로 검색할 수 있습니다.
- 서버사이드 페이지네이션으로 동작하며, 화면 진입 시 목록이 자동으로 로드됩니다.
- 재사용 후보는 Task History의 Prompt Review 아코디언에서 품질 등급과 코멘트를 저장하고 "재사용 가능"으로 등록한 프롬프트입니다. 재사용 가능으로 저장할 때는 의도 반영·정체성 유지·움직임 자연스러움·왜곡 없음·배경 안정성 중 하나 이상을 선택해야 합니다.
- 세그먼트 설정 화면에서 열면, 화면 상단에 적용 대상 workflow·세그먼트가 표시됩니다. `프롬프트 재사용`을 누르면 그 **적용 대상 세그먼트**의 Positive/Negative Prompt가 선택한 항목으로 즉시 바뀌고 세그먼트 설정 화면으로 돌아갑니다. 라이브러리 메뉴에서 직접 열었을 때는 현재 선택된 세그먼트가 적용 대상입니다.
- 재사용은 Prompt 값만 바꿉니다. 현재 Workspace의 입력 이미지, Keyframe Slot 연결, Wan Node Config 및 workflow 선택은 유지됩니다. 적용 뒤 실행 전 확인 화면에서 최종 Prompt와 현재 이미지 조합을 다시 검토합니다.
- 단일 이미지 I2V workflow는 시작 Keyframe 하나만 사용하므로 실행 전 확인에서 화살표나 빈 끝 프레임이 표시되지 않습니다. 두 장 이상을 요구하는 workflow만 시작→끝 Keyframe 쌍을 표시합니다.

재사용은 workflow를 그대로 복사하는 기능이 아닙니다. Prompt Library는 **검수된 Prompt 문장과 리뷰 정보**를 현재 세그먼트에 적용합니다. 입력 Asset, 선택한 workflow, Node Config, Keyframe 수는 현재 Workspace 설정을 따릅니다. 따라서 재사용한 뒤에도 실행 전 확인에서 현재 workflow와 이미지 조합에 맞는지 반드시 검토합니다.

## 7. Assets · 자산 관리

좌측 사이드바 `Assets` 메뉴입니다. 과거 컬렉션(5c) 화면은 여기로 통합되어, Asset 목록 안에서 컬렉션 필터/칩으로 관리합니다.

![Assets 화면](v4-05-assets.jpg)

- 컬럼: Collection(드롭다운으로 담기/빼기), Asset ID, 미리보기, Asset 이름, 생성일, 생성자, 입력 이미지, 다운로드.
- 목록 위 `컬렉션 관리` 영역에서 새 컬렉션 이름을 입력하고 `컬렉션 만들기`를 선택합니다. 생성된 컬렉션은 즉시 좌측 필터와 각 Asset 행의 `+ 컬렉션에 담기` 목록에 표시됩니다.
- 미리보기 컬럼(Asset ID 바로 뒤에 배치)의 축소 썸네일을 클릭하면 원본 크기 미리보기 모달이 뜹니다. 이미지는 그대로, 영상은 브라우저가 자동 재생하는 첫 프레임을 썸네일로 사용합니다. 모달에서 다운로드도 가능합니다.
- 좌측 사이드바에서 `전체` 또는 특정 컬렉션으로 필터링할 수 있고, 상단 입력창으로 새 컬렉션을 만들 수 있습니다.

입력 이미지는 업로드와 동시에 Asset으로 관리되고, 영상 생성 결과는 해당 Task의 출력 Asset으로 관리됩니다. Task History에서 `재작업`을 선택하면 원래 Task에 연결된 입력 Asset을 다시 불러오므로, 같은 이미지 기반으로 Prompt나 Node Config만 바꿔 새 작업을 만들 수 있습니다.

## 8. 사용자 매뉴얼 화면

좌측 사이드바 `User Manual` 메뉴(HELP 그룹)에서 바로 이 문서를 볼 수 있습니다. 문서 맨 위 **목차 링크**를 클릭하면 같은 문서 안의 해당 절로 부드럽게 이동합니다. 상단 검색창은 입력한 단어를 본문에서 하이라이트하고 `다음` 버튼으로 결과를 순서대로 이동합니다. 검색 결과가 없는 경우에는 문서 위치를 바꾸지 않고 안내만 표시합니다.

목차나 검색 결과를 누른 뒤 검은 화면이나 로그인 화면으로 이동하면, 구버전 정적 파일이 브라우저에 남아 있을 수 있습니다. 현재 화면을 한 번 새로고침한 뒤 다시 시도하세요. 목차 이동은 새 URL을 열거나 세션을 끝내지 않습니다.

## 관리자 운영 매뉴얼

이 장은 역할·권한을 가진 운영자를 위한 화면입니다. 일반 사용자의 영상 생성, 작업 이력 확인, 프롬프트 재사용은 GENERATE 영역에서 수행합니다. ADMIN 영역은 사용자·정책·워크플로·카탈로그·Sandbox 같은 공통 운영 데이터를 변경하는 곳입니다.

## 9. 관리자 콘솔 전환

`admin:*` 또는 개별 관리 권한이 있는 사용자는 사이드바 상단 `관리자 콘솔 →` 버튼으로 ADMIN 영역에 진입합니다. ADMIN 사이드바 메뉴는 다음 순서로 고정되어 있습니다: 역할 & 권한 → 사용자 → 프롬프트 카탈로그 → 워크플로 정의 → Sandbox Pod → Task Policy → System Status → Metadata → 감사 로그.

![관리자 · 역할 & 권한 화면](v4-06-admin-roles.jpg)

## 10. 역할 & 권한 / 기능 리소스 매핑

`역할 & 권한` 메뉴입니다. 좌측 사이드바에 `ROLES · N` 목록(SUPER_ADMIN/ADMIN/OPERATOR/VIEWER)이 있고, 역할을 선택하면 본문에 해당 역할의 권한 칩 목록과 `Save Role Permissions` 저장 버튼, 그 아래 이 역할에 대한 변경 기록(감사 로그)이 표시됩니다. `admin:*` 권한은 와일드카드로, 다른 모든 권한을 포함한 것으로 취급되어 화면에 별도 표시됩니다.

역할 권한은 해당 역할 사용자 전체에 적용됩니다. 사용자 개별 예외 권한은 [사용자 관리](#11-사용자-관리) 화면에서 별도로 관리합니다.

역할 권한을 변경하면 즉시 해당 역할 사용자의 메뉴 노출과 기능 활성화가 바뀝니다. 동시 작업 제출 정책은 Admin 사이드바의 독립된 **Task Policy** 메뉴에서 관리합니다.

헤더 우측 `기능 리소스 매핑 보기` 버튼을 누르면 화면(MENU)·동작(ACTION) 단위로 어떤 권한 코드가 필요한지 보여주는 표로 이동합니다 — 특정 메뉴나 버튼이 왜 안 보이는지 확인할 때 유용합니다.

![기능 리소스 매핑 화면](v4-17-admin-resource-map.jpg)

## 11. 사용자 관리

`사용자` 메뉴에서 전체 사용자 목록(이름/ID/역할/상태)을 확인합니다. `New User` 버튼으로 신규 사용자를 등록하고, 행을 클릭하면 사용자 상세 화면으로 이동합니다.

![사용자 목록 화면](v4-07-admin-users.jpg)

사용자 상세 화면에서는 ID(신규 등록 시에만 입력 가능)/Name/Role/State를 수정하고, Role Default Permissions(역할 기본 권한, 읽기 전용)와 Extra Permissions(사용자 개별 예외 권한, 역할 기본 권한과 중복 선택 불가)를 관리합니다. Effective Permissions는 두 권한을 합친 최종 값입니다.

![사용자 상세 화면](v4-08-admin-user-detail.jpg)

비밀번호 재설정과 사용자 비활성화는 각각 전용 카드의 버튼으로 처리합니다(일반 저장과 분리되어 있어, 값 충돌 없이 안전하게 동작합니다). 기본 SUPER_ADMIN 계정(`dobedub`)은 시스템 잠금을 방지하기 위해 비활성화할 수 없습니다.

## 12. 프롬프트 카탈로그 관리

`프롬프트 카탈로그` 메뉴는 세 화면을 함께 제공합니다(헤더 우측 버튼으로 전환).

**카탈로그 계층** — Positive Prompt / Negative Prompt 최상위 아래 카테고리 → 서브카테고리 → 키워드까지 트리로 관리합니다. 트리를 펼치면 레벨별로 글자 크기·굵기가 단계적으로 작아집니다(최상위가 가장 크고 진하게).

![카탈로그 계층 화면(트리 펼침)](v4-10-admin-catalog-tree-expanded.jpg)

**용어 관리** — 같은 트리에서 개별 키워드(용어) 추가·수정에 초점을 맞춘 화면입니다. 변경한 키워드는 사용자의 Prompt Builder 카탈로그에 반영되며, 사용자는 Refresh Builder로 최신 목록을 다시 읽을 수 있습니다.

**Negative 기본값** — 카탈로그 트리를 Negative scope로 필터링한 뷰입니다. 모든 Run에 항상 적용되는 기본 네거티브는 워크플로 JSON의 네거티브 노드에 내장되어 있어 이 화면에서 관리하지 않습니다 — 여기서는 그 위에 추가로 얹을 선택 용어(Negative 계열)만 관리합니다.

![Negative 기본값 화면](v4-11-admin-negative-defaults.jpg)

카탈로그를 수정한 뒤 사용자는 Prompt Builder의 `Refresh Builder`를 눌러 최신 계층과 키워드를 다시 불러옵니다. 이미 작성 중인 세그먼트의 선택 값·Scene Detail·Draft는 Refresh Builder로 초기화되므로, 필요한 문장은 적용 또는 복사한 뒤 갱신하는 것이 안전합니다.

## 13. 워크플로 정의 관리

`워크플로 정의` 메뉴입니다. 좌측 사이드바에 등록된 워크플로 목록(활성/비활성 배지 포함)이 있고, 선택하면 오른쪽에 Workflow ID·Mode·Input Images·Subgraphs·Workflow File·Param Config·Metadata·등록/수정 시각 등 상세 정보가 표시됩니다. `Activate`/`Deactivate`로 사용 가능 여부를 전환합니다.

![워크플로 정의 상세 화면](v4-12-admin-workflows.jpg)

`New Workflow` 버튼으로 등록 화면으로 이동해 Workflow JSON과 Param Config JSON(비우면 저장 시 자동 생성)을 업로드하고 Workflow ID·Description을 입력합니다. 저장 시 세그먼트 기본값과 메타데이터가 자동으로 생성/갱신됩니다. 활성화해야 사용자의 Workspace 목록에 나타납니다.

## 14. Sandbox Pod

`Sandbox Pod` 메뉴입니다. 일상적인 영상 생성용 RunPod Serverless와는 분리된 전용 Pod로, 개발/디버깅 목적의 HTTP 서비스(ComfyUI 등)에 접근할 때 사용합니다.

![Sandbox Pod 화면](v4-13-admin-sandbox-pod.jpg)

Pod ID/이름은 Network Volume ID와 Template ID로 매 요청마다 재해결됩니다(고정 값이 아님 — RunPod 측 마이그레이션에 대응하기 위함). `Deploy Sandbox Pod`/`Stop Pod`/`Refresh Status`로 제어하며, 상태는 ComfyUI `8188` 서비스 주소와 `INITIALIZING`/`READY`/`EXITED` 등으로 표시됩니다. 하단 `Pod 제어 이력`은 감사 로그와 연동되어 있습니다.

Sandbox Pod는 Pod 상태와 HTTP 서비스만 관리합니다. 동시 작업 제출 정책은 별도 **Task Policy** 메뉴에서 확인·수정합니다.

## 15. Task Policy

Admin 사이드바에서 `Sandbox Pod` 바로 아래에 있는 **Task Policy** 메뉴입니다. `사용자당 동시 활성 Task`와 `전체 동시 활성 Task`를 설정합니다. 기본값은 각각 3개와 10개입니다.

화면은 상단의 **동시 실행 한도** 카드와 하단의 **Task Policy 변경 이력** 표로 나뉩니다. 두 입력칸은 한 사용자 기준과 모든 사용자 합산 기준을 명확히 분리하고, 변경 이력 표는 화면 폭이 좁아져도 가로 스크롤로 확인하므로 텍스트가 겹치지 않습니다.

운영 절차:

1. 현재 정책 값을 확인합니다. 조회에는 `roles:read`, 변경에는 `roles:write`가 필요합니다.
2. 개별 사용자의 동시 제출 수와 전체 서버리스 처리 여유를 함께 고려해 두 값을 입력합니다.
3. `Save Task Policy`를 누릅니다. 저장한 값은 **이후 제출부터** 적용되고 변경 이력은 하단 감사 로그에 남습니다.
4. `QUEUED`, `IN_QUEUE`, `IN_PROGRESS`, `RUNNING`만 한도에 포함됩니다. 완료·실패·취소·시간초과 Task는 즉시 한도에서 빠집니다.

한도를 초과하면 새 Task를 만들지 않고 다음 안내가 표시됩니다: `사용자 동시 활성 Task 한도(n개)에 도달했습니다. Task History에서 진행 상태를 확인하거나 완료 후 다시 제출하세요.`

전체 한도를 넘는 경우에는 `전체 동시 활성 Task 한도(n개)에 도달했습니다. 잠시 후 다시 시도하세요.`가 표시됩니다. 정책을 낮춰도 이미 실행 중인 Task를 강제로 취소하지는 않으며, **다음 제출부터** 새 한도가 적용됩니다. 작업이 장시간 멈춘 것처럼 보이면 먼저 Task History에서 RunPod 상태·실패 사유를 확인하고, 필요할 때만 취소/재실행을 선택하세요.

## 16. System Status

`System Status` 메뉴입니다. Execution(dry-run/실제 실행 모드), ComfyUI RunPod, Qwen Prompt LLM, Workflows, Segment Defaults, Metadata, Storage 7개 카드로 전체 시스템 헬스를 한눈에 확인합니다.

![System Status 화면](v4-14-admin-system-status.jpg)

`Test ComfyUI` 버튼은 실제 작업을 생성하지 않고 헬스체크만 호출해 endpoint 접근·worker 상태·queue 상태를 확인합니다. `Refresh`로 전체 카드를 다시 조회합니다.

## 17. Metadata

`Metadata` 메뉴입니다. 워크플로를 선택하면 Node Count·Subgraphs·Generated At·Fingerprint 등 요약 정보와, 좌측 사이드바의 Summary/Subgraphs/Parameters/Models/Nodes 탭으로 더 세부적인 메타데이터를 조회할 수 있습니다.

![Metadata 화면](v4-15-admin-metadata.jpg)

`Rebuild Metadata` 버튼으로 선택한 워크플로의 메타데이터를 워크플로 JSON 기준으로 다시 생성합니다.

## 18. 감사 로그

`감사 로그` 메뉴입니다. **어드민 정보 수정 행위만** 기록합니다 — 역할 권한 변경, 사용자 생성/수정/비밀번호 초기화/비활성화, 프롬프트 카탈로그(시스템 프롬프트·카테고리 그룹·카테고리·용어) 수정, Sandbox Pod 시작/중지가 대상입니다. 로그인 시도와 개인 작업 이력 삭제는 정보 수정이 아니라는 판단으로 기록하지 않습니다(과거에는 기록했으나 2026-08-12부로 범위를 좁혔습니다).

![감사 로그 화면](v4-16-admin-audit-log.jpg)

- 컬럼: 시각 / 행위자 / 작업(짧은 한글 라벨로 표시, 원래 값은 마우스 오버 시 확인) / 대상(넓게 표시되어 긴 값도 줄바꿈되지 않음) / 상세(JSON 보기).
- 상단 검색창으로 action(예: `role.permissions.update`)·targetType(예: `role`)을 직접 입력해 필터링할 수 있습니다(Enter 또는 Search 클릭 시 적용).
- 3b(역할 & 권한)·5b(Sandbox Pod)·7a(시스템 프롬프트)·프롬프트 카탈로그 화면에도 각 대상별로 좁힌 감사 로그가 같은 컴포넌트로 삽입되어 있습니다.

## 19. 권한 코드 요약표

역할 & 권한 화면에서 다루는 권한 코드입니다(SUPER_ADMIN 기준 전체 목록).

| 권한 코드 | 대상 |
| --- | --- |
| `admin:*` | 전체 운영 및 시스템 설정 권한(와일드카드) |
| `users:read` / `users:write` | 사용자 조회 / 사용자 생성·수정·비밀번호 재설정·비활성화 |
| `roles:read` / `roles:write` | 역할·권한 조회 / 역할 권한 수정 |
| `workflows:read` / `workflows:write` / `workflows:activate` | 워크플로 조회 / 등록·수정 / 활성화·비활성화 |
| `prompt-catalog:read` / `prompt-catalog:write` | 프롬프트 카탈로그 조회 / 수정 |
| `prompts:build` | 프롬프트 생성(Keyword Builder, Qwen 생성) |
| `prompts:reuse` | Prompt Library 재사용 조회·적용 |
| `prompts:review` | Task History에서 프롬프트 품질 평가 |
| `jobs:run` / `jobs:cancel` | 영상 생성 실행 / 취소 |
| `history:read` / `history:delete` | 작업 이력 조회 / 삭제 |
| `metadata:read` / `metadata:rebuild` | 메타데이터 조회 / 재생성 |
| `system:read` | System Status 조회 |
| `manual:read` | 사용자 매뉴얼 조회 |
| `sandbox:read` / `sandbox:control` | Sandbox Pod 조회 / 시작·중지 제어 |

## 20. 운영 시 주의사항

- **세션은 탭 종속입니다.** 같은 계정이라도 다른 탭/창의 세션은 공유되지 않습니다. 같은 탭에서 새로고침해도 로그인 상태는 유지되며, 로그아웃 또는 탭/브라우저 종료 시 정리됩니다.
- **Task History는 작업의 단일 기준 화면입니다.** 생성 진행·결과 전용 화면을 따로 사용하지 않습니다. 모든 상태 확인, 취소, 결과 확인, 다운로드, 재작업, 프롬프트 평가는 Task History에서 처리합니다.
- **재실행은 항상 전체 세그먼트 단위입니다.** 부분 재실행 기능은 없습니다.
- **삭제는 소프트 삭제입니다.** Task History에서 지운 작업은 목록·재사용 후보에서 즉시 빠지지만, 완전히 파기되지는 않습니다. 완전 삭제가 필요하면 별도로 요청하세요.
- **Negative 기본값과 세그먼트 Negative는 다른 개념입니다.** 워크플로 JSON에 내장된 기본 네거티브는 화면에서 수정할 수 없고, 관리자 화면에서는 그 위에 추가되는 선택 용어만 관리합니다.
- **감사 로그는 어드민 정보 수정만 남습니다.** 로그인 이력이나 사용자의 자기 작업 삭제 이력은 감사 로그에서 조회되지 않습니다.
- **Prompt 생성과 영상 생성은 별도 서비스입니다.** Qwen이 OFFLINE이면 영문 Prompt 자동 생성은 실패할 수 있지만, 직접 입력·키워드 초안·기존 Prompt 재사용은 가능한 범위에서 계속 사용할 수 있습니다. ComfyUI가 OFFLINE이면 새 영상 Task 제출은 할 수 없습니다.
- **Task Policy는 대기열을 만드는 기능이 아닙니다.** 현재 정책을 초과한 제출은 자동 대기열에 쌓이지 않고 즉시 거절됩니다. 사용자는 안내 메시지를 보고 나중에 다시 제출해야 합니다.
- **작업 결과의 공식 보관 기준은 Asset 연결입니다.** 브라우저의 임시 미리보기나 로컬 다운로드 파일이 아니라, Task History의 입력/출력 Asset과 Final 출력이 추적 기준입니다.

## 21. 문제 해결

| 증상 | 확인 사항 |
| --- | --- |
| 로그인이 안 됨 | ID/Password 재확인, 계정이 INACTIVE 상태인지 관리자에게 문의 |
| 사이드바에 메뉴가 안 보임 | 해당 기능에 필요한 권한이 없을 수 있습니다 — [기능 리소스 매핑](#10-역할--권한--기능-리소스-매핑)에서 필요 권한 확인 |
| `실행 전 확인으로 →` 버튼이 비활성 | 모든 세그먼트에 프롬프트가 적용되지 않았습니다 — 좌측 사이드바에서 "설정 필요"로 표시된 세그먼트를 확인하세요 |
| `Run` 버튼이 비활성 | 실행 전 확인 화면의 "제출 검증" 카드에서 통과하지 못한 항목을 확인하세요 |
| 작업 제출이 거절됨 | Task Policy의 사용자별 또는 전체 활성 Task 한도를 초과했을 수 있습니다. Task History의 진행 작업을 확인하세요 |
| 새로고침 뒤 로그인 화면이 보임 | 최신 화면을 한 번 다시 로드한 뒤 로그인하세요. 이후 같은 탭 새로고침은 세션을 유지합니다. 명시 로그아웃 또는 탭 종료 뒤에는 정상적으로 다시 로그인해야 합니다 |
| User Manual 목차 클릭 후 다른 화면으로 이동 | 최신 화면으로 새로고침하세요. 목차는 문서 안에서만 이동하며 로그인 경로로 전환되지 않아야 합니다 |
| Prompt Library에 원하는 프롬프트가 없음 | Task History의 Prompt Review에서 "재사용 가능"으로 등록되어야 목록에 나타납니다 |
| Qwen Prompt가 생성되지 않음 | System Status에서 Qwen 상태를 확인하고, Scene Detail 또는 Positive 키워드가 하나 이상 있는지 확인하세요. 서버리스 콜드 스타트 중에는 응답 시간이 길어질 수 있습니다 |
| Prompt Builder의 키워드가 최신 카탈로그와 다름 | 관리자 변경 후 `Refresh Builder`를 눌러 최신 카탈로그를 다시 읽으세요. 갱신 전 현재 초안이 필요한 경우 먼저 적용 또는 복사하세요 |
| 입력 이미지가 재작업 화면에 보이지 않음 | Task History의 Assets에 입력 Asset이 연결돼 있는지 확인하세요. 권한 오류가 나오면 `history:read`와 Asset 조회 권한을 관리자에게 요청하세요 |
| 완료 Task에 영상이 없음 | Overview 상태와 Assets의 Final 출력 연결을 확인하세요. RunPod가 완료됐더라도 서버 저장이 실패하면 Task가 FAILED로 정리될 수 있습니다 |
| System Status에서 ComfyUI/Qwen이 OFFLINE | RunPod endpoint 상태를 확인하고, `Test ComfyUI`로 재확인하세요 — 지속되면 인프라 담당자에게 문의 |
| Sandbox Pod가 EXITED 상태 | `Deploy Sandbox Pod`로 재배포하세요. Pod ID는 재배포 시마다 새로 해결됩니다 |
