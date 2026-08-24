# Notion 연동과 오류 복구

Notion 동기화는 선택 기능입니다. 로컬 분류와 리뷰는 Notion 설정 없이 트레이의 `로컬 문서 갱신`만으로 사용할 수 있습니다.

[English](NOTION_INTEGRATION.md) · [기본 사용 가이드로 돌아가기](../README.ko.md)

## 준비 사항

1. Notion integration을 만듭니다.
2. 사용할 데이터베이스를 integration에 연결합니다.
3. `scripts/.env.example`을 `scripts/.env`로 복사합니다.
4. 다음 값을 입력합니다.

```text
NOTION_TOKEN=...
NOTION_DATABASE_ID=...
```

## 데이터베이스 속성

다음 속성은 필수입니다.

| 이름 | 형식 | 용도 |
| :--- | :--- | :--- |
| `Sync Key` | `rich_text` | 로컬 문서와 Notion 페이지의 영구 연결 |

다음 속성은 선택 사항입니다.

| 이름 | 형식 | 용도 |
| :--- | :--- | :--- |
| `Source ID` | `rich_text` | 주제별 원본 구간 식별 |
| `Source Heading` | `rich_text` | 원본 Heading 표시 |

`로컬 상대경로` 속성은 사용하지 않습니다. 로컬 경로가 바뀌어도 페이지를 유지할 수 있도록 Sync Key가 페이지 식별을 담당합니다.

## 실행 파일

전체 동기화:

트레이 아이콘을 우클릭하고 `외부 서비스 > Notion > 전체 동기화`를 선택합니다.

이 파일은 로컬 분류를 먼저 실행한 뒤 Daily, Subject, Topic Review를 Notion에 동기화합니다.

최근 Daily note만 빠르게 동기화:

트레이 아이콘을 우클릭하고 `외부 서비스 > Notion > 최근 일지 동기화`를 선택합니다.

기본값은 최근 수정된 일지 1개입니다.

```powershell
.\scripts\run_notion_daily_sync.bat --recent-daily 2
.\scripts\run_notion_daily_sync.bat Daily_Logs\2026-06\26.06.26.md
```

Daily-only 모드는 `Subject/`, `Topic_Reviews/`와 orphan cleanup을 건너뜁니다.

## 동기화 순서

전체 동기화는 링크가 올바르게 연결되도록 다음 순서를 사용합니다.

1. `Daily_Logs/` 원본을 먼저 업로드합니다.
2. 원본 일지의 Notion URL을 수집합니다.
3. `Subject/` 문서를 업로드하며 `Date/Log` 링크를 Notion URL로 바꿉니다.
4. 하위 `Topic_Reviews/`를 업로드합니다.
5. 상위 종합 리뷰를 업로드하며 하위 리뷰 링크를 Notion URL로 바꿉니다.
6. 더 이상 로컬에 없는 페이지의 정리 계획을 계산합니다.
7. 안전 조건을 통과한 orphan 또는 중복 페이지를 archive합니다.

## Sync Key와 페이지 갱신

Sync Key는 대략 다음 형식을 사용합니다.

```text
daily::{daily identity}
subject::{Source ID}::{category path}
timeline::{category path}
```

문서 제목이나 로컬 폴더가 바뀌어도 Sync Key가 같으면 기존 Page ID 안에서 속성과 블록을 갱신합니다. URL이 유지되므로 다른 페이지에서 연결한 링크도 유지됩니다.

동기화 결과는 `scripts/notion_sync_state.json`에 저장됩니다.

- Page ID와 URL
- 마지막 성공 내용 해시
- 참조 이미지 해시
- 미해결 관리 링크
- 렌더링 버전

내용과 이미지가 바뀌지 않은 문서는 다음 실행에서 건너뜁니다. 렌더링 방식이 바뀌면 내부 버전이 올라가 필요한 문서만 다시 업로드합니다.

## 링크 변환

