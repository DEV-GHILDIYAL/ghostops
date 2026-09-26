import subprocess
import json
import os
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'ghostops-dashboard-secret-key-1337'
# Initialize Flask-SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

EVENTS_FILE = "events.json"
RCA_FILE = "rca_reports.json"

def get_pods():
    """Queries minikube/kubectl for active ghostops-app pods."""
    cmd = ["kubectl", "get", "pods", "-l", "app=ghostops-app", "-o", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        try:
            return json.loads(result.stdout).get("items", [])
        except json.JSONDecodeError:
            return []
    return []

def read_json(filename):
    if not os.path.exists(filename):
        return []
    try:
        with open(filename, "r") as f:
            return json.load(f)
    except:
        return []

def write_json(filename, data):
    try:
        with open(filename, "w") as f:
            json.dump(data, f, indent=4)
        return True
    except:
        return False

# --- WebSockets connection event ---
@socketio.on('connect')
def handle_connect():
    print("Dashboard Client connected via WebSocket.")
    # Stream initial full state immediately upon connection
    pods = get_pods()
    events = read_json(EVENTS_FILE)
    rca_reports = read_json(RCA_FILE)
    emit('init_state', {
        'pods': pods,
        'events': events,
        'rca_reports': rca_reports
    })

@socketio.on('request_refresh')
def handle_refresh():
    pods = get_pods()
    events = read_json(EVENTS_FILE)
    rca_reports = read_json(RCA_FILE)
    emit('state_update', {
        'pods': pods,
        'events': events,
        'rca_reports': rca_reports
    })

# --- HTTP Endpoints ---
@app.route("/")
def index():
    pods = get_pods()
    events = read_json(EVENTS_FILE)
    rca_reports = read_json(RCA_FILE)
    return render_template("index.html", pods=pods, events=events, rca_reports=rca_reports)

@app.route("/trigger-chaos", methods=["POST"])
def trigger_chaos():
    # Execute chaos.py script synchronously
    result = subprocess.run(["python", "chaos.py"], capture_output=True, text=True)
    
    # Immediately query fresh state and broadcast to all socket clients
    pods = get_pods()
    socketio.emit('state_update', {
        'pods': pods,
        'events': read_json(EVENTS_FILE),
        'rca_reports': read_json(RCA_FILE)
    })
    
    return jsonify({
        "status": "success" if result.returncode == 0 else "error",
        "output": result.stdout + result.stderr
    })

# --- API endpoints for Healer and RCA to stream real-time updates ---
@app.route("/api/event", methods=["POST"])
def receive_event():
    event_data = request.json
    if not event_data:
        return jsonify({"status": "error", "message": "Missing JSON body"}), 400
        
    events = read_json(EVENTS_FILE)
    events.append(event_data)
    write_json(EVENTS_FILE, events)
    
    # Broadcast to all connected clients
    socketio.emit('new_event', event_data)
    
    # Also broadcast full status update
    socketio.emit('state_update', {
        'pods': get_pods(),
        'events': events,
        'rca_reports': read_json(RCA_FILE)
    })
    return jsonify({"status": "success", "message": "Event logged and streamed."})

@app.route("/api/rca", methods=["POST"])
def receive_rca():
    rca_data = request.json
    if not rca_data:
        return jsonify({"status": "error", "message": "Missing JSON body"}), 400
        
    reports = read_json(RCA_FILE)
    reports.append(rca_data)
    write_json(RCA_FILE, reports)
    
    # Broadcast new RCA to all connected clients
    socketio.emit('new_rca', rca_data)
    
    # Also broadcast full status update
    socketio.emit('state_update', {
        'pods': get_pods(),
        'events': read_json(EVENTS_FILE),
        'rca_reports': reports
    })
    return jsonify({"status": "success", "message": "RCA report logged and streamed."})

# Trigger state broadcasts periodically via background task or let it be event-driven
# We will use active event-driven emissions for instantaneous performance,
# with a fallback loop if necessary.
def background_status_pinger():
    while True:
        socketio.sleep(4)  # Every 4 seconds, check pod states silently and broadcast changes
        try:
            pods = get_pods()
            socketio.emit('pods_update', {'pods': pods})
        except:
            pass

# Start status pinger in background thread
socketio.start_background_task(background_status_pinger)

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
