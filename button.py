import Jetson.GPIO as GPIO
import time
import subprocess

BUTTON_PIN = 12
BUZZER_PIN = 19

CONTAINER_NAME = "iot-2708"
CONTAINER_WORKDIR = "/ultralytics/workspace/smart-trash-can"
MAIN_SCRIPT = "main.py"

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


def run_command(command):
    subprocess.run(command, check=False)


def is_main_running():
    result = subprocess.run(
        [
            "docker",
            "exec",
            CONTAINER_NAME,
            "sh",
            "-lc",
            "pgrep -af 'python3 .*main.py' | grep -v pgrep",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        check=False,
    )
    return bool(result.stdout.strip())


def start_main():
    if is_main_running():
        print("main.py is already running")
        return

    print("Start main.py")
    try:
        cmd = [
            "docker",
            "exec",
            "-d",
            "-w",
            CONTAINER_WORKDIR,
            CONTAINER_NAME,
            "bash",
            "-lc",
            "python3 -u main.py",
        ]
        print(f"Running command: {' '.join(cmd)}")
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            check=False,
        )
        print(f"Return code: {result.returncode}")
        if result.stdout:
            print(f"Stdout: {result.stdout}")
        if result.stderr:
            print(f"Stderr: {result.stderr}")
        
        if result.returncode != 0:
            print(f"Error starting main.py: {result.stderr}")
        else:
            time.sleep(2)  # Wait longer for process to start
            if is_main_running():
                print("main.py started successfully")
            else:
                print("Warning: main.py may have crashed immediately")
                # Check docker logs for clues
                logs_cmd = ["docker", "logs", "--tail", "20", CONTAINER_NAME]
                logs_result = subprocess.run(logs_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, check=False)
                if logs_result.stdout:
                    print(f"Last container logs:\n{logs_result.stdout}")
    except Exception as e:
        print(f"Exception in start_main: {e}")


def stop_main():
    print("Stop main.py")
    run_command([
        "docker",
        "exec",
        CONTAINER_NAME,
        "sh",
        "-c",
        "pkill -2 -f 'python3 -u main.py' || true",
    ])


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