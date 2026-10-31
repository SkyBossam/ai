# 파이 통합 실행 및 아이쿠 연결

## 현재 설치된 파이

- 접속: `ssh pi@172.20.10.2`
- 설치 폴더: `/home/pi/sky-eye-deploy-20261101/sky-eye-pi-armv7`
- 바로가기: `/home/pi/sky-eye` (위 폴더를 가리키는 심볼릭 링크)
- Pi 4 / Bullseye / ARMv7 32비트 / Python 3.9. 64비트 OS용 패키지가 아니다.
- USB 카메라 `/dev/video0`, USB GH300 마이크 `plughw:CARD=GH300,DEV=0`.

```bash
bash ~/sky-eye/start-all.sh          # 카메라 기본 5클래스 + 울음/추천 + 통합 출력
bash ~/sky-eye/stop-all.sh           # 카메라·마이크 중지, 출력기는 unavailable 기록
bash ~/sky-eye/watch.sh              # 카메라 상태
bash ~/sky-eye/cry-watch.sh          # 울음 점수·입력 레벨
bash ~/sky-eye/cry-cause-demo.sh     # 가상 피드백 예시, 실제 프로필 변경 없음
systemctl --user status sky-eye sky-eye-cry sky-eye-export --no-pager
```

`start-all.sh objects`는 베개·장난감이 추가된 실험용 7클래스 모델을 선택한다. 기본 5클래스와 동시에 실행하지 않는다. 7클래스는 장난감 성능이 충분히 검증되지 않았으므로 기본값으로 삼지 않았다.

PC PowerShell에서 터널을 열고 창을 유지한다:

```powershell
ssh -L 8765:127.0.0.1:8765 pi@172.20.10.2
```

브라우저: <http://127.0.0.1:8765/>. 감지 박스, 울음 점수, 돌봄 추천, 종료된 울음의 피드백 버튼, 별도 시뮬레이션 예시를 제공한다. 영상·피드백 API는 파이의 루프백에서만 수신한다.

## 아이쿠 전송 프로그램이 읽을 고정 경로

| 용도 | 경로 |
|---|---|
| 카메라·울음·추천 통합 현재 상태 | `/home/pi/sky-eye/output/status.json` |
| 통합 이벤트 스트림 (한 줄에 JSON 하나) | `/home/pi/sky-eye/output/events.jsonl` |
| 원본 카메라 상태·이벤트 | `/home/pi/sky-eye/logs/YYYYMMDD-HHMMSS/{status.json,events.jsonl}` |
| 원본 울음 상태·이벤트 | `/home/pi/sky-eye/logs/cry/{status.json,events.jsonl}` |
| 개인화 프로필 (기기 내부용) | `/home/pi/sky-eye/state/cry-personal/profile.json` |

전송기는 통합 두 파일만 읽으면 된다. `sky-eye-export.service`가 0.5초마다 상태를 갱신하며 상태 파일은 임시 파일 작성 후 교체하므로 완성된 JSON을 읽는다. 이벤트는 append 전용이다. 마지막 줄이 개행으로 끝나지 않으면 다음 갱신을 기다린다.

`status.json` 형식:

```json
{
  "schema_version": "sky-eye.status.v1",
  "wall_time_unix": 1793475395.9,
  "status": "normal",
  "reason": "",
  "video": {
    "available": true,
    "age_s": 0.1,
    "source": "logs/20261101-043618/status.json",
    "data": {
      "posture": {"posture": "supine", "airway": "airway_visible"},
      "posture_state": "normal",
      "risk_elapsed_s": {"prone": 0, "face_covered": 0},
      "geometry_valid": false,
      "fall": {"state": "unavailable"},
      "processing_fps": 4.0
    }
  },
  "audio": {"available": true, "age_s": 0.5, "source": "logs/cry/status.json", "data": {}},
  "personalization": {
    "experimental": true,
    "simulation": false,
    "state": "insufficient_history",
    "n_feedback": 0,
    "required_feedback": 10,
    "recommendations": []
  }
}
```

위 값은 형식 설명을 위한 예시다. 실제 `data`에는 추가 필드가 포함된다.

