from flask import Flask, render_template_string, redirect, url_for, request
from flask_httpauth import HTTPBasicAuth
import subprocess
import threading
import os
import sys
import logging

app = Flask(__name__)
auth = HTTPBasicAuth()
script_process = None

# Set up logging for the Flask app
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('dashboard.log')  # Logs for the dashboard app
    ]
)

# Define your username and password
USER_DATA = {
    "admin": "password123"  # Change this password to something secure
}

# HTML templates
INDEX_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>Telescope Control Dashboard</title>
</head>
<body>
    <h1>Telescope Control Dashboard</h1>
    <p>Script status: <strong>{{ status }}</strong></p>
    <form action="{{ url_for('start_script') }}" method="post">
        <button type="submit">Start Script</button>
    </form>
    <form action="{{ url_for('stop_script') }}" method="post">
        <button type="submit">Stop Script</button>
    </form>
    <a href="{{ url_for('view_logs') }}">View Logs</a>
</body>
</html>
'''

LOGS_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>Script Logs</title>
</head>
<body>
    <h1>Script Logs</h1>
    <pre>{{ logs }}</pre>
    <a href="{{ url_for('index') }}">Back to Dashboard</a>
</body>
</html>
'''

# Authentication handler
@auth.verify_password
def verify_password(username, password):
    if username in USER_DATA and USER_DATA[username] == password:
        return username
    return None

@app.route('/')
@auth.login_required
def index():
    status = 'Running' if script_process and script_process.poll() is None else 'Stopped'
    return render_template_string(INDEX_HTML, status=status)

@app.route('/start', methods=['POST'])
@auth.login_required
def start_script():
    global script_process
    if not script_process or script_process.poll() is not None:
        # Start the script
        logging.info("Starting the telescope script.")
        script_process = subprocess.Popen(
            ['python', 'infinite.py'],  # Replace 'your_script.py' with your actual script filename
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True
        )
        return redirect(url_for('index'))
    else:
        return 'Script is already running.', 200

@app.route('/stop', methods=['POST'])
@auth.login_required
def stop_script():
    global script_process
    if script_process and script_process.poll() is None:
        logging.info("Stopping the telescope script.")
        script_process.terminate()
        script_process.wait()
        return redirect(url_for('index'))
    else:
        return 'Script is not running.', 200

@app.route('/logs')
@auth.login_required
def view_logs():
    if os.path.exists('script.log'):
        with open('script.log', 'r') as f:
            logs = f.read()
    else:
        logs = 'No logs available.'
    return render_template_string(LOGS_HTML, logs=logs)

if __name__ == '__main__':
    # Use Waitress for production serving
    from waitress import serve
    serve(app, host='192.168.99.1', port=5000)
