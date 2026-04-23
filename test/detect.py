import cv2
import numpy as np
from ultralytics import YOLO


MODEL_PATH = "yolo11n-ver1.engine"
CAMERA_PATH = (
    "nvarguscamerasrc ! video/x-raw(memory:NVMM), width=1640, height=1232, framerate=30/1 ! "
    "nvvidconv ! video/x-raw, format=BGRx ! videoconvert ! video/x-raw, format=BGR ! appsink"
)
CONFIDENCE = 0.5


def main():
    model = YOLO(MODEL_PATH, task="detect")
    cap = cv2.VideoCapture(CAMERA_PATH, cv2.CAP_GSTREAMER)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    if not cap.isOpened():
        print("Can't open camera")
        return

    for _ in range(10):
        cap.read()

    dummy = np.zeros((320, 320, 3), dtype=np.uint8)
    for _ in range(3):
        model(dummy, conf=CONFIDENCE)

    try:
        while True:
            print("Processing frame...")
            ret, frame = cap.read()
            if not ret:
                break

            results = model(frame, conf=CONFIDENCE)
            annotated_frame = results[0].plot()

            labels = []
            for box in results[0].boxes:
                cls_id = int(box.cls[0])
                labels.append(model.names[cls_id])

            if labels:
                print("Detected:", ", ".join(labels))

            # cv2.imshow("Detection", annotated_frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()