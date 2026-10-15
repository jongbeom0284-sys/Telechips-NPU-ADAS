# 빌드와 통합

## 1. 보드 없이 재현

```bash
make check
python3 tools/replay_control.py --scenario center-close
```

표준 Python 라이브러리만 사용하며 모델·SDK·IPC 장치가 필요하지 않습니다. `make`는 framebuffer 도구를 빌드하고 제어 로직·메시지 분할 처리 테스트를 실행합니다.

## 2. NPU 소스 컴파일 확인

로컬 ENLIGHT SDK의 `build_network/enlight/`에 `enlight_network.h`와 의존 헤더가 있어야 합니다.

```bash
make check-sdk ENLIGHT_INCLUDE=/path/to/tc-nn-toolkit/build_network/enlight
```

이 단계는 호스트에서 object 파일을 만드는 검사입니다. 실제 보드용 `net.so`를 완성하거나 NPU 추론을 실행하는 명령은 아닙니다. 보드 실행에는 SDK가 제공하는 런타임·생성 network 파일과 AArch64 toolchain이 추가로 필요합니다.

### UFLD

- softmax 실습 경로는 `npu/ufld/custom_postproc.c`입니다. 이 버전의 `custom_postproc_run`은 세 번째 인자로 18×4 크기의 `float *loc` 버퍼를 받습니다. SDK의 기본 2인자 함수와 호출부를 그대로 섞으면 안 됩니다.
- TCP 통합 경로는 `npu/ufld/post_process.c`입니다. SDK에서 만든 UFLD 네트워크의 `run_post_process` 자리에 연결합니다. INT8 출력이 `[201,18,4]` 순서로 연속 배치된다는 가정을 확인해야 합니다.
- 두 경로를 함께 링크하는 것만으로 자동 연동되지는 않습니다. 서로 다른 실습 단계의 구현입니다.

### YOLO

`npu/yolo/result_sender.c`를 모델 plugin의 빌드 대상에 추가합니다. SDK가 생성한 detector wrapper에서 탐지 결과가 채워진 뒤 아래를 호출합니다.

```c
#include "result_sender.h"

/* SDK detector execution has populated objs_buf_base. */
yolo_send_objects(objs_buf_base);
```

실제 SDK의 `enlight_objs_t`가 필요하며, 가짜 타입으로 보드 ABI를 대체하지 않습니다.

### 송신 대상

공개본 기본 주소는 `127.0.0.1`입니다. 실제 실습 네트워크에서는 환경변수로 수신 보드 주소를 지정합니다.

```bash
export D3G_RESULT_HOST=<D3-G-address>
export D3G_RESULT_PORT=6000
export YOLO_RESULT_PORT=6001
```

`UFLD_TCP_DISABLE=1`, `YOLO_TCP_DISABLE=1`이면 각 송신을 비활성화합니다.

## 3. 제어 수신 앱

아래는 통신 연동을 위한 dry-run 예시입니다. 인지 결과 수신 포트는 loopback에 엽니다.

```bash
python3 control/Data_parsing_student.py --mode listen --listen-host 127.0.0.1 --dry-run
```

UFLD·YOLO는 각각 6000·6001, 상태 출력은 9998·9999 포트를 사용합니다. 현재 Qt 상태 출력 서버는 `--listen-host`와 별도로 모든 인터페이스에 bind하므로, 보드 없는 로직 확인에는 위의 `replay_control.py`를 사용하세요. 실제 IPC/CAN 출력에는 교육 환경의 `Library/IPC_Library.py`와 `/dev/tcc_ipc_micom`이 필요합니다. 공개 저장소는 그 라이브러리를 포함하지 않습니다. 실습 앱의 라이브러리 import fallback은 장치 출력을 검증하지 않으므로, 실제 IPC 동작 확인에는 사용하지 않습니다.

## 4. framebuffer 로그 뷰어

```bash
make
# 보드의 32bpp framebuffer에 표시할 때만 실행
tcnnapp <board-runtime-options> 2>&1 | ./build/ufld_log_viewer /dev/fb0
```

`tools/run_ufld_yolo_log.sh`는 당시 보드에서 사용한 실행 스크립트입니다. `tcnnapp`, 모델 폴더, `/home/root/ufld_log_viewer` 배치가 필요하며 `UFLD_PATH`, `YOLO_PATH`, `VIDEO_PATH`로 모델·입력 위치를 바꿀 수 있습니다. 뷰어는 softmax 경로가 출력하는 `Point[row][lane]` 로그를 읽으며, JSON 전용 경로의 출력을 직접 그리지는 않습니다.

## 5. LeNet 실습

`examples/lenet/train_lenet.py`는 PyTorch·torchvision·ONNX export 환경이 필요합니다. 실행하면 MNIST를 내려받아 CPU로 10 epoch 학습하고 ONNX 파일을 생성합니다. 공개 정리 과정에서는 학습이나 데이터셋 다운로드를 다시 실행하지 않았습니다.
