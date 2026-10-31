# 아이쿠 AI · SkyBossam

침대 위 아기의 자세·얼굴 상태, 침대 가장자리 접근 위험, 울음 후보와 개인화 돌봄 힌트를 분석하는 코드입니다. 카메라는 한 번의 YOLO 추론 결과를 자세·얼굴 판정과 가장자리 위험 규칙에서 함께 사용합니다.

| 기능 | 주요 코드 |
|---|---|
| 몸·얼굴 탐지 및 시간에 따른 위험 판정 | `src/sleepsafe/`, `src/sky_edge/pipeline.py` |
| 낙상 관련 추적·침대 가장자리 접근 경고 | `src/camera_fall/` |
| 울음 감지·개인화 돌봄 추천 | `cry_personal.py`, `src/sky_edge/audio.py`, `src/sky_edge/personalization.py` |
| 파이 실행·브라우저 확인·통합 JSON 출력 | `src/sky_edge/`, `deploy/pi/` |

## 1. 설치 환경

| 용도 | 환경 |
|---|---|
| PC 코드 확인·테스트 | Python 3.11 권장, Git, Windows 또는 Linux. 기존 통합 테스트는 Python 3.12에서도 확인 |
| 현재 파이 통합 실행 | Raspberry Pi 4, Raspberry Pi OS Bullseye **32비트 ARMv7**, Python 3.9, USB 카메라·마이크 |
| 기존 5클래스 YOLO 학습 | 별도 PC 가상환경, `requirements-posture-train.txt`; GPU 사용 시 CUDA에 맞는 PyTorch 필요 |
| 물체 추가 학습 | NVIDIA L4, 별도 환경의 `training/objects/requirements.txt` 및 CUDA용 PyTorch |

현재 32비트 파이는 NCNN CPU와 `tflite-runtime==2.13.0`을 사용합니다. `requirements-pi.txt`는 별도의 **64비트 Python 3.11 ONNX Runtime 프로필**이므로 32비트 설치에 사용하지 않습니다. 파이 실시간 실행에는 PyTorch나 TensorFlow 학습 환경이 필요하지 않습니다.

## 2. PC 설치와 기본 확인

```bash
git clone https://github.com/SkyBossam/ai.git
cd ai
python -m venv .venv
```

가상환경을 활성화합니다.

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# Linux / macOS
source .venv/bin/activate
```

PowerShell에서 활성화가 제한되면 명령의 `python` 대신 `.\.venv\Scripts\python.exe`를 사용합니다. 다음은 테스트·기존 낙상 연구 코드용 설치입니다. GPU 재학습 환경은 7절에서 따로 설정합니다.

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements-train.txt
python -m unittest discover -s tests -v
```

머지 후 통합 테스트 **51개 통과**를 확인했습니다. 이 테스트는 모델 입출력·판정 규칙·파일 출력·미리보기 API 등을 점검하며, 실제 낙상 사건이나 울음 원인의 정확도를 측정하는 평가는 아닙니다.

모델과 카메라 없이도 개인화 추천 시뮬레이션을 확인할 수 있습니다.

```powershell
# Windows PowerShell, 저장소 루트에서
$env:PYTHONPATH = "$PWD/src"
$env:OPENBLAS_NUM_THREADS = "1"
python -m sky_edge.personalization demo
```

```bash
# Linux / macOS, 저장소 루트에서
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 python -m sky_edge.personalization demo
```

`simulation: true`인 가상 피드백 10건의 예시입니다. 실제 보호자 기록을 만들거나 수정하지 않습니다.

## 3. 모델 파일 준비

Git에는 소스·설정·작은 개인화 변환 파일을 포함합니다. **PT/ONNX/NCNN/TFLite 가중치와 학습 데이터는 별도 준비가 필요합니다.** 저장소를 복제하는 것만으로 실시간 모델 실행에 필요한 모든 파일이 생기지는 않습니다.

별도로 제공되는 `sky-eye-integrated-20261101.tar.gz`를 사용합니다. 이 파일은 현재 GitHub 저장소의 다운로드 자산으로 게시되어 있지 않으므로 프로젝트 담당자에게 전달받아야 합니다. 파일 경로·해시는 [모델 자산 안내](docs/MODEL_ASSETS.md)와 [`models/ASSETS.json`](models/ASSETS.json)을 참고하세요.

| 모델 경로 | 용도 |
|---|---|
| `models/infant/model.onnx`, `model.ncnn.param`, `model.ncnn.bin` | 기본 5클래스 자세·얼굴 탐지 |
| `models/objects/` | 베개·장난감이 추가된 실험용 7클래스 모델 |
| `models/cry-personal/yamnet_emb.tflite` | 울음 점수와 1024차원 임베딩 |
| `models/cry-personal/cry_personal_*.npz`, `cry_personal_ctx.json` | 개인화 특징 변환·맥락 모델 |
| `models/cry/yamnet_class_map.csv` | YAMNet 소리 클래스 이름 |

소스 체크아웃에서 직접 실행한다면 배포 압축의 `models/` 내용을 저장소의 `models/`로 복사합니다. 모델 파일과 함께 해당 `model_meta.json`도 복사해야 체크섬이 일치합니다. 체크섬으로 검증하는 파일은 임의로 편집하거나 줄바꿈을 변환하지 않습니다.

## 4. 라즈베리파이 설치·환경 설정

### 새 파이에 배포 압축으로 설치

PC 터미널에서 실제 계정과 IP를 넣어 전송·접속합니다. PC와 파이는 같은 네트워크에 연결되어 있어야 합니다.

```bash
scp sky-eye-integrated-20261101.tar.gz PI_USER@PI_HOST:~/
ssh PI_USER@PI_HOST
```

다음 명령은 **파이 터미널**에서 실행합니다.

```bash
tar -xzf ~/sky-eye-integrated-20261101.tar.gz -C ~
cd ~/sky-eye-integrated-20261101
bash deploy/pi/install-integrated.sh
```

설치기는 압축의 `SHA256SUMS`를 확인하고 apt·가상환경 의존성과 사용자 서비스를 설치합니다. 인터넷 연결과 `sudo` 권한이 필요합니다. **`install-integrated.sh`는 배포 압축에서 실행하는 설치기**입니다. `SHA256SUMS`가 없는 Git 체크아웃에서 그대로 실행하지 않습니다.

설치 후 `~/sky-eye`가 설치 폴더를 가리킵니다. 이미 다른 설치를 가리키는 `~/sky-eye`가 있으면 자동 덮어쓰기하지 않고 중단합니다. 기존 설치를 사용 중이라면 아래 실행 명령만 사용하고, 교체 시에는 설정·개인화 기록의 이전 방법을 먼저 정합니다.

### 장치 설정

설치 폴더에서 다음 파일을 장치에 맞게 확인합니다.

| 파일 | 확인할 설정 |
|---|---|
| `deploy/pi/config.json` | `camera_source` USB 카메라 번호, `frame_size`, `inference_backend=ncnn`, `preview_port=8765` |
| `deploy/pi/cry.json` | 마이크 `device`, YAMNet 경로, 울음 기준 `threshold=0.3` |
| `deploy/pi/geometry.json` | 침대 다각형·경계와 `calibration_valid` |
| `configs/risk_r0.yaml` | 가장자리 접근 위험 규칙 |

```bash
ls /dev/video*
arecord -l
```

기존 검증 장치는 카메라 `/dev/video0`, 마이크 `plughw:CARD=GH300,DEV=0`입니다. 다른 마이크라면 `arecord -l`의 결과에 맞게 `cry.json`의 `device`를 바꿉니다. 모델 자산이나 장치가 없으면 해당 입력을 정상으로 간주하지 않습니다.

침대 보정 방법은 다음 명령과 [배포 안내](deploy/pi/SSH_DEPLOY.md)를 확인합니다. 기본 설정은 `calibration_valid=false`이며 보정 전에는 가장자리 위험 판정이 비활성입니다.

```bash
cd ~/sky-eye
.venv/bin/python deploy/pi/calibrate.py --help
```

## 5. 파이 실행·종료와 화면 확인

```bash
bash ~/sky-eye/start-all.sh          # 기본 카메라 + 울음·추천 + 통합 출력
bash ~/sky-eye/watch.sh              # 카메라 감지 상태 확인, Ctrl+C로 조회 종료
bash ~/sky-eye/cry-watch.sh          # 울음 점수·마이크 레벨 확인
bash ~/sky-eye/cry-cause-demo.sh     # 가상 피드백 추천 예시
bash ~/sky-eye/stop-all.sh           # 카메라·마이크 중지
```

`stop-all.sh` 후에도 출력 서비스는 남아 입력을 `unavailable`로 기록합니다. 출력 서비스까지 중지하려면 `systemctl --user stop sky-eye-export`를 실행합니다.

```bash
systemctl --user status sky-eye sky-eye-cry sky-eye-export --no-pager
journalctl --user -u sky-eye -u sky-eye-cry -u sky-eye-export -n 50 --no-pager
```

베개·장난감 모델을 시험할 때는 `bash ~/sky-eye/start-all.sh objects`를 사용합니다. 기본 모델과 동시에 실행하지 않으며, 물체 모델은 실험용입니다.

PC에서 SSH 터널을 열고 해당 터미널을 유지합니다.

```bash
ssh -L 8765:127.0.0.1:8765 PI_USER@PI_HOST
```

PC 브라우저에서 <http://127.0.0.1:8765/>를 열면 감지 박스·상태, 울음 점수, 돌봄 힌트와 피드백 버튼을 확인할 수 있습니다. 실제 추천은 **유효한 보호자 피드백 10건과 현재 울음 창 10개**가 모이면 표시합니다. 현재 입력을 기다리는 상태에서 추천이 비어 있는 것은 정상입니다.

## 6. 출력 파일과 서버 연동

| 경로 | 내용 |
|---|---|
| `~/sky-eye/output/status.json` | 카메라·울음·추천 통합 현재 상태 |
| `~/sky-eye/output/events.jsonl` | 한 줄에 JSON 하나인 통합 이벤트 |
| `~/sky-eye/logs/YYYYMMDD-HHMMSS/` | 실행 회차별 원본 카메라 상태·이벤트 |
| `~/sky-eye/logs/cry/` | 원본 울음 상태·이벤트 |
| `~/sky-eye/state/cry-personal/profile.json` | 기기 내부의 개인화 기록 |

```bash
cat ~/sky-eye/output/status.json
tail -n 5 ~/sky-eye/output/events.jsonl
```

이 저장소의 통합 실행은 **모델 분석과 파일 출력까지** 담당합니다. 아이쿠 기기 전송 프로그램·PC 백엔드·앱으로 보내는 연결은 별도입니다. JSON 필드, 입력 유효 시간, 이벤트 중복 제거와 보호자 피드백 전달 방식은 [파이·아이쿠 연동 계약](docs/PI_INTEGRATION.md)을 참고하세요. 실제 사용자 기록·로그는 Git에 올리지 않습니다.

## 7. 학습·평가 코드 실행

학습은 파이 실시간 실행 환경과 분리합니다. GPU를 사용한다면 먼저 해당 CUDA 환경에 맞는 PyTorch·torchvision을 설치합니다.

### 기존 자세·얼굴 5클래스

```bash
python -m pip install -r requirements-posture-train.txt
python scripts/prepare_dataset.py --raw /path/to/roboflow-dataset
python scripts/train.py --data datasets/sleepsafe/data_original.yaml --name A_original_320_aug --imgsz 320
python scripts/run_experiments.py --help
python scripts/sweep_thresholds.py --help
python scripts/export_model.py --help
```

`--raw`는 실제 데이터 경로로 바꿉니다. 원본 데이터는 [데이터 설정](configs/dataset.yaml)을 참고해 출처 이용 조건에 따라 별도로 준비합니다.

### 베개·장난감 추가 학습

별도 가상환경에 `training/objects/requirements.txt`를 설치하고, [물체 추가 학습 안내](docs/POSTURE_AND_OBJECTS.md)에 따라 `training/objects/bundle/`의 데이터·매니페스트·기존 체크포인트를 준비합니다. 이 실행 코드는 고정 입력 해시, Ultralytics 8.4.176, L4 GPU 조건을 검사합니다.

```bash
# Linux 학습 서버, 저장소 루트에서
PYTHONPATH=src python training/objects/test_partial_labels.py
PYTHONPATH=src python training/objects/train_objects.py
```

기타 진입점은 [낙상·가장자리 연구 코드](docs/FALL_DETECTION.md), [울음 개인화·시뮬레이션](docs/CRY_PERSONALIZATION.md)을 참고하세요. 전체 울음 시뮬레이션·YAMNet 재내보내기용 `requirements-cry-simulation.txt`는 별도의 Python 3.10/3.11 PC 환경에서 사용하며 파이에 설치하지 않습니다.

## 동작 범위

자세·얼굴 위험은 기본 5초 지속 시 시작하고 정상 3초 지속 시 해소합니다. 가장자리 출력은 접근 경고이며 실제 추락 확정 판정이 아닙니다. 울음 추천은 수유·기저귀·안아주기를 먼저 확인하는 실험적 힌트입니다. 사진 지표나 통합 테스트 결과를 실제 낙상 사건·울음 원인 정확도로 해석하지 않습니다.
