#!/bin/bash
set -e

cat <<EOF > /app/netatmo.ini
[credentials]
client_id = ${NETATMO_CREDENTIALS_CLIENT_ID}
client_secret = ${NETATMO_CREDENTIALS_CLIENT_SECRET}
username = ${NETATMO_CREDENTIALS_USERNAME}
password = ${NETATMO_CREDENTIALS_PASSWORD}
redirect_uri = ${NETATMO_CREDENTIALS_REDIRECT_URI}
refresh_token = ${NETATMO_CREDENTIALS_REFRESH_TOKEN}
scopes = ${NETATMO_CREDENTIALS_SCOPES}

[home]
home_id = ${NETATMO_HOME_ID}

[mqtt]
topic = ${NETATMO_MQTT_TOPIC}
broker = ${NETATMO_MQTT_BROKER}
port  = ${NETATMO_MQTT_PORT}

[global]
frequency = ${NETATMO_GLOBAL_FREQUENCY}

[logging]
severity = ${NETATMO_LOG_SEVERITY}
filename = ${NETATMO_LOG_FILENAME}

[http]
host = ${NETATMO_HTTP_HOST}
port = ${NETATMO_HTTP_PORT}
EOF

echo "Generated netatmo.ini."
exec python /app/netatmo.py --daemon --webserver