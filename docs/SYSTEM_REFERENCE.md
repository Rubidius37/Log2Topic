# 시스템 구조와 유지보수

이 문서는 Log2Topic의 로컬 분류 구조와 유지보수 기준을 설명합니다. 처음 사용하는 사람은 먼저 루트의 `README.md`를 읽으면 됩니다.

[기본 사용 가이드로 돌아가기](../README.md)

## 로컬 처리 흐름

일반 사용자의 기본 실행 파일은 `Log2Topic.exe`입니다. 전용 Windows 앱이 트레이를 소유하고 실제 작업은 `scripts/` 아래의 내부 BAT와 프로젝트 전용 Python에 위임합니다.

1. `Workspace/Daily_Logs/`의 Markdown 원본을 읽습니다.
2. `Workspace/Classification_Rules.md`에서 계층형 분류 규칙을 불러옵니다.
3. 원본 구간별 Source ID를 확인하거나 새로 발급합니다.
4. `Subject/`에 주제별 문서를 생성합니다.
5. `Topic_Reviews/`에 하위 리뷰와 Level 1~2 종합 리뷰를 생성합니다.
6. 분류 결과와 검토 대상을 `scripts/organizer_metadata.json`에 저장합니다.

Notion 설정은 이 과정에서 읽지 않습니다. 트레이의 `로컬 문서 갱신`은 Notion과 Cloudinary 모듈을 호출하지 않습니다.

## 주요 파일과 폴더

- `Log2Topic.exe`: 일반 사용자를 위한 Windows 트레이 앱
- `Log2Topic.bat`: EXE가 없는 개발 환경에서 PowerShell 트레이를 여는 대체 실행 파일
- `Workspace/Daily_Logs/`: 사용자가 작성하는 원본 일지
- `Workspace/Classification_Rules.md`: Level 1~5 분류 구조와 선택적 키워드
- `Workspace/Subject/`: 자동 생성되는 주제별 문서
- `Workspace/Topic_Reviews/`: 자동 생성되는 리뷰와 종합 리뷰
- `Workspace/attachments/`: Obsidian 첨부 이미지
- `assets/log2topic.ico`: 트레이와 Windows 시작 바로가기에 사용하는 프로그램 아이콘
- `scripts/hierarchical_classifier.py`: 생산용 로컬 분류기
- `scripts/classification_review_dashboard.py`: 분류 검토 대시보드 서버
- `scripts/classification_review_ui/`: 대시보드 화면
- `app/Log2Topic.cs`: 전용 Windows 트레이 앱 소스
- `scripts/log2topic_tray.ps1`: EXE가 없는 개발 환경을 위한 대체 트레이
- `scripts/resolve_python.bat`: 프로젝트 전용 Python을 우선 선택하는 공통 실행기
- `scripts/configure_automation.ps1`: 로그인 시작과 예약 작업 등록
- `scripts/organizer_metadata.json`: Source ID와 현재 분류 결과를 연결하는 로컬 상태
- `scripts/source_id_backups/`: 원본에 Source ID나 수동 분류를 기록하기 전 백업

`Workspace/Subject/`, `Workspace/Topic_Reviews/`, metadata는 다시 생성할 수 있는 결과물입니다. 장기 보관해야 할 원문은 `Workspace/Daily_Logs/`입니다.

Subject 문서를 생성할 때 원본 일지의 이미지 링크는 원본 문서 위치를 기준으로 먼저 해석한 뒤, 생성된 Subject 문서 위치를 기준으로 상대경로를 다시 계산합니다. 따라서 원본이 Obsidian Wikilink(`![[...]]`)인지 Markdown 이미지 링크(`![](...)`)인지와 관계없이 생성 문서에서 `Workspace/attachments/` 이미지를 열 수 있습니다.

## 계층형 분류 규칙

분류 단계는 다음과 같습니다.

```text
Level 1 > Level 2 > Level 3 > Level 4 > Level 5
```

`Workspace/Classification_Rules.md`는 상속형 표입니다. 비어 있는 셀은 같은 열의 바로 위 값을 이어받으므로 하위 경로를 추가할 때 상위 이름을 반복하지 않아도 됩니다.

### Heading 매칭