생성 문서의 표준 Markdown 상대 링크는 동기화 과정에서 관리 대상 문서의 Notion URL로 변환합니다. 이전 버전 문서와 원본 일지에 남아 있는 Obsidian `[[...]]` 위키링크도 같은 방식으로 계속 지원합니다.

대상 페이지 업로드가 실패했지만 이전 URL이 sync state에 있으면 마지막 정상 URL을 계속 사용합니다. 한 번도 성공하지 않아 URL이 없는 링크는 표시 텍스트로 남기고 다음 동기화에서 다시 해결합니다.

미해결 링크가 남으면 전체 실행은 부분 실패로 끝나며 orphan cleanup을 수행하지 않습니다.

## Markdown 변환

Notion 렌더러는 다음 형식을 변환합니다.

- Heading과 일반 문단
- 글머리 목록과 번호 목록의 탭 또는 공백 들여쓰기
- Obsidian 콜아웃의 제목과 전체 본문
- 단독 `---` 수평선
- `$$...$$` 블록 수식
- 문장 안의 `$...$` 인라인 수식
- 표준 Markdown 링크와 Obsidian 위키링크
- Obsidian 이미지 링크

Notion API의 블록 수 제한을 넘는 긴 콜아웃이나 목록은 부모 블록을 먼저 만든 뒤 자식을 최대 100개씩 나누어 추가합니다. 중첩 구조는 가능한 한 유지합니다.

## 이미지와 Cloudinary

Obsidian 이미지 형식은 다음과 같이 사용할 수 있습니다.

```markdown
![[image.png]]
![[a.png]]![[b.png]]![[c.png]]
![[a.png]]설명![[b.png]]
```

이미지는 다음 순서로 찾습니다.

1. Vault 기준 상대경로
2. `attachments/`
3. vault 전체에서 같은 파일명 검색

Cloudinary를 사용하려면 `.env`에 다음 값을 추가합니다.

```text
CLOUDINARY_CLOUD_NAME=...
CLOUDINARY_UPLOAD_PRESET=...
```

분류 검토 대시보드는 외부 연결 없이 `http://127.0.0.1:8000`에서만 열립니다. 이 localhost 서버는 Notion 이미지 전송과 관계가 없습니다.

로컬 이미지를 포함한 문서를 Notion에 동기화하려면 Cloudinary 설정이 필요합니다. 자동 터널이나 localhost 이미지 fallback은 사용하지 않습니다. Cloudinary가 없으면 텍스트 전용 문서와 외부 `https://` 이미지 문서는 동기화할 수 있지만, 로컬 이미지를 포함한 문서는 깨진 링크로 성공 처리하지 않고 실패로 기록합니다. 기존 Notion 페이지와 마지막 성공 해시는 유지됩니다.

Cloudinary가 설정된 상태에서도 이미지 파일을 찾지 못하거나 업로드가 실패하면 해당 문서를 실패로 기록합니다.

Cloudinary에는 검증을 통과한 Vault 내부 이미지 파일만 전송합니다.

- 허용 형식: PNG, JPEG, GIF, WebP, BMP, TIFF, SVG
- 절대경로, `../` 경로 이탈과 URL 인코딩된 경로 이탈은 차단
- symlink나 junction의 실제 위치가 Vault 밖이면 차단
- `.git`, `.obsidian`, `scripts`, `.codex` 등 보호 디렉터리의 파일은 차단
- 확장자와 파일 시그니처가 일치하지 않는 파일은 차단

따라서 `![[scripts/.env]]`나 Vault 밖 파일을 이미지처럼 참조해도 Cloudinary 요청은 실행되지 않습니다. 안전하지 않은 이미지 참조가 발견되면 해당 문서의 동기화만 실패하며 기존 Notion 페이지와 마지막 성공 상태는 유지됩니다. 오류 원인은 `scripts/notion_sync_report.md`에서 확인할 수 있습니다.

### 이미지 캐시

`scripts/cloudinary_cache.json`은 이미지 내용 해시와 Cloudinary URL을 저장합니다.

- 같은 이미지는 다시 분류하거나 동기화해도 재업로드하지 않습니다.
- 파일명이 같아도 이미지 바이트가 바뀌면 새 이미지로 감지합니다.
- 여러 문서가 같은 이미지를 참조하면 업로드 결과를 공유합니다.
- Notion 페이지 반영 전 이미지는 `pending`, 반영 후에는 `committed`로 표시합니다.

### 자동 정리

전체 동기화의 기본 auto cleanup은 Notion 반영에 실패한 뒤 남은 오래된 `pending` 업로드만 지연 삭제합니다. `committed` 이미지는 자동 삭제하지 않고 report에만 표시합니다.

기본 조건:

```text
CLOUDINARY_CLEANUP_AFTER_SYNC=auto
CLOUDINARY_PENDING_GRACE_DAYS=14
CLOUDINARY_PENDING_MIN_FULL_SYNCS=3
CLOUDINARY_PENDING_MAX_DELETE=10
CLOUDINARY_PENDING_MAX_DELETE_RATIO=0.05
```

실제 삭제에는 다음 인증정보가 필요합니다.

```text
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...
```

동기화가 부분 실패했거나 로컬 이미지 참조를 완전히 해석하지 못한 실행에서는 미사용 횟수를 올리거나 삭제하지 않습니다.

모든 미사용 후보를 수동으로 검토하려면 다음 파일을 실행합니다.

```powershell
.\scripts\run_cloudinary_cleanup.bat
```

`committed` 이미지를 포함해 실제 삭제하려면 report를 확인한 뒤 명시적으로 실행합니다.

```powershell
.\scripts\run_cloudinary_cleanup.bat --delete
```

삭제된 이미지는 archive된 과거 Notion 페이지에서도 보이지 않을 수 있습니다.

## 재시도와 부분 실패

조회와 멱등성이 보장되는 요청은 `429`, `5xx`, 타임아웃에서 자동 재시도합니다.

페이지 생성과 블록 추가는 중복 페이지나 블록을 막기 위해 명시적인 `429`만 자동 재시도합니다. `5xx`나 응답 유실처럼 실제 반영 여부가 불확실한 쓰기는 같은 요청을 즉시 반복하지 않습니다.

일부 문서가 실패해도 나머지 문서는 가능한 범위까지 계속 처리합니다. 다음 중 하나라도 남으면 종료 코드 `1`의 `PARTIAL FAILURE`로 끝납니다.

- 페이지 업로드 실패
- 관리 링크 미해결
- 로컬 상태 checkpoint 저장 실패
- orphan cleanup 안전 검사 실패
- cleanup 작업 실패

부분 실패에서는 orphan archive를 건너뛰고 Cloudinary 삭제도 수행하지 않습니다. 원인을 해결한 뒤 같은 배치를 다시 실행하면 성공 해시가 없는 대상을 다시 처리합니다.

## 기존 페이지 갱신 실패 복구

기존 페이지의 새 본문을 추가하다 실패하면 응답으로 ID를 확인한 새 블록은 가능한 범위에서 롤백하고 이전 본문을 유지합니다. 응답이 유실되어 결과를 확정할 수 없으면 성공 해시를 갱신하지 않습니다.

새 본문 추가 후 이전 블록 삭제 단계에서 실패하면 새 본문과 일부 이전 본문이 일시적으로 함께 보일 수 있습니다. 다음 실행에서는 현재 블록 전체를 기준으로 완전한 본문을 다시 구성하고 이전 블록을 정리합니다.

정리 작업 없이 복구 동기화를 먼저 실행하려면 다음 옵션을 사용합니다.

```powershell
.\scripts\run_notion_sync.bat --skip-orphan-cleanup
```

## orphan과 중복 페이지 보호

로컬 분류기는 `Daily_Logs/`에 Markdown 파일이 하나도 없으면 기존 `Subject/`, `Topic_Reviews/`, metadata를 수정하지 않습니다.

Notion orphan cleanup도 archive 전에 계획을 만듭니다. 다음 상황에서는 정리를 차단합니다.

- 활성 로컬 Sync Key가 0개
- archive 후보가 10개 이상이면서 기존 페이지의 20% 이상
- 같은 Sync Key의 정본 페이지를 증명할 수 없는 충돌
- 업로드 또는 관리 링크가 부분 실패한 실행

의도적인 대규모 재분류이고 cleanup 계획을 검토했다면 다음 옵션으로 수량 제한만 한 번 해제할 수 있습니다.

```powershell
.\scripts\run_notion_sync.bat --allow-large-cleanup
```

이 옵션도 정본 충돌이나 업로드 실패에 따른 차단은 해제하지 않습니다.

동일 Sync Key 페이지가 여러 개면 sync state에 저장된 Page ID를 먼저 정본으로 유지합니다. state가 정본을 가리키지 않고 후보가 여러 개라면 어느 페이지도 자동 archive하지 않습니다.

## 리포트

문제가 생기면 다음 파일을 먼저 확인합니다.

- `scripts/reports/notion_sync_report.md`: 단계별 성공과 실패, Sync Key, 오류, 미해결 링크
- `scripts/reports/notion_orphan_cleanup_plan.md`: 정본 페이지, 중복과 orphan 후보, 차단 이유
- `scripts/reports/cloudinary_cleanup_report.md`: 사용 중 이미지와 미사용 후보

권장 복구 순서:

1. `notion_sync_report.md`에서 첫 실패 원인을 확인합니다.
2. 인증정보, 데이터베이스 속성, 네트워크 또는 로컬 파일 문제를 수정합니다.
3. `scripts/run_notion_sync.bat --skip-orphan-cleanup`으로 다시 실행합니다.
4. 실패와 미해결 링크가 0인지 확인합니다.
5. 트레이의 `외부 서비스 > Notion > 전체 동기화`를 한 번 더 실행해 필요한 cleanup을 수행합니다.

## 오류별 확인 사항

- `401`, `403`: `NOTION_TOKEN`, 데이터베이스 ID와 integration 연결 권한 확인
- `400` 속성 오류: `Sync Key`가 `rich_text`인지 확인
- `429`: 잠시 기다린 뒤 재실행하고 API 사용 제한 확인
- `5xx`, 타임아웃: Notion 서비스와 네트워크 확인 후 재실행
- `Local image file was not found`: 첨부파일 위치와 실제 파일명 확인
- Cloudinary 업로드 실패: cloud name, upload preset과 이미지 파일 확인
- `[BUSY]`: 다른 로컬 분류나 동기화가 끝난 뒤 재실행
- 상태 JSON 손상: 파일을 삭제하지 말고 먼저 복사해 보관한 뒤 복구 여부 결정

## 코드 구조

Notion 코드는 로컬 분류기와 분리되어 있습니다.

- `scripts/sync_to_notion.py`: CLI, 설정과 전체 실행 순서
- `scripts/notion_api.py`: HTTP 요청, 재시도, 페이지와 블록 작업
- `scripts/notion_render.py`: Markdown과 Notion 블록 변환
- `scripts/notion_state.py`: Sync Key 상태, 해시, checkpoint와 report
- `scripts/sync_cleanup.py`: 정본 선택, orphan 보호와 Cloudinary 후처리
- `scripts/sync_contracts.py`: 공용 속성명과 Sync Key 정규화
- `scripts/cloudinary_cleanup.py`: 이미지 사용 여부와 삭제 수명주기

API 변경은 `notion_api.py`, 표시 형식은 `notion_render.py`, 상태 형식은 `notion_state.py`, 정리 정책은 `sync_cleanup.py`에서 다룹니다.
