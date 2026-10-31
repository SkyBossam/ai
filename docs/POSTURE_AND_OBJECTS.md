# 자세·얼굴 유지 및 베개·장난감 추가 학습

`scripts/prepare_dataset.py`, `train.py`, `run_experiments.py`, `evaluate.py`, `sweep_thresholds.py`, `export_model.py`는 기존 5클래스 학습·평가 흐름이다. 패키지는 `src/sleepsafe`에 배치했고 상대 경로의 기준은 이 저장소 루트다.
`training/objects`는 L4에서 실행한 7클래스 추가 학습 코드다. 기존 사진 재학습과 출처별 부분 라벨 마스크를 사용해 라벨이 없는 클래스를 음성으로 학습하지 않도록 한다. 기존 몸/얼굴 클래스와 pillow/toy를 유지한다. PC 공통 의존성은 루트 `requirements.txt`이며, YOLO 버전을 부분 라벨 구현에 필요한 8.4.176으로 통일했다. 기존 5클래스 실험의 8.3.221 환경과 다르므로 과거 결과의 재현에는 당시 환경 기록이 필요하다.
해당 폴더 아래 `bundle/manifest.json`, `bundle/dataset`, `bundle/baseline/best.pt`를 준비한 뒤 실행한다. 데이터와 체크포인트는 Git에 포함하지 않았다. 원래 스크립트의 고정 입력 해시·Ultralytics 8.4.176·NVIDIA L4 검사 조건을 유지했으므로 다른 환경/데이터에서는 먼저 해당 조건을 검토해야 한다.

```bash
PYTHONPATH=src python scripts/train.py --help
PYTHONPATH=src python scripts/run_experiments.py --help
PYTHONPATH=src python training/objects/test_partial_labels.py
PYTHONPATH=src python training/objects/train_objects.py
```

추가 학습 결과는 실험용이다. 장난감과 얼굴 가림의 일반화는 충분히 검증되지 않았다. 현재 파이 기본값은 기존 5클래스 모델이다. 자세·얼굴의 위험 기준은 5초, 정상 해소는 3초이며 1초 이내의 탐지 공백을 허용한다. 실제 영상 단위 평가와 침대 영역 보정은 별도 필요하다.

원본 5클래스 소스: https://github.com/wlsdn66597/sky_bossam/tree/suffocation-prevention
원본 커밋: 09b708977cf7523b9a6b2e7848b33273d8443f4c. 파이 통합 실행과 출력 계약은 `docs/PI_INTEGRATION.md`를 참고한다.
