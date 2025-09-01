# Watchdog Service for ODR-AudioEncoder
This is a Python3 script that aims to check the audio encoders of an ODR DAB+ multiplex every 5 minutes and restarts them in case of a failure.

In case the status of one of the audio encoders is "FATAL" or "EXITED" in Supervisor, the script attempts to restart it until it works again, **along with the associated PAD encoder**.

If the first restart attempt does not work, a new one is issued every 15 seconds as long as necessary.

# Instructions for integrating the script into the web interface of Supervisor

-> Download the Python script (ODR-AudioEnc_Watchdog.py) and place it in the directory of your choice.

-> Open the Python script in a text editor and modify the credentials and port to connect to the Supervisor web interface on ```Line 8```.
If you kept the factory values (Credentials: odr/odr and Port 8001), ignore this step.

Otherwise, replace ```SUPERVISOR_URL = "http://odr:odr@127.0.0.1:8001/RPC2"``` with ```SUPERVISOR_URL = "http://(your username):(your password)@127.0.0.1:(your port)/RPC2"```

-> Create the following entry in the Supervisor config file:
```
[program:40-ODR-AudioEnc_Watchdog]
command=python3 ODR-AudioEnc_Watchdog.py
directory=/home/odr/ [<- Edit this value with the path where the script is located]
autostart=true
autorestart=true
user=root
stderr_logfile=/var/log/ODR-AudioEnc_Watchdog.err.log
stdout_logfile=/var/log/ODR-AudioEnc_Watchdog.out.log
```

-> Add the watchdog service to the Supervisor interface with SupervisorCTL:
```
sudo supervisorctl reread
sudo supervisorctl update
```

-> Log in to the Supervisor interface on your web browser (Default is ```http://127.0.0.1:8001/```), and click on "40-ODR-AudioEnc_Watchdog" in the process list.

If working well, you should get the following message:
```[INFO] The watchdog service is now running. All audio encoders are checked every 5 minutes to detect a possible failure.```
