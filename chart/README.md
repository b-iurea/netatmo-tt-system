# Netatmo True Temperature System

This Helm chart deploys a microservice that retrieves temperature data from the Netatmo API and publishes it to an MQTT broker. It also exposes a health endpoint.

## Functionality

This module consists of two main components:

*   **Netatmo API Service:** Retrieves temperature data from Netatmo using their private API.
*   **MQTT Broker:** An Eclipse Mosquitto instance for publishing the temperature data.

## Usage

This module is designed to be deployed as a Helm chart.  After deployment, the Netatmo API service will periodically fetch temperature data and publish it to the configured MQTT topic.

### Prerequisites

*   Helm installed
*   Kubernetes cluster
*   Netatmo API credentials (client ID, client secret, username, password, home ID, refresh token, scopes, redirect URI)

### Installation

1.  Clone the repository containing the Helm chart.
2.  Create a `values.yaml` file with your desired configuration, including Netatmo API credentials and MQTT settings.
3.  Install the chart using Helm:

    ```bash
    helm install netatmo-tt-system ./ -f values.yaml
    ```

## Configuration

The module is configured primarily through the `values.yaml` file. Here's a breakdown of the key configuration parameters:

*   **`namespaceOverride`:**  Override the default namespace (`netatmo-system`).
*   **`netatmo.image`:** Configuration for the Netatmo API service image.
    *   `repository`: The Docker image repository.
    *   `tag`: The image tag.
    *   `pullPolicy`: The image pull policy.
*   **`netatmo.replicaCount`:** The number of Netatmo API service replicas.
*   **`netatmo.service`:** Configuration for the Netatmo API service.
    *   `port`: The port the service listens on (default: 8000).
    *   `type`: The service type (e.g., `ClusterIP`, `LoadBalancer`).
*   **`mqtt`:** Configuration for the MQTT broker.
    *   `enabled`: Whether to deploy the MQTT broker.
    *   `image`:
        *   `repository`: The MQTT broker image repository.
        *   `tag`: The image tag.
        *   `pullPolicy`: The image pull policy.
    *   `service`:
        *   `port`: The MQTT broker port (default: 1883).
        *   `type`: The service type.
    *   `config`:
        *   `allow_anonymous`: Whether to allow anonymous connections.
        *   `persistence`: Whether to enable persistence.
*   **`env`:** Environment variables for the Netatmo API service.
    *   `mqtt`:
        *   `topic`: The MQTT topic to publish to.
    *   `http`:
        *   `host`: The HTTP host.
    *   `global`:
        *   `frequency`: The frequency of data retrieval (in seconds).
    *   `logging`:
        *   `severity`: The logging severity.
        *   `filename`: The log filename.
*   **`secretEnv`:**  Secrets for the Netatmo API credentials.  These should be populated with your actual credentials.
    *   `client_id`
    *   `client_secret`
    *   `username`
    *   `password`
    *   `home_id`
    *   `refresh_token`
    *   `redirect_uri`
    *   `scopes`

### Example `values.yaml`

```yaml
namespaceOverride: "netatmo-system"

netatmo:
  image:
    repository: bogdaniurea/netatmo-tt-system
    tag: "0.1.0"
    pullPolicy: Always

  replicaCount: 1

  service:
    port: 8000
    type: ClusterIP

mqtt:
  enabled: true
  image:
    repository: eclipse-mosquitto
    tag: "2.0.22"
    pullPolicy: IfNotPresent

  service:
    port: 1883
    type: ClusterIP

  config:
    allow_anonymous: true
    persistence: false

env:
  mqtt:
    topic: "netatmo/truetemperature"

  http:
    host: "0.0.0.0"

  global:
    frequency: "30"

  logging:
    severity: "WARNING"
    filename: "netatmo.log"

secretEnv:
  client_id: "YOUR_CLIENT_ID"
  client_secret: "YOUR_CLIENT_SECRET"
  username: "YOUR_USERNAME"
  password: "YOUR_PASSWORD"
  home_id: "YOUR_HOME_ID"
  refresh_token: "YOUR_REFRESH_TOKEN"
  redirect_uri: https://api.netatmo.com/oauth2/redirect
  scopes: read_thermostat write_thermostat read_smarther write_smarther
```

**Important:** Replace the placeholder values in `secretEnv` with your actual Netatmo API credentials.

## Dependencies

This chart depends on the following:

*   A Kubernetes cluster
*   Helm
*   The `bogdaniurea/netatmo-tt-system` Docker image (or a suitable replacement)
*   The `eclipse-mosquitto` Docker image (if MQTT is enabled)

## Health Check

The Netatmo API service exposes a `/health` endpoint that can be used to check its health.  This is used by the readiness and liveness probes in the deployment.


---

🌍 This README is available in multiple languages:  
🔗 [readme.maxpfeffer.de](https://readme.maxpfeffer.de/readme/818ff332645aef9a1364ef318defe87b3fa2963ebc1929cf285b0b6ffdef27144afdf609dd77d543cc7ac6417eeb9d7feece47c098880b891e8255190168a8fc)