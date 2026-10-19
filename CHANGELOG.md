# Changelog

## 1.1.2

### 한국어 (Korean)
- **기존 Obsidian Vault 직접 연결 (`작업공간 / Vault` 폴더 찾아보기)**:
  - 설정 창(`자동 실행 및 동기화 설정...`)에 `작업공간 / Vault` 경로 입력란(플레이스홀더: `비워 두면 기본 Workspace/ 폴더 사용`)과 `[찾아보기...]` 버튼을 추가하여, 기존 Obsidian Vault 파일을 옮기지 않고 그대로 연결해 사용할 수 있습니다 (`LOG2TOPIC_WORKSPACE` 환경변수도 지원).
- **초보자용 1~2단계 및 용도별 시작 분류 규칙 템플릿 3종**:
  - 설정 창에서 `단순 과제형 1~2단계 (초보자 권장)`, `연구·실험 노트형 (3단계)`, `소프트웨어 개발·QA형 (3~4단계)` 템플릿을 선택해 즉시 시작할 수 있으며, 교체 전 기존 `Classification_Rules.md`는 `scripts/source_id_backups/rule_templates/`에 자동 백업됩니다.
- **Linux / macOS 하이브리드 시스템 트레이 및 데스크톱 GUI (`scripts/log2topic_gui.py`)**:
  - `./Log2Topic.sh tray` 및 `./Log2Topic.sh gui` 명령을 추가하여 `pystray`+`Pillow` 설치 시 네이티브 시스템 트레이/메뉴 막대 아이콘으로, 미설치 시 표준 `tkinter` 기반 데스크톱 컨트롤 및 설정 창으로 동작합니다 (`notify-send` / `osascript` 완료 알림 포함).
- **대용량 코퍼스(1,000개 일지 / 3,500개 장문 구간) 성능 최적화 및 벤치마크 도구 추가**:
  - 이미지 경로 확인 전 `os.path.isfile()` 선검사, 불필요한 `os.path.realpath()` 및 링크 정규식 호출 제거, 변경 없는 `Subject/`·`Topic_Reviews/` 파일의 불필요한 재쓰기(`os.fsync`/`os.replace`) 생략으로 재컴파일 속도를 약 2.5배 개선하고 Obsidian 파일 수정 시각(`mtime`)을 보존했습니다 (`scripts/benchmark_large_corpus.py` 추가).
- **복사·붙여넣기 ID 충돌 안전성 및 안정성 보강**:
  - 복사 후 원본만 수정하여 `source_anchor`와 `source_fingerprint`가 서로 다른 구간을 가리킬 때는 추측해 ID를 넘기지 않고 중복 오류로 안전하게 중단하도록 수정했습니다.
  - 대시보드 `윗 구간에 합치기` 실행 시 구간 내부에 하위 제목(`###` 등)이 포함되어 있어도 연쇄 병합 마커를 부착해 다음 갱신 시 분리되지 않도록 보강했습니다.
  - Windows 트레이 앱의 `SynchronizationContext` 캡처 시점을 컨트롤 생성 이후로 수정하여 백그라운드 작업 완료 알림의 UI 스레드 마샬링을 보장했습니다.

### English
- **Use Existing Obsidian Vaults in Place (`Workspace / Vault` Folder Picker)**:
  - Added a `Workspace / Vault` path field (with `Default: Workspace/ (if left empty)` cue banner) and `Browse...` button in the Settings dialog, plus `LOG2TOPIC_WORKSPACE` environment variable support.
- **Starter Classification Rule Templates (3 Presets)**:
  - Added selectable rule templates (`Simple 1-2 level`, `Research & experiment notes`, and `Software & QA engineering`) with automatic backups of existing `Classification_Rules.md` under `scripts/source_id_backups/rule_templates/`.
- **Linux & macOS Hybrid System Tray & Desktop GUI (`scripts/log2topic_gui.py`)**:
  - Added `./Log2Topic.sh tray` and `./Log2Topic.sh gui` supporting native system tray / menu bar icons (via optional `pystray` + `Pillow`), zero-dependency `tkinter` controller & settings dialogs, and desktop completion notifications (`notify-send` / `osascript`).
