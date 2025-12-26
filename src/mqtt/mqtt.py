import logging
import json
import paho.mqtt.client as paho
import os
import time


logging.basicConfig(level=logging.INFO)

ENVIRONMENT = os.environ.get("ENVIRONMENT", "prod").lower()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
stream_handler = logging.StreamHandler()
logging_formatter = logging.Formatter(
    '%(levelname)-8s [%(filename)s:%(lineno)d] (' + ENVIRONMENT + ') - %(message)s')
stream_handler.setFormatter(logging_formatter)
logger.addHandler(stream_handler)

class MQTT():

    broker = "127.0.0.1"
    port = 1883
    topic = "netatmo"
    client = None

    def __init__(self, broker=None, port=None, topic=None):
        logger.info("Init")
        # Allow configuration from constructor or environment variables
        if broker is None:
            broker = os.environ.get("NETATMO_MQTT_BROKER", self.broker)
        if port is None:
            port = os.environ.get("NETATMO_MQTT_PORT", self.port)
        if topic is None:
            topic = os.environ.get("NETATMO_MQTT_TOPIC", self.topic)

        if broker is not None:
            self.broker = broker
        if port is not None:
            try:
                self.port = int(port)
            except Exception:
                logger.warning("Invalid MQTT_PORT '%s', using default %s", port, self.port)
        if topic is not None:
            self.topic = topic

        # optional auth
        self.username = os.environ.get("MQTT_USER")
        self.password = os.environ.get("MQTT_PASS")
        self.keepalive = int(os.environ.get("MQTT_KEEPALIVE", 60))
        self.tls = os.environ.get("MQTT_TLS", "false").lower() in ("1", "true", "yes")
        # Log the resolved configuration so we can debug env vs defaults
        logger.info("MQTT resolved config: broker=%s port=%s topic=%s tls=%s", self.broker, self.port, self.topic, self.tls)

    def send_message(self, payload, topic=None, item=None, mode="state"):
        if self.client is None:
            self.__connect_queue()
        if topic == None:
            topic = self.topic
        if type(payload) == str:
            message = payload
        else:
            message = json.dumps(payload)
        if item != None:
            topic = f"{topic}/{item}/{mode}"
        else:
            topic = f"{topic}/{mode}"
        try:
            rc = self.client.publish(topic, message)
            logger.debug("Published to %s rc=%s", topic, rc)
        except Exception as e:
            logger.error("Failed to publish to MQTT broker %s:%s - %s", self.broker, self.port, e)
            # Try reconnect once
            try:
                self.__connect_queue()
                self.client.publish(topic, message)
            except Exception as e2:
                logger.error("Publish retry failed: %s", e2)
        pass

    def mqtt_on_message(self, client, userdata, message):
        if not message.topic.endswith("/state"):
            epoch = str(time.time())
            logger.info(f"message received {message.payload} - epoch={epoch} ")
            logger.info(f"message topic={message.topic}")
            logger.info(f"message qos={message.qos}")
            logger.info(f"message retain flag={message.retain}")

    def on_disconnect(self, client, userdata, rc):
        if rc != 0:
            logger.warning("Unexpected MQTT disconnection. Attempting to reconnect.")
            try:
                self.client.reconnect()
            except Exception as e:
                logger.error("Error trying to reconnect to mqtt. Exception %s", e)

    def subscribe_topic(self, topic=None, qos=1, on_message=None):
        if self.client == None:
            self.__connect_queue()
        if topic == None:
            topic = f"{self.topic}/+/update" 
        logger.info(f"Subscribing to mqtt topic {topic}")
        self.client.subscribe(topic, qos=qos)
        if on_message == None:
            self.client.on_message=self.mqtt_on_message
        else:
            self.client.on_message=on_message
        self.on_disconnect=self.on_disconnect
        # Use loop_forever when subscribing in foreground, but ensure callbacks are set
        try:
            self.client.loop_forever()
        except KeyboardInterrupt:
            logger.info("MQTT subscribe loop interrupted by user")
        except Exception as e:
            logger.error("MQTT loop_forever error: %s", e)

    def __connect_queue(self):
        paho_client = "mqtt_netatmo_" + str(time.time())
        client = paho.Client(client_id=paho_client, callback_api_version=1)

        # set auth if provided
        if getattr(self, 'username', None):
            client.username_pw_set(self.username, self.password)

        # TLS not currently configured beyond flag; user can extend if needed
        if getattr(self, 'tls', False):
            try:
                client.tls_set()
            except Exception as e:
                logger.warning("Failed to enable TLS on mqtt client: %s", e)

        # register callbacks
        client.on_disconnect = self.on_disconnect
        client.on_message = self.mqtt_on_message

        max_attempts = 5
        attempt = 0
        while attempt < max_attempts:
            attempt += 1
            try:
                logger.info("Connecting to MQTT broker %s:%s (attempt %s/%s)", self.broker, self.port, attempt, max_attempts)
                client.connect(self.broker, self.port, keepalive=getattr(self, 'keepalive', 60))
                # start network loop in background
                client.loop_start()
                self.client = client
                logger.info("Connected to MQTT broker %s:%s", self.broker, self.port)
                return
            except Exception as e:
                logger.error("MQTT connect attempt %s failed: %s", attempt, e)
                # If last attempt, raise
                if attempt >= max_attempts:
                    logger.critical("Could not connect to MQTT broker after %s attempts", max_attempts)
                    raise
                # exponential backoff with jitter
                backoff = min(2 ** attempt, 30)
                jitter = backoff * 0.1
                sleep_time = backoff + (jitter * (0.5 - time.time() % 1))
                logger.info("Retrying MQTT connect in %.1f seconds", sleep_time)
                time.sleep(sleep_time)
        