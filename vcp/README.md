# VCP 주변장치 실습

NPU 통합과 함께 사용한 텔레칩스 VCP 환경의 개인 작업분입니다.

| 경로 | 내용 |
|---|---|
| `test.app.gpio/led.*` | GPIO LED 점멸 |
| `test.app.i2c/lcd1602.*` | I2C 초기화·주소 확인·LCD 출력 |
| `test.app.pdm/pdm_led.*` | PDM 출력으로 LED 제어 |
| `test.app.pdm/pdm_motor.*` | 50Hz 주기, 각도에 따른 pulse width로 서보 구동 실습 |
| `integration.patch` | BSP의 task·CAN enum·빌드 목록 등 수정 기록 |

기반은 [FreeRTOS-VCP](https://github.com/topst-development/FreeRTOS-VCP)이며 정확한 기준 revision은 [`UPSTREAM_COMMIT`](UPSTREAM_COMMIT)에 있습니다. 원본 BSP는 별도로 준비하고 폴더 이름에 맞춰 `sources/app.sample/` 아래에 추가 모듈을 배치합니다.

patch는 당시 실습 상태를 남긴 자료입니다. BSP의 `lcd.h`·`lcd.c`, GPIO·PDM 포트 정의 등 추가 의존성과 실습 모듈 간 충돌을 확인해야 하며, 저장소만으로 독립 빌드되지는 않습니다. 실제 모터·LCD를 연결한 재검증과 BSP 전체 빌드는 이번 공개 작업에 포함하지 않았습니다.
