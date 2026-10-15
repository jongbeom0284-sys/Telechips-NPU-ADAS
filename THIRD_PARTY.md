# 출처와 공개 범위

텔레칩스 교육 환경에서 작업한 소스를 공개용으로 정리했습니다. 교육 프레임워크와 기반 모델의 성과를 개인이 처음부터 만든 것으로 주장하지 않습니다.

| 구성 | 출처 / 관계 |
|---|---|
| NPU 실행 API, tensor·detector 타입 | 로컬에 설치한 ENLIGHT SW Toolkit / SDK. SDK 본체와 생성된 network·command·weight 데이터는 제외했습니다. |
| `npu/ufld/` | SDK의 custom postprocess 연결 방식을 사용한 UFLD 후처리와 TCP 전송 작업입니다. `enlight_network.h` 등은 SDK에서 가져와야 합니다. |
| `npu/yolo/result_sender.c` | 로컬 YOLO 통합 코드에서 사용자 추가 송신부를 분리했습니다. SDK가 생성한 detector 초기화·실행 코드는 포함하지 않았습니다. |
| `control/Data_parsing_student.py` | 교육용 소켓·IPC/CAN·상태 송신 골격을 바탕으로 한 실습 파일입니다. 전체 프레임워크의 단독 저작을 주장하지 않으며, 학생 구현 구역의 제어 판단과 결과 연동을 함께 확인할 수 있도록 보존했습니다. |
| VCP BSP | [topst-development/FreeRTOS-VCP](https://github.com/topst-development/FreeRTOS-VCP). 원본 전체 대신 추가 모듈과 최소 문맥의 수정 patch를 포함합니다. 기준 commit은 `vcp/UPSTREAM_COMMIT`에 있습니다. |
| 교육 환경 참고 | [topst-development/Education](https://github.com/topst-development/Education). 원본 교육 PDF·실행파일·IPC 라이브러리는 이 저장소에 복사하지 않았습니다. |
| UFLD / YOLOv8s | 기존 차선 인식·객체 탐지 모델을 이용한 적용 프로젝트입니다. 기반 모델·가중치의 권리와 사용 조건은 각 원 프로젝트에 따릅니다. |

이 정리는 모든 구성에 새로운 단일 라이선스를 부여하지 않습니다. 공급업체 및 제3자 코드·모델·데이터의 조건은 각각의 원본 배포 조건을 확인해야 합니다.

공개본은 WSL 원본을 보존한 복사본입니다. 보드 사설 주소의 기본값을 loopback으로 바꾸고, YOLO 송신부를 별도 파일로 추출했으며, 설명·재현 예제·검증 코드를 추가했습니다. VCP patch는 당시 작업 상태를 기록한 것으로 전체 BSP 빌드 완료를 보증하는 패치가 아닙니다.
