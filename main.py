import cv2
import numpy as np
import time
import logging
import serial
import os
import base64
import queue
import threading
from ultralytics import YOLO
import detection_status
import web_server

#CONSTANTS
MODEL_PATH = "yolo11n-ver1.engine" #"yolo11n-ver1.pt" # 
SERIAL_PORT = "/dev/ttyUSB0" #'COM12' # /dev/ttyUSB0
CAMERA_PATH = "nvarguscamerasrc ! video/x-raw(memory:NVMM), width=1640, height=1232, framerate=30/1 ! nvvidconv ! video/x-raw, format=BGRx ! videoconvert ! video/x-raw, format=BGR ! appsink"
DATASET_DIR = "dataset"
BAUDRATE = 9600

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("smart-trash-can")


def log_stage(start_time, message):
    elapsed = time.perf_counter() - start_time
    logger.info("[+%.3fs] %s", elapsed, message)


class LatestFrameBuffer:
    """Background reader that always keeps only the newest camera frame."""

    def __init__(self, cap):
        self.cap = cap
        self.lock = threading.Lock()
        self.latest_frame = None
        self.latest_id = 0
        self.running = False
        self.thread = None

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.thread.start()
        logger.info("LatestFrameBuffer started")

    def _reader_loop(self):
        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                logger.warning("Camera read failed in LatestFrameBuffer")
                time.sleep(0.01)
                continue

            with self.lock:
                self.latest_frame = frame
                self.latest_id += 1

    def get_latest(self, last_frame_id, timeout=0.3):
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            with self.lock:
                frame_id = self.latest_id
                frame = self.latest_frame

            if frame is not None and frame_id != last_frame_id:
                return frame_id, frame.copy()

            time.sleep(0.002)

        return None, None

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1)
        logger.info("LatestFrameBuffer stopped")


def parse_bin_status(response, expected_count=4):
    """Parse comma-separated bin status values safely.

    Accepts integers or float-like tokens (e.g. 1, 0, 1.0),
    then normalizes each value to 0/1.
    Returns None when payload is not a valid bin-status message.
    """
    tokens = [token.strip() for token in response.split(",") if token.strip()]
    if len(tokens) != expected_count:
        return None

    parsed = []
    for token in tokens:
        try:
            value = float(token)
        except ValueError:
            return None

        parsed.append(1 if value >= 0.5 else 0)

    return parsed

# Define groups of trash for 4 bins
group_1 = ["plastic"]
group_2 = ["paper", "tissue"]
group_3 = ["plastic-bag", "foam-box", "organic", "plastic-cup"]
group_4 = ["battery", "metal"]