| 앱 항목 | JSON 참조 위치 |
|---|---|
| 바로/옆/엎드림 | `video.data.posture.posture`: `supine / side / prone / null` |
| 코·입 보임/가림 | `video.data.posture.airway`: `airway_visible / airway_covered / null` |
| 자세·얼굴 위험 | 루트 `status`: `normal / caution / risk / unavailable` |
| 가장자리 위험 | `video.data.fall`, 단 `video.available && video.data.geometry_valid`일 때만 해석 |
| 울음 후보 | `audio.data.cry_detected`, 아기 울음 점수 `audio.data.baby_cry_score` |
| 돌봄 추천 | `personalization.recommendations`: `{action,label,score}` 배열 |
| 추천 표시 가능 여부 | `personalization.state == "ready"` 및 비어 있지 않은 추천 배열 |
| 실제 개인화 답변 수 | `personalization.n_feedback` |

카메라 입력이 3초 넘게 오래되거나 중지되면 루트 `status=unavailable`, `video.available=false`이다. 울음 입력은 4초 기준이며 사용할 수 없으면 루트 `personalization=null`이다. 전송기는 파일 자체의 `wall_time_unix`도 검사해야 한다. 출력기까지 중지되면 파일은 더 이상 갱신되지 않는다. `unavailable`은 안전·위험 해소를 뜻하지 않는다.

`events.jsonl` 형식:

```json
{"schema_version":"sky-eye.event.v1","id":"sha256...","source":"20261101-043618/events.jsonl","source_event_id":"원본ID","kind":"risk_started","wall_time_unix":1793475395.9,"payload":{"branch":"posture","kind":"risk_started","event_id":"원본ID","risk_type":"prone"}}
```

- `id`: 원본 파일 경로·바이트 위치·내용으로 만든 전송 항목 ID. 재전송 중복 제거에 사용한다. 체크포인트 저장 직전 중단되면 같은 `id`가 다시 기록될 수 있다. 수신기는 `id`로 멱등 처리한다.
- `source_event_id`: 원본 위험 에피소드 ID. 전송 항목 ID와 다르다. 자세 위험 시작/종료를 묶을 때 `source + source_event_id`를 사용한다.
- `payload`는 원본 이벤트를 보존한다. 자세 `risk_started/risk_ended/status_changed/posture_changed/risk_interrupted`, 가장자리 이벤트, 울음 후보/울음 에피소드 시작·종료가 들어온다. 모든 이벤트가 보호자 알림은 아니다.
- 최초 실행에는 기존 로그도 내보낸다. 과거 이벤트를 현재 알림으로 재발송하지 않도록 수신기에서 시각과 이미 처리한 ID를 확인한다.
- `wall_time_unix`는 UNIX 초. **영상 원본의 `ts`, `started_at`, `confirmed_at`, `ended_at`, `video_ts_s`는 monotonic 초**이므로 그대로 날짜로 해석하지 않는다. 자세 이벤트는 `wall_time_unix - payload.ts`를 더해 UNIX 시각으로 바꿀 수 있다. 울음 원본의 `wall_time_unix`, `t0/t1`, UI의 `started_at/ended_at`는 UNIX 초다.

저장소 `suffocation-prevention` 브랜치의 `server/app.py` 및 `docs/api.md`는 개발용 `/devices/{id}/heartbeat`, `/devices/{id}/events` 규격을 제공한다. 현재 통합 패키지는 **파일 출력까지** 담당한다. 이 개발 서버는 수유/울음/가장자리의 전용 API가 없고 정식 아이쿠의 등록·인증·앱 프로그램도 저장소에서 확인되지 않았다. 실제 PC 백엔드의 요청 형식·주소에 맞춘 전송 및 앱 표시는 별도 연결해야 한다. 서버 설정 변경을 파이에 자동 적용하는 기능도 이 패키지에는 없다.

기존 개발 서버에 연결할 때 heartbeat의 `status/reason/posture/airway/elapsed/fps`를 통합 상태에서 매핑할 수 있다. `/events`는 `risk_started/risk_ended`만 받으므로 나머지 종류를 그대로 전송하지 않는다. `risk_interrupted`를 정상 해소로 바꾸지 말고 관찰 중단으로 처리한다.

## 울음 원인 시뮬레이션의 기기 적용

원본 `cry_personal.py`와 `yamnet_emb.tflite`, `cry_personal_basis.npz`, `cry_personal_acoustic.npz`, `cry_personal_ctx.json`을 포함한다. 원본 모델은 한 번의 추론으로 521종 점수와 1024차원 임베딩을 함께 출력한다. 이전의 점수 전용 양자화 모델도 `models/cry/`에 보관했다. 두 YAMNet을 동시에 실행하지 않는다.