- H1은 자동 분류의 대분류 경계를 정합니다.
- H2~H5는 현재 부모 아래에 같은 이름의 분류가 있을 때 경로를 확장합니다.
- H1을 인식하지 못한 새 구간은 키워드만으로 대분류를 추측하지 않고 `Unclassified/Missing Level 1`에 둡니다.
- 분류 단계보다 깊은 Heading은 문서 구조로 유지되지만 분류 경로에는 추가되지 않습니다.

```markdown
# Projects
## Sample Project
### Testing
```

위 이름은 설명을 위한 가상 예시입니다. 해당 구간은 `Projects > Sample Project > Testing`으로 분류됩니다.

### 키워드와 형제 경계

키워드는 Heading만으로 부족한 경우의 보조 수단입니다. 제목과 본문 도입부에서 검사하며 같은 H1 안에서 세분화하거나 중복 경로를 추가할 때 사용합니다.

`Sample Project`와 `Archive Project`처럼 서로 다른 Level 2가 별도 대상을 뜻하면 명시적으로 매칭된 대상이 경계가 됩니다. 다른 형제의 일반 키워드가 발견되어도 그 경계를 넘어 하위 경로를 만들지 않습니다. 프로젝트명처럼 고유한 식별자는 Level 2 키워드에, `Testing`이나 `Meeting` 같은 일반 표현은 가능한 한 Level 3 이하에 두는 편이 안전합니다.

`Methods`처럼 한 내용이 여러 주제에 걸릴 수 있는 대분류에서는 일치하는 여러 경로를 함께 생성할 수 있습니다.

### 수동 분류

원본 구간에 다음 형식으로 경로를 지정할 수 있습니다.

```markdown
Category: Projects/Sample Project/Testing/Functional Test/Test Case A
```

여러 경로는 쉼표로 구분합니다.

```markdown
Category: Methods/Data Analysis/Visualization, Projects/Sample Project/Reporting
```

직접 입력하기보다 트레이의 `분류 검토 대시보드 열기`를 사용하는 편이 오타를 줄일 수 있습니다.

## Source ID

생산 분류기는 원본 일지의 각 관리 구간에 영구 Source ID를 부여합니다.

```html
<!-- research-notes-source-id: 9f2a6e1c0b7d4a33 -->
```

이 주석은 Obsidian 읽기 화면과 생성 문서 본문에는 표시되지 않습니다. 분류명이나 Heading 위치가 바뀌어도 같은 원본 구간을 추적하고, 이전 주제 파일을 정리한 뒤 새 경로에 연결하기 위해 사용합니다.

이전 버전에서 생성한 Source ID 주석은 로컬 분류를 처음 실행할 때 현재 형식으로 자동 정규화되며, ID 값은 바뀌지 않습니다.

새 ID를 기록하기 전 원본은 `scripts/source_id_backups/automatic/{실행시각}/`에 보관됩니다. 모든 변경안을 준비한 뒤 원자적으로 교체하며, 스캔 중 원본이 바뀌거나 Source ID가 중복되면 생성 작업을 중단합니다.

검증만 할 때는 다음 명령을 사용합니다.

```powershell
.\scripts\run_local.bat --dry-run
```

특수한 읽기 전용 환경에서는 `--no-persist-source-ids`를 사용할 수 있지만, Heading이 바뀔 때 추적 안정성이 낮아지므로 일반 운영에는 권장하지 않습니다.

## 생성 문서와 리뷰

주제별 문서에는 원본 일지 링크, Source ID, 원본 Heading 정보가 들어갑니다. `Date/Log`는 문서 위치를 기준으로 한 표준 Markdown 상대 링크이므로 Obsidian, GitHub, VS Code와 일반 Markdown 뷰어에서 원본을 열 수 있습니다.

`Topic_Reviews/`에는 다음 내용이 생성됩니다.

- 해당 주제의 기록 스냅샷
- 최근 업데이트
- 진행 흐름
- 확인할 이슈 후보
- 관련 원본과 하위 문서 링크

Level 1 종합 리뷰는 최근 20건, Level 2 종합 리뷰는 최근 50건의 상세 흐름을 표시합니다. Level 3~5 리뷰는 해당 경로의 전체 기록을 표시합니다. 같은 원본 구간이 여러 하위 주제에 연결되어도 종합 리뷰에서는 Source ID 기준으로 한 번만 집계합니다.