- **Large-Corpus Performance Optimization & Benchmark (`scripts/benchmark_large_corpus.py`)**:
  - Eliminated redundant `os.path.realpath()` calls and skipped rewriting unchanged `Subject/` and `Topic_Reviews/` files, achieving ~2.5x faster warm compiles (~26.7s for 1,000 files / 3,500 heavy sections / 12.04 MB) while preserving file `mtime`s.
- **Safety & Reliability Fixes**:
  - Aborts safely on ambiguous copy-paste duplicates when `source_anchor` and `source_fingerprint` point to different sections; preserves nested subheadings during dashboard `Merge into previous`; ensures WinForms `SynchronizationContext` is captured after control creation.

## 1.1.1

- Preserved permanent Source IDs across heading renames and section moves when `organizer_metadata.json` is present; copy-paste Source ID regeneration now activates only when the same ID appears in two or more distinct source sections.
- Restored strict H1/H2/H3 classification boundaries so unrecognized top-level headings are always surfaced for review instead of silently absorbed, and added a one-click "Merge into previous" (`<!-- research-notes-merge-above -->`) action in the review dashboard.
- Restored the default keyword scan window to the opening 800 characters (`LOG2TOPIC_KEYWORD_SCAN_CHARS`) to avoid false-positive keyword matches in long notes.
- Added completion notifications with `needs_review` counts after local updates in the Windows tray app, repository display and per-version skip handling in update prompts, rollback error logging in `update_windows_app.ps1`, and confirmation prompts in `log2topic.py rebuild`.

## 1.1.0

- Classification review dashboard now supports adding new classification rules directly to `Classification_Rules.md` (with one-click prefill from the current section's heading path), resetting manual `Category:` overrides, and detecting conflicts when headings are edited after manual classification.
- Added Notion "Sync original logs only" (`--all-daily`) to both the manual tray/CLI menu and scheduled automation modes (`ExternalOriginals`), alongside optional source backup batch retention limits (off by default, configurable count).
- Expanded general Markdown editor compatibility: CommonMark link/image titles, parenthesized and angle-bracketed paths, document-relative image resolution, preserved image alt text in `Subject/` documents, unified date parsing (`YYYY-MM-DD`, `YYYY.MM.DD`, `YYYYMMDD`, `YY.MM.DD`, `YYMMDD`), and standard blockquote (`>`) rendering in Notion sync.
- Added Linux support (`Log2Topic.sh`, `setup_workspace.sh`, `scripts/*.sh`, `scripts/configure_automation.py` for `systemd --user` / `cron` and XDG autostart, and `Log2Topic-linux-v1.1.0.tar.gz` release archive), bilingual English/Korean README and scripts, and updated project license to GNU General Public License v3.0 (GPL-3.0).

## 1.0.17

- Notion sync supports bounded data URL images through validated temporary attachments and the existing Cloudinary content cache. Unsupported inline images leave a visible omission notice while the rest of the document syncs.
- SVG uploads now accept a restricted static subset and reject scripts, external references, HTML content, document types, and excessive complexity. Inline image errors and manifests do not expose the original data URL.
- Inline images remain protected during Cloudinary cleanup; image examples in fenced and inline code are excluded from upload and image manifests.

## 1.0.16

- Normal local classification now consolidates multiple Source ID comments when heading edits merge them into one source unit. It preserves the ID below the classification heading, or the first ID in the unit, and backs up the original before saving.
- Body text, nested headings, quoted markers, fenced code examples, and existing empty-parent ID relocation are preserved. Headings and ID comments inside fenced code do not act as classification boundaries or permanent IDs. IDs shared by separate units or files remain errors.
- Dry runs show retained and removed IDs. Classification reports include consolidated-unit and removed-marker counts; obsolete generated documents are cleaned up during the normal update.
- Generated image and document links consistently resolve Windows short path names before computing relative paths.
