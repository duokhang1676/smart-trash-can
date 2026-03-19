import cv2
import numpy as np
import time
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
CAMERA_PATH = "/dev/video0" # /dev/video0
DATASET_DIR = "dataset"
BAUDRATE = 9600

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
    while True:
        item = save_queue.get()
        if item is None:
            save_queue.task_done()
            break

        image_path, label_path, annotated_frame, yolo_lines = item
        cv2.imwrite(image_path, annotated_frame)
        with open(label_path, "w", encoding="utf-8") as label_file:
            label_file.write("\n".join(yolo_lines))
        print(f"Image saved: {image_path}")
        print(f"Labels saved: {label_path}")
        save_queue.task_done()

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
def process_frame(frame, model, ser, save_queue, images_dir, labels_dir, object_detected, full_status):
    # Detect
    results = model(frame, conf=0.5)
    if len(results[0].boxes) > 0:
        if object_detected:
            return  # Skip processing if we already have a detected object until it clears to avoid duplicates.
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
            object_detected = True
            for group in detected_groups:
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
    else:
        object_detected = False

# Main loop to read from camera, process frames, and handle serial communication.
def main_loop(model, cap, ser, save_queue, images_dir, labels_dir, object_detected, full_status):
    if not cap.isOpened():
        print("Can't open camera")
        return

    frame_count = 0
    while True:
        response = ser.readline().decode().strip()
        if response:
            full_status = [int(x) for x in response.split(',') if x.strip()]
            print(f"Received bin status: {full_status}")
        ret, frame = cap.read()
        if not ret:
            break
        
        # frame_count += 1
        # if frame_count % 5 != 0:
        #     continue
        process_frame(frame, model, ser, save_queue, images_dir, labels_dir, object_detected, full_status)

# Main entry point: initialize model, camera, serial, and start processing loop.
def main():
    model = YOLO(MODEL_PATH, task="detect")
    cap = cv2.VideoCapture(CAMERA_PATH, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    # Warm-up camera
    for _ in range(10):
        cap.read()

    # Warm-up model
    dummy = np.zeros((320, 320, 3), dtype=np.uint8)
    for _ in range(5):
        model(dummy)

    ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=1)
    time.sleep(2)  # Wait for serial connection to initialize.

    images_dir, labels_dir = create_dataset_files(model)

    save_queue = queue.Queue()
    save_thread = threading.Thread(target=save_worker, args=(save_queue,), daemon=True)
    save_thread.start()

    # Start web server in separate thread
    web_thread = threading.Thread(target=web_server.start_web_server, args=(5000,), daemon=True)
    time.sleep(2)  # Give web server a moment to start before main loop begins.
    web_thread.start()
    print("Web server started at http://localhost:5000")

    try:
        time.sleep(1)  # Short delay to ensure everything is initialized before starting main loop.
        full_status = [0] * 4  # Assuming 4 bins (1 = full, 0 = not full)
        object_detected = False
        main_loop(model, cap, ser, save_queue, images_dir, labels_dir, object_detected, full_status)
    finally:
        save_queue.put(None)
        save_queue.join()
        save_thread.join()
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()