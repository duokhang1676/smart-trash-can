"""Global detection status manager for sharing data between main loop and web server."""

import threading

# Thread-safe dictionary to store current detection status
_status_lock = threading.Lock()
_status_condition = threading.Condition(_status_lock)
_detection_status = {
    "detected_labels": [],
    "detected_groups": [],
    "frame_thumbnail": "",
    "sequence": 0,
    "counts": {
        "group_1": 0,
        "group_2": 0,
        "group_3": 0,
        "group_4": 0,
        "total": 0
    }
}


def update_detection(detected_labels, detected_groups, frame_thumbnail=""):
    """Update detection status with current frame results."""
    with _status_condition:
        _detection_status["detected_labels"] = list(detected_labels)
        _detection_status["detected_groups"] = list(detected_groups)
        _detection_status["frame_thumbnail"] = frame_thumbnail
        _detection_status["sequence"] += 1
        _status_condition.notify_all()


def increment_counts(group_id):
    """Increment count for a specific group."""
    with _status_lock:
        if group_id == 1:
            _detection_status["counts"]["group_1"] += 1
        elif group_id == 2:
            _detection_status["counts"]["group_2"] += 1
        elif group_id == 3:
            _detection_status["counts"]["group_3"] += 1
        elif group_id == 4:
            _detection_status["counts"]["group_4"] += 1
        _detection_status["counts"]["total"] += 1


def get_status():
    """Get current detection status."""
    with _status_lock:
        return {
            "detected_labels": list(_detection_status["detected_labels"]),
            "detected_groups": list(_detection_status["detected_groups"]),
            "frame_thumbnail": _detection_status["frame_thumbnail"],
            "counts": _detection_status["counts"].copy()
        }


def wait_for_update(last_sequence, timeout=30):
    """Wait until a new update is available, then return (sequence, status)."""
    with _status_condition:
        if _detection_status["sequence"] <= last_sequence:
            _status_condition.wait(timeout=timeout)

        if _detection_status["sequence"] <= last_sequence:
            return None, None

        return _detection_status["sequence"], {
            "detected_labels": list(_detection_status["detected_labels"]),
            "detected_groups": list(_detection_status["detected_groups"]),
            "frame_thumbnail": _detection_status["frame_thumbnail"],
            "counts": _detection_status["counts"].copy()
        }


def reset_counts():
    """Reset all counts to zero."""
    with _status_condition:
        _detection_status["counts"] = {
            "group_1": 0,
            "group_2": 0,
            "group_3": 0,
            "group_4": 0,
            "total": 0
        }
        _detection_status["sequence"] += 1
        _status_condition.notify_all()
