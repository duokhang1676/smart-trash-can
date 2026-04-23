import Jetson.GPIO as GPIO
import time
import os

BUTTON_PIN = 12
BUZZER_PIN = 19

CONTAINER_NAME = "iot-2708"
MAIN_PATH = "/ultralytics/workspace/smart-trash-can/main.py"

DOUBLE_CLICK_TIME = 0.4
LONG_PRESS_TIME = 2

GPIO.setmode(GPIO.BOARD)
GPIO.setup(BUTTON_PIN, GPIO.IN)
GPIO.setup(BUZZER_PIN, GPIO.OUT)

last_state = GPIO.input(BUTTON_PIN)
press_time = 0
release_time = 0
click_count = 0
long_press_fired = False


def beep(duration):
    GPIO.output(BUZZER_PIN, GPIO.HIGH)
    time.sleep(duration)
    GPIO.output(BUZZER_PIN, GPIO.LOW)


def start_main():
    print("Start main.py")
    command = (
        f"docker exec -d {CONTAINER_NAME} "
        f"python3 {MAIN_PATH}"
    )
    os.system(command)


def stop_main():
    print("Stop main.py")
    command = (
        f"docker exec {CONTAINER_NAME} "
        f"pkill -2 -f 'python3 {MAIN_PATH}'"
    )
    os.system(command)


try:
    print("Listening...")

    while True:
        current_state = GPIO.input(BUTTON_PIN)

        if last_state == 1 and current_state == 0:
            press_time = time.time()
            long_press_fired = False

        elif (
            current_state == 0
            and not long_press_fired
            and (time.time() - press_time) >= LONG_PRESS_TIME
        ):
            print("Long press")
            beep(0.5)
            click_count = 0
            long_press_fired = True
            release_time = 0

        elif last_state == 0 and current_state == 1:
            if not long_press_fired:
                click_count += 1
                release_time = time.time()

            long_press_fired = False

        if click_count > 0 and (time.time() - release_time) > DOUBLE_CLICK_TIME:
            if click_count == 1:
                print("Single click")
                beep(0.1)
                start_main()

            elif click_count == 2:
                print("Double click")
                beep(0.1)
                time.sleep(0.1)
                beep(0.1)
                stop_main()

            click_count = 0

        last_state = current_state
        time.sleep(0.01)

except KeyboardInterrupt:
    pass

finally:
    GPIO.cleanup()