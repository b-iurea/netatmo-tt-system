# Netatmo Integration Module

This module integrates with Netatmo devices to retrieve data and control them via the Netatmo API. It publishes data to an MQTT broker and provides a REST API for interacting with the service.

Original repository for source code:
  https://github.com/redcorjo/netatmo_api

## Functionality

*   Retrieves data from Netatmo devices (homes, rooms, modules).
*   Publishes data to an MQTT broker.
*   Provides a REST API for setting thermostat mode and true temperature.
*   Generates OpenHAB configuration files.

## Usage Examples

### Using the REST API

The module exposes a REST API built with FastAPI. Here are some examples of how to use it.

#### Setting Thermostat Mode

This endpoint allows you to set the thermostat mode for a home. The available modes are `schedule`, `away`, and `hg` (frost guard).

```bash
curl -X PUT "http://<host>:<port>/setthermode?mode=away"
```

```java
// Example of calling the setthermmode endpoint in Java
// Replace <host> and <port> with the actual values

String url = "http://<host>:<port>/setthermode?mode=away";

URL obj = new URL(url);
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PUT");
int responseCode = con.getResponseCode();
System.out.println("Response Code : " + responseCode);

BufferedReader in = new BufferedReader(new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();

while ((inputLine = in.readLine()) != null) {
	response.append(inputLine);
}
in.close();

System.out.println(response.toString());
```

#### Setting True Temperature

This endpoint allows you to set the true temperature for a specific room. You need to provide the `room_id` and the `corrected_temperature`.

```bash
curl -X PUT "http://<host>:<port>/truetemperature/{room_id}?corrected_temperature=21.5"
```

```java
// Example of calling the truetemperature endpoint in Java
// Replace <host>, <port>, and {room_id} with the actual values

String url = "http://<host>:<port>/truetemperature/1234567890?corrected_temperature=21.5";

URL obj = new URL(url);
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PUT");
int responseCode = con.getResponseCode();
System.out.println("Response Code : " + responseCode);

BufferedReader in = new BufferedReader(new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();

while ((inputLine = in.readLine()) != null) {
	response.append(inputLine);
}
in.close();

System.out.println(response.toString());
```

### Using the `MyNetatmo` Service Directly

```java
//This is a python example
from src.netatmo import MyNetatmo

netatmo = MyNetatmo(settings_file="/path/to/your/netatmo.ini")

# Set thermostat mode
response = netatmo.setthermmode(mode="away")
print(response)

# Set true temperature for a room
response = netatmo.truetemperature(room_id="your_room_id", corrected_temperature=21.5)
print(response)
```

## Configuration Details

The module requires a configuration file (`netatmo.ini`) with the following structure:

```ini
[credentials]
client_id = YOUR_CLIENT_ID
client_secret = YOUR_CLIENT_SECRET
username = YOUR_USERNAME
password = YOUR_PASSWORD
redirect_uri = https://api.netatmo.com/oauth2/redirect
refresh_token = YOUR_REFRESH_TOKEN
scopes = read_thermostat write_thermostat read_smarther write_smarther

[home]
home_id = YOUR_HOME_ID

[mqtt]
topic = netatmo/home/data
broker = 127.0.0.1
port  = 1883

[global]
frequency = 30

[logging]
severity = INFO
filename = netatmo.log

[http]
host = 127.0.0.1
port = 8080
```

*   **`[credentials]`**:  Netatmo API credentials.
    *   `client_id`: Your Netatmo client ID.
    *   `client_secret`: Your Netatmo client secret.
    *   `username`: Your Netatmo username.
    *   `password`: Your Netatmo password.
    *   `redirect_uri`: The redirect URI for OAuth2.
    *   `refresh_token`: The refresh token for OAuth2.
    *   `scopes`: The required API scopes.
*   **`[home]`**: Home settings.
    *   `home_id`: Your Netatmo home ID.
*   **`[mqtt]`**: MQTT broker settings.
    *   `topic`: The MQTT topic to publish data to.
    *   `broker`: The MQTT broker address.
    *   `port`: The MQTT broker port.
*   **`[global]`**: Global settings.
    *   `frequency`: The frequency (in seconds) to retrieve data from the Netatmo API.
*   **`[logging]`**: Logging settings.
    *   `severity`: The logging level (e.g., INFO, WARNING, ERROR).
    *   `filename`: The log filename.
*   **`[http]`**: HTTP server settings.
    *   `host`: The host address for the REST API.
    *   `port`: The port for the REST API.

## Dependencies

The module depends on the following Python packages:

```
requests
urllib3
paho.mqtt
apscheduler
jinja2
fastapi
uvicorn[standard]
lxml
```

These dependencies can be installed using pip:

```bash
pip install -r requirements.txt
```

## Running the Module

The module can be run as a daemon with a webserver using the following command:

```bash
python src/netatmo.py --daemon --webserver
```

## Helm Chart

This module can also be deployed as a Helm chart. See the `chart/README.md` file for more information.

[![Artifact Hub](https://img.shields.io/endpoint?url=https://artifacthub.io/badge/repository/netatmo-tt-system)](https://artifacthub.io/packages/search?repo=netatmo-tt-system)

## OpenHAB Integration

The module can generate OpenHAB configuration files for easy integration with OpenHAB. Use the `-oh` flag to specify the OpenHAB base directory:

```bash
sudo ./netatmo.py  -oh /etc/openhab
```

This will create three files:

*   `/etc/openhab/things/netatmo.things`
*   `/etc/openhab/items/netatmo.items`
*   `/etc/openhab/sitemaps/netatmo.sitemap`


---

🌍 This README is available in multiple languages:  
🔗 [readme.maxpfeffer.de](https://readme.maxpfeffer.de/readme/5a6e4d2bcaa66c27ccb473012a1e8381a3ad5cc200f4cb4d9d8fd8910cd9b43af817cd6623781fa9ba32a7b28cf6c401471f2f963fadc42c466361adc3500394)