## 분류 검토 대시보드

트레이가 호출하는 `scripts/run_classification_review_dashboard.bat`은 `scripts/organizer_metadata.json`의 모든 `needs_review` 항목을 표시합니다.

- Level 1이 없는 구간
- 하위 분류를 정하지 못하고 상위 경로에서 멈춘 구간
- 규칙에 없는 수동 분류 경로
- 원본과 metadata가 어긋난 구간

하위 분류를 선택하면 화면에서 상위 경로도 자동 체크됩니다. 저장 요청에는 가장 구체적인 최종 경로만 포함하므로 `Category:`에 상위와 하위가 중복되지 않습니다. 상위 체크를 해제하면 해당 가지의 하위 선택도 함께 해제됩니다.

대시보드는 생성된 `Subject/` 파일이 아니라 Source ID에 해당하는 원본 구간의 `Category:` 줄을 추가하거나 변경합니다. 원본의 헤딩과 본문은 그대로 유지되며, 저장 후 `Subject/`와 `Topic_Reviews/`가 다시 생성됩니다. 화면을 연 뒤 원본이 바뀌면 fingerprint 충돌로 저장을 중단하므로 새로 고침 후 다시 선택해야 합니다. 수정 전 원본은 `scripts/source_id_backups/classification_review/`에 보관됩니다.

브라우저 탭마다 localhost 서버와 지속 연결을 유지합니다. 마지막 대시보드 탭을 닫아 연결이 끊기면 3초의 유예 시간 후 서버가 종료됩니다. 새로고침하거나 다른 탭이 연결되면 예약된 종료를 취소합니다. 분류 저장과 문서 재생성이 진행 중이면 해당 작업이 끝날 때까지 종료를 미룹니다. 브라우저나 운영체제가 비정상 종료되어 연결 해제가 감지되지 않은 예외 상황에서는 서버 콘솔의 `Ctrl+C`로 종료할 수 있습니다.

트레이는 대시보드 BAT를 `--nopause`와 숨김 창으로 실행합니다. 이 모드의 표준 출력과 오류는 `scripts/reports/classification_review_dashboard.log`에 누적됩니다. 내부 BAT를 직접 실행하면 콘솔을 표시하므로 즉시 오류를 확인하거나 `Ctrl+C`로 서버를 종료할 수 있습니다.

## 동시 실행 잠금

분류, Notion 동기화, Cloudinary cleanup은 같은 vault에서 동시에 하나만 실행됩니다. 잠금 정보는 `scripts/.runtime/automation.lock`에 기록됩니다.

다른 작업이 실행 중이면 두 번째 작업은 `[BUSY]`와 종료 코드 `3`으로 끝나며 파일이나 원격 페이지를 수정하지 않습니다. 운영체제 수준 잠금은 프로세스 종료 시 자동 해제되므로 lock 파일이 남아 있다는 이유만으로 직접 삭제할 필요는 없습니다.

분류 대시보드는 화면이 열려 있는 전체 시간이 아니라 저장과 재생성 구간에서만 잠금을 사용합니다.

## 원자적 상태 저장

다음 JSON 상태는 같은 폴더의 임시 파일에 전체 내용을 먼저 기록하고 `flush`, `fsync`, `os.replace` 순서로 교체합니다.

- `scripts/organizer_metadata*.json`
- `scripts/notion_sync_state*.json`
- `scripts/cloudinary_cache.json`

파일이 존재하지만 JSON이 손상된 경우 빈 상태로 자동 초기화하지 않습니다. 기존 파일을 보존하고 작업을 중단합니다. 손상된 상태 파일을 바로 삭제하지 말고 먼저 다른 위치에 복사해 두어야 합니다.

## 트레이와 예약 작업

`Log2Topic.exe`는 같은 작업공간에서 중복 실행되지 않으며 모든 일반 기능을 우클릭 메뉴로 제공합니다. 프로세스와 트레이 아이콘은 전용 앱이 소유하므로 작업 관리자에는 `Log2Topic`으로 표시됩니다. EXE가 없는 개발 환경에서는 `Log2Topic.bat`이 기존 PowerShell 트레이를 대신 실행합니다.

