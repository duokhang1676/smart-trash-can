import Jetson.GPIO as GPIO
import time
import os
import subprocess

BUTTON_PIN = 12
BUZZER_PIN = 19

DOUBLE_CLICK_TIME = 0.5
LONG_PRESS_TIME = 2

CONTAINER_NAME = "iot-2708"
PROJECT_PATH = "/ultralytics/workspace/smart-trash-can"
HOTSPOT_SSID = "EcoSort"
HOTSPOT_PASSWORD = "ecosort25"
HOTSPOT_CONN_NAME = "EcoSortHotspot"
WIFI_STATE_FILE = "/tmp/ecosort_prev_wifi.txt"

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


def run_cmd(command):
    return subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        check=False,
    )


def run_nmcli(args):
    """Run nmcli; fallback to sudo -n when direct call is not authorized."""
    direct = run_cmd(["nmcli"] + args)
    if direct.returncode == 0:
        return direct

    err_text = (direct.stderr or "") + (direct.stdout or "")
    auth_markers = ["not authorized", "permission denied", "insufficient privileges"]
    if any(marker in err_text.lower() for marker in auth_markers):
        return run_cmd(["sudo", "-n", "nmcli"] + args)

    return direct


def print_nmcli_auth_hint_if_needed(result):
    if result.returncode == 0:
        return

    err_text = ((result.stderr or "") + "\n" + (result.stdout or "")).lower()
    if "not authorized" in err_text or "a password is required" in err_text:
        print("Network permission missing for nmcli.")
        print("Run button with sudo, or grant passwordless nmcli:")
        print("sudo visudo -f /etc/sudoers.d/90-ecosort-nmcli")
        print("Add: dk ALL=(root) NOPASSWD:/usr/bin/nmcli")


def get_wifi_interface():
    result = run_nmcli(["-t", "-f", "DEVICE,TYPE", "device", "status"])
    if result.returncode != 0:
        print_nmcli_auth_hint_if_needed(result)
        return None

    for line in result.stdout.splitlines():
        parts = line.strip().split(":")
        if len(parts) >= 2 and parts[1] == "wifi":
            return parts[0]
    return None


def save_current_wifi_profile():
    result = run_nmcli(["-t", "-f", "NAME,UUID,TYPE", "connection", "show", "--active"])
    if result.returncode != 0:
        print_nmcli_auth_hint_if_needed(result)
        return

    for line in result.stdout.splitlines():
        parts = line.strip().split(":")
        if len(parts) >= 3 and parts[2] == "802-11-wireless":
            with open(WIFI_STATE_FILE, "w") as f:
                f.write(parts[1] + "\n")
                f.write(parts[0] + "\n")
            return


def switch_to_hotspot():
    interface = get_wifi_interface()
    if not interface:
        print("No Wi-Fi interface found")
        return False

    save_current_wifi_profile()

    # Reuse hotspot profile if it already exists; otherwise create it.
    has_hotspot = run_nmcli(["-t", "-f", "NAME", "connection", "show"])
    if has_hotspot.returncode == 0 and HOTSPOT_CONN_NAME in has_hotspot.stdout:
        up_result = run_nmcli(["connection", "up", HOTSPOT_CONN_NAME, "ifname", interface])
        if up_result.returncode != 0:
            print(f"Cannot enable hotspot profile: {up_result.stderr.strip()}")
            print_nmcli_auth_hint_if_needed(up_result)
            return False
    else:
        create_result = run_nmcli(
            [
                "device",
                "wifi",
                "hotspot",
                "ifname",
                interface,
                "con-name",
                HOTSPOT_CONN_NAME,
                "ssid",
                HOTSPOT_SSID,
                "password",
                HOTSPOT_PASSWORD,
            ]
        )
        if create_result.returncode != 0:
            print(f"Cannot create hotspot: {create_result.stderr.strip()}")
            print_nmcli_auth_hint_if_needed(create_result)
            return False

    print(f"Hotspot enabled: {HOTSPOT_SSID} (password: {HOTSPOT_PASSWORD})")
    return True


def restore_previous_wifi_profile():
    interface = get_wifi_interface()

    run_nmcli(["connection", "down", HOTSPOT_CONN_NAME])

    if not os.path.exists(WIFI_STATE_FILE):
        print("No previous Wi-Fi profile to restore")
        return

    try:
        with open(WIFI_STATE_FILE, "r") as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]
        if len(lines) < 2:
            print("Wi-Fi restore file is invalid")
            return

        prev_uuid, prev_name = lines[0], lines[1]

        up_by_uuid = ["connection", "up", "uuid", prev_uuid]
        if interface:
            up_by_uuid.extend(["ifname", interface])

        result = run_nmcli(up_by_uuid)
        if result.returncode != 0:
            up_by_name = ["connection", "up", prev_name]
            if interface:
                up_by_name.extend(["ifname", interface])
            result = run_nmcli(up_by_name)

        if result.returncode == 0:
            print(f"Restored Wi-Fi: {prev_name}")
        else:
            print(f"Cannot restore previous Wi-Fi: {result.stderr.strip()}")
            print_nmcli_auth_hint_if_needed(result)
    finally:
        try:
            os.remove(WIFI_STATE_FILE)
        except OSError:
            pass


def start_main():
    check_command = (
        f"docker exec {CONTAINER_NAME} "
        f"pgrep -f 'python3 main.py'"
    )

    result = os.system(check_command)

    if result == 0:
        print("main.py is already running")
        beep(0.2)
        return

    if not switch_to_hotspot():
        print("Failed to switch to hotspot. main.py will not start.")
        beep(0.3)
        return

    print("Start main.py")

    command = (
        f"docker exec -d {CONTAINER_NAME} "
        f"bash -c "
        f"\"export PYTHONPATH=/usr/local/lib/python3.8/site-packages:$PYTHONPATH && "
        f"cd {PROJECT_PATH} && "
        f"python3 main.py > main.log 2>&1\""
    )

    start_result = os.system(command)
    if start_result != 0:
        print("Failed to start main.py, restoring previous Wi-Fi")
        restore_previous_wifi_profile()


def stop_main():
    print("Stop main.py")

    command = (
        f"docker exec {CONTAINER_NAME} "
        f"pkill -2 -f 'python3 main.py'"
    )

    os.system(command)
    restore_previous_wifi_profile()


try:
    print("Listening...")
    beep(0.1)
    time.sleep(0.1)
    beep(0.1)
    time.sleep(0.1)
    beep(0.1)
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

            stop_main()

            print("Shutdown Jetson...")
            os.system("sudo shutdown -h now")

            click_count = 0
            long_press_fired = True
            release_time = 0

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