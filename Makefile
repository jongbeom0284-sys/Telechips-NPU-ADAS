CC ?= cc
PYTHON ?= python3
CFLAGS ?= -O2 -Wall -Wextra -std=gnu99

.PHONY: all check check-sdk
all: build/ufld_log_viewer

build/ufld_log_viewer: tools/ufld_log_viewer.c
	mkdir -p build
	$(CC) $(CFLAGS) $< -o $@

check: all
	$(PYTHON) -m py_compile control/Data_parsing_student.py examples/lenet/train_lenet.py tools/replay_control.py
	$(PYTHON) -m unittest discover -s tests -v
	sh -n tools/run_ufld_yolo_log.sh

# ENLIGHT_INCLUDE points to the installed SDK's build_network/enlight directory.
check-sdk:
	test -n "$(ENLIGHT_INCLUDE)"
	mkdir -p build
	$(CC) $(CFLAGS) -D__i386__ -I"$(ENLIGHT_INCLUDE)" -c npu/ufld/post_process.c -o build/ufld_post_process.o
	$(CC) $(CFLAGS) -D__i386__ -I"$(ENLIGHT_INCLUDE)" -c npu/ufld/custom_postproc.c -o build/custom_postproc.o
	$(CC) $(CFLAGS) -D__i386__ -I"$(ENLIGHT_INCLUDE)" -c npu/yolo/result_sender.c -o build/yolo_result_sender.o