`자동 실행 및 동기화 설정`은 `scripts/configure_automation.ps1`을 통해 로그인 시작 폴더의 바로가기와 Windows 작업 스케줄러의 `Log2Topic_Scheduled_Update` 작업을 관리합니다. 실행 모드는 로컬 전용과 외부 서비스 포함으로 나뉘며, 외부 서비스 목록에서 현재 Notion을 선택할 수 있습니다. 모드, 서비스, 시간과 요일은 `scripts/.runtime/tray_settings.json`에 저장됩니다. 기존 `Notion` 모드 설정은 `External + Notion`으로 자동 이관되고, `Log2Topic_Local_Update`, `Log2Topic_Notion_Sync`, `ResearchNotes_*` 작업은 새 설정을 저장할 때 정리됩니다.

## 배포 구조

배포용 Git 저장소는 README와 상세 문서, `Log2Topic.exe`, `app/Log2Topic.cs`와 재빌드 스크립트, 공식 CPython 임베디드 ZIP, 범용 분류 규칙 예시, 실행 배치, Python 스크립트, 분류 검토 UI와 테스트를 추적합니다.

현재 공식 지원 환경은 Windows 10/11 x64입니다. 시스템 Python 설치와 PATH 설정은 필요하지 않습니다. 최초 실행 시 EXE가 `runtime/python-3.13.15-embed-amd64.zip`을 `runtime/python/`에 안전하게 풀고 `_pth`에 프로젝트 모듈 경로를 추가합니다. ZIP과 버전이 바뀌면 런타임을 원자적으로 교체하며, BAT는 전용 Python을 먼저 찾고 개발 환경에서만 시스템 Python 3.10 이상을 대체 경로로 사용합니다.

개인 일지, 첨부파일, `.env`, 상태 JSON, 실행 리포트와 생성 문서는 `.gitignore`로 제외합니다. 공개 기본 규칙인 `Workspace/Classification_Rules.md`는 개인 개발 작업공간에서 복사하지 않고 배포 저장소에서 별도로 추적하고 수동 관리합니다. 따라서 배포 사용자는 개인 개발 저장소나 그 이력에 접근할 필요가 없습니다.

## Git 관리

이 저장소는 개인 일지보다 자동화 코드와 분류 규칙의 이력을 관리합니다. 다음 내용은 `.gitignore`로 제외됩니다.

- `Workspace/Daily_Logs/`, `Workspace/Subject/`, `Workspace/Topic_Reviews/`, `Workspace/attachments/`
- `scripts/.env`
- organizer metadata, Notion sync state, Cloudinary cache
- 실행 리포트와 백업
- Obsidian 및 로컬 에이전트 설정

## 유지보수 기준

안정 운영 대상으로 고정한 로컬 기능은 다음과 같습니다.

- H1 경계와 H2~H5 Heading 기반 5단계 분류
- 선택적 키워드와 다중 분류
- 영구 Source ID와 이전 생성물 정리
- 분류 검토 대시보드
- 하위 리뷰와 Level 1~2 종합 리뷰
- 프로세스 잠금과 원자적 상태 저장
- Git 기반 Windows 앱과 내장 Python 배포

Notion과 Cloudinary는 로컬 기본 동작과 분리된 선택적 연동으로 유지합니다. 새로운 외부 서비스나 자동 수정 기능은 실제 필요와 실패 사례를 확인한 뒤 추가합니다.

## 개발 검증

```powershell
.\scripts\build_windows_app.ps1
.\Log2Topic.exe --prepare-runtime
.\runtime\python\python.exe -m unittest discover -s tests
.\runtime\python\python.exe -m compileall -q scripts tests
.\runtime\python\python.exe .\scripts\hierarchical_classifier.py --validate-rules
.\runtime\python\python.exe .\scripts\hierarchical_classifier.py --production --output-dir Subject --review-dir Topic_Reviews --metadata-file organizer_metadata.json --dry-run
```

마지막 명령도 실행 파일은 프로젝트 루트에 있지만, 실제 원본과 생성 문서는 `Workspace/`에서 찾습니다.
