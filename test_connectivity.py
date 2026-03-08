#!/usr/bin/env python3
"""Quick connectivity test for Edilkamin pellet stove."""

import argparse
import sys
import time

import httpx
from pycognito import Cognito

USER_POOL_ID = "eu-central-1_BYmQ2VBlo"
CLIENT_ID = "7sc1qltkqobo3ddqsk4542dg2h"
API_URL = "https://the-mind-api.edilkamin.com/"


def sign_in(username: str, password: str) -> str:
    print(f"[1/3] Authenticating as {username}...")
    t0 = time.time()
    cognito = Cognito(USER_POOL_ID, CLIENT_ID, username=username)
    cognito.authenticate(password)
    user = cognito.get_user()
    token = user._metadata["id_token"]
    print(f"  OK  — got id_token in {time.time() - t0:.2f}s")
    return token


def test_device_info(token: str, mac: str) -> dict | None:
    mac = mac.replace(":", "").lower()
    url = f"{API_URL}device/{mac}/info"
    headers = {"Authorization": f"Bearer {token}"}
    print(f"[2/3] GET {url}")
    t0 = time.time()
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.get(url, headers=headers)
            r.raise_for_status()
            data = r.json()
            print(f"  OK  — {r.status_code} in {time.time() - t0:.2f}s")
            return data
    except httpx.HTTPStatusError as e:
        print(f"  FAIL — HTTP {e.response.status_code}: {e.response.text[:200]}")
    except httpx.ReadTimeout:
        print(f"  FAIL — ReadTimeout after {time.time() - t0:.2f}s")
    except Exception as e:
        print(f"  FAIL — {type(e).__name__}: {e}")
    return None


def test_mqtt_check(token: str, mac: str) -> str | None:
    mac = mac.replace(":", "").lower()
    url = f"{API_URL}mqtt/command"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"mac_address": mac, "name": "check"}
    print(f"[3/3] PUT {url}  (check command)")
    t0 = time.time()
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.put(url, json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
            print(f"  OK  — {r.status_code} in {time.time() - t0:.2f}s: {data}")
            return data
    except httpx.HTTPStatusError as e:
        print(f"  FAIL — HTTP {e.response.status_code}: {e.response.text[:200]}")
    except httpx.ReadTimeout:
        print(f"  FAIL — ReadTimeout after {time.time() - t0:.2f}s")
    except Exception as e:
        print(f"  FAIL — {type(e).__name__}: {e}")
    return None


def print_device_summary(data: dict):
    print("\n--- Device Summary ---")
    status = data.get("status", {})
    nvm = data.get("nvm", {})

    temp = status.get("temperatures", {}).get("enviroment")
    target = nvm.get("user_parameters", {}).get("enviroment_1_temperature")
    power = status.get("commands", {}).get("power")
    phase = status.get("state", {}).get("operational_phase")
    fans = nvm.get("installer_parameters", {}).get("fans_number", "?")
    pellet = status.get("flags", {}).get("is_pellet_in_reserve")
    auto = nvm.get("user_parameters", {}).get("is_auto")

    print(f"  Power:        {'ON' if power else 'OFF'}")
    print(f"  Phase:        {phase}")
    print(f"  Temperature:  {temp}°C  (target: {target}°C)")
    print(f"  Auto mode:    {auto}")
    print(f"  Fans:         {fans}")
    print(f"  Pellet low:   {pellet}")


def main():
    parser = argparse.ArgumentParser(description="Test Edilkamin pellet stove connectivity")
    parser.add_argument("--username", "-u", required=True, help="Edilkamin account email")
    parser.add_argument("--password", "-p", required=True, help="Edilkamin account password")
    parser.add_argument("--mac", "-m", required=True, help="Device MAC address (e.g. aa:bb:cc:dd:ee:ff)")
    parser.add_argument("--skip-mqtt", action="store_true", help="Skip the mqtt/command check test")
    args = parser.parse_args()

    print("=" * 50)
    print("Edilkamin Connectivity Test")
    print("=" * 50)

    try:
        token = sign_in(args.username, args.password)
    except Exception as e:
        print(f"  FAIL — {type(e).__name__}: {e}")
        sys.exit(1)

    info = test_device_info(token, args.mac)
    if info:
        print_device_summary(info)

    if not args.skip_mqtt:
        print()
        test_mqtt_check(token, args.mac)
    else:
        print("\n[3/3] Skipped mqtt/command test (--skip-mqtt)")

    print("\n" + "=" * 50)
    if info:
        print("Result: device/info endpoint is WORKING")
        print("  -> Your integration should work with the coordinator fix.")
    else:
        print("Result: device/info endpoint FAILED")
        print("  -> Check credentials and MAC address.")
    print("=" * 50)


if __name__ == "__main__":
    main()
