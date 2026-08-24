# Log2Topic 사용자 안내

이 문서는 Log2Topic의 편집기 설정과 평소 사용 방법을 자세히 설명합니다. 처음 실행하는 중이라면 먼저 [README의 처음 시작하기](../README.ko.md#처음-시작하기)를 따라 첫 분류를 완료하세요.

[English](USER_GUIDE.md) · [README로 돌아가기](../README.ko.md) · [분류 규칙](../Classification_Rules.md) · [Notion 연동](NOTION_INTEGRATION.ko.md)

## 작업공간 준비

Log2Topic은 프로젝트 최상위 폴더를 하나의 Markdown 작업공간으로 사용합니다.

```text
Log2Topic/
├─ Log2Topic.exe
├─ Classification_Rules.md
├─ Daily_Logs/
├─ attachments/
├─ Subject/             # 첫 분류 뒤 생성
├─ Topic_Reviews/       # 첫 분류 뒤 생성
├─ scripts/
└─ runtime/
```

- 원본 일지는 `Daily_Logs/` 아래에 `.md` 파일로 저장합니다.
- `Subject/`와 `Topic_Reviews/`는 자동 생성물이므로 직접 수정하지 않습니다.
- `attachments/`는 이미지와 첨부파일을 모으기 위한 권장 폴더이며 필수는 아닙니다.
- 프로젝트를 압축 파일 안이나 `Program Files`처럼 쓰기 권한이 제한된 위치에서 실행하지 않습니다.

현재 공식 배포본은 Windows 10/11 x64용입니다. 프로젝트에 전용 Python 실행 환경이 포함되어 있으므로 Python을 설치하거나 PATH를 설정할 필요가 없습니다.

## Markdown 편집기 설정

### Obsidian

Obsidian에서는 **새 Vault 만들기**가 아니라 **폴더를 Vault로 열기**를 선택하고, `Log2Topic.exe`와 `Classification_Rules.md`가 있는 최상위 폴더를 지정합니다. `Daily_Logs/`만 따로 Vault로 열면 생성 문서의 상대 링크가 올바르게 연결되지 않습니다.

별도 Obsidian 플러그인은 필요하지 않습니다. 다음 설정은 파일 정리와 다른 Markdown 도구와의 호환성을 위해 권장합니다.

- **첨부파일 기본 위치**: `attachments`
- **Daily Notes 저장 위치**: Daily Notes 기능을 쓴다면 `Daily_Logs`
- **새 링크 형식**: 다른 도구와 함께 쓴다면 **현재 파일 기준 상대 경로**
- **위키링크 사용**: 어느 쪽이어도 분류는 동작하지만 범용 호환성을 원하면 끄는 편이 좋음

`attachments/`가 아닌 위치를 사용해도 문서에 적힌 이미지 상대경로가 올바르면 처리할 수 있습니다. Notion 이미지 동기화에서는 문서의 상대경로, `attachments/`, 작업공간 안의 같은 파일명 순서로 이미지를 찾습니다.

### 다른 Markdown 도구

- Log2Topic 최상위 폴더 전체를 작업공간으로 엽니다.
- 일지는 `Daily_Logs/` 아래에 `.md` 확장자로 저장합니다.
- Heading의 `#` 개수와 분류 규칙의 Level을 맞춥니다.
- 생성 링크는 표준 Markdown 상대 링크입니다.
- 백링크 목록과 그래프는 Markdown 표준 기능이 아니므로 편집기에 따라 제공되지 않을 수 있습니다.

## Log2Topic 실행

1. `Log2Topic.exe`를 더블클릭합니다.
2. 최초 실행 설정 창에서 자동 작업과 Windows 로그인 시 실행 여부를 선택합니다. 둘 다 나중에 바꿀 수 있습니다.
3. 작업표시줄 알림 영역에서 Log2Topic 아이콘을 찾습니다. 보이지 않으면 `^`를 눌러 숨겨진 아이콘을 확인합니다.
4. 아이콘을 우클릭해 로컬 갱신, 분류 검토, 외부 서비스와 자동 실행 설정을 사용합니다.

최초 실행은 전용 Python 환경을 준비하느라 조금 더 걸릴 수 있습니다. 현재 실행 파일은 디지털 서명되지 않았습니다. Windows가 **PC 보호** 창을 표시하면 공식 배포 위치에서 받은 파일인지와 파일 이름이 `Log2Topic.exe`인지 확인한 뒤 실행 여부를 결정하세요.

## 분류 규칙 작성

분류 규칙은 최상위 폴더의 `Classification_Rules.md` 표에 작성합니다. 표의 여섯 열과 열 순서는 바꾸지 않습니다.

| 분류 규칙 | 일지 Heading |
| :--- | :--- |
| Level 1 | `#` |
| Level 2 | `##` |
| Level 3 | `###` |
| Level 4 | `####` |
| Level 5 | `#####` |

Heading이 분류명과 정확히 일치하면 매칭 키워드는 없어도 됩니다. 같은 부모 아래에 경로를 추가할 때 상위 셀을 비우면 바로 위 행의 값을 이어받습니다. 키워드 문법과 Level 간 경계는 [Classification_Rules.md](../Classification_Rules.md)의 표 아래 설명을 참고하세요.

## 평소 사용 방법

### 일지 작성

`Daily_Logs/`에 Markdown 파일을 만들고 분류 규칙과 같은 이름을 Heading으로 작성합니다.

```markdown
# Projects
## Sample Project
### Testing

오늘 검토한 내용을 작성합니다.
```

파일명은 자유롭게 정할 수 있습니다. Windows 메모장을 사용했다면 파일 이름이 `.md.txt`로 저장되지 않았는지 확인하세요.

여러 주제에 동시에 연결해야 하는 내용은 분류 검토 대시보드에서 복수 경로를 선택할 수 있습니다. 직접 작성할 때는 원본 구간에 `Category:`로 전체 경로를 명시할 수도 있습니다.

### AI 서비스의 Markdown 답변 붙여넣기

AI 서비스의 답변에는 `# 분석 결과`, `## 원인` 같은 Markdown Heading이 포함될 수 있습니다. 그대로 붙여넣으면 분류기가 답변 안의 Heading을 새로운 분류 경계로 읽을 수 있습니다.

가장 안전한 방법은 **실제 분류 Heading 아래에 답변 전체를 인용문 또는 Obsidian 콜아웃으로 넣는 것**입니다. 빈 줄과 코드 블록을 포함한 모든 줄 앞에 `>`를 붙이세요.

```markdown
# Projects
## Sample Project
### Testing

> [!quote] AI 서비스 답변
> # 분석 결과
>
> ## 가능한 원인
> 첫 번째 원인에 대한 설명입니다.
>
> ## 확인 방법
> 측정 순서에 대한 설명입니다.
```

위 예제의 실제 분류 경로는 `Projects > Sample Project > Testing`입니다. 콜아웃 안의 Heading은 화면 구성에만 쓰이고 분류 Heading으로 인식되지 않습니다. Notion 동기화를 사용하면 제목과 하위 내용을 포함한 Notion 콜아웃으로 변환됩니다.

콜아웃을 사용하지 않으려면 AI에게 처음부터 Heading을 쓰지 않도록 요청할 수 있습니다.

```text
Markdown으로 답하되 H1~H6 Heading(#, ##, ### 등)은 사용하지 말고,
각 구획의 제목은 **굵은 글씨**로 작성해줘.
```

> [!warning] 코드 블록만으로는 분류를 막을 수 없습니다
> 현재 분류기는 fenced code block 안에서도 줄 맨 앞의 `#`를 Heading으로 읽을 수 있습니다. 코드 형태를 유지해야 한다면 코드 블록을 포함한 모든 줄을 콜아웃 안에 넣으세요.

### 로컬 문서 갱신

트레이 아이콘을 우클릭하고 `로컬 문서 갱신`을 선택합니다. 실행이 끝나면 다음 폴더가 갱신됩니다.

- `Subject/`: 주제별로 모은 이력 문서
- `Topic_Reviews/`: 주제별 진행 흐름과 검토 항목

두 폴더를 직접 수정해도 다음 갱신 때 덮어써질 수 있습니다. 수정할 내용은 원본 일지나 `Classification_Rules.md`에 반영하세요.

### 애매한 분류 확인

트레이에서 `분류 검토 대시보드 열기`를 선택하면 미분류 항목과 상위 단계에 멈춘 항목을 확인할 수 있습니다.

하위 분류를 선택하면 상위 경로도 자동으로 선택됩니다. 적용하면 원본의 해당 구간에 `Category:` 수동 분류 정보가 추가되거나 변경되고, 기존 Heading과 본문은 유지됩니다. 변경 전 원본은 `scripts/source_id_backups/classification_review/`에 백업됩니다.

대시보드는 기본 브라우저에서 열리지만 이 PC의 로컬 서버(`http://127.0.0.1:8000`)가 화면을 제공합니다. 일지 내용을 외부 서비스로 전송하지 않으며, 대시보드 탭을 모두 닫으면 서버도 잠시 뒤 종료됩니다. 실행 기록은 `scripts/reports/classification_review_dashboard.log`에서 확인할 수 있습니다.

## 자동 실행

트레이의 `자동 실행 및 동기화 설정`에서 다음 항목을 선택할 수 있습니다.

- Windows 로그인 시 트레이 자동 실행
- 자동 작업 사용 여부
- 로컬 갱신 또는 로컬 갱신 후 외부 서비스 동기화
- 실행 시간과 요일
- 예약 시간에 PC가 꺼져 있었을 때 다음 기회에 실행할지 여부
- 화면 언어: Windows 표시 언어 자동 감지, English 또는 한국어

정기 작업은 Windows 작업 스케줄러에 등록되므로 트레이를 종료해도 설정한 시간에 실행됩니다.
화면 언어를 변경한 경우 Log2Topic을 종료한 뒤 다시 실행해야 트레이 메뉴와 설정 화면에 적용됩니다. 분류 검토 대시보드도 같은 언어 설정을 사용합니다.

## 선택 기능: Notion

로컬 기능만 사용할 때는 Notion이나 Cloudinary를 설정할 필요가 없습니다. 연결하려면 [Notion 연동 안내](NOTION_INTEGRATION.ko.md)를 처음부터 순서대로 진행하세요.

하나의 Notion 데이터베이스에는 하나의 기준 Markdown 작업공간만 연결하는 것을 권장합니다. 서로 다른 문서 집합을 가진 여러 PC가 같은 데이터베이스에 전체 동기화를 실행하면 다른 작업공간의 페이지를 로컬에 없는 문서로 판단할 수 있습니다.

## 자주 사용하는 파일

| 파일 | 용도 |
| :--- | :--- |
| `Log2Topic.exe` | 트레이 앱 실행과 일반 기능 접근 |
| `Classification_Rules.md` | 주제 트리와 보조 키워드 관리 |
| `Daily_Logs/` | 사용자가 작성하는 원본 일지 |
| `Subject/` | 자동 생성되는 주제별 이력 |
| `Topic_Reviews/` | 자동 생성되는 주제별 리뷰 |

평소에는 `Log2Topic.exe`, `Classification_Rules.md`와 `Daily_Logs/`만 알아도 충분합니다.

## 문제 해결

### 트레이 아이콘이 나타나지 않음

- 작업표시줄의 숨겨진 아이콘을 확인합니다.
- `scripts/.runtime/app_error.log`를 확인합니다.
- 전용 Python 환경 문제는 `runtime/PYTHON_RUNTIME.md`를 확인합니다.

### 일지가 분류되지 않음

- 일지가 `Daily_Logs/` 아래에 있는지 확인합니다.
- 파일 확장자가 `.md`인지 확인합니다.
- Heading의 `#` 뒤에 공백이 있는지 확인합니다.
- Heading 이름과 `Classification_Rules.md`의 경로가 맞는지 확인합니다.
- 인식 가능한 Level 1 Heading이 없는 구간은 미분류로 보존됩니다.

### 작업이 실행되지 않음

- `[BUSY]` 메시지는 다른 분류나 동기화가 실행 중이라는 뜻입니다. 기존 작업이 끝난 뒤 다시 실행합니다.
- 대시보드에서 원본 변경 경고가 나오면 새로 고침한 뒤 다시 적용합니다.
- 로컬 분류 보고서와 로그는 `scripts/reports/`에서 확인합니다.

### Notion 동기화 오류

- `scripts/reports/notion_sync_report.md`를 확인합니다.
- `scripts/.env`의 토큰과 데이터베이스 ID를 확인합니다.
- Notion 데이터베이스에 내부 연결이 추가되었는지 확인합니다.
- 자세한 복구 절차는 [Notion 연동 안내](NOTION_INTEGRATION.ko.md)를 참고합니다.

외부 서비스 동기화가 실패해도 로컬 원본과 생성 문서는 그대로 사용할 수 있습니다.

## 피드백과 문제 제보

버그, 사용 중 막힌 부분과 기능 제안은 GitHub `Issues` 탭에 남겨주세요.

- **버그 제보**: 실행되지 않거나 예상과 다르게 동작하는 문제
- **기능 제안**: 새로운 기능, 사용성 또는 문서 개선 의견

버그 제보에는 Windows 버전, 사용한 Markdown 도구, 재현 순서, 예상 결과와 실제 결과를 적어주세요. 같은 문제가 이미 등록되어 있는지 먼저 검색하면 중복 확인이 쉬워집니다.

공개 Issue에는 연구자료와 인증정보를 첨부하지 마세요. 특히 다음 내용을 제거하거나 가상 데이터로 바꿔야 합니다.

- `Daily_Logs/`, `Classification_Rules.md`, `attachments/`의 실제 연구 내용
- `scripts/.env`의 Notion 및 Cloudinary 인증정보
- `scripts/notion_sync_state.json`과 보고서의 페이지 ID, 경로와 문서 제목

문제를 보여주는 최소 예제가 필요하면 실제 자료 대신 가상의 분류명, 문서명과 내용을 사용하세요.
