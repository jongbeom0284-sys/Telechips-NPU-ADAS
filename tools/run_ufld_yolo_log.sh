#!/bin/sh
UFLD_PATH=${UFLD_PATH:-/home/root/UFLD_quantized}
YOLO_PATH=${YOLO_PATH:-/home/root/yolov8s_quantized}
VIDEO_PATH=${VIDEO_PATH:-/dev/video2}
pkill ufld_log_viewer 2>/dev/null
pkill ufld_fb_viewer 2>/dev/null
tcnnapp -n "$UFLD_PATH" -N "$YOLO_PATH" -p "$VIDEO_PATH" -g log 2>&1 | /home/root/ufld_log_viewer
