# SSH 배포

대상: Raspberry Pi 4. 64비트 OS/Python 3.11~3.13에서는 ONNX Runtime CPU를 사용할 수 있다. **32비트 Bullseye/Python 3.9 배포는 ARM 최적화 NCNN CPU 프로필**을 사용한다. 같은 ONNX에서 FP32로 변환하고 출력·박스를 비교한다. OpenCV DNN은 비교용 대안으로 남긴다. 공통 전처리·후처리를 사용하며 파이에 PyTorch·Ultralytics를 설치하지 않는다. 설치 시 파이에 인터넷 연결이 필요하다.

## 1. 전송·설치

PC에서 계정·주소와 실제 압축 파일 이름을 넣는다. SSH 포트가 다르면 scp에는 `-P 포트`, ssh에는 `-p 포트`를 추가한다.

```powershell
scp ./sky-eye-pi-baseline.tar.gz USER@PI_HOST:~/
ssh USER@PI_HOST
```

파이에서:

```bash
tar -xzf sky-eye-pi-baseline.tar.gz
cd sky-eye-pi-baseline
sha256sum -c SHA256SUMS
bash deploy/pi/install.sh usb
```

CSI 리본 카메라라면 마지막 명령을 `bash deploy/pi/install.sh csi`로 바꾼다. CSI는 apt의 Picamera2·OpenCV·NumPy를 함께 사용한다. USB는 별도 가상환경의 headless OpenCV를 사용한다. 카메라 장치 권한이 없으면 `sudo usermod -aG video "$USER"` 후 SSH를 다시 연결한다.

32비트 Bullseye는 `install.sh usb`가 ARMv7 설치기로 연결된다. piwheels의 Python 3.9 빌드와 각 파일 SHA256을 고정한다. NCNN 번들은 `inference_backend: ncnn`을 사용하며 ncnn 1.0.20260526을 설치한다. `verify_opencv.py --backend ncnn`으로 ONNX Runtime에서 추출한 고정 입력·출력과 비교할 수 있다. 이 프로필은 Bullseye/Python 3.9 전용이다.

## 2. 카메라·성능 확인

```bash
bash deploy/pi/edge.sh check
bash deploy/pi/edge.sh snapshot --output snapshot.jpg
bash deploy/pi/edge.sh benchmark --image snapshot.jpg --seconds 180 --output benchmark.json
```

PC에서 `scp USER@PI_HOST:~/sky-eye-pi-baseline/snapshot.jpg ./`로 화면을 가져올 수 있다. 모델 처리 시간과 p95, 온도가 benchmark.json에 저장된다. 벤치마크는 카메라 수신 시간을 제외한다. 실제 실행은 `run_summary.json`에서 처리 FPS와 프레임 나이를 확인한다. 기본 R0 관찰 공백 예산은 0.5초다. 처리 시간이 이를 넘으면 경계 이동의 연속 근거를 충분히 얻지 못할 수 있다. 실측 없이 FPS를 보장하지 않는다.

USB 장치 번호·카메라 종류·해상도·목표 FPS는 `deploy/pi/config.json`에 있다. CSI는 `camera_backend: picamera2`다. 추론 프레임은 쌓지 않고 가장 최근 프레임을 사용한다. `threads`는 1/2/4를 각각 벤치마크해서 정한다.

## 3. 침대 좌표 보정

snapshot.jpg에서 침대 모서리 좌표를 시계 또는 반시계 순서로 읽는다. 각 변은 현재 꼭짓점에서 다음 꼭짓점까지이며 `open`(열린 가장자리), `rail`(난간), `wall`, `unknown` 중 하나다. 아래 숫자는 예시이므로 실제 화면 좌표로 바꾼다.

```bash
.venv/bin/python deploy/pi/calibrate.py --size 640 480 \
  --polygon '64,72;576,72;576,422;64,422' \
  --edges 'rail,open,rail,wall' --confirmed
```

실제 화면 확인 전에는 `--confirmed`를 쓰지 않는다. 기본 geometry.json은 calibration_valid=false이며, 이 상태에서는 자세·얼굴 판정만 동작하고 경계 경고는 분석 불가다. 카메라를 옮기거나 방향·화면 비율을 바꾸면 다시 보정한다. 모델이 침대 경계를 자동 탐지하지 않는다.

## 4. 실행·자동 시작

```bash
bash deploy/pi/edge.sh run --seconds 60 --print-status
bash deploy/pi/install-service.sh
systemctl --user enable --now sky-eye
sudo loginctl enable-linger "$USER"
journalctl --user -u sky-eye -f
```

중지: `systemctl --user stop sky-eye`. 로그는 `logs/날짜-시각/`의 status.json, events.jsonl, run_summary.json에 남는다. 자동 시작은 설치 스크립트가 임의로 켜지 않는다. 수동 카메라 검사를 마친 뒤 위 명령으로 켠다. 실행마다 새 로그 폴더를 쓴다.

카메라 오류는 분석 불가 상태와 error.json으로 남긴다. 이 상태를 정상 복귀로 처리하지 않는다. 프로세스 재시작 시 로컬 타이머는 새로 시작하므로 보호자 알림의 수명·확인 상태는 서버에서 관리해야 한다.

## 판정과 모델 교체

- 프레임당 YOLO는 한 번 실행한다. 같은 몸 박스를 두 판정기에 전달한다. 겹친 자세 후보를 정리하고, 여러 몸 중 추적 대상을 고를 수 없으면 분석 불가로 남긴다.
- 자세/얼굴: 엎드림·얼굴 가림 5초, 정상 복귀 3초, 허용 공백 1초. 정상·위험 상태와 분리해 자세 변화 이벤트도 기록한다. 자세 변화 이벤트는 영상에서 실제 뒤집는 동작을 검증한 분류기가 아니다.
- 경계: 열린 가장자리 근접·바깥 방향 이동 0.6초가 이어지면 경계 이탈 경고. 실제 낙하 확정은 아니다. 난간 근접만으로 이탈 경고를 만들지 않는다.
- 5클래스 모델은 자세·얼굴만 탐지한다. 추가 학습 7클래스 모델은 마지막에 pillow/toy가 붙는다. 물체는 표시만 하며 물체 발견 자체로 위험을 발생시키지 않는다.
- 서버 푸시·보호자 알림은 이 패키지에 연결되어 있지 않다. `events.jsonl`은 branch=posture/fall로 구분한 로컬 이벤트다. 서버 확인·2차 알림은 별도다.
- 새 모델은 ONNX와 model_meta.json을 함께 교체한다. 운영 중 파일을 덮어쓰기보다 서비스를 중지하고 새 릴리스 폴더를 배포한다. `check`, 실제 영상, 성능 측정을 다시 실행한 뒤 서비스를 전환한다.

공식 설치 근거: [Raspberry Pi Python 가상환경](https://github.com/raspberrypi/documentation/blob/master/documentation/asciidoc/computers/os/using-python.adoc), [Picamera2](https://github.com/raspberrypi/picamera2), [ONNX Runtime ARM64 wheel](https://pypi.org/project/onnxruntime/1.20.1/).
