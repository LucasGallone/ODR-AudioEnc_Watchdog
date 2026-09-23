#!/usr/bin/env python3
import os
import time
import re
import xmlrpc.client
import smtplib
import ssl
import sys
import threading
from email.mime.text import MIMEText
from email.utils import formatdate
from datetime import datetime

# ==============================================================================
# =========================== CONFIGURATION SECTION ============================
# ======================= CUSTOMIZE YOUR SETTINGS BELOW ========================
# ==============================================================================

# HTTP Configuration of the Supervisor interface (Default: odr:odr [username:password] and port 8001)
SUPERVISOR_URL = "http://odr:odr@127.0.0.1:8001/RPC2"

# Path to the Supervisor configuration file containing the encoders data
# Required to send alert emails mentioning the streams URLs ("stream" mode) - Edit it if it doesn't match the location of yours
SUPERVISOR_CONF_FILE = "/home/odr/ODR-mmbTools/config/supervisor/ODR-encoders.conf"

# Email Alert Configuration
ENABLE_EMAIL_ALERTS = False # False = Do not send email alerts / True = Send email alerts
SEND_TEST_EMAIL_ON_START = False # True = Send a test email on service startup, think to disable it by using False afterwards!
SMTP_SERVER = "smtp.example.com"
SMTP_PORT = 587
SMTP_USER = "alert" # Most often the beginning of the sender address before the @
SMTP_PASSWORD = "p4ssw0rd" # Password of the sender email account
SMTP_FROM = "alert@example.com" # Sender email address
SMTP_TO = ["engineer@example.com", "josh@example.com", "steve@example.com", "george@example.com"] # Maximum of 4 recipients, remove the example addresses if you activate the service (leave the arguments as "",)
SMTP_USE_TLS = True # True = Enable TLS encryption (STARTTLS, usually port 587), False = No encryption (usually port 25)

# Periodic "Lifeline" Test Email
ENABLE_PERIODIC_TEST_EMAIL = False # True = Send a periodic test email to confirm that the watchdog service is active, False = Do not send periodic tests
PERIODIC_TEST_HOURS = 168 # Number of hours between each periodic test email, if enabled (Default: 168 = 1 week)

# Encoders Restart & Alert Timers Configuration
CHECK_INTERVAL_SECONDS = 180 # Seconds between each global check of all audio encoders
FIRST_RESTART_DELAY = 5 # Seconds before the first restart attempt in case of an encoder failure
SUBSEQUENT_RESTART_DELAY = 120 # Seconds before new attempts in case the first one was not successful
ALERT_DELAY_MINUTES = 60 # Minutes before sending an alert email in case of a continuous encoder failure (an automatic "back on air" email will then be sent when restored)

# Encoders Identification Mode for the emails ("dictionary", "stream", or "process")
# "dictionary" = Use the station names from the configurable list below as service identification value in the emails
# "stream" = Use the stream URL of the encoder as service identification value in the emails
# "process" = Use the process name as displayed on Supervisor as service identification value in the emails
IDENTIFIER_MODE = "process"

# Dictionary of Station Names - Linked to the "dictionary" encoders identification mode
# Format: "[AudioEnc process ID]": "[Station name]",
# AudioEnc process ID can be found after "odr-audioencoder-" in the encoder service name on Supervisor ("odr-audioencoder-XXX")
# Add as much as needed, the list is not limited to 3 entries
STATION_NAMES = {
    "a111111b-aaaa-1111-222f-333f33f3f333f": "Station Example 1",
    "a111111b-bbbb-2222-333f-444f44f4f444f": "Station Example 2",
    "a111111b-cccc-3333-444f-555f55f5f555f": "Station Example 3",
}

# ==============================================================================
# ====================== END OF THE CONFIGURATION SECTION ======================
# ============================ DO NOT MODIFY BELOW =============================
# ==============================================================================

# Regex to identify the audioencoder services and their associated padencoders
AUDIO_PATTERN = re.compile(r"^odr-audioencoder-[0-9a-fA-F-]+$")
PAD_PATTERN   = re.compile(r"^odr-padencoder-[0-9a-fA-F-]+$")

