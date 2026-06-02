"""
GPU cluster management script for demo use.

Usage:
    python manage_gpu.py create              -- try L4 across regions until one works
    python manage_gpu.py create t4           -- try T4 instead
    python manage_gpu.py create l4 us-east4  -- specific GPU + region
    python manage_gpu.py status              -- check state and billing
    python manage_gpu.py delete              -- shut down and stop all charges
"""
import os
import sys
import time
import json

sys.path.insert(0, os.path.dirname(__file__))
from CloudManager import CloudManager
from google.auth.transport.requests import AuthorizedSession

RESOURCE_ID  = "demo-gpu"
SECRETS_PATH = os.path.join(os.path.dirname(__file__), "client_secrets.json")
STATE_FILE   = os.path.join(os.path.dirname(__file__), ".demo-gpu-state.json")

GPU_SPECS = {
    "l4": ("g2-standard-4", "NVIDIA_L4",       1.37),
    "t4": ("n1-standard-4", "NVIDIA_TESLA_T4",  0.54),
}

# L4 quota (value=1): europe-west4, europe-west3, europe-west1, europe-west6, us-central1
# T4 quota: europe-west4 confirmed; us-central1/us-east1/us-east4/us-west1 increase pending
L4_REGIONS = [
    "europe-west4",    # Docker image is here -> fastest pull; confirmed L4 quota
    "us-central1",     # confirmed L4 quota (capacity issues before - retry last)
    "europe-west3",    # confirmed L4 quota
    "europe-west1",    # confirmed L4 quota
    "europe-west6",    # confirmed L4 quota
]
T4_REGIONS = [
    "europe-west4",    # confirmed T4 quota
    # "us-central1",     # quota increase pending
    # "us-east1",        # quota increase pending
    # "us-east4",        # quota increase pending
    # "us-west1",        # quota increase pending
]


# Local state (tracks which region the resource was created in)

def _save_state(region: str, gpu: str):
    with open(STATE_FILE, "w") as f:
        json.dump({"region": region, "gpu": gpu, "resource_id": RESOURCE_ID}, f)

def _load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _clear_state():
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)


# API helpers

def _manager() -> CloudManager:
    m = CloudManager(client_secrets_path=SECRETS_PATH)
    m.authenticate()
    m.get_project_info()
    return m


def _api_url(m: CloudManager, region: str, suffix: str = "") -> str:
    base = (
        f"https://{region}-aiplatform.googleapis.com/v1"
        f"/projects/{m.project_id}/locations/{region}"
        f"/persistentResources/{RESOURCE_ID}"
    )
    return base + suffix


def _get_state(m: CloudManager, region: str) -> str:
    try:
        resp = AuthorizedSession(m.creds).get(_api_url(m, region))
        if resp.status_code == 404:
            return "NOT_FOUND"
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            print(f"[GPU] Resource error: {data['error'].get('message', data['error'])}")
        return data.get("state", "UNKNOWN")
    except Exception:
        return "UNKNOWN"


def _try_create(m: CloudManager, region: str, machine_type: str, accelerator_type: str) -> bool:
    """Returns True if creation request accepted, False if region has no capacity."""
    session = AuthorizedSession(m.creds)
    url = (
        f"https://{region}-aiplatform.googleapis.com/v1"
        f"/projects/{m.project_id}/locations/{region}"
        f"/persistentResources?persistentResourceId={RESOURCE_ID}"
    )
    body = {
        "resourcePools": [{
            "machineSpec": {
                "machineType":      machine_type,
                "acceleratorType":  accelerator_type,
                "acceleratorCount": 1,
            },
            "replicaCount": "1",
            "diskSpec": {
                "bootDiskType":   "pd-ssd",
                "bootDiskSizeGb": 200,
            },
        }]
    }
    resp = session.post(url, json=body)
    if resp.ok:
        return True
    text = resp.text.lower()
    if resp.status_code in (429, 503) or "insufficient" in text or "quota" in text or "unavailable" in text:
        return False
    print(f"[GPU] Unexpected error {resp.status_code}: {resp.text}")
    resp.raise_for_status()


def _delete_in_region(m: CloudManager, region: str):
    """Delete resource in a specific region and poll until gone."""
    resp = AuthorizedSession(m.creds).delete(_api_url(m, region))
    if not resp.ok and resp.status_code != 404:
        print(f"[GPU] Delete request error: {resp.text}")
        return
    for _ in range(12):
        time.sleep(15)
        state = _get_state(m, region)
        if state == "NOT_FOUND":
            return
        print(f"[GPU]   still deleting... ({state})")
    print("[GPU] Resource may still be deleting - check Cloud Console.")


# Commands

