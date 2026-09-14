# DOBEDUB STUDIO 사용자 매뉴얼

작성일: 2026년 8월 13일 · 최종 재작성: 2026년 9월 14일

대상 앱: DOBEDUB STUDIO v4 (좌측 사이드바 + 라우트 기반 UI)

운영 목적: ComfyUI WAN Image-to-Video workflow 실행, 프롬프트 생성/재사용, 작업 이력·자산·운영 관리

주요 연동: RunPod Serverless ComfyUI, RunPod vLLM Qwen(Grok 프롬프트 생성), DB 기반 작업/자산/프롬프트 관리, Sandbox Pod

:::info 이 문서를 읽는 방법
이 매뉴얼은 실제 로그인한 화면을 직접 캡처하여 작성했습니다. 화면 캡처가 있는 절은 현재 앱과 1:1로 대응합니다. 다만 신규 화면(프롬프트 지시 관리, Batch 처리, Runpod ComfyUI 요청 등)의 세부 검증 규칙 일부는 화면 캡처와 표시된 항목을 근거로 설명했으며, 서버 내부 로직까지 전수 테스트하지는 않았습니다. 화면 문구와 이 문서의 설명이 다르면 화면 문구를 우선하세요.
:::

## 전체 업무 흐름

**v4의 영상 생성은 한 화면에서 끝까지 진행하는 마법사가 아니라, 서로 분리된 화면을 순서대로 오가며 진행하는 파이프라인입니다.** 아래 순서를 기본 업무 절차로 사용하세요.

| 단계 | 사용하는 화면 | 사용자가 하는 일 | 시스템이 관리하는 일 |
| --- | --- | --- | --- |
| 1. 접속 | 로그인 | ID와 비밀번호로 로그인 | 권한과 세션을 확인하고 메뉴를 구성 |
| 2. 컷 준비 | LOCAL · 이미지 컷 분할 | 웹툰 원본을 브라우저에서 PNG 컷으로 분할 | 서버 업로드 없이 로컬에서만 처리(정책만 서버 제공) |
| 3. 프롬프트 준비 | Grok 프롬프트 생성 | workflow를 선택하고 이미지를 업로드해 Positive Prompt 생성을 요청 | Qwen/Grok 서비스가 이미지별 프롬프트를 비동기로 생성 |
| 4. 제출 준비 | Batch 처리 | 생성된 프롬프트가 연결된 이미지 ZIP과 길이·화질을 선택해 Batch를 만듦 | Batch 단위로 프롬프트 생성/영상 생성 큐를 구성 |
| 5. 영상 생성 요청 | Runpod ComfyUI 요청 | 요청 준비된 이미지를 선택해 RunPod에 실제 제출 | RunPod Serverless ComfyUI에 제출하고 진행 상태를 추적 |
| 6. 결과 확인 | 작업 이력 | 완료/실패/진행 중 작업을 조회하고 결과를 확인 | 작업자별·워크플로별 통계를 집계 |
| 7. 정리 | Collection 관리 | 생성된 영상을 컬렉션으로 분류 | 자산을 DB에 보관 |

**가장 중요한 원칙은 각 화면이 독립적인 작업 단계라는 점입니다.** 이미지 업로드(Grok 프롬프트 생성) → Batch 생성(Batch 처리) → 실제 제출(Runpod ComfyUI 요청)이 서로 다른 화면으로 나뉘어 있으므로, 한 화면을 닫아도 다음 화면에서 이어서 진행할 수 있습니다. 진행 상태는 각 화면의 대시보드 카드(예: Runpod ComfyUI 요청의 `Incomplete Requests`)에서 계속 확인할 수 있습니다.

:::tip 어디서부터 시작해야 하는지 모를 때
홈 대시보드의 "시스템 상태 · 작업 현황"에서 ComfyUI Serverless/Qwen LLM/Sandbox Pod가 모두 `ONLINE`(또는 `RUNNING`)인지 먼저 확인하세요. 이미 만들어 둔 프롬프트가 있다면 Batch 처리로, 아직 없다면 Grok 프롬프트 생성부터 시작합니다.
:::

## 목차

