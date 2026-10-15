#ifndef NPU_ADAS_YOLO_RESULT_SENDER_H
#define NPU_ADAS_YOLO_RESULT_SENDER_H

#include "enlight_network.h"

/* Call after the SDK detector populates its result buffer. */
void yolo_send_objects(const enlight_objs_t *objects);

#endif