BAD_STATUS = {"FATAL", "EXITED"}

# Dictionary for tracking outage duration: {service_name: (first_outage_timestamp, email_sent_bool)}
failure_tracker = {}

# Set to track services currently restarting (prevents duplicate threads)
active_restarts = set()

# Cache to store feed URLs while services are active
stream_url_cache = {}

def get_stream_url(service):
    """Retrieves the stream URL from cache or directly from the Supervisor configuration file."""
    if service in stream_url_cache and stream_url_cache[service]:
        return stream_url_cache[service]

    uuid = service.replace("odr-audioencoder-", "")
    url = None

    try:
        if os.path.isfile(SUPERVISOR_CONF_FILE):
            with open(SUPERVISOR_CONF_FILE, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            # Isolates the specific section of this audio encoder within the file
            section_pattern = rf"\[program:odr-audioencoder-{uuid}\](.*?)(?=\n\[program:|\Z)"
            match_section = re.search(section_pattern, content, re.DOTALL)
            section_text = match_section.group(1) if match_section else content

            # Extraction of the stream URL (--gst-uri)
            m = re.search(r"--gst-uri=([^\s'\"]+)", section_text)
            if not m:
                m = re.search(r"(https?://[^\s'\"]+)", section_text)
            if m:
                url = m.group(1)
    except Exception:
        pass

    if url:
        stream_url_cache[service] = url
    return url

def get_service_identity(service):
    """Returns (type, value) for a service based on IDENTIFIER_MODE and fallbacks."""
    uuid = service.replace("odr-audioencoder-", "")
    
    if IDENTIFIER_MODE == "dictionary":
        if uuid in STATION_NAMES:
            return "dictionary", STATION_NAMES[uuid]
        url = get_stream_url(service)
        if url:
            return "stream", url
        return "process", service
        
    elif IDENTIFIER_MODE == "stream":
        url = get_stream_url(service)
        if url:
            return "stream", url
        return "process", service
        
    return "process", service

def build_email_strings(service, status, timestamp, is_recovery=False):
    """Generates the exact subject and body for emails based on the identity type."""
    id_type, id_value = get_service_identity(service)
    date_str = datetime.fromtimestamp(timestamp).strftime("%d/%m/%Y at %H:%M:%S")
    
    if not is_recovery:
        if id_type == "process":
            subject = f"[ODR-AudioEnc Watchdog] Alert for \"{id_value}\""
            body = f"\"{id_value}\" is down since {date_str}!\n\nA new email will be sent once the encoder is functional again.\n(Process status = {status})"
        elif id_type == "stream":
            subject = f"[ODR-AudioEnc Watchdog] Alert for URL \"{id_value}\""
            body = f"The audio encoder for the \"{id_value}\" stream is down since {date_str}!\n\nA new email will be sent once the encoder is functional again.\n(Process status = {status})"
        else: # dictionary
            subject = f"[ODR-AudioEnc Watchdog] Alert for \"{id_value}\""
            body = f"The audio encoder for the \"{id_value}\" service is down since {date_str}!\n\nA new email will be sent once the encoder is functional again.\n(Process status = {status})"
    else:
        if id_type == "process":
            subject = f"[ODR-AudioEnc Watchdog] Back on air: \"{id_value}\""
            body = f"\"{id_value}\" is functional again.\n\nEmail sent on: {date_str}"
        elif id_type == "stream":
            subject = f"[ODR-AudioEnc Watchdog] Back on air: URL \"{id_value}\""
            body = f"The audio encoder for the \"{id_value}\" stream is functional again.\n\nEmail sent on: {date_str}"
        else: # dictionary
            subject = f"[ODR-AudioEnc Watchdog] Back on air: \"{id_value}\""
            body = f"The audio encoder for the \"{id_value}\" service is functional again.\n\nEmail sent on: {date_str}"
            
    return subject, body

def send_alert_email(subject, body, is_test=False):
    """Sends an email alert via SMTP to up to 4 recipients if the feature is enabled."""
    if not ENABLE_EMAIL_ALERTS or not SMTP_SERVER:
        return

    # Filtering out empty recipients
    recipients = [r for r in SMTP_TO[:4] if r.strip()]
    if not recipients:
        log("WARNING: Email alerts enabled but no valid recipients configured.", level="WARNING")
        return

    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = SMTP_FROM
        msg['To'] = ", ".join(recipients)
        msg['Date'] = formatdate(localtime=True)

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
        server.ehlo()  # Initial identification
        
        if SMTP_USE_TLS:
            context = ssl.create_default_context()
            server.starttls(context=context)  # Securing the line
            server.ehlo()  # New post-encryption identification

        # Authentication is attempted only if a user is defined
        if SMTP_USER and SMTP_PASSWORD:
            server.login(SMTP_USER, SMTP_PASSWORD)

        server.send_message(msg)
        server.quit()
        
        if is_test:
            log("Test email sent successfully. Please check your inbox to confirm.", level="SMTP TEST")
    except Exception as e:
        log("Alert email sending failed! The mail server might be down, otherwise check the SMTP service configuration.", level="SMTP FAIL")

def log(msg, level="INFO"):
    """Shows informative messages with date and hour"""
    now = datetime.now().strftime("%d/%m/%Y @ %H:%M:%S")
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
    def check_and_send_alert():
        if not ENABLE_EMAIL_ALERTS: return
        if service_name not in failure_tracker: return
        first_fail, alert_sent = failure_tracker[service_name]
        if not alert_sent and (time.time() - first_fail) >= (ALERT_DELAY_MINUTES * 60):
            failure_tracker[service_name] = (first_fail, True)
            fail_str = datetime.fromtimestamp(first_fail).strftime("%d/%m/%Y @ %H:%M:%S")
            log(f"{service_name} is down since {fail_str}. Sending email alert.", level="SMTP")
            try:
                st = server.supervisor.getProcessInfo(service_name)['statename'].upper()
            except:
                st = "UNKNOWN"
            subject, body = build_email_strings(service_name, st, first_fail, is_recovery=False)
            send_alert_email(subject, body)

    def smart_sleep(seconds):
        for _ in range(seconds):
            check_and_send_alert()
            time.sleep(1)

    first_attempt = True
    while True:
        if service_name not in failure_tracker:
            failure_tracker[service_name] = (time.time(), False)
        
        check_and_send_alert()

        if first_attempt:
            smart_sleep(FIRST_RESTART_DELAY)
            first_attempt = False

        try:
            info = server.supervisor.getProcessInfo(service_name)
            statename = info['statename'].upper()

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
            smart_sleep(5)

        except Exception as e:
            log(f"RESTART ATTEMPT FAILED: Error during the restart attempt of {service_name} - New attempt in {SUBSEQUENT_RESTART_DELAY} seconds.", level="ERROR")
            smart_sleep(SUBSEQUENT_RESTART_DELAY)
            continue

        # Recheck the status
        try:
            info = server.supervisor.getProcessInfo(service_name)
            if info['statename'].upper() == "RUNNING":
                log(f"{service_name} is now RUNNING.")
                break
            else:
                log(f"RESTART ATTEMPT FAILED: {service_name} status is {info['statename'].upper()} - New attempt in {SUBSEQUENT_RESTART_DELAY} seconds.", level="ERROR")
                smart_sleep(SUBSEQUENT_RESTART_DELAY)
        except Exception:
            smart_sleep(SUBSEQUENT_RESTART_DELAY)

def restart_audio_with_pad(server_unused, audio_service):
    """Restarts the audioencoder if the service is down, as well as the associated padencoder no matter its status"""
    # Prevents the launch of multiple simultaneous threads for the same service
    if audio_service in active_restarts:
        return
        
    active_restarts.add(audio_service)
    try:
        # Creation of a local ServerProxy instance for this thread to avoid network collisions (thread safety)
        server = xmlrpc.client.ServerProxy(SUPERVISOR_URL)
        
        uuid = audio_service.replace("odr-audioencoder-", "")
        pad_service = f"odr-padencoder-{uuid}"

        services = get_services_status(server)
        audio_status = services.get(audio_service, "UNKNOWN")

        if audio_status in BAD_STATUS:
            log(f"AUDIO ENCODER FAILURE DETECTED: Restart attempt of {audio_service} (Process status = {audio_status})")
            restart_service(server, audio_service)

        # Force restart of padencoder
        log(f"Forcing restart of the associated {pad_service}")
        restart_service(server, pad_service, force=True)
    except Exception as e:
        log(f"ERROR: Exception in restart thread for {audio_service}: {e}", level="ERROR")
    finally:
        active_restarts.discard(audio_service)

def main():
    if SEND_TEST_EMAIL_ON_START:
        log('Test email mode enabled! Remember to set the "SEND_TEST_EMAIL_ON_START" argument in the script to "False" once you no longer need it.', level="SMTP INFO")
        test_body = (
            "This is a test email sent by the ODR-AudioEnc Watchdog service.\n\n"
            "It confirms that your SMTP configuration is correct, and you can now receive alert emails in the event of an encoder failure."
        )
        send_alert_email("[ODR-AudioEnc Watchdog] Test Email", test_body, is_test=True)

    server = xmlrpc.client.ServerProxy(SUPERVISOR_URL)
    log(f"The watchdog service is now running. All audio encoders are checked every {CHECK_INTERVAL_SECONDS} seconds to detect failures.")

    last_periodic_test = time.time()

    while True:
        # Verification and sending of the periodic test email ("Lifeline")
        if ENABLE_PERIODIC_TEST_EMAIL and (time.time() - last_periodic_test) >= (PERIODIC_TEST_HOURS * 3600):
            date_str = datetime.now().strftime("%d/%m/%Y - %H:%M:%S")
            subject = "[ODR-AudioEnc Watchdog] Periodic Test"
            body = f"This email confirms that the watchdog service is running properly and is ready to send you an alert if necessary.\n\nYou are receiving this email because you have enabled the periodic test in the script configuration.\n\nEmail sent on: {date_str}"
            
            send_alert_email(subject, body)
            log(f"Periodic test email sent successfully (configured every {PERIODIC_TEST_HOURS} hours).", level="SMTP")
            last_periodic_test = time.time()

        services = get_services_status(server)
        
        # Tracker and cache update for all encoders
        for service, status in services.items():
            if service.startswith("odr-audioencoder-"):
                # Caching the feed URL if not already cached
                if service not in stream_url_cache:
                    get_stream_url(service)
                        
            if service.startswith("odr-audioencoder-") or service.startswith("odr-padencoder-"):
                if status in BAD_STATUS:
                    if service not in failure_tracker:
                        failure_tracker[service] = (time.time(), False)
                elif status == "RUNNING" and service in failure_tracker:
                    if service not in active_restarts:
                        _, alert_sent = failure_tracker[service]
                        if alert_sent and ENABLE_EMAIL_ALERTS:
                            log(f"{service} is operational again. Sending restoration email.", level="SMTP")
                            subject, body = build_email_strings(service, status, time.time(), is_recovery=True)
                            send_alert_email(subject, body)
                        
                        del failure_tracker[service]
                        
                        # Forces re-extraction of the URL during the next cycle if the configuration has changed
                        if service in stream_url_cache:
                            del stream_url_cache[service]

        # Restart trigger (emails are handled directly by the background thread)
        for service, status in services.items():
            if service.startswith("odr-audioencoder-") and status in BAD_STATUS:
                # Asynchronous launch to handle multiple failures simultaneously
                if service not in active_restarts:
                    threading.Thread(target=restart_audio_with_pad, args=(server, service), daemon=True).start()
                
        time.sleep(CHECK_INTERVAL_SECONDS)  # Global check of all audioencoder services every XX seconds

if __name__ == "__main__":
    main()