1. [서비스 개요](#1-서비스-개요)
2. [로그인](#2-로그인)
3. [화면 공통 구조](#3-화면-공통-구조)
4. [사용자 업무 매뉴얼](#사용자-업무-매뉴얼)
   - [이미지 준비 · LOCAL 이미지 컷 분할](#4-이미지-준비--local-이미지-컷-분할)
   - [Grok 프롬프트 생성](#5-grok-프롬프트-생성)
   - [Batch 처리](#6-batch-처리)
   - [Runpod ComfyUI 요청](#7-runpod-comfyui-요청)
   - [작업 이력](#8-작업-이력)
   - [Collection 관리](#9-collection-관리)
   - [사용자 매뉴얼 화면 · Metadata](#10-사용자-매뉴얼-화면--metadata)
5. [관리자 운영 매뉴얼](#관리자-운영-매뉴얼)
   - [관리자 콘솔 전환](#11-관리자-콘솔-전환)
   - [역할 & 권한 / 기능 리소스 매핑](#12-역할--권한--기능-리소스-매핑)
   - [사용자 관리](#13-사용자-관리)
   - [프롬프트 지시 관리](#14-프롬프트-지시-관리)
   - [프롬프트 카탈로그 관리](#15-프롬프트-카탈로그-관리)
   - [워크플로 정의 관리](#16-워크플로-정의-관리)
   - [Sandbox Pod](#17-sandbox-pod)
     - [FileBrowser로 파일 확인](#filebrowser로-파일-확인)
     - [JupyterLab과 터미널 사용](#jupyterlab과-터미널-사용)
     - [Network Volume 사용량 조회와 정리](#network-volume-사용량-조회와-정리)
   - [Runpod Worker 설정](#18-runpod-worker-설정)
   - [Metadata(관리자)](#19-metadata관리자)
   - [감사 로그](#20-감사-로그)
6. [권한 코드 요약표](#21-권한-코드-요약표)
7. [운영 시 주의사항](#22-운영-시-주의사항)
8. [문제 해결](#23-문제-해결)

## 수정 이력

| 일자 | 변경 전 | 변경 후 | 비고 |
| --- | --- | --- | --- |
| 2026-09-14 | STEP1~4 Workspace 마법사(이미지 로드→세그먼트 설정→실행 전 확인) 기준 설명, v4 캡처 다수 누락, 강조 표시 수단이 볼드뿐 | **전면 재작성.** 실제 로그인 화면 18장 재캡처, 실제 GENERATE 흐름(Grok 프롬프트 생성→Batch 처리→Runpod ComfyUI 요청→작업 이력→Collection 관리)에 맞춰 사용자 업무 매뉴얼을 다시 작성. 전체 업무 흐름을 문서 맨 앞으로 이동. `:::warning` 등 색상 콜아웃과 `==강조==` 표기 지원 추가(`manual_service.py`) | 전체 |
| 2026-08-18 | Sandbox Pod 접속 링크와 저장소 관리 절차가 간략함 | FileBrowser·JupyterLab·터미널·Network Volume 사용량 조회 및 정리 절차 추가 | Sandbox Pod 운영 |
| 2026-08-05 | 구버전 캡처 이미지 사용 | v3 현재 화면 14장 신규 캡처 후 전면 재작성 | 당시 문서 기준 |
| 2026-08-12 | 모달 기반 UI(Admin Console/Prompt Builder/Metadata View 등) 설명 | **전면 재작성.** GNB·모달이 사라지고 좌측 사이드바 + 라우트 기반 화면(v4)으로 전환 | v4 구조 전환 |
| 2026-09-11 | 웹툰 원본 컷을 I2V 입력용 이미지로 준비하는 절차가 외부 도구에 의존 | **LOCAL `이미지 컷 분할` 추가.** ECS/로컬 서버는 화면 코드와 정책만 제공하고, PDF·이미지·ZIP 컷 분할은 사용자의 브라우저 로컬 파일 시스템에서만 수행 | 이미지 준비 |

## 1. 서비스 개요

DOBEDUB STUDIO는 이미지를 영상으로 변환하는 ComfyUI WAN Image-to-Video workflow를 웹 UI에서 실행하는 사내 도구입니다. 사용자는 ComfyUI 화면을 직접 열지 않고 다음을 수행합니다.

- 웹툰 원본 컷을 브라우저에서 로컬로 분할(LOCAL 이미지 컷 분할)
- workflow 선택과 이미지 업로드 후 Grok(Qwen)으로 Positive Prompt 자동 생성
- 생성된 프롬프트와 이미지 ZIP을 묶어 Batch로 구성(길이·화질 선택)
- Runpod ComfyUI 요청 화면에서 준비된 요청을 RunPod Serverless로 실제 제출
- 작업 이력에서 진행·완료·실패 확인, Collection 관리에서 결과 영상 분류
- (관리자) 사용자, 역할·권한, 워크플로, 프롬프트 카탈로그/지시문, Sandbox Pod, Runpod Worker 설정, 감사 로그 관리

v4는 좌측 사이드바 + 상단 헤더 + 본문(+ 있는 화면은 우측 정보 패널)으로 구성된 라우트 기반 화면입니다. 화면마다 고유 URL이 있고, 브라우저 새로고침이나 뒤로가기도 정상 동작합니다. 홈 화면에는 "시스템 상태 · 작업 현황" 대시보드가 있어 ComfyUI Serverless, Qwen LLM, Sandbox Pod, RunPod Worker 동시 실행, Workflows DB 상태와 최근 7/30일 작업 통계를 한 화면에서 볼 수 있습니다.

## 2. 로그인

앱 접속 시 로그인 화면이 먼저 표시됩니다. 로그인은 `ID`와 `Password`만 사용하며, 사내 전용으로 외부 SSO는 없습니다.

![로그인 화면](v4-00-login.jpg)

로그인 절차:

1. `ID` 입력란에 사번 또는 계정 ID를 입력합니다.
2. `Password` 입력란에 비밀번호를 입력합니다.
3. `접속하기` 버튼을 클릭합니다.

로그인 화면 우측의 "시스템 상태" 카드에서 ComfyUI Serverless·Qwen LLM의 공개 헬스체크 상태를 로그인 전에도 미리 확인할 수 있습니다.

:::info 세션 규칙
세션은 브라우저 탭에 종속됩니다. 같은 탭에서 새로고침해도 로그인 상태는 유지되며, 명시적으로 로그아웃하거나 탭/브라우저를 종료하면 세션이 정리됩니다. 비활성 계정은 미입력 오류도 같은 자리에 표시됩니다.
:::

## 3. 화면 공통 구조

로그인 후 모든 화면은 아래 레이아웃을 공유합니다.

- **좌측 사이드바** — 상단에 로고, `HOME`/`LOCAL`/`GENERATE`/`ADMIN` 대분류와 1차 메뉴 목록, 화면별 하위 정보(2차 메뉴·필터·트리 등)가 이어집니다.
- **상단 헤더** — 현재 위치(eyebrow 텍스트, 예: `GENERATE / TASK HISTORY`)와 화면 제목, 우측에 화면별 주요 액션 버튼이 있습니다.
- **본문** — 화면의 핵심 콘텐츠(표, 카드, 폼 등).
- **우측 정보 패널** — 있는 화면에서는 요약 정보, 검증 상태, 보조 액션을 보여줍니다(모든 화면에 있는 것은 아닙니다).

![홈 대시보드 — 공통 레이아웃 예시](v4-01-home-dashboard.jpg)

권한이 없는 메뉴 항목은 사이드바에서 아예 보이지 않습니다. 로그인한 사용자 이름·역할과 로그아웃 버튼은 사이드바 하단에 표시됩니다.

### GENERATE ↔ ADMIN 전환

권한이 있는 사용자는 사이드바 하단의 전환 버튼으로 두 영역을 오갈 수 있습니다.

- GENERATE 영역에서: `관리자 콘솔 →` 버튼 → ADMIN 영역으로 이동
- ADMIN 영역에서: `← 스튜디오` 버튼 → GENERATE 영역(홈)으로 이동

### LOCAL 메뉴

`이미지 컷 분할`은 `GENERATE` 위의 독립 `LOCAL` 영역에 표시됩니다. RunPod/ECS 작업 큐에 제출하는 기능이 아니라, 향후 I2V 입력에 사용할 컷 PNG를 사용자의 컴퓨터에서 직접 만드는 로컬 처리 기능입니다.

- 지원 브라우저: 데스크톱 Chrome·Edge 최신 버전
- **서버 전송 없음**: 원본 파일, 결과 컷, 로컬 절대경로, 파일명 목록은 DOBEDUB 서버·ECS·EFS·S3·RDS로 전송하지 않습니다.

## 사용자 업무 매뉴얼

이 장은 영상을 생성하는 사용자의 실제 업무 순서입니다. Grok 프롬프트 생성 → Batch 처리 → Runpod ComfyUI 요청은 서로 다른 화면으로 분리되어 있으므로, 순서대로 화면을 이동하며 진행합니다.

## 4. 이미지 준비 · LOCAL 이미지 컷 분할

`이미지 컷 분할`은 웹툰 원본을 향후 I2V 파이프라인 입력 이미지로 쓰기 위해 PNG 컷으로 나누는 기능입니다. 서버 생성 작업과 다르게 업로드·다운로드가 없고, 실제 처리는 브라우저 로컬 실행 영역에서 끝납니다.

![LOCAL 이미지 컷 분할 화면](v4-02-local-cut-split.jpg)

1. `작업 폴더 연결`로 시스템 폴더가 아닌 별도 작업 폴더를 연결합니다. 이 위치에 `<입력명>_cuts` 출력 폴더가 생성됩니다.
2. `파일 선택` 또는 `폴더 선택`으로 PDF, JPG/JPEG, PNG, WEBP, GIF, ZIP 또는 폴더를 선택합니다. 끌어놓기도 지원합니다.
3. 화면이 처리 대상 수, 작업 위치, 출력 위치, 출력 구조, 적용 정책 버전을 표시합니다.
4. `작업 요청`을 누르면 `<입력명>_cuts` 출력 구조에 PNG 컷, `summary.csv`, `manifest.json`, `_debug/` 검수 자료를 생성합니다.
5. 다른 DOBEDUB 화면으로 이동해도 같은 탭에서는 진행 상태를 유지합니다.

출력 규칙:

- 모든 컷과 debug 이미지는 입력 형식과 관계없이 PNG입니다.
- 원본 crop 픽셀 크기와 종횡비를 유지하며 I2V 모델별 리사이즈·패딩은 하지 않습니다.
- PDF는 300dpi로 페이지를 렌더링한 뒤 페이지별 `PPP-CC.png` 형식으로 저장합니다.
- ZIP은 로컬에 별도로 풀지 않고 항목 단위로 처리하며, 출력은 `<압축파일명>_cuts/<ZIP 내부 상대경로>/<원본 파일명>/` 구조를 따릅니다.

검수 상태: `fullpage`(컷 경계를 못 찾아 전체를 1컷으로 저장), `review_continuous`(긴 연속 장면 — 수평 장면 전환 후보 검수 필요), `thin`/`many`(너무 얇거나 컷이 많아 사람 확인 필요), `missing_output`/`error`(검증된 PNG 없음 또는 처리 오류 — `실패/누락 재시도`로 해당 단위만 재처리).

## 5. Grok 프롬프트 생성

좌측 사이드바 `GENERATE` 그룹의 `Grok 프롬프트 생성` 메뉴입니다. 이미지를 업로드하면 Qwen(Grok) 서비스가 워크플로 지시문에 맞춰 Positive Prompt를 자동으로 만들어 줍니다.

![Grok 프롬프트 생성 화면](v4-05-grok-prompt.jpg)

화면 구성:

- **Prompt Workflow** — 프롬프트를 생성할 워크플로 지시문을 카드에서 선택합니다(예: `1-images_10s_chain_81`, `1-images_81`, `wan22_10s_chain`, `wan22_default_81`). 워크플로를 선택하지 않으면 상단에 `워크플로를 선택하세요. 연결된 지시문이 없으면 프롬프트 생성 요청을 시작할 수 없습니다.` 안내가 표시되고 요청이 차단됩니다.
- **Image Upload** — `이미지 업로드` 카드에 파일을 선택하거나 끌어놓습니다. 업로드한 이미지는 이미지별로 개별 삭제할 수 있습니다.
- **Batch Prompt Generation** — 업로드된 이미지 수를 표시하고, `Generate Prompts for N Images` 버튼으로 선택한 워크플로 지시문 기준 일괄 생성을 요청합니다.
- **Prompt Generation Dashboard** — 진행 중인 프롬프트 생성 배치의 상태를 보여줍니다. 항목이 모두 완료 또는 실패하면 이 목록에서 빠지고 Prompt History로 이동합니다.
- **Image Prompt Mapping** — 이미지별로 생성된 Positive Prompt를 확인·수정하는 영역입니다(화면 하단, 스크롤 시 노출).

:::warning 프롬프트 생성 = 영상 생성이 아님
이 화면에서 만든 프롬프트는 아직 RunPod에 제출되지 않습니다. 다음 단계인 [Batch 처리](#6-batch-처리) 또는 [Runpod ComfyUI 요청](#7-runpod-comfyui-요청)에서 실제 영상 생성 제출이 이루어집니다.
:::

## 6. Batch 처리

`Batch 처리` 메뉴에서는 워크플로·이미지 ZIP·길이·화질을 지정해 프롬프트 생성과 RunPod 영상 생성을 배치 단위로 진행합니다.

![Batch 처리 화면](v4-04-batch.jpg)

- **Batch 생성** 카드 — `Prompt Workflow` 선택, `작업 ZIP` 업로드, `길이(프레임 수)`(예: 49 / 81), `Quality`(예: SD · 409K px) 를 지정하고 `작업 요청`을 누릅니다.
- **Built-in Negative Prompt** — 선택한 워크플로의 기본 Negative Prompt가 표시됩니다. 값을 수정하면 이번 Batch의 모든 이미지 요청에 적용되고, 비워두면 워크플로 내장값을 그대로 사용합니다.
- **진행 중 Batch** — `프롬프트 생성`과 `RunPod 영상 생성` 두 패널로 나뉘어 Batch ID별 대기/생성 중/완료/실패 건수를 각각 보여줍니다.

## 7. Runpod ComfyUI 요청

`Runpod ComfyUI 요청` 메뉴는 프롬프트까지 준비된 이미지를 실제 RunPod Serverless ComfyUI에 제출하는 화면입니다.

![Runpod ComfyUI 요청 화면](v4-06-runpod-request.jpg)

- **RunPod Progress Dashboard** — `Incomplete Requests`(아직 제출하지 않은 준비 완료 요청), `Request Ready`, `Pending Submit`, `RunPod Queued`, `In Progress`, `Completed`, `Failed` 카운트를 보여줍니다. 그 아래 작업자별 카드에서 요청 준비/Pending/큐/실행/완료/실패 건수를 확인합니다.
- **Incomplete RunPod Requests** 표 — 작업자·워크플로·상태·Quality로 좁혀서 조회하고, 행을 선택한 뒤 우측 상단 `선택 N건 RunPod 요청` 버튼으로 실제 제출합니다. 컬럼: 이미지 미리보기, 입력 파일, 작업자, Prompt Batch ID, Item No., Positive Prompt, Workflow, Length, Quality, 상태.

:::danger 실제 과금·실행이 발생하는 단계
이 화면에서 `선택 N건 RunPod 요청`을 누르는 순간부터 RunPod Serverless GPU 실행과 과금이 시작됩니다. 이전 단계(Grok 프롬프트 생성·Batch 처리)는 프롬프트만 준비할 뿐 GPU 작업을 실행하지 않습니다.
:::

## 8. 작업 이력

좌측 사이드바 `작업 이력` 메뉴입니다. `RunPod 이력`과 `프롬프트 이력` 두 탭으로 나뉩니다.

![작업 이력 화면](v4-03-task-history.jpg)

- **조회 조건** — 작업자, 실행일, 작업 ID(Studio Task / RunPod Job ID), Batch ID, 워크플로우, 결과로 필터링합니다.
- **선택 항목에 대한 작업** — 체크한 행에 대해 `선택 재실행`, `선택 다운로드`, `선택 ZIP`, `선택 삭제`를 실행합니다. `현재 필터 전체 선택`, `조회 오류 재실행`, `배치 ZIP` 바로가기도 제공합니다.
- **조회 결과** 표 — No / 작업자 / 실행일 / 워크플로우 / Batch ID / Prompt ID / Studio Task / RunPod Job ID / 결과(`Complete` 등) / 입력 이미지 / 생성 영상 컬럼으로 구성됩니다.
- **우측 RunPod 조회 통계 패널** — 현재 필터 기준 총건/완료/실패/취소/제출대기/진행 건수, 완료·실패·취소·진행 비율을 보여주는 결과 구성 막대, 적용된 필터 목록(Batch ID, 작업 ID 등)을 표시합니다.

## 9. Collection 관리

좌측 사이드바 `Collection 관리` 메뉴입니다(전체 자산 수가 헤더에 표시됩니다).

![Collection 관리 화면](v4-07-collection.jpg)

- 상단 `컬렉션 관리` 카드에서 새 컬렉션 이름을 입력하고 `컬렉션 만들기`를 누릅니다. `전체 목록`과 각 컬렉션(자산 수 표시, `삭제` 버튼 포함)이 칩으로 나열됩니다.
- 표 컬럼: Collection(드롭다운으로 담기/빼기), Asset ID, 미리보기, Asset 이름, 생성일(KST·UTC 함께 표시), 생성자, 입력 이미지, 다운로드.

:::danger 빈 컬렉션만 삭제할 수 있습니다
자산 수가 0개인 컬렉션만 삭제할 수 있습니다. 분류된 자산이 남아 있으면 삭제가 차단되며, 먼저 각 Asset 행에서 다른 컬렉션으로 옮기거나 분류를 해제해야 합니다. 컬렉션 삭제는 Asset·원본 파일·다른 컬렉션 분류를 삭제하지 않습니다.
:::

컬렉션은 현재 접속한 환경의 DB에 저장됩니다. 로컬 개발 DB와 운영 ECS/RDS의 컬렉션 데이터는 자동으로 서로 복사되지 않습니다.

## 10. 사용자 매뉴얼 화면 · Metadata

좌측 사이드바 `HELP` 그룹의 `User Manual` 메뉴에서 바로 이 문서를 볼 수 있습니다.

![User Manual 화면](v4-09-user-manual-screen.jpg)

문서 맨 위 **목차 링크**를 클릭하면 같은 문서 안의 해당 절로 이동합니다. 상단 검색창은 입력한 단어를 본문에서 하이라이트하고 `다음` 버튼으로 결과를 순서대로 이동합니다.

같은 HELP 그룹의 `Metadata` 메뉴에서는 워크플로를 선택해 Node Count·Subgraphs·Generated At·Object Info Snapshot·Fingerprint 등 요약 정보를 조회합니다. 좌측 `Summary`/`Subgraphs`/`Parameters`/`Models`/`Nodes` 탭에서 더 세부적인 메타데이터를 확인할 수 있습니다.

![Workflow Metadata 화면](v4-08-metadata.jpg)

## 관리자 운영 매뉴얼

이 장은 역할·권한을 가진 운영자를 위한 화면입니다. 일반 사용자의 영상 생성, 작업 이력 확인은 GENERATE 영역에서 수행합니다. ADMIN 영역은 사용자·정책·워크플로·카탈로그·Sandbox 같은 공통 운영 데이터를 변경하는 곳입니다.

## 11. 관리자 콘솔 전환

`admin:*` 또는 개별 관리 권한이 있는 사용자는 사이드바 하단 `관리자 콘솔 →` 버튼으로 ADMIN 영역에 진입합니다. ADMIN 사이드바 메뉴는 다음 순서로 표시됩니다: Sandbox Pod → 워크플로 정의 → 프롬프트 지시 관리 → 프롬프트 카탈로그 → 사용자 → 역할 & 권한 → Runpod Worker 설정 → 감사 로그.

## 12. 역할 & 권한 / 기능 리소스 매핑

`역할 & 권한` 메뉴입니다. 좌측 사이드바에 `ROLES · N` 목록(SUPER_ADMIN/ADMIN/OPERATOR/VIEWER)이 있고, 역할을 선택하면 본문에 해당 역할의 권한 칩 목록과 `Save Role Permissions` 저장 버튼, 그 아래 이 역할에 대한 변경 기록이 표시됩니다.

![역할 & 권한 화면](v4-15-admin-roles-permissions.jpg)

역할 권한은 해당 역할 사용자 전체에 적용됩니다. 사용자 개별 예외 권한은 [사용자 관리](#13-사용자-관리) 화면에서 별도로 관리합니다. 헤더 우측 `기능 리소스 매핑 보기` 버튼으로 화면·동작 단위 필요 권한 표로 이동할 수 있습니다.

## 13. 사용자 관리

`사용자` 메뉴에서 전체 사용자 목록(Name/ID/Role/State)을 확인합니다. `New User` 버튼으로 신규 사용자를 등록하고, 행을 클릭하면 사용자 상세 화면으로 이동합니다.

![사용자 목록 화면](v4-14-admin-users.jpg)

사용자 상세 화면에서는 ID(신규 등록 시에만 입력 가능)/Name/Role/State를 수정하고, Role Default Permissions(역할 기본 권한, 읽기 전용)와 Extra Permissions(사용자 개별 예외 권한)를 관리합니다.

:::warning 기본 SUPER_ADMIN 계정은 비활성화할 수 없습니다
시스템 잠금을 방지하기 위해 기본 SUPER_ADMIN 계정(`dobedub`)은 비활성화가 차단됩니다.
:::

## 14. 프롬프트 지시 관리

`프롬프트 지시 관리` 메뉴입니다. Grok(Qwen)이 이미지로부터 Positive Prompt를 생성할 때 사용하는 지시문(Instruction Document)을 워크플로별로 관리합니다.

![프롬프트 생성 지시 관리 화면](v4-12-admin-prompt-instruction.jpg)

- **Target Workflow** — 지시문을 연결할 워크플로를 선택합니다.
- **Instruction Documents** — 선택한 워크플로에 연결된 지시문 목록입니다. 각 문서는 `문서 코드`·`역할`(예: CORE/ROUTER/GUIDE)·버전과 함께 표시되며, `+ 지시문 추가`로 새 문서를 만들거나 `Markdown 가져오기`로 기존 문서를 불러올 수 있습니다.
- **Instruction Editor** — 문서 코드, 문서명, 역할, 정렬 순서, 출처/메모, `이 문서를 Grok 실행 지시문에 적용` 체크박스, 지시문 본문(Markdown)을 편집합니다.

:::warning 지시문 수정은 이후 생성 결과에 즉시 반영됩니다
지시문을 저장하면 연결된 워크플로의 [Grok 프롬프트 생성](#5-grok-프롬프트-생성) 요청부터 바로 새 지시문이 적용됩니다. 운영 중인 워크플로의 CORE 지시문을 수정할 때는 특히 주의하세요.
:::

## 15. 프롬프트 카탈로그 관리

`프롬프트 카탈로그` 메뉴는 여러 화면을 함께 제공합니다(헤더 우측 버튼으로 전환).

**카탈로그 계층** — Positive Prompt / Negative Prompt 최상위 아래 카테고리 → 서브카테고리 → 키워드까지 트리로 관리합니다.

![카탈로그 계층 화면](v4-13-admin-prompt-catalog.jpg)

**용어 관리** — 같은 트리에서 개별 키워드(용어) 추가·수정에 초점을 맞춘 화면입니다. **Negative 기본값** — 카탈로그 트리를 Negative scope로 필터링한 뷰입니다. 모든 Run에 항상 적용되는 기본 네거티브는 워크플로 JSON의 네거티브 노드에 내장되어 있어 이 화면에서 관리하지 않으며, 여기서는 그 위에 추가로 얹을 선택 용어만 관리합니다.

## 16. 워크플로 정의 관리

`워크플로 정의` 메뉴입니다. 좌측 사이드바에 등록된 워크플로 목록(활성/비활성 배지 포함)이 있고, 선택하면 오른쪽에 Workflow ID·Name·Mode·Input Images·Subgraphs·Workflow File·Param Config·Param Config Source·Metadata·Description·Registered At·Updated At이 표시됩니다. `Activate`/`Deactivate`로 사용 가능 여부를 전환합니다.

![워크플로 정의 상세 화면](v4-11-admin-workflow-definition.jpg)

`New Workflow` 버튼으로 등록 화면으로 이동해 Workflow JSON과 Param Config JSON(비우면 저장 시 자동 생성)을 업로드하고 Workflow ID·Description을 입력합니다. 활성화해야 사용자의 프롬프트 생성/Batch 화면 목록에 나타납니다.

## 17. Sandbox Pod

`Sandbox Pod` 메뉴입니다. 일상적인 영상 생성용 RunPod Serverless와는 분리된 전용 Pod로, 개발/디버깅 목적의 HTTP 서비스(ComfyUI 등)에 접근할 때 사용합니다.

![Sandbox Pod 화면](v4-10-admin-sandbox-pod.jpg)

Pod ID/이름은 Network Volume ID와 Template ID로 매 요청마다 재해결됩니다. `Deploy Sandbox Pod`/`Refresh Status`로 제어하며, Pod 목록에는 GPU 타입별 **RunPod 재고 등급 배지**(재고 충분/보통/부족/없음)가 함께 표시되어, 같은 GPU로 새 Pod를 만들 때 성공 가능성을 가늠할 수 있습니다(이 재고 등급은 최대 10분까지 지연될 수 있는 참고 정보이며, 해당 Pod 자체의 실시간 가용성과는 다릅니다).

`Start 실패 대응` 카드에는 다음 자동 정책이 표시됩니다.

- 선택 파드 기동 실패 시 다른 파드를 우선순위대로 자동 시작
- 새 파드 생성 시 같은 GPU의 정지 파드를 자동 삭제(Network Volume은 유지)
- 모든 파드 기동 실패 시 `RUNPOD_SANDBOX_GPU_FALLBACK_TYPE_IDS` 환경변수 순서대로 새 GPU 타입 시도

### FileBrowser로 파일 확인

1. Sandbox Pod 상태가 `READY`인지 확인합니다.
2. `HTTP Services`의 **FileBrowser · HTTP 8080** 링크를 새 탭으로 엽니다.
3. FileBrowser 화면에서 `/workspace`를 열어 Network Volume의 모델, 워크플로, 결과 파일 구조를 확인합니다.

Studio는 FileBrowser의 ID/비밀번호를 생성·저장·표시·변경하지 않습니다. 인증 설정은 RunPod Pod 또는 FileBrowser 자체에서 관리합니다.

### JupyterLab과 터미널 사용

1. Sandbox Pod가 `READY` 상태인지 확인합니다.
2. **JupyterLab · HTTP 8888** 링크를 엽니다(Pod 템플릿에 노출된 경우에만 보임).
3. JupyterLab 왼쪽 Launcher에서 **Terminal**을 선택합니다.

```bash
cd /workspace
pwd
ls -lah
```

### Network Volume 사용량 조회와 정리

Studio의 Sandbox Pod 화면에 보이는 Storage 값은 **할당 용량**입니다. 실제 사용량은 Pod 내부에서 다음 명령으로 조회합니다.

```bash
df -h /workspace
du -sh /workspace/* 2>/dev/null | sort -h
du -sh /workspace/models/* 2>/dev/null | sort -h
find /workspace -type f -size +5G -print
```

:::danger Network Volume 삭제는 되돌릴 수 없습니다
`rm -rf /workspace/models`처럼 상위 모델 디렉터리를 한 번에 삭제하는 명령은 사용하지 마세요. Network Volume은 Pod와 독립적으로 유지되므로, 잘못 삭제한 파일은 Pod를 다시 시작해도 복구되지 않습니다. 등록된 Workflow가 사용하는 checkpoint·VAE·LoRA·CLIP·UNet은 삭제 전 반드시 Metadata와 Workflow 모델 인벤토리로 참조 여부를 확인하세요.
:::

## 18. Runpod Worker 설정

Admin 사이드바 가장 아래쪽에 있는 **Runpod Worker 설정** 메뉴입니다(구 Task Policy). `사용자당 동시 활성 Task`와 `전체 동시 활성 Task` 한도를 설정합니다.

![Runpod Worker 설정 화면](v4-16-admin-runpod-worker.jpg)

1. 현재 정책 값을 확인합니다.
2. 개별 사용자의 동시 제출 수와 전체 서버리스 처리 여유를 함께 고려해 두 값을 입력합니다.
3. `Save Task Policy`를 누릅니다. 저장한 값은 **이후 제출부터** 적용됩니다.
4. `QUEUED`, `IN_QUEUE`, `IN_PROGRESS`, `RUNNING`만 한도에 포함됩니다.

:::warning 한도는 대기열을 만들지 않습니다
현재 정책을 초과한 제출은 자동 대기열에 쌓이지 않고 즉시 거절됩니다. 정책을 낮춰도 이미 실행 중인 Task를 강제로 취소하지는 않으며, 다음 제출부터 새 한도가 적용됩니다.
:::

## 19. Metadata(관리자)

ADMIN 영역에서도 [10. 사용자 매뉴얼 화면 · Metadata](#10-사용자-매뉴얼-화면--metadata)와 같은 Metadata 화면에 접근할 수 있습니다. `Rebuild Metadata` 버튼으로 선택한 워크플로의 메타데이터를 워크플로 JSON 기준으로 다시 생성합니다.

## 20. 감사 로그

`감사 로그` 메뉴입니다. **어드민 정보 수정 행위만** 기록합니다 — 역할 권한 변경, 사용자 생성/수정/비밀번호 초기화/비활성화, 프롬프트 카탈로그·지시문 수정, Sandbox Pod 시작/중지가 대상입니다. 로그인 시도와 개인 작업 이력 삭제는 기록하지 않습니다.

![감사 로그 화면](v4-17-admin-audit-log.jpg)

- 컬럼: 시각 / 행위자 / 작업(짧은 한글 라벨) / 대상 / 상세(JSON 보기).
- 상단 검색창으로 action(예: `role.permissions.update`)·targetType(예: `role`)을 입력해 필터링합니다.

## 21. 권한 코드 요약표

역할 & 권한 화면에서 다루는 권한 코드입니다(SUPER_ADMIN 화면에서 실제로 확인한 목록 기준).

| 권한 코드 | 대상 |
| --- | --- |
| `admin:*` | 전체 운영 및 시스템 설정 권한(와일드카드) |
| `users:read` / `users:write` | 사용자 조회 / 사용자 생성·수정·비밀번호 재설정·비활성화 |
| `roles:read` / `roles:write` | 역할·권한 조회 / 역할 권한 수정 |
| `workflows:read` / `workflows:write` / `workflows:activate` | 워크플로 조회 / 등록·수정 / 활성화·비활성화 |
| `prompt-catalog:read` / `prompt-catalog:write` | 프롬프트 카탈로그·지시문 조회 / 수정 |
| `prompts:build` / `prompts:reuse` | 프롬프트 생성(Grok) / 재사용 |
| `prompts:review` | 프롬프트 품질 평가 |
| `jobs:run` / `jobs:cancel` / `jobs:manage` | 영상 생성 실행 / 취소 / 전체 관리 |
| `history:read` / `history:delete` | 작업 이력 조회 / 삭제 |
| `metadata:read` / `metadata:rebuild` | 메타데이터 조회 / 재생성 |
| `system:read` | 시스템 상태 조회 |
| `manual:read` | 사용자 매뉴얼 조회 |
| `sandbox:read` / `sandbox:control` | Sandbox Pod 조회 / 시작·중지 제어 |
| `tasks:read` | 작업 이력(작업자별 실행) 조회 |
| `task-policy:read` / `task-policy:write` | Runpod Worker 설정 조회 / 수정 |

## 22. 운영 시 주의사항

:::danger 삭제는 소프트 삭제입니다
작업 이력에서 지운 작업은 목록·재사용 후보에서 즉시 빠지지만, 완전히 파기되지는 않습니다. 완전 삭제가 필요하면 별도로 요청하세요. Collection 관리의 컬렉션 삭제도 빈 컬렉션에서만 가능합니다.
:::

:::warning Runpod ComfyUI 요청부터 실제 과금·실행입니다
Grok 프롬프트 생성과 Batch 처리는 프롬프트·요청을 준비할 뿐 GPU 작업을 실행하지 않습니다. `선택 N건 RunPod 요청`을 눌러야 실제 RunPod Serverless 실행과 과금이 시작됩니다.
:::

:::warning Runpod Worker 설정 한도 초과는 즉시 거절입니다
대기열에 쌓이지 않고 바로 거절되므로, 작업 이력에서 진행 중 작업을 먼저 확인한 뒤 다시 제출하세요.
:::

:::info Negative 기본값과 추가 Negative는 다른 개념입니다
워크플로 JSON에 내장된 기본 네거티브는 화면에서 수정할 수 없고, 프롬프트 카탈로그 관리 화면에서는 그 위에 추가되는 선택 용어만 관리합니다.
:::

:::info 세션은 탭 종속입니다
같은 계정이라도 다른 탭/창의 세션은 공유되지 않습니다. 같은 탭에서 새로고침해도 로그인 상태는 유지되며, 로그아웃 또는 탭/브라우저 종료 시 정리됩니다.
:::

:::info 감사 로그는 어드민 정보 수정만 남습니다
로그인 이력이나 사용자의 자기 작업 삭제 이력은 감사 로그에서 조회되지 않습니다.
:::

## 23. 문제 해결

| 증상 | 확인 사항 |
| --- | --- |
| 로그인이 안 됨 | ID/Password 재확인, 계정이 INACTIVE 상태인지 관리자에게 문의 |
| 사이드바에 메뉴가 안 보임 | 해당 기능에 필요한 권한이 없을 수 있습니다 — [기능 리소스 매핑](#12-역할--권한--기능-리소스-매핑)에서 필요 권한 확인 |
| Grok 프롬프트 생성 요청이 시작되지 않음 | 워크플로 지시문을 선택했는지, 연결된 지시문이 있는지 확인하세요(관리자에게 [프롬프트 지시 관리](#14-프롬프트-지시-관리) 확인 요청) |
| 작업 제출이 거절됨 | Runpod Worker 설정의 사용자별 또는 전체 활성 Task 한도를 초과했을 수 있습니다. 작업 이력의 진행 작업을 확인하세요 |
| 새로고침 뒤 로그인 화면이 보임 | 최신 화면을 한 번 다시 로드한 뒤 로그인하세요. 이후 같은 탭 새로고침은 세션을 유지합니다 |
| User Manual 목차 클릭 후 다른 화면으로 이동 | 최신 화면으로 새로고침하세요. 목차는 문서 안에서만 이동해야 합니다 |
| 완료 작업에 영상이 없음 | 작업 이력에서 결과 상태와 RunPod Job ID를 확인하세요. RunPod가 완료됐더라도 서버 저장이 실패하면 실패로 정리될 수 있습니다 |
| Sandbox Pod가 EXITED 상태 | `Deploy Sandbox Pod`로 재배포하세요. Pod ID는 재배포 시마다 새로 해결됩니다 |
| Sandbox Pod GPU 재고 배지가 `재고 없음`인데도 실행 중 Pod가 있음 | 재고 배지는 같은 GPU로 **새로 생성**할 때의 참고 정보입니다. 이미 실행 중인 Pod의 가용성과는 무관합니다 |
