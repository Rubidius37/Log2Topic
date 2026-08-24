# Log2Topic

**A local-first Markdown research log organizer**

매일의 기록을 사용자가 정한 Heading과 분류 규칙에 따라 주제별 Markdown으로 재구성하는 로컬 우선 시스템입니다. 원본은 `Daily_Logs/`에 유지하고, 다시 찾아보기 쉬운 개인 지식 위키를 자동으로 만듭니다.

[English](README.md) · [빠른 시작](#처음-시작하기) · [사용자 안내](docs/USER_GUIDE.ko.md) · [분류 규칙](Classification_Rules.md) · [Notion 연동](docs/NOTION_INTEGRATION.ko.md)

## 처음 시작하기

현재 배포본은 **Windows 10/11 x64**용입니다. Python, Git, Notion 계정은 필요하지 않습니다. [Obsidian](https://obsidian.md/download)을 권장하지만 폴더 단위로 파일을 여는 다른 Markdown 편집기도 사용할 수 있습니다.

### 1. 프로젝트 폴더 준비

내려받은 프로젝트를 `문서\Log2Topic`처럼 파일을 수정할 수 있는 일반 폴더에 둡니다. 압축 파일 안이나 `Program Files`에서는 실행하지 마세요.

```text
Log2Topic/
├─ Log2Topic.exe
├─ Classification_Rules.md
├─ Daily_Logs/
├─ attachments/
├─ scripts/
└─ runtime/
```

`Daily_Logs/`와 `attachments/`가 없으면 첫 실행 때 만들어집니다. `Subject/`와 `Topic_Reviews/`는 첫 분류 뒤 생성됩니다.

### 2. Markdown 작업공간 열기

Obsidian에서 **폴더를 Vault로 열기**를 선택하고 `Log2Topic.exe`가 있는 최상위 폴더를 지정합니다. `Daily_Logs/`만 따로 열면 생성 문서의 상대 링크가 올바르게 연결되지 않습니다. 다른 편집기에서도 같은 최상위 폴더를 작업공간으로 여세요.

### 3. Log2Topic 실행

1. `Log2Topic.exe`를 더블클릭합니다.
2. 최초 설정에서 자동 작업은 `사용 안 함`으로 저장해도 됩니다.
3. 작업표시줄 알림 영역의 Log2Topic 아이콘을 찾습니다. 보이지 않으면 `^`를 눌러 숨겨진 아이콘을 확인합니다.

알림 영역에서 찾아야 할 **Log2Topic 트레이 아이콘**은 다음과 같습니다.

<img src="assets/log2topic.png" alt="Log2Topic 트레이 아이콘" width="64">

이 아이콘을 우클릭하면 다음과 같은 메뉴가 표시됩니다.

<img src="assets/log2topic-tray-menu-ko.png" alt="Log2Topic 트레이 메뉴" width="338">

메뉴와 설정 화면은 기본적으로 Windows 표시 언어를 따릅니다. `자동 실행 및 동기화 설정...`의 언어 항목에서 `System default`, `English`, `한국어` 중 하나를 선택할 수 있으며, 변경한 언어는 Log2Topic을 다시 실행하면 적용됩니다.

프로젝트에 전용 Python 실행 환경이 포함되어 있어 Python 설치나 PATH 설정은 필요하지 않습니다. 실행 파일은 아직 디지털 서명되지 않았으므로 Windows 경고가 나오면 파일 이름과 내려받은 위치를 확인한 뒤 실행 여부를 결정하세요.

### 4. 첫 분류 규칙과 일지 작성

`Classification_Rules.md`의 표에 주제 경로를 작성합니다. 표의 여섯 열과 순서는 유지하고, Level 1부터 Level 5를 일지의 `#`부터 `#####` Heading과 맞춥니다. Heading이 분류명과 같으면 매칭 키워드는 비워도 됩니다.

`Daily_Logs/`에 `.md` 파일을 만들고 다음처럼 작성합니다.

```markdown
# Projects
## Sample Project
### Testing

첫 번째 테스트 기록입니다.
```

처음에는 기본 제공 예제를 그대로 사용해도 됩니다. 분류표의 빈 셀 상속, 키워드와 경계 규칙은 [Classification_Rules.md](Classification_Rules.md)에 설명되어 있습니다.

### 5. 첫 결과 확인

1. 트레이의 Log2Topic 아이콘을 우클릭합니다.
2. `로컬 문서 갱신`을 선택합니다.
3. 완료 후 `Subject/`와 `Topic_Reviews/`를 확인합니다.
4. 생성 문서의 `Date/Log` 링크로 원본 일지가 열리는지 확인합니다.

여기까지 성공하면 기본 기능을 사용할 준비가 끝난 것입니다. Obsidian 첨부파일 위치, 검토 대시보드와 자동 실행 설정은 [사용자 안내](docs/USER_GUIDE.ko.md)에서 이어서 확인할 수 있습니다.

## 핵심 특징

- **로컬 우선**: 외부 전송 없이 내 컴퓨터에서 분류와 검토
- **단일 원본**: `Daily_Logs/`만 작성하고 주제 문서와 리뷰는 자동 생성
- **계층형 분류**: Markdown Heading을 Level 1부터 Level 5까지의 주제 경로로 변환
- **규칙 기반 처리**: AI 분류 없이 동일한 원본과 규칙에 재현 가능한 결과
- **Source ID 추적**: 제목이나 주제 경로가 바뀌어도 원본과 파생 문서 관계 유지
- **표준 Markdown**: Obsidian, VS Code와 일반 Markdown 편집기에서 사용 가능
- **선택적 연동**: 로컬 기능은 독립적으로 유지하고 Notion과 Cloudinary는 필요할 때만 연결

## 동작 흐름

실선은 기본 로컬 동작이고, 점선은 사용자가 설정한 외부 연동입니다.

```mermaid
flowchart TD
    A["일지 작성<br/>Daily_Logs/*.md"]
    B["주제 규칙 정의<br/>Classification_Rules.md"]
    C["로컬 문서 갱신"]
    D["Heading과 규칙 매칭<br/>Source ID로 추적"]
    E["주제 문서<br/>Subject/"]
    F["리뷰 문서<br/>Topic_Reviews/"]
    G["분류 검토 대시보드"]
    N["외부 서비스 동기화"]

    A --> C
    B --> C
    C --> D
    D --> E
    D --> F
    D --> G
    E -.-> N
    F -.-> N
    N -.-> J["Notion / Cloudinary"]
```

생성된 `Subject/`와 `Topic_Reviews/`는 직접 고치지 않습니다. 원본 일지나 분류 규칙을 수정한 뒤 다시 갱신하면 Source ID를 기준으로 기존 결과가 정리됩니다.

## 평소 사용 방법

1. `Daily_Logs/`에 Heading과 내용을 작성합니다.
2. 트레이에서 `로컬 문서 갱신`을 실행합니다.
3. 미분류 항목이 있으면 `분류 검토 대시보드 열기`에서 경로를 선택합니다.

### AI 서비스의 Markdown 답변을 넣을 때

AI 답변의 `# 분석 결과` 같은 Heading은 분류 경계로 오인될 수 있습니다. 실제 분류 Heading 아래에서 답변 전체를 인용문 또는 Obsidian 콜아웃으로 넣고, 빈 줄을 포함한 모든 줄 앞에 `>`를 붙이세요.

```markdown
### Testing

> [!quote] AI 서비스 답변
> # 분석 결과
>
> ## 가능한 원인
> 원인에 대한 설명입니다.
```

콜아웃 안의 Heading은 분류에 사용되지 않습니다. 단순히 코드 블록으로 감싸는 것만으로는 충분하지 않습니다. 전체 예제와 Heading을 쓰지 않는 프롬프트는 [사용자 안내](docs/USER_GUIDE.ko.md#ai-서비스의-markdown-답변-붙여넣기)를 참고하세요.

## 선택 사항: 외부 서비스

로컬 분류만 사용할 때는 외부 서비스 설정이 필요하지 않습니다.

### Notion

Notion 데이터베이스로 일지, 주제 문서와 리뷰를 동기화할 수 있습니다. 내부 연결, `Sync Key`, Cloudinary 이미지와 오류 복구 설정은 [Notion 연동 안내](docs/NOTION_INTEGRATION.ko.md)를 순서대로 따라가세요. 하나의 Notion 데이터베이스에는 하나의 기준 Markdown 작업공간만 연결하는 것을 권장합니다.

## 지원 환경

- 공식 지원: Windows 10/11 x64
- 권장 편집기: Obsidian 데스크톱
- 사용 가능: 폴더와 표준 Markdown 상대 링크를 지원하는 편집기
- 현재 미지원: Windows ARM, macOS, Linux 배포본
- 인터넷 없이 사용 가능: 로컬 분류와 검토 대시보드

## 문제가 생겼을 때

- 트레이 아이콘이 없으면 숨겨진 아이콘과 `scripts/.runtime/app_error.log`를 확인합니다.
- 일지를 찾지 못하면 `Daily_Logs/` 아래의 파일 확장자가 `.md`인지 확인합니다.
- `[BUSY]`가 나오면 진행 중인 분류나 동기화가 끝난 뒤 다시 실행합니다.
- Notion 오류는 `scripts/reports/notion_sync_report.md`에서 확인합니다.

더 많은 점검 순서는 [사용자 안내의 문제 해결](docs/USER_GUIDE.ko.md#문제-해결)을 참고하세요.

## 피드백과 문제 제보

버그와 기능 제안은 이 저장소의 GitHub `Issues` 탭에 남겨주세요. 공개 Issue에는 **연구자료와 인증정보**를 첨부하지 말고, 실제 내용 대신 재현 가능한 가상 예제를 사용하세요. 자세한 작성 기준은 [사용자 안내](docs/USER_GUIDE.ko.md#피드백과-문제-제보)에 있습니다.

## 문서

- [사용자 안내](docs/USER_GUIDE.ko.md): Obsidian 설정, 일상 사용, 검토, 자동 실행과 문제 해결
- [분류 규칙](Classification_Rules.md): Level 계층, 상속형 표, 키워드와 경계 규칙
- [Notion 연동](docs/NOTION_INTEGRATION.ko.md): 데이터베이스 연결, 이미지와 동기화 복구
- [시스템 구조](docs/SYSTEM_REFERENCE.ko.md): Source ID, 내부 상태와 유지보수 기준

## 라이선스

이 프로젝트는 [MIT License](LICENSE)로 배포됩니다.
