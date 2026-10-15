# 인지 결과 메시지

TCP 스트림에 JSON 객체를 보내며 송신부는 각 메시지 끝에 newline을 붙입니다. 수신부의 `ResultStreamDecoder`는 TCP read가 메시지 경계와 일치하지 않는 경우와 여러 JSON이 붙어서 들어오는 경우를 처리합니다.

## UFLD · 6000

```json
{"source":"yocto-ufld","lane":{"steer":0.15,"unit":"normalized","confidence":0.5},"lanePoints":[[[300,500],[320,600]],[[900,500],[920,600]]],"objects":[]}
```

- `steer`: 화면 중앙과 선택한 차선들의 중심 사이 편차를 [-1,1]로 정규화한 참고값.
- `confidence`: 유효 차선 개수 / 4. 모델이 출력한 calibrated confidence가 아닙니다.
- `lanePoints`: 1280×720 영상 좌표의 차선별 point 배열.
- 현재 코드는 유효 point가 3개 이상인 차선이 2개 미만이면 송신을 생략합니다.

## YOLO · 6001

```json
{"source":"yocto-yolo","objects":[{"class":0,"score":0.9,"x":500,"y":200,"w":300,"h":200}]}
```

`x`,`y`는 좌상단, `w`,`h`는 폭과 높이입니다. `bbox` / `box` 배열을 사용하는 재현 입력도 `[x,y,w,h]` 형식입니다. `[x1,y1,x2,y2]` 형식이 아닙니다.

제어 판단의 영역 기준은 1280×720입니다. YOLO 송신부는 SDK가 반환한 좌표를 그대로 직렬화하므로, 실제 모델의 출력 좌표계가 640×640 또는 정규화 좌표라면 제어에 넘기기 전에 반드시 맞춰야 합니다. 자동 변환이 구현됐다고 가정하지 않습니다.

수신 앱은 최신 차선 결과와 최신 객체 결과를 병합합니다. YOLO의 빈 `objects`는 이전 객체를 지웁니다. 데이터별 timestamp·만료 검사는 현재 구현에 없습니다.
