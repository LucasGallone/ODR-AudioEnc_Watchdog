# Watchdog Service for ODR-AudioEncoder
A zero-dependency Python 3 watchdog script designed to monitor [ODR-AudioEnc](https://github.com/Opendigitalradio/ODR-AudioEnc) and associated PAD encoders running under **Supervisor** for DAB+ multiplexes, and automatically restart them in case of an outage.

If an audio encoder crashes with a `FATAL` or `EXITED` status, the script attempts to revive it, **along with its associated PAD encoder**, until normal broadcasting resumes. Multiple encoders can be restarted simultaneously in the background.

You can learn more about Opendigitalradio and discover their tools [by clicking here](http://www.opendigitalradio.org/).

---

## Features
* **Zero External Dependencies:** Built entirely with native Python 3 standard modules.
* **Asynchronous Multi-encoder Restarts:** Handled concurrently via background threads.
* **Email Alerts (via SMTP):**
  * Customizable delay before sending an alert for persistent outages.
  * Automatic **"Back on air"** restoration email once the encoder recovers.
  * Optional periodic **"Lifeline" test email** (once a week, for example) confirming the watchdog is active.
  * One-time startup test email mode included, to verify that the SMTP configuration is correct at first use.
  * Support for explicit STARTTLS and unencrypted SMTP.
* **Smart Station Identification in Emails:**
  * **Dictionary mode:** Map UUIDs (Encoder process IDs in Supervisor) to readable station names, using a manual dictionary in the script.
  * **Stream mode:** Automatically extracts the stream URL directly from your `ODR-encoders.conf` file.
  * **Process mode:** Raw Supervisor process name.
* **Fully Customizable Timers:** Control check intervals, first restart delay, subsequent retry delays, and alert thresholds directly from the configuration section.

---

## Installation & Configuration

### 1. Download the script
Place `ODR-AudioEnc_Watchdog.py` into the directory of your choice on the host machine (e.g. `/home/odr/`).

### 2. Customize your settings
Open `ODR-AudioEnc_Watchdog.py` with a text editor and adjust the settings in the configuration section:
* **Supervisor connection:** Port and credentials (default: `odr:odr` on port `8001`).
* **ODR configuration file:** Set `SUPERVISOR_CONF_FILE` to point to your `ODR-encoders.conf` path if you want to use the "Stream" mode for the stations identification.
* **Email alerts:** Enable or disable SMTP alerts, specify server details, recipients (up to 4), and alert delays.
* **Identification mode:** Choose between `"dictionary"`, `"stream"`, or `"process"`.

---

## Running with Supervisor

### 1. Create a Supervisor entry
Create a configuration file (e.g. `/etc/supervisor/conf.d/40-ODR-AudioEnc_Watchdog.conf`):
```ini
[program:40-ODR-AudioEnc_Watchdog]
command=python3 /home/odr/ODR-AudioEnc_Watchdog.py
directory=/home/odr/
autostart=true
autorestart=true
user=root
stderr_logfile=/var/log/ODR-AudioEnc_Watchdog.err.log
stdout_logfile=/var/log/ODR-AudioEnc_Watchdog.out.log
```
(Paths may vary depending on the host machine configuration.)

### 2. Check that the process is running properly
Once installation and configuration are complete, click the program name to verify that the watchdog service is running correctly.
<br>
You should see a confirmation message indicating that the server is up and running.