- 추천 행동: `feed` 수유 / `diaper` 기저귀 / `hold` 안아주기·자세 바꾸기.
- `max(baby_cry_score, crying_score) >= 0.3`인 약 1초 창을 울음 후보로 수집한다. 연속 비울음 창 3개가 오면 에피소드를 종료한다. 2.5초 넘는 입력 공백, 서비스 중단 또는 300창 제한은 관찰 중단으로 저장하며 해당 구간에는 피드백 버튼을 표시하지 않는다.
- 정상 종료된 울음에 보호자가 실제 행동을 기록한다. `unknown/self`는 기록하되 추천 학습 10건에 포함하지 않는다. 답변을 자동 생성하지 않는다.
- 원본 코드의 10건 최소 피드백 조건을 유지했다. 기기 어댑터는 현재 울음 창 10개도 모인 뒤 1·2순위 힌트를 표시한다. 초반에는 `insufficient_history`가 정상이다.
- 소리 기반 추천은 원본의 자체 비교 게이트를 유지한다. 과거 피드백 비교가 충분하지 않거나 소리를 쓴 예측이 더 낫지 않으면 맥락·이력만 쓴다. `sound_on=false`는 오류가 아니다.
- 점수는 실험 알고리즘의 상대 가중치다. 실제 원인이 맞을 확률이나 의료 진단 정확도로 해석하지 않는다.
- `cry-cause-demo.sh`와 화면의 시뮬레이션 예시는 **가상 피드백 10건**을 메모리에서 만들고 원본 추천 함수를 실행한다. 실제 프로필과 통합 이벤트에는 저장하지 않는다.
- 마이크 원본 WAV는 저장하지 않는다. 개인화 프로필에는 요약 임베딩·특징·행동 이력이 남는다. 배포 압축에는 개인 프로필, 비밀번호, 기기 키가 없다.

터미널 또는 외부 전송 프로그램에서 보호자 답변을 전달할 때:

```bash
bash ~/sky-eye/cry-feedback.sh feedback --episode-uid '화면 또는 JSON의 UUID' --action hold
bash ~/sky-eye/cry-feedback.sh feed   # 실제 수유한 사실만 기록
```

명령은 `input/cry_commands/*.json`에 원자적으로 기록하고 울음 서비스가 처리한다. 반환된 `command_id`의 결과는 `input/cry_receipts/<command_id>.json`의 `ok/error`로 확인한다. 큐 접수는 학습 완료 응답이 아니다. 5분 넘게 처리되지 않은 명령은 만료된다. 동일 에피소드·동일 답은 멱등 처리하고 이미 기록된 답을 다른 값으로 덮어쓰지 않는다.

## 새 파이 설치

압축을 홈 아래 새 폴더에 풀고 다음을 실행한다. 현재 파이의 폴더를 덮어쓸 필요는 없다.

```bash
tar -xzf sky-eye-integrated-20261101.tar.gz
cd sky-eye-integrated-20261101
bash deploy/pi/install-integrated.sh
bash ~/sky-eye/start-all.sh
```

설치에는 인터넷 및 apt 설치 권한이 필요하다. 카메라용 NCNN/OpenCV/NumPy와 Bullseye 호환 `tflite-runtime==2.13.0`을 설치한다. 설치기는 기존 `~/sky-eye`가 다른 폴더를 가리키면 덮어쓰지 않고 멈춘다. 기존 파이를 교체할 때는 먼저 서비스를 중지하고, 사용자 프로필·설정의 이전 방식을 정해야 한다. 시뮬레이션 전체 재학습은 `sim/`의 PC용 코드이며 별도의 데이터·의존성이 필요하다. 파이 실시간 추론에 pandas/TensorFlow를 설치할 필요는 없다.

현재 배포에서는 카메라의 기존 부팅 설정만 유지했다. 필요할 때 직접 전체 부팅 실행을 설정할 수 있다:

```bash
systemctl --user enable sky-eye sky-eye-cry sky-eye-export
```

침대 영역 보정은 아직 `calibration_valid=false`이므로 가장자리 위험 판정은 활성화하지 않았다. 자세·얼굴, 울음 후보 및 돌봄 힌트 테스트와 별도로 실제 카메라 각도에서 보정해야 한다. 결과는 사진/공개 울음 클립과 기기 통합 점검이며 실제 낙상 사건·실제 울음 원인 성능을 입증하지 않는다.
