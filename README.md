# GhostOps

A simple demonstration of Kubernetes chaos engineering and self-healing.

## Prerequisites

- Kubernetes cluster (Minikube, Kind, or similar)
- `kubectl` configured and authenticated
- Python 3.x

## Setup

1. **Deploy the application:**
   ```bash
   kubectl apply -f app.yaml
   ```

2. **Verify deployment:**
   ```bash
   kubectl get pods -l app=ghostops-app
   ```

## Usage

### Chaos Engineering
To simulate a pod failure, run the chaos script:
```bash
python chaos.py
```
This will randomly select and delete one of the running `ghostops` pods.

### Self-Healing
To start the automated healer, run:
```bash
python healer.py
```
The healer monitors pod health every 10 seconds. If it detects a pod that is not in the `Running` state, it triggers a `rollout restart` to restore service health.

## Files
- `app.yaml`: Kubernetes Deployment and Service manifests.
- `chaos.py`: Script to terminate random pods.
- `healer.py`: Script to monitor and restore deployment.
- `requirements.txt`: Project dependencies (standard library).