def create_frame_thumbnail_data_url(frame, center_xy=None, width=480, crop_scale=0.65, jpeg_quality=75):
    """Convert a frame to compact JPEG data URL for web UI preview."""
    image_h, image_w = frame.shape[:2]

    if center_xy is not None:
        cx, cy = center_xy
        crop_w = max(120, int(image_w * crop_scale))
        crop_h = max(90, int(image_h * crop_scale))

        x1 = max(0, min(cx - crop_w // 2, image_w - crop_w))
        y1 = max(0, min(cy - crop_h // 2, image_h - crop_h))
        x2 = min(image_w, x1 + crop_w)
        y2 = min(image_h, y1 + crop_h)
        frame = frame[y1:y2, x1:x2]
        image_h, image_w = frame.shape[:2]

    if image_w > width:
        scale = width / float(image_w)
        frame = cv2.resize(frame, (width, int(image_h * scale)), interpolation=cv2.INTER_AREA)

    ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality])
    if not ok:
        return ""

    encoded = base64.b64encode(buffer).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"

def create_dataset_files(model):
    # Create dataset directories and labelmap/classes files.
    images_dir = os.path.join(DATASET_DIR, "images")
    labels_dir = os.path.join(DATASET_DIR, "labels")
    labelmap_path = os.path.join(DATASET_DIR, "labelmap.txt")
    classes_path = os.path.join(DATASET_DIR, "classes.txt")
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(labels_dir, exist_ok=True)

    if isinstance(model.names, dict):
        class_names = [model.names[i] for i in sorted(model.names.keys())]
    else:
        class_names = list(model.names)

    with open(labelmap_path, "w", encoding="utf-8") as labelmap_file:
        labelmap_file.write("\n".join(class_names))

    with open(classes_path, "w", encoding="utf-8") as classes_file:
        classes_file.write("\n".join(class_names))

    return images_dir, labels_dir


# Worker thread to save images and labels without blocking main loop.
def save_worker(save_queue):
    logger.info("save_worker thread started")
    while True:
        item = save_queue.get()
        if item is None:
            logger.info("save_worker received stop signal")
            save_queue.task_done()
            break

        image_path, label_path, annotated_frame, yolo_lines = item
        cv2.imwrite(image_path, annotated_frame)
        with open(label_path, "w", encoding="utf-8") as label_file:
            label_file.write("\n".join(yolo_lines))
        print(f"Image saved: {image_path}")
        print(f"Labels saved: {label_path}")
        save_queue.task_done()
    logger.info("save_worker thread stopped")

# Helper function to determine which group a label belongs to.
def get_group_for_label(label):
    if label in group_1:
        return 1
    if label in group_2:
        return 2
    if label in group_3:
        return 3
    if label in group_4:
        return 4
    return None

# Process a single frame: detect objects, determine groups, send serial commands, and queue saves.
def process_frame(frame, model, ser, save_queue, images_dir, labels_dir, detection_state, full_status):
    detect_started = time.perf_counter()
    # Detect
    results = model(frame, conf=0.5)
    infer_ms = (time.perf_counter() - detect_started) * 1000.0
    if infer_ms > 300:
        logger.warning("Slow inference: %.1f ms", infer_ms)
    if len(results[0].boxes) > 0:
        # Debounce: skip if command was sent recently (within debounce_seconds)
        current_time = time.time()
        if current_time - detection_state['last_send_time'] < detection_state['debounce_seconds']:
            return  # Skip processing - too soon after last detection
        saved_any = False
        image_h, image_w = frame.shape[:2]
        yolo_lines = []
        detected_groups = set()
        detected_labels = []
        best_center_xy = None
        best_conf = -1.0
        for box in results[0].boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            cls_id = int(box.cls[0])
            label = model.names[cls_id]
            conf = float(box.conf[0])
            detected_labels.append(label)
            x_center = ((x1 + x2) / 2) / image_w
            y_center = ((y1 + y2) / 2) / image_h
            box_w = (x2 - x1) / image_w
            box_h = (y2 - y1) / image_h
            yolo_lines.append(f"{cls_id} {x_center:.6f} {y_center:.6f} {box_w:.6f} {box_h:.6f}")
            detected_groups.add(get_group_for_label(label))

            if conf > best_conf:
                best_conf = conf
                best_center_xy = ((x1 + x2) // 2, (y1 + y2) // 2)

        if len(detected_groups) == 1 and None not in detected_groups:
            for group in detected_groups:
                # Update last send time to enable debouncing
                detection_state['last_send_time'] = time.time()
                # Increment count for valid group
                detection_status.increment_counts(group)
                if group == 1:
                    ser.write(b'1')
                elif group == 2:
                    ser.write(b'2')
                elif group == 3:
                    ser.write(b'3')
                elif group == 4:
                    ser.write(b'4')
                # Save frame and labels for valid detection
                if full_status[group - 1] == 0:  # Only save if bin is not full
                    saved_any = True

        # Update web UI with detected labels and detected frame thumbnail.
        frame_thumbnail = create_frame_thumbnail_data_url(frame, center_xy=best_center_xy)
        detection_status.update_detection(detected_labels, detected_groups, frame_thumbnail)

        if saved_any:
            sample_name = str(int(time.time() * 1000))
            image_path = os.path.join(images_dir, f"{sample_name}.jpg")
            label_path = os.path.join(labels_dir, f"{sample_name}.txt")
            # Save in background to avoid delaying serial/event loop.
            save_queue.put((image_path, label_path, frame.copy(), yolo_lines[:]))

# Main loop to read from camera, process frames, and handle serial communication.
def main_loop(model, frame_buffer, ser, save_queue, images_dir, labels_dir, detection_state, full_status):
    frame_count = 0
    last_frame_id = 0
    loop_started = time.perf_counter()
    logger.info("main_loop started")
    while True:
        frame_count += 1

        serial_t0 = time.perf_counter()
        response = ""
        if ser.in_waiting > 0:
            response = ser.readline().decode(errors="ignore").strip()
        serial_wait_ms = (time.perf_counter() - serial_t0) * 1000.0
        if serial_wait_ms > 700:
            logger.warning("Serial read wait: %.1f ms", serial_wait_ms)

        if response:
            parsed_status = parse_bin_status(response, expected_count=len(full_status))
            if parsed_status is None:
                logger.warning("Ignored non-bin serial payload: %s", response)
            else:
                full_status = parsed_status
                print(f"Received bin status: {full_status}")

        read_t0 = time.perf_counter()
        frame_id, frame = frame_buffer.get_latest(last_frame_id, timeout=0.3)
        read_ms = (time.perf_counter() - read_t0) * 1000.0
        if read_ms > 200:
            logger.warning("Camera read slow: %.1f ms", read_ms)

        if frame is None:
            logger.warning("No new frame available at count=%d", frame_count)
            continue

        last_frame_id = frame_id
        
        # frame_count += 1
        # if frame_count % 5 != 0:
        #     continue
        process_frame(frame, model, ser, save_queue, images_dir, labels_dir, detection_state, full_status)

        if frame_count % 30 == 0:
            elapsed = time.perf_counter() - loop_started
            fps = frame_count / elapsed if elapsed > 0 else 0.0
            logger.info("Loop heartbeat: frames=%d, avg_fps=%.2f", frame_count, fps)

    logger.info("main_loop exited")

# Main entry point: initialize model, camera, serial, and start processing loop.
def main():
    start_time = time.perf_counter()
    log_stage(start_time, "Program start")

    log_stage(start_time, f"Loading model: {MODEL_PATH}")
    model = YOLO(MODEL_PATH, task="detect")
    log_stage(start_time, "Model loaded")

    log_stage(start_time, "Opening camera")
    cap = cv2.VideoCapture(CAMERA_PATH, cv2.CAP_GSTREAMER)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    log_stage(start_time, "Camera open request sent")

    if not cap.isOpened():
        logger.error("Can't open camera")
        return
    log_stage(start_time, "Camera is opened")

    # Warm-up camera
    log_stage(start_time, "Camera warm-up started")
    for _ in range(10):
        cap.read()
    log_stage(start_time, "Camera warm-up finished")

    log_stage(start_time, "Starting latest-frame buffer")
    frame_buffer = LatestFrameBuffer(cap)
    frame_buffer.start()
    log_stage(start_time, "Latest-frame buffer started")

    # Warm-up model
    log_stage(start_time, "Model warm-up started")
    dummy = np.zeros((320, 320, 3), dtype=np.uint8)
    for _ in range(5):
        model(dummy)
    log_stage(start_time, "Model warm-up finished")

    log_stage(start_time, f"Opening serial: {SERIAL_PORT} @ {BAUDRATE}")
    ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=0)
    log_stage(start_time, "Serial opened")

    time.sleep(2)  # Wait for serial connection to initialize.
    log_stage(start_time, "Serial init wait done")

    log_stage(start_time, "Preparing dataset directories")
    images_dir, labels_dir = create_dataset_files(model)
    log_stage(start_time, f"Dataset ready: images={images_dir}, labels={labels_dir}")

    log_stage(start_time, "Starting save worker thread")
    save_queue = queue.Queue()
    save_thread = threading.Thread(target=save_worker, args=(save_queue,), daemon=True)
    save_thread.start()
    log_stage(start_time, "Save worker thread started")

    # Start web server in separate thread
    log_stage(start_time, "Starting web server thread")
    web_thread = threading.Thread(target=web_server.start_web_server, args=(5000,), daemon=True)
    time.sleep(2)  # Give web server a moment to start before main loop begins.
    web_thread.start()
    logger.info("Web server started at http://localhost:5000")
    log_stage(start_time, "Web server thread started")

    try:
        time.sleep(1)  # Short delay to ensure everything is initialized before starting main loop.
        log_stage(start_time, "Pre-loop delay done")
        full_status = [0] * 4  # Assuming 4 bins (1 = full, 0 = not full)
        # Debounce state: track last time command was sent to prevent rapid re-triggering
        detection_state = {
            'last_send_time': 0,
            'debounce_seconds': 2.5  # Wait 2.5 seconds between commands for same object
        }
        log_stage(start_time, "Entering main_loop")
        main_loop(model, frame_buffer, ser, save_queue, images_dir, labels_dir, detection_state, full_status)
        log_stage(start_time, "main_loop returned")
    except Exception:
        logger.exception("Unhandled exception in main")
        raise
    finally:
        log_stage(start_time, "Cleanup started")
        frame_buffer.stop()
        ser.close()
        save_queue.put(None)
        save_queue.join()
        save_thread.join()
        cap.release()
        cv2.destroyAllWindows()
        log_stage(start_time, "Cleanup finished")


if __name__ == "__main__":
    main()