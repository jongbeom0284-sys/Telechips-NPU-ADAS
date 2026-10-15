#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
소켓 수신, JSON 변환, Qt 상태 송신, IPC/CAN 전송 골격은 구현되어 있습니다.

학생들은 아래의 "학생 구현 영역"에서 파싱된 JSON을 바탕으로
차량 제어값 산출 로직만 구현하면 됩니다.
UFLD 차선 결과는 6000 포트로 받고, YOLO 객체 결과는 6001 포트로 받습니다.
"""

import argparse
import json
import logging
import socket
import threading
import time
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple, Union


# =============================================================================
# IPC Library Import (Optional)
# =============================================================================
try:
    from Library.IPC_Library import IPC_SendPacketWithIPCHeader
except ImportError:
    def IPC_SendPacketWithIPCHeader(*args, **kwargs):
        """Fallback stub for local syntax/unit-test environments."""
        return None


# =============================================================================
# Logging Configuration
# =============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)-8s %(name)s: %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)


# =============================================================================
# Enums & Constants
# =============================================================================

class VehicleControlCommand(IntEnum):
    """VCP (Vehicle Control Protocol) IO type identifiers."""

    BREAK_LIGHT = 0x101
    MOTOR_A     = 0x106
    WHEEL       = 0x107
    EMER_SIGNAL = 0x103
    FUEL_L      = 0x105
    TURN_SIGNAL = 0x102
    HEAD_LIGHT  = 0x104


class ControlAction(IntEnum):
    """VCP control action values."""

    ON  = 0x01
    OFF = 0x02


class TurnSignalDirection(IntEnum):
    """Turn signal direction subtypes."""

    LEFT  = 0x01
    RIGHT = 0x02


class DetectedZone:
    """5-zone detection grid names."""

    LEFT_UPPER = "LEFT_UPPER"
    LEFT_LOWER = "LEFT_LOWER"
    RIGHT_UPPER = "RIGHT_UPPER"
    RIGHT_LOWER = "RIGHT_LOWER"
    CENTER = "CENTER"
    NONE = "NONE"


class ZoneID(IntEnum):
    """Zone IDs for the existing Qt zone visualization."""

    LEFT_UPPER  = 1
    LEFT_LOWER  = 2
    RIGHT_LOWER = 3
    RIGHT_UPPER = 4
    CENTER      = 5


class NetworkConfig:
    """Network constants for AI-G/D3-G communication."""

    SERVER_IP = "127.0.0.1"
    RESULT_PORT = 6000
    YOLO_RESULT_PORT = 6001
    QT_DASHBOARD_PORT = 9998
    QT_LANE_PORT = 9999
    LISTEN_HOST = "0.0.0.0"


class VideoConfig:
    """Coordinate-space constants used for result scaling only."""

    MODEL_W = 640
    MODEL_H = 640
    OUTPUT_W = 1280
    OUTPUT_H = 720


DEFAULT_CRUISE_SPEED_KMH = 35.0
DEFAULT_CAUTION_SPEED_KMH = 20.0
DEFAULT_STOP_SPEED_KMH = 0.0
DEFAULT_STEER_BIAS = 0.20
DEFAULT_MAX_ANGLE_DEG = 30.0
DEFAULT_MAX_BUFFER_CHARS = 1_000_000
DEFAULT_COMMAND_RESEND_INTERVAL_S = 0.5


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class AppConfig:
    """Application configuration without scenario or video inputs."""

    mode: str = "listen"
    listen_host: str = NetworkConfig.LISTEN_HOST
    ai_g_host: str = NetworkConfig.SERVER_IP
    ai_g_result_port: int = NetworkConfig.RESULT_PORT
    yolo_result_port: int = NetworkConfig.YOLO_RESULT_PORT
    ipc_path: str = "/dev/tcc_ipc_micom"
    dry_run: bool = False
    max_angle_deg: float = DEFAULT_MAX_ANGLE_DEG
    command_resend_interval_s: float = DEFAULT_COMMAND_RESEND_INTERVAL_S
    qt_dashboard_port: int = NetworkConfig.QT_DASHBOARD_PORT
    qt_lane_port: int = NetworkConfig.QT_LANE_PORT


@dataclass
class VehicleState:
    """Current vehicle state published to the Qt dashboard."""

    frame: int = 0
    speed_kmh: float = 0.0
    rpm: float = 552.0
    steer: float = 0.0
    headlights: bool = False
    left_blinker: bool = False
    right_blinker: bool = False
    brake_light: bool = False
    emergency_light: bool = False
    fuel_level: float = 100.0
    zone: str = DetectedZone.NONE
    reason: str = "waiting-for-ai-result"

    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary for dashboard serialization."""

        return {
            "frame": self.frame,
            "speed_kmh": self.speed_kmh,
            "rpm": self.rpm,
            "steer": self.steer,
            "headlights": self.headlights,
            "left_blinker": self.left_blinker,
            "right_blinker": self.right_blinker,
            "brake_light": self.brake_light,
            "fuel_level": self.fuel_level,
            "emergency_light": self.emergency_light,
            "zone": self.zone,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class LaneSteer:
    """Steering value extracted from an AI-G lane-recognition result."""

    value: float
    unit: str = "normalized"


@dataclass
class ObjectDetectionResult:
    """AI-G object detection result with 5-zone support."""

    zone: str
    center_x: int
    center_y: int
    box_x: int
    box_y: int
    box_w: int
    box_h: int
    score: float = 0.0
    label: str = "object"
    detected: bool = True

    @property
    def area(self) -> int:
        return max(0, self.box_w) * max(0, self.box_h)

    @staticmethod
    def determine_zone_5division(
        center_x: int,
        center_y: int,
        screen_width: int = VideoConfig.OUTPUT_W,
        screen_height: int = VideoConfig.OUTPUT_H,
    ) -> str:
        """Classify an object center into left/right/center and upper/lower."""

        x_third1 = int(screen_width * 1 / 3)
        x_third2 = int(screen_width * 2 / 3)
        y_half = int(screen_height * 0.5)

        if center_x < x_third1:
            x_zone = "LEFT"
        elif center_x < x_third2:
            x_zone = "CENTER"
        else:
            x_zone = "RIGHT"

        if x_zone == "CENTER":
            return DetectedZone.CENTER

        y_zone = "UPPER" if center_y < y_half else "LOWER"
        return f"{x_zone}_{y_zone}"

    @staticmethod
    def get_zone_id(zone: str) -> int:
        """Get zone ID for UI display."""

        zone_map = {
            DetectedZone.LEFT_UPPER: ZoneID.LEFT_UPPER,
            DetectedZone.LEFT_LOWER: ZoneID.LEFT_LOWER,
            DetectedZone.CENTER: ZoneID.CENTER,
            DetectedZone.RIGHT_UPPER: ZoneID.RIGHT_UPPER,
            DetectedZone.RIGHT_LOWER: ZoneID.RIGHT_LOWER,
        }
        return int(zone_map.get(zone, ZoneID.CENTER))


@dataclass(frozen=True)
class ControlDecision:
    """Control values derived from lane and object-recognition results."""

    steer: float
    speed_kmh: float
    brake_light: bool
    emergency_light: bool
    left_blinker: bool
    right_blinker: bool
    zone: str
    reason: str


Chunk = Union[bytes, str]


def empty_ai_result_json() -> Dict[str, Any]:
    return {
        "source": "",
        "lane": None,
        "lanePoints": [],
        "objects": [],
    }


def parse_ai_result_json(message: Union[Chunk, Dict[str, Any]]) -> Dict[str, Any]:
    """AI-G 수신 메시지를 dict JSON으로 변환"""

    if isinstance(message, dict):
        return dict(message)
    if isinstance(message, bytes):
        message = message.decode("utf-8", errors="replace")
    if not isinstance(message, str):
        return {}

    try:
        data = json.loads(message.strip())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _dict_or_none(value: Any) -> Optional[Dict[str, Any]]:
    return dict(value) if isinstance(value, dict) else None


def _list_of_dicts(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [dict(value)]
    return []


def normalize_ai_result_json(data: Dict[str, Any]) -> Dict[str, Any]:
    """AI-G 결과를 JSON 구조로 정리"""

    if not isinstance(data, dict):
        data = {}

    result = empty_ai_result_json()
    result["source"] = str(data.get("source", ""))

    lane = _dict_or_none(data.get("lane"))
    if lane is None and "steer" in data:
        lane = {
            "steer": data.get("steer"),
            "unit": data.get("unit", "normalized"),
        }
    result["lane"] = lane

    lane_points = data.get("lanePoints", data.get("lanes", []))
    result["lanePoints"] = lane_points if isinstance(lane_points, list) else []

    objects: List[Dict[str, Any]] = []
    for key in ("objects", "detections", "boxes"):
        objects.extend(_list_of_dicts(data.get(key)))

    nested_yolo = data.get("yolo", data.get("object_detection"))
    if isinstance(nested_yolo, dict):
        nested = normalize_ai_result_json(nested_yolo)
        objects.extend(nested["objects"])

    if not objects and any(key in data for key in ("x", "y", "w", "h", "bbox", "box")):
        objects.append(dict(data))
    result["objects"] = objects

    return result


def merge_ai_result_json(
    current: Dict[str, Any],
    incoming: Dict[str, Any],
    source: str = "combined",
) -> Dict[str, Any]:
    """최신 UFLD JSON과 YOLO JSON을 하나의 JSON으로 합칩니다."""

    merged = normalize_ai_result_json(current)
    update = normalize_ai_result_json(incoming)

    merged["source"] = source or update.get("source", "") or merged.get("source", "")
    if update["lane"] is not None:
        merged["lane"] = update["lane"]
    if update["lanePoints"]:
        merged["lanePoints"] = update["lanePoints"]
    if source == "yolo" or update["objects"]:
        merged["objects"] = update["objects"]

    return merged

# =============================================================================
# 학생 구현 영역: 파싱된 JSON 기반 제어 판단
# =============================================================================
def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def decide_control_from_json(
    data: Dict[str, Any],
    max_angle_deg: float = DEFAULT_MAX_ANGLE_DEG,
) -> ControlDecision:
    lane = data.get("lane") or {}
    objects = data.get("objects") or []

    # 1. 차선 기반 조향
    steer = 0.0
    if isinstance(lane, dict) and lane.get("steer") is not None:
        steer = float(lane["steer"])
        if lane.get("unit") in ("deg", "degree", "degrees"):
            steer = steer / max_angle_deg
    steer = clamp(steer, -1.0, 1.0)

    # 2. 객체 기반 위험 판단
    target = None
    for obj in objects:
        box = obj.get("bbox") or obj.get("box")
        if isinstance(box, list) and len(box) >= 4:
            x, y, w, h = box[:4]
        else:
            x = obj.get("x", obj.get("box_x", 0))
            y = obj.get("y", obj.get("box_y", 0))
            w = obj.get("w", obj.get("box_w", 0))
            h = obj.get("h", obj.get("box_h", 0))

        cx = int(x + w / 2)
        cy = int(y + h / 2)
        zone = ObjectDetectionResult.determine_zone_5division(cx, cy)
        area = int(w) * int(h)

        if target is None or area > target["area"]:
            target = {"zone": zone, "area": area}

    speed = DEFAULT_CRUISE_SPEED_KMH
    brake = False
    emergency = False
    zone = DetectedZone.NONE
    reason = "lane-following"

    if target:
        zone = target["zone"]
        area = target["area"]

        if zone == DetectedZone.CENTER and area > 45000:
            speed = DEFAULT_STOP_SPEED_KMH
            brake = True
            emergency = True
            reason = "center object close: stop"
        elif zone == DetectedZone.CENTER:
            speed = DEFAULT_CAUTION_SPEED_KMH
            brake = True
            reason = "center object: caution"
        elif zone in (DetectedZone.LEFT_LOWER, DetectedZone.RIGHT_LOWER):
            speed = DEFAULT_CAUTION_SPEED_KMH
            reason = f"side lower object: {zone}"

    # 3. 커브에서는 속도 살짝 줄이기
    if speed > 0 and abs(steer) > 0.45:
        speed = min(speed, DEFAULT_CAUTION_SPEED_KMH)
        reason += " / sharp steering"

    return ControlDecision(
        steer=steer,
        speed_kmh=speed,
        brake_light=brake,
        emergency_light=emergency,
        left_blinker=steer < -0.35,
        right_blinker=steer > 0.35,
        zone=zone,
        reason=reason,
    )

def decide_control_from_ai_result(
    message: str,
    max_angle_deg: float = DEFAULT_MAX_ANGLE_DEG,
) -> ControlDecision:
    """단일 AI-G 메시지를 파싱한 뒤 학생 구현 함수로 전달합니다."""

    data = normalize_ai_result_json(parse_ai_result_json(message))
    return decide_control_from_json(data, max_angle_deg=max_angle_deg)


# =============================================================================
# Result Stream Decoder
# =============================================================================


def _decode(chunk: Chunk) -> str:
    if isinstance(chunk, bytes):
        return chunk.decode("utf-8", errors="replace")
    return chunk


def _complete_json_object_span(text: str) -> Tuple[Optional[int], Optional[int]]:
    """문자열에서 완성된 JSON 객체 하나의 시작/끝 위치를 찾습니다."""

    start = None
    depth = 0
    in_string = False
    escaped = False

    for index, char in enumerate(text):
        if start is None:
            if char == "{":
                start = index
                depth = 1
            continue

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return start, index + 1

    return start, None


def _strip_line(line: str) -> str:
    return line.strip("\r\n\t \x00")


def _iter_numeric_lines(text: str) -> Iterator[str]:
    for line in text.splitlines():
        message = _strip_line(line)
        if not message:
            continue
        try:
            float(message)
        except ValueError:
            continue
        yield message


class ResultStreamDecoder:
    """Extract newline, numeric, or concatenated JSON messages from TCP bytes."""

    def __init__(self, max_buffer_chars: int = DEFAULT_MAX_BUFFER_CHARS):
        self.max_buffer_chars = max_buffer_chars
        self._buffer = ""

    def feed(self, chunk: Chunk) -> Iterator[str]:
        self._buffer += _decode(chunk)
        yield from self._pop_messages(final=False)

    def close(self) -> Iterator[str]:
        yield from self._pop_messages(final=True)

    def _pop_messages(self, final: bool) -> Iterator[str]:
        while self._buffer:
            start, end = _complete_json_object_span(self._buffer)

            if start is not None and end is not None:
                prefix = self._buffer[:start]
                yield from _iter_numeric_lines(prefix)
                message = self._buffer[start:end].strip()
                if message:
                    yield message
                self._buffer = self._buffer[end:]
                continue

            if start is not None:
                prefix = self._buffer[:start]
                yield from _iter_numeric_lines(prefix)
                self._buffer = self._buffer[start:]
                if final:
                    message = _strip_line(self._buffer)
                    if message:
                        yield message
                    self._buffer = ""
                return

            consumed = yield from self._pop_lines_from_buffer(final=final)
            if consumed:
                continue

            if len(self._buffer) > self.max_buffer_chars:
                self._buffer = self._buffer[-self.max_buffer_chars:]
            return

    def _pop_lines_from_buffer(self, final: bool) -> Iterator[str]:
        if "\n" not in self._buffer and not final:
            return False

        if final:
            lines = self._buffer.splitlines()
            self._buffer = ""
        else:
            parts = self._buffer.split("\n")
            lines = parts[:-1]
            self._buffer = parts[-1]

        for line in lines:
            message = _strip_line(line)
            if message:
                yield message
        return True


# =============================================================================
# Communication Handlers
# =============================================================================

class IPCController:
    """Handles IPC/CAN communication with the vehicle."""

    def __init__(self, ipc_path: str, dry_run: bool = False):
        self.ipc_path = ipc_path
        self.dry_run = dry_run
        self.ipc_file: Optional[object] = None
        self.enabled = False
        self._initialize()

    def _initialize(self) -> None:
        if self.dry_run:
            logger.info("IPC dry-run mode enabled")
            return

        try:
            self.ipc_file = open(self.ipc_path, "wb")
            self.enabled = True
            logger.info("IPC device opened: %s", self.ipc_path)
        except FileNotFoundError:
            logger.warning("IPC device not found: %s -> dry-run logging", self.ipc_path)
        except Exception as exc:
            logger.error("IPC initialization failed: %s -> dry-run logging", exc)

    def send_command(
        self,
        command_type: int,
        value: int,
        subtype: Optional[int] = None,
    ) -> bool:
        if self.dry_run or not self.enabled or not self.ipc_file:
            if subtype is None:
                logger.info("DRY-RUN CAN 0x%03X %s", command_type, int(value))
            else:
                logger.info("DRY-RUN CAN 0x%03X subtype=%s value=%s", command_type, int(subtype), int(value))
            return True

        try:
            payload = (
                bytes([int(subtype), int(value)]) if subtype is not None
                else int(value).to_bytes(1, "big", signed=True)
            )
            IPC_SendPacketWithIPCHeader(self.ipc_file, 1, 0, int(command_type), payload)
            return True
        except Exception as exc:
            logger.error("IPC send failed: %s", exc)
            return False

    def close(self) -> None:
        if self.ipc_file:
            try:
                self.ipc_file.close()
            except Exception as exc:
                logger.warning("Error closing IPC file: %s", exc)
            finally:
                self.ipc_file = None
                self.enabled = False


class VehicleCommandHandler:
    """Converts control decisions to VCP CAN commands."""

    def __init__(
        self,
        ipc_controller: IPCController,
        resend_interval_s: float = DEFAULT_COMMAND_RESEND_INTERVAL_S,
        time_fn=time.monotonic,
    ):
        self.ipc = ipc_controller
        self.resend_interval_s = max(0.0, float(resend_interval_s))
        self.time_fn = time_fn
        self._last_commands: Dict[Tuple[int, Optional[int]], Tuple[int, float]] = {}

    def _send_if_needed(
        self,
        command_type: int,
        value: int,
        subtype: Optional[int] = None,
    ) -> bool:
        key = (int(command_type), int(subtype) if subtype is not None else None)
        value = int(value)
        now = self.time_fn()
        last = self._last_commands.get(key)

        if last is not None:
            last_value, last_sent_at = last
            if value == last_value and now - last_sent_at < self.resend_interval_s:
                logger.debug(
                    "Skipping unchanged CAN 0x%03X subtype=%s value=%s",
                    int(command_type),
                    key[1],
                    value,
                )
                return False

        sent = self.ipc.send_command(command_type, value, subtype)
        if sent is not False:
            self._last_commands[key] = (value, now)
            return True
        return False

    def set_speed(self, speed_kmh: float) -> None:
        value = max(0, min(127, int(speed_kmh)))
        if self._send_if_needed(VehicleControlCommand.MOTOR_A, value):
            logger.info("Speed command: %.1f km/h", speed_kmh)

    def set_steering(self, steer: float) -> None:
        clamped = clamp(steer, -1.0, 1.0)
        value = int((clamped - 1.0) * 127 / -2.0)
        value = max(0, min(127, value))
        if self._send_if_needed(VehicleControlCommand.WHEEL, value):
            logger.info("Steering command: %.2f -> %s", clamped, value)

    def set_brake_light(self, enabled: bool) -> None:
        action = ControlAction.ON if enabled else ControlAction.OFF
        if self._send_if_needed(VehicleControlCommand.BREAK_LIGHT, action):
            logger.info("Brake Light: %s", "ON" if enabled else "OFF")

    def set_emergency_light(self, enabled: bool) -> None:
        action = ControlAction.ON if enabled else ControlAction.OFF
        if self._send_if_needed(VehicleControlCommand.EMER_SIGNAL, action):
            logger.info("Emergency Light: %s", "ON" if enabled else "OFF")

    def set_turn_signal(self, direction: str, enabled: bool) -> None:
        subtype = TurnSignalDirection.LEFT if direction == "left" else TurnSignalDirection.RIGHT
        action = ControlAction.ON if enabled else ControlAction.OFF
        if self._send_if_needed(VehicleControlCommand.TURN_SIGNAL, action, subtype):
            logger.info("Turn signal %s: %s", direction.upper(), "ON" if enabled else "OFF")

    def apply_decision(self, decision: ControlDecision) -> None:
        """Send all CAN controls needed by one AI result decision."""

        self.set_steering(decision.steer)
        self.set_speed(decision.speed_kmh)
        self.set_brake_light(decision.brake_light)
        self.set_emergency_light(decision.emergency_light)
        self.set_turn_signal("left", decision.left_blinker)
        self.set_turn_signal("right", decision.right_blinker)


class SocketManager:
    """Manages socket connections."""

    def __init__(self):
        self.sockets: Dict[str, socket.socket] = {}

    def create_client_socket(self, name: str, host: str, port: int) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.connect((host, port))
        logger.info("Socket '%s' connected to %s:%s", name, host, port)
        self.sockets[name] = sock
        return sock

    def create_server_socket(self, name: str, port: int, host: str = "0.0.0.0", listen_backlog: int = 1) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen(listen_backlog)
        logger.info("Server socket '%s' listening on %s:%s", name, host, port)
        self.sockets[name] = sock
        return sock

    def close_all(self) -> None:
        for name, sock in self.sockets.items():
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except (OSError, BrokenPipeError):
                pass
            try:
                sock.close()
            except Exception as exc:
                logger.warning("Error closing socket '%s': %s", name, exc)
        self.sockets.clear()


# =============================================================================
# AI Result Control Application
# =============================================================================

class AIResultControlApp:
    """Orchestrates AI-G result reception, CAN output, and Qt status servers."""

    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.running = threading.Event()
        self.lock = threading.RLock()
        self.threads: List[threading.Thread] = []
        self.vehicle_state = VehicleState()
        self.latest_ai_json: Dict[str, Any] = empty_ai_result_json()
        self.ipc = IPCController(cfg.ipc_path, dry_run=cfg.dry_run)
        self.vehicle_cmd = VehicleCommandHandler(
            self.ipc,
            resend_interval_s=cfg.command_resend_interval_s,
        )
        self.socket_mgr = SocketManager()

    def __enter__(self):
        self.running.set()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    def _handle_result_message(self, message: str, source: str = "combined") -> None:
        incoming_json = normalize_ai_result_json(parse_ai_result_json(message))

        with self.lock:
            self.latest_ai_json = merge_ai_result_json(
                self.latest_ai_json,
                incoming_json,
                source=source,
            )
            decision = decide_control_from_json(self.latest_ai_json, max_angle_deg=self.cfg.max_angle_deg)

        self.vehicle_cmd.apply_decision(decision)

        with self.lock:
            self.vehicle_state.frame += 1
            self.vehicle_state.steer = decision.steer
            self.vehicle_state.speed_kmh = decision.speed_kmh
            self.vehicle_state.rpm = 552.0 + abs(decision.speed_kmh) * 40
            self.vehicle_state.brake_light = decision.brake_light
            self.vehicle_state.emergency_light = decision.emergency_light
            self.vehicle_state.left_blinker = decision.left_blinker
            self.vehicle_state.right_blinker = decision.right_blinker
            self.vehicle_state.zone = decision.zone
            self.vehicle_state.reason = decision.reason

        logger.info(
            "%s result -> steer %.3f speed %.1f brake=%s emergency=%s zone=%s reason=%s",
            source.upper(),
            decision.steer,
            decision.speed_kmh,
            decision.brake_light,
            decision.emergency_light,
            decision.zone,
            decision.reason,
        )

    def _iter_socket_messages(self, conn: socket.socket) -> Iterator[str]:
        decoder = ResultStreamDecoder()
        while self.running.is_set():
            chunk = conn.recv(4096)
            if not chunk:
                yield from decoder.close()
                return
            yield from decoder.feed(chunk)

    def _worker_result_listen(self, source: str, port: int) -> None:
        result_sock = self.socket_mgr.create_server_socket(
            f"{source}-result", port, host=self.cfg.listen_host
        )
        result_sock.settimeout(1.0)
        try:
            while self.running.is_set():
                try:
                    conn, addr = result_sock.accept()
                except socket.timeout:
                    continue
                except OSError as exc:
                    if not self.running.is_set():
                        break
                    logger.warning("AI-G %s result accept failed: %s", source, exc)
                    continue
                logger.info("AI-G %s result client connected: %s:%s", source, addr[0], addr[1])
                with conn:
                    for message in self._iter_socket_messages(conn):
                        if message:
                            self._handle_result_message(message, source=source)
                logger.info("AI-G %s result client disconnected: %s:%s", source, addr[0], addr[1])
        finally:
            logger.info("%s result listen worker ended", source)

    def _worker_result_connect(self, source: str, port: int) -> None:
        while self.running.is_set():
            try:
                conn = self.socket_mgr.create_client_socket(f"{source}-result", self.cfg.ai_g_host, port)
                with conn:
                    for message in self._iter_socket_messages(conn):
                        if message:
                            self._handle_result_message(message, source=source)
                break
            except (ConnectionRefusedError, OSError) as exc:
                logger.warning("AI-G %s result connection failed: %s; retrying", source, exc)
                time.sleep(0.5)
        logger.info("%s result connect worker ended", source)

    def _worker_dashboard(self) -> None:
        dashboard_sock = self.socket_mgr.create_server_socket("dashboard", self.cfg.qt_dashboard_port)
        dashboard_sock.settimeout(1.0)
        try:
            while self.running.is_set():
                try:
                    conn, addr = dashboard_sock.accept()
                except socket.timeout:
                    continue
                except OSError as exc:
                    if not self.running.is_set():
                        break
                    logger.warning("Dashboard accept failed: %s", exc)
                    continue
                logger.info("Dashboard connected: %s", addr)
                thread = threading.Thread(target=self._handle_dashboard_client, args=(conn,), daemon=True)
                thread.start()
                self.threads.append(thread)
        finally:
            logger.info("Dashboard server ended")

    def _handle_dashboard_client(self, conn: socket.socket) -> None:
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        try:
            while self.running.is_set():
                with self.lock:
                    payload = self.vehicle_state.to_dict()
                conn.sendall((json.dumps(payload) + "\n").encode("utf-8"))
                time.sleep(1.0 / 30.0)
        except (BrokenPipeError, ConnectionResetError):
            logger.info("Dashboard client disconnected")
        finally:
            conn.close()

    def _worker_zone_visualization(self) -> None:
        zone_sock = self.socket_mgr.create_server_socket("zone", self.cfg.qt_lane_port, listen_backlog=5)
        zone_sock.settimeout(1.0)
        try:
            while self.running.is_set():
                try:
                    conn, addr = zone_sock.accept()
                except socket.timeout:
                    continue
                except OSError as exc:
                    if not self.running.is_set():
                        break
                    logger.warning("Zone accept failed: %s", exc)
                    continue
                logger.info("Zone client connected: %s", addr)
                thread = threading.Thread(target=self._handle_zone_client, args=(conn,), daemon=True)
                thread.start()
                self.threads.append(thread)
        finally:
            logger.info("Zone visualization server ended")

    def _handle_zone_client(self, conn: socket.socket) -> None:
        try:
            while self.running.is_set():
                with self.lock:
                    zone_id = ObjectDetectionResult.get_zone_id(self.vehicle_state.zone)
                conn.sendall(f"object_detected_lane_{zone_id}\n".encode("utf-8"))
                time.sleep(1.0 / 20.0)
        except (BrokenPipeError, ConnectionResetError):
            logger.info("Zone client disconnected")
        finally:
            conn.close()

    def start(self) -> None:
        worker_functions = [self._worker_dashboard, self._worker_zone_visualization]
        if self.cfg.mode == "listen":
            worker_functions.append(lambda: self._worker_result_listen("ufld", self.cfg.ai_g_result_port))
            worker_functions.append(lambda: self._worker_result_listen("yolo", self.cfg.yolo_result_port))
        else:
            worker_functions.append(lambda: self._worker_result_connect("ufld", self.cfg.ai_g_result_port))
            worker_functions.append(lambda: self._worker_result_connect("yolo", self.cfg.yolo_result_port))

        for worker_func in worker_functions:
            thread = threading.Thread(target=worker_func, daemon=False)
            thread.start()
            self.threads.append(thread)

        logger.info("AI result control app started (mode=%s)", self.cfg.mode)

    def stop(self) -> None:
        if not self.running.is_set():
            return
        logger.info("Stopping AI result control app...")
        self.running.clear()
        self.socket_mgr.close_all()
        for thread in self.threads:
            if thread.is_alive():
                thread.join(timeout=1.0)
        self.ipc.close()
        logger.info("Cleanup complete")

    def run(self) -> None:
        self.start()
        try:
            while self.running.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        finally:
            self.stop()


# =============================================================================
# Main
# =============================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="D3-G AI result controller: lane/object recognition results -> CAN commands"
    )
    parser.add_argument("--mode", choices=["listen", "connect"], default="listen",
                        help="listen on D3-G for AI-G result pushes, or connect to AI-G result server")
    parser.add_argument("--listen-host", default=NetworkConfig.LISTEN_HOST,
                        help="bind host for --mode listen")
    parser.add_argument("--ai-ip", default=NetworkConfig.SERVER_IP,
                        help="AI-G host used by --mode connect")
    parser.add_argument("--ai-result-port", type=int, default=NetworkConfig.RESULT_PORT,
                        help="AI-G/D3-G UFLD lane result TCP port")
    parser.add_argument("--yolo-result-port", type=int, default=NetworkConfig.YOLO_RESULT_PORT,
                        help="AI-G/D3-G YOLO object result TCP port")
    parser.add_argument("--ipc-path", default="/dev/tcc_ipc_micom",
                        help="Path to D3-G IPC device")
    parser.add_argument("--dry-run", action="store_true",
                        help="log CAN commands instead of writing /dev/tcc_ipc_micom")
    parser.add_argument("--max-angle-deg", type=float, default=DEFAULT_MAX_ANGLE_DEG,
                        help="degree value that maps lane steering to normalized +/-1")
    parser.add_argument("--command-resend-interval", type=float,
                        default=DEFAULT_COMMAND_RESEND_INTERVAL_S,
                        help="minimum seconds before resending unchanged CAN commands")
    parser.add_argument("--qt-dashboard-port", type=int, default=NetworkConfig.QT_DASHBOARD_PORT)
    parser.add_argument("--qt-lane-port", type=int, default=NetworkConfig.QT_LANE_PORT)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = AppConfig(
        mode=args.mode,
        listen_host=args.listen_host,
        ai_g_host=args.ai_ip,
        ai_g_result_port=args.ai_result_port,
        yolo_result_port=args.yolo_result_port,
        ipc_path=args.ipc_path,
        dry_run=args.dry_run,
        max_angle_deg=args.max_angle_deg,
        command_resend_interval_s=args.command_resend_interval,
        qt_dashboard_port=args.qt_dashboard_port,
        qt_lane_port=args.qt_lane_port,
    )
    with AIResultControlApp(cfg) as app:
        app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
