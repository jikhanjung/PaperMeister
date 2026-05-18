# 20260518_035 — Preferences 탭 위젯화, biblio auto/manual 분리 토글, 폴더 process 시 failed 재시도

## 컨텍스트

세션 사이에 사용자가 서버 재시동 시점에 보낸 PDF들이 `failed`로 떨어진 케이스를 만남. 폴더 우클릭 → Process Folder 해도 failed는 retry가 안 됨. 이어서 LLM 사용량 제어를 위해 biblio extraction을 disable 가능하게 해달라는 요청 + Preferences가 평평하게 길어진 게 거슬리니 탭으로 재구성. 마지막에 auto/manual 분리해 LLM provider 라디오 enable 정책을 OR 로직으로.

## 변경 사항

### 1. 폴더 Process Folder에 failed 포함

`desktop/windows/main_window.py::_process_folder`:

기존 쿼리:
```python
where(... PaperFile.status == 'pending' ...)
```

→ pending + failed 둘 다 수집:
```python
.where(... PaperFile.status.in_(['pending', 'failed']) ...)
pending_ids = [r.id for r in rows if r.status == 'pending']
failed_ids  = [r.id for r in rows if r.status == 'failed']
```

다이얼로그 메시지 케이스별 분기:
- 둘 다 있음: `"Process 12 pending + retry 5 failed PDF(s)?"`
- failed만: `"Retry 5 failed PDF(s)?"`
- pending만: `"Process 12 pending PDF(s)?"` (기존)

Yes 누르면 failed → pending로 일괄 reset (`PaperFile.update(status='pending').where(...)`) + PaperList의 pill도 즉시 `err → wait` 갱신. 단건 우클릭 Retry와 동일한 패턴이라 일관됨.

### 2. Auto-biblio extract 토글

`auto_biblio_extract` pref (기본 True). OCR 완료 직후 자동 큐잉 게이팅.

`desktop/windows/main_window.py::_on_file_processed`:
```python
if (
    status == 'processed'
    and pf.hash
    and get_pref('auto_biblio_extract', True)
):
    self._auto_biblio_queue.append((pf.paper_id, pf.id))
    self._drain_biblio_queue()
```

OFF면 pill이 `OCR`에서 정지 (`done`/`rev` 전환 없음).

### 3. Preferences → `QTabWidget`

`papermeister/ui/preferences_dialog.py` 전면 재작성. 평면 `QVBoxLayout` + 굵은 section 라벨 → 네 탭으로 분리:

- **OCR** — 백엔드 3종 라디오 + Endpoint ID + API Key + URL
- **Biblio** — auto/manual 체크박스 + LLM provider 라디오
- **Zotero** — User ID + API Key + write-back / upload-JSON 체크박스 + Test Connection
- **About** — PaperMeister 헤더 + Client ID (read-only) + 짧은 설명

탭 위젯에 `objectName='PrefsTabs'` 부여 → QSS 스코핑.

### 4. 다크 테마 QSS의 탭 스타일 스코핑 확장

`desktop/theme/qss.py`의 `#SourceTabs`/`#DetailTabs` 규칙(5개 — `::pane`, `QTabBar`, `QTabBar::tab`, `:hover`, `:selected`)에 `#PrefsTabs`를 추가.

증상: PreferencesDialog 첫 띄움 시 탭 라벨이 흰 바탕 흰 글자로 안 보임. 다크 테마 QSS가 두 specific objectName만 스코핑하고 있었음. PrefsTabs도 같은 룩(muted/primary 색 + accent blue 2px 밑줄)으로 합류.

### 5. Biblio 탭 — auto/manual 분리, OR 로직으로 라디오 enable

처음 안은 "체크박스 OFF면 라디오 disable" 하나만 가는 거였는데, 그러면 수동 우클릭 Extract Biblio가 작동할 때도 모델 선택을 못 함. 두 케이스(auto / manual)를 의미상 분리:

```
[ ✓ ] Auto-extract biblio after OCR completes
[ ✓ ] Enable manual biblio extraction (right-click → Extract Biblio)
( ) Claude Sonnet                                ← 둘 중 하나라도 ON이면 활성
( ) Qwen3-14B
```

| auto | manual | 라디오 | 자동 파이프라인 | 우클릭 |
|---|---|---|---|---|
| ON | ON | enabled | 작동 | 작동 |
| ON | OFF | enabled | 작동 | **메뉴 회색** |
| OFF | ON | enabled | 멈춤 (OCR pill에서 정지) | 작동 |
| OFF | OFF | **disabled** | 멈춤 | **메뉴 회색** |

새 pref `manual_biblio_extract` (bool, 기본 True). 라디오 enable 판정은 `_refresh_biblio_radio_state()` 헬퍼에서 `auto OR manual` 계산.

### 6. 컨텍스트 메뉴 Extract Biblio 게이팅

`desktop/views/paper_list.py::contextMenuEvent`의 `processed` 분기:

```python
extract_act = menu.addAction('Extract Biblio', ...)
if not manual_biblio_enabled:
    extract_act.setEnabled(False)
    extract_act.setToolTip(
        'Disabled: turn on "Enable manual biblio extraction" in Preferences → Biblio'
    )
```

action 객체에 직접 setEnabled. 사용자가 메뉴 열면 회색 항목 + 툴팁으로 "켜는 방법" 안내.

## Pref 신설

| key | type | default | 효과 |
|---|---|---|---|
| `auto_biblio_extract` | bool | True | OCR 완료 → 자동 biblio 큐잉 |
| `manual_biblio_extract` | bool | True | 우클릭 → Extract Biblio 메뉴 활성 |

둘 다 True 디폴트라 기존 사용자에게 동작 변화 없음.

## 파일

```
papermeister/ui/preferences_dialog.py  — QTabWidget 재작성 + manual checkbox + _refresh_biblio_radio_state
desktop/views/paper_list.py            — 컨텍스트 메뉴 Extract Biblio 게이팅
desktop/windows/main_window.py         — _on_file_processed gating, _process_folder failed retry
desktop/theme/qss.py                   — #PrefsTabs 스코프 추가 (5개 규칙)
```

## 부가 메모

폴더 retry는 단건 retry와 동일 패턴: status를 `'pending'`으로 reset해서 시작점을 명확하게 만든 다음 ProcessWindow에 넘김. ProcessWorker 자체는 status를 체크하지 않고 file_ids만 가지고 처리하므로 reset이 강제 사항은 아님 — 다만 처리 도중 pill이 `err`로 남아있다가 갑자기 `wait`/`OCR`로 점프하면 UX가 깨져서 명시적으로 reset.

탭 라벨 가시성 이슈는 dialog가 application-wide QSS에 의존하는 구조라서 발생. PreferencesDialog는 `papermeister/ui/` (frozen) 쪽이지만 desktop 앱이 띄울 때 stylesheet가 dialog에도 cascade. 이 cascade가 specific objectName 스코핑에 가려서 발생한 케이스. 다른 dialog가 추가될 때마다 비슷한 문제 생길 수 있으니 새 dialog는 objectName 부여 + qss.py에 한 줄씩 합류 패턴 유지.
