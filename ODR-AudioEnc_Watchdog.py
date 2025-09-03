#!/usr/bin/env python3
import time
import re
import xmlrpc.client
from datetime import datetime

# HTTP Configuration of the Supervisor interface, with default username and password "odr" and port 8001 - Modify the credentials and port if needed
SUPERVISOR_URL = "http://odr:odr@127.0.0.1:8001/RPC2"

# Regex to identify the audioencoder services and their associated padencoders
AUDIO_PATTERN = re.compile(r"^odr-audioencoder-[0-9a-fA-F-]+$")
PAD_PATTERN   = re.compile(r"^odr-padencoder-[0-9a-fA-F-]+$")

# States that indicate an audioencoder service is down
BAD_STATUS = {"FATAL", "EXITED"}

def log(msg, level="INFO"):
    """Shows informative messages with date and hour"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{level}] {now} - {msg}", flush=True)

def get_services_status(server):
    """Returns a dect {service_name: status} from Supervisor"""
    services = {}
    try:
        all_processes = server.supervisor.getAllProcessInfo()
        for p in all_processes:
            name = p['name']
            status = p['statename'].upper()
            if AUDIO_PATTERN.match(name) or PAD_PATTERN.match(name):
                services[name] = status
    except Exception as e:
        log(f"ERROR: Unable to retrieve status: {e}", level="ERROR")
    return services

def restart_service(server, service_name, force=False):
    """
    Restarts a service via Supervisor.
    If force=True, restarts the service even with RUNNING status.
    """
    while True:
        try:
            info = server.supervisor.getProcessInfo(service_name)
            statename = info['statename'].upper()
            spawnerr = info['spawnerr']

            if statename == "RUNNING" and not force:
                log(f"{service_name} is already RUNNING.")
                break

            if statename != "STOPPED" or force:
                try:
                    server.supervisor.stopProcess(service_name)
                except Exception:
                    pass
                time.sleep(1)

            server.supervisor.startProcess(service_name)
            time.sleep(2)

        except Exception as e:
            log(f"RESTART ATTEMPT FAILED: Error during the restart attempt of {service_name} - New attempt in 2 minutes.", level="ERROR")
            time.sleep(120)

        # Recheck the status
        try:
            info = server.supervisor.getProcessInfo(service_name)
            if info['statename'].upper() == "RUNNING":
                log(f"{service_name} is now RUNNING.")
                break
        except Exception:
            time.sleep(15)

def restart_audio_with_pad(server, audio_service):
    """Restarts the audioencoder if the service is down, as well as the associated padencoder no matter its status"""
    uuid = audio_service.replace("odr-audioencoder-", "")
    pad_service = f"odr-padencoder-{uuid}"

    services = get_services_status(server)
    audio_status = services.get(audio_service, "UNKNOWN")

    if audio_status in BAD_STATUS:
        log(f"AUDIO ENCODER FAILURE DETECTED: Restart attempt of {audio_service} because status={audio_status}")
        restart_service(server, audio_service)

    # Force restart of padencoder
    log(f"Forcing restart of the associated {pad_service}")
    restart_service(server, pad_service, force=True)

def main():
    server = xmlrpc.client.ServerProxy(SUPERVISOR_URL)
    log("The watchdog service is now running. All audio encoders are checked every 5 minutes to detect a possible failure.")

    while True:
        services = get_services_status(server)
        for service, status in services.items():
            if service.startswith("odr-audioencoder-") and status in BAD_STATUS:
                restart_audio_with_pad(server, service)
        time.sleep(300)  # Global check of all audioencoder services every 5 minutes

if __name__ == "__main__":
    main()
