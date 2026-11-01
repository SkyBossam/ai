# 모델 자산

소스와 작은 개인화 변환 파일은 Git에 포함합니다. 실행용 ONNX/NCNN/TFLite 가중치는 [Release v0.1.0](https://github.com/SkyBossam/ai/releases/tag/v0.1.0)의 배포 압축으로 제공합니다. 학습 데이터·가상환경·실제 사용자 기록은 포함하지 않습니다.

- [모델 포함 배포 압축](https://github.com/SkyBossam/ai/releases/download/v0.1.0/sky-eye-integrated-20261101.tar.gz)
- [SHA-256 확인 파일](https://github.com/SkyBossam/ai/releases/download/v0.1.0/sky-eye-integrated-20261101.tar.gz.sha256)

Linux/파이에서 두 파일을 같은 폴더에 내려받은 뒤 확인합니다.

```bash
sha256sum -c sky-eye-integrated-20261101.tar.gz.sha256
tar -xzf sky-eye-integrated-20261101.tar.gz
cd sky-eye-integrated-20261101
sha256sum -c SHA256SUMS
bash deploy/pi/install-integrated.sh
```

통합 설치기는 Pi 4 / Bullseye / ARMv7 32비트 / Python 3.9 기준입니다. 카메라·마이크와 침대 경계는 실제 설치 환경에 맞게 설정합니다. 다른 OS의 카메라 설치는 `deploy/pi/SSH_DEPLOY.md`를 확인합니다.

Git 체크아웃에서 실행한다면 압축의 `models/` 전체를 저장소에 복사합니다. 가중치와 `model_meta.json`, 클래스맵을 함께 복사해야 체크섬 검증이 일치합니다. 개별 파일을 임의로 편집하거나 줄바꿈을 바꾸지 않습니다. [`models/ASSETS.json`](../models/ASSETS.json)은 공개 배포 모델 파일의 경로와 SHA-256입니다.

공개 배포 압축은 소스·설정·모델·공개 테스트 음원만 포함합니다. 실제 프로필·이벤트 로그·기기 키·인증 정보·장치 점검 보고서는 포함하지 않습니다. 제3자 모델과 공개 음원의 출처·이용 조건은 각 메타데이터와 `assets/test-clip-attribution.json`에 유지합니다.