def cmd_create(gpu: str = "l4", forced_region: str = None):
    if gpu not in GPU_SPECS:
        print(f"Unknown GPU '{gpu}'. Choose: {', '.join(GPU_SPECS)}")
        sys.exit(1)

    machine_type, accelerator_type, cost_hr = GPU_SPECS[gpu]
    regions = [forced_region] if forced_region else (L4_REGIONS if gpu == "l4" else T4_REGIONS)

    m = _manager()

    # If resource already exists from a previous run, reuse it
    saved = _load_state()
    if saved:
        region = saved["region"]
        state  = _get_state(m, region)
        if state == "RUNNING":
            print(f"[GPU] '{RESOURCE_ID}' is already RUNNING in {region}.")
            print(f"[GPU] Billing at ~${cost_hr:.2f}/hr. Run the app: python ../main.py")
            m.vertex_region = region
            m.use_persistent_resource(RESOURCE_ID)
            return
        if state in ("ERROR", "STOPPED"):
            print(f"[GPU] Previous resource in {region} is {state}. Cleaning up...")
            _delete_in_region(m, region)
            _clear_state()

    # Try each region until one accepts the request
    chosen_region = None
    for region in regions:
        print(f"[GPU] Trying {region}...", end=" ", flush=True)
        accepted = _try_create(m, region, machine_type, accelerator_type)
        if accepted:
            print("accepted!")
            chosen_region = region
            _save_state(region, gpu)
            break
        else:
            print("no capacity.")

    if not chosen_region:
        print(f"\n[GPU] No region had available {gpu.upper()} capacity.")
        other = "t4" if gpu == "l4" else "l4"
        print(f"[GPU] Try the other GPU type: python manage_gpu.py create {other}")
        sys.exit(1)

    print(f"[GPU] Provisioning in {chosen_region}. Polling every 30s (up to 15 min)...")
    for i in range(30):
        time.sleep(30)
        state = _get_state(m, chosen_region)
        elapsed = (i + 1) * 30
        print(f"[GPU] {elapsed}s - {state}")
        if state == "RUNNING":
            print(f"\n[GPU] Ready! ~${cost_hr:.2f}/hr is now billing.")
            print(f"[GPU] Region: {chosen_region}")
            print(f"[GPU] Run the app:      cd .. && python main.py")
            print(f"[GPU] Stop charges:     python manage_gpu.py delete")
            return
        if state in ("ERROR", "UNKNOWN"):
            print(f"\n[GPU] Failed in {chosen_region}. Try again - will pick a different region.")
            _clear_state()
            return

    print("[GPU] Still provisioning - check Cloud Console.")


def cmd_status():
    saved = _load_state()
    m = _manager()

    if not saved:
        print("[GPU] No active resource found. Run: python manage_gpu.py create")
        return

    region = saved["region"]
    gpu    = saved.get("gpu", "l4")
    _, _, cost_hr = GPU_SPECS.get(gpu, GPU_SPECS["l4"])

    state = _get_state(m, region)
    print(f"\n[GPU] PersistentResource '{RESOURCE_ID}' in {region}: {state}")

    if state == "RUNNING":
        print(f"[GPU] Billing at ~${cost_hr:.2f}/hr  (~${cost_hr * 24:.2f}/day)")
        print("[GPU] Stop charges: python manage_gpu.py delete")
    elif state == "NOT_FOUND":
        print("[GPU] Resource is gone. Clearing local state.")
        _clear_state()
    elif state == "ERROR":
        print("[GPU] Run 'create' again to delete and retry.")


def cmd_delete():
    saved = _load_state()
    m = _manager()

    if not saved:
        print("[GPU] No active resource tracked locally. Checking us-central1 as fallback...")
        region = "us-central1"
    else:
        region = saved["region"]

    state = _get_state(m, region)
    if state == "NOT_FOUND":
        print(f"[GPU] Resource not found in {region}. No charges.")
        _clear_state()
        return

    print(f"[GPU] Found '{RESOURCE_ID}' in {region} ({state}). Deleting...")
    _delete_in_region(m, region)
    state = _get_state(m, region)
    if state == "NOT_FOUND":
        print("[GPU] Deleted. GPU charges have stopped.")
        _clear_state()
    else:
        print(f"[GPU] State is '{state}' - may still be stopping. Run 'status' to confirm.")


# Entry point

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] not in ("create", "status", "delete"):
        print(__doc__)
        sys.exit(1)

    cmd = args[0]
    if cmd == "create":
        gpu    = args[1].lower() if len(args) > 1 else "l4"
        region = args[2]         if len(args) > 2 else None
        cmd_create(gpu, region)
    elif cmd == "status":
        cmd_status()
    elif cmd == "delete":
        cmd_delete()
