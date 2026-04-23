import Jetson.GPIO as GPIO
import time
import subprocess
import signal

BUTTON_PIN = 12
BUZZER_PIN = 19

DOUBLE_CLICK_TIME = 0.5
LONG_PRESS_TIME = 2

GPIO.setmode(GPIO.BOARD)

GPIO.setup(
    BUTTON_PIN,
    GPIO.IN,
    pull_up_down=GPIO.PUD_UP
)

GPIO.setup(BUZZER_PIN, GPIO.OUT)

last_state = GPIO.input(BUTTON_PIN)
press_time = 0
release_time = 0
click_count = 0
long_press_fired = False

main_process = None


def beep(duration):
    GPIO.output(BUZZER_PIN, GPIO.HIGH)
    time.sleep(duration)
    GPIO.output(BUZZER_PIN, GPIO.LOW)


def start_main():
    global main_process

    if main_process is None or main_process.poll() is not None:
        print("Start main.py")
        main_process = subprocess.Popen(
            ["python3", "main.py"]
        )
    else:
        print("main.py is already running")


def stop_main():
    global main_process

    if main_process is not None and main_process.poll() is None:
        print("Stop main.py")
        main_process.send_signal(signal.SIGINT)
        main_process.wait()
        main_process = None
    else:
        print("main.py is not running")


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

        elif last_state == 0 and current_state == 1:
            if not long_press_fired:
                click_count += 1
                release_time = time.time()

            long_press_fired = False

        if (
            click_count > 0
            and (time.time() - release_time) > DOUBLE_CLICK_TIME
        ):
            if click_count == 1:
                print("Single click")
                beep(0.1)
                start_main()

            elif click_count >= 2:
                print("Double click")
                beep(0.1)
                time.sleep(0.1)
                beep(0.1)
                stop_main()

            click_count = 0

        last_state = current_state
        time.sleep(0.02)

except KeyboardInterrupt:
    stop_main()
    GPIO.cleanup()