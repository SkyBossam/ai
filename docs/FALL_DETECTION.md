# 낙상·침대 가장자리 위험 코드

`src/camera_fall`은 몸 박스 탐지·추적, 침대 경계 보정, R0 가장자리 접근 경고와 시계열 모델, 영상 단위 평가 코드를 포함한다. R0의 출력은 실제 추락 사건의 확정 판정이 아니다.
의존성은 루트 `requirements.txt`에 통합했으며 PC와 ARM 환경에 따라 설치 항목을 구분한다. 현재 사용 중인 32비트 Pi 4의 NCNN 통합 실행은 `codex/suffocation-prevention` 브랜치의 `deploy/pi`에 있다. 해당 통합 실행은 한 번의 YOLO 추론으로 자세·얼굴 판정과 가장자리 규칙에 같은 몸 박스를 공급한다.

```bash
python scripts/preflight.py
python scripts/run_camera.py --help
python -m unittest discover -s tests -v
```

`examples/`에는 영상·이벤트·출처 그룹 입력 예시가 있다. 기본 분할이나 사진 지표를 실제 낙상 사건 성능으로 해석하지 않는다. 실제 카메라 각도에서 침대 영역을 보정하고 촬영 회차를 분리한 영상 평가가 필요하다. 실행 전에 `docs/MODEL_ASSETS.md`를 참고해 필요한 가중치를 준비한다.
