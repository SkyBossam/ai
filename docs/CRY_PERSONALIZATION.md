# 울음 개인화·돌봄 추천

`cry_personal.py`는 수유·기저귀·안아주기/자세 바꾸기 중 먼저 확인해 볼 행동을 실험적으로 추천한다. 원인 확정이나 의료 진단 모델이 아니다. `sim/`에는 원본 시뮬레이션·특징 변환·YAMNet 내보내기 코드가 있다.
시뮬레이션 의존성은 `requirements-cry-simulation.txt`로 구분했다. 실시간 추론에는 TensorFlow 학습 환경이 필요하지 않다. 현재 32비트 Bullseye 파이에서는 NumPy와 `tflite-runtime==2.13.0`, 마이크 입력용 ALSA를 사용한다.

```bash
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 python -m sky_edge.personalization demo
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 python -m sky_edge.audio live
```

위 실시간 실행 전에는 `docs/MODEL_ASSETS.md`에 따라 YAMNet TFLite를 복사한다. 테스트 마이크 장치는 `deploy/pi/cry.json`에서 바꿀 수 있다.
실제 보호자 피드백 10건과 현재 울음 후보 창 10개가 있어야 추천을 표시한다. `unknown/self`는 학습 10건에 포함하지 않는다. 소리 특징의 자체 비교 게이트도 원본 설정을 유지한다. `demo`는 가상 피드백 10건을 메모리에서 만들며 실제 프로필을 수정하지 않는다.
기기 실행은 약 1초마다 울음 점수와 임베딩을 함께 계산한다. 비울음 창 3개면 에피소드를 종료하고 보호자가 그친 행동을 기록할 수 있다. `state/cry-personal/profile.json`은 실제 기기 내부 기록이므로 Git에 올리지 않는다. 마이크 원본 WAV를 저장하지 않는다.

원본 소스: https://github.com/wlsdn66597/sky_bossam/tree/cry-personalization
원본 커밋: d35f355c3cf25d532226029a0e13caaba78410e6. 파이 어댑터·명령 큐·통합 출력은 현재 배포 코드에 추가된 부분이다.
