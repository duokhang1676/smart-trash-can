"""Flask web server with WebSocket for realtime detection updates."""

import threading
from flask import Flask, jsonify, render_template
from flask_socketio import SocketIO, emit
import detection_status

app = Flask(__name__, template_folder="templates", static_folder="public", static_url_path="/public")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Track notification thread
_notification_thread = None
_notification_stop_event = threading.Event()


@app.route("/")
def index():
    """Serve the main HTML page."""
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    """API endpoint to get current detection status."""
    status = detection_status.get_status()
    return jsonify(status)


def notify_clients_thread():
    """Background thread to monitor detection updates and broadcast to all connected clients."""
    last_sequence = -1
    while not _notification_stop_event.is_set():
        sequence, status = detection_status.wait_for_update(last_sequence, timeout=5)
        if sequence is not None:
            last_sequence = sequence
            # Emit from the SocketIO server context to all connected clients.
            socketio.emit("status_update", status)


def start_notification_thread():
    """Start background thread for status notifications."""
    global _notification_thread
    _notification_stop_event.clear()
    _notification_thread = threading.Thread(target=notify_clients_thread, daemon=True)
    _notification_thread.start()


def stop_notification_thread():
    """Stop background notification thread."""
    _notification_stop_event.set()
    if _notification_thread:
        _notification_thread.join(timeout=2)


@socketio.on("connect")
def on_connect():
    """Handle new client connection."""
    status = detection_status.get_status()
    emit("status_update", status)


@socketio.on("disconnect")
def on_disconnect():
    """Handle client disconnection."""
    pass


@socketio.on("reset_counts")
def on_reset_counts():
    """Handle reset counts request from client."""
    detection_status.reset_counts()
    status = detection_status.get_status()
    socketio.emit("status_update", status)


def start_web_server(port=5000):
    """Start Flask web server with WebSocket support."""
    start_notification_thread()
    try:
        socketio.run(app, host="0.0.0.0", port=port, debug=False, use_reloader=False)
    finally:
        stop_notification_thread()
