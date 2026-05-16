import subprocess
import json
import os
from flask import Flask, render_template, jsonify, request

app = Flask(__name__)

def get_pods():
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

@app.route("/")
def index():
    pods = get_pods()
    events = read_json("events.json")
    rca_reports = read_json("rca_reports.json")
    return render_template("index.html", pods=pods, events=events, rca_reports=rca_reports)

@app.route("/trigger-chaos", methods=["POST"])
def trigger_chaos():
    result = subprocess.run(["python", "chaos.py"], capture_output=True, text=True)
    return jsonify({
        "status": "success" if result.returncode == 0 else "error",
        "output": result.stdout + result.stderr
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
