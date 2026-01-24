import json
import time
import logging
import paho.mqtt.client as mqtt
from typing import Callable, Dict, Any, Optional

# Configure logging for better visibility in your Home Assistant logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MQTTHandler")

class MQTTHomeAssistant:
    """
    A communication module for Home Assistant using MQTT.
    Designed to handle JSON messages and facilitate file transfers via HTTP notifications.
    """

    def __init__(
        self, 
        client_id: str, 
        broker_address: str = "localhost", 
        port: int = 1883,
        keepalive: int = 60
    ):
        self.client_id = client_id
        self.broker_address = broker_address
        self.port = port
        self.keepalive = keepalive
        
        # Initialize Paho Client
        self.client = mqtt.Client(client_id=client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        
        # Internal callback registry
        self.on_message_received: Optional[Callable[[str, Dict[str, Any]], None]] = None

        # Set MQTT callbacks
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            logger.info(f"Connected to MQTT Broker as '{self.client_id}'")
        else:
            logger.error(f"Failed to connect, return code {rc}")

    def _on_disconnect(self, client, userdata, disconnect_flags, rc, properties=None):
        logger.warning(f"Disconnected from broker. Reconnecting...")
        
    def _on_message(self, client, userdata, msg):
        """Processes incoming MQTT packets."""
        try:
            payload = json.loads(msg.payload.decode())
            topic = msg.topic
            
            # Ensure the payload has the expected ID and Context structure
            sender_id = payload.get("id", "unknown")
            context = payload.get("context", {})
            
            logger.debug(f"Received from {sender_id} on {topic}: {context}")
            
            if self.on_message_received:
                self.on_message_received(topic, payload)
                
        except json.JSONDecodeError:
            logger.error(f"Received non-JSON payload on {msg.topic}: {msg.payload}")
        except Exception as e:
            logger.error(f"Error processing message: {e}")

    def connect(self):
        """Starts the connection and the background loop."""
        try:
            self.client.connect(self.broker_address, self.port, self.keepalive)
            self.client.loop_start()
        except Exception as e:
            logger.error(f"Connection failed: {e}")

    def subscribe(self, topic: str):
        """Subscribe to a specific topic (e.g., 'home/satellites/all' or 'home/server')."""
        self.client.subscribe(topic)
        logger.info(f"Subscribed to {topic}")

    def publish_message(self, topic: str, context: Dict[str, Any]):
        """
        Sends a standard JSON packet.
        Format: { 'id': 'my-client-id', 'context': { ... } }
        """
        payload = {
            "id": self.client_id,
            "context": context
        }
        self.client.publish(topic, json.dumps(payload))

    def notify_audio_download(self, target_topic: str, filename: str, download_url: str):
        """
        Specific helper to trigger the 'download x' logic.
        """
        context = {
            "action": "download_audio",
            "filename": filename,
            "url": download_url
        }
        self.publish_message(target_topic, context)

    def stop(self):
        """Gracefully stop the MQTT client."""
        self.client.loop_stop()
        self.client.disconnect()

# --- Example Usage ---
if __name__ == "__main__":
    # 1. Initialize (The broker must be running)
    my_node = MQTTHomeAssistant(client_id="satellite_01", broker_address="127.0.0.1")

    # 2. Define how to handle messages
    def handle_incoming(topic, data):
        sender = data.get("id")
        ctx = data.get("context", {})
        
        if ctx.get("action") == "download_audio":
            print(f"--- TRIGGERING DOWNLOAD: {ctx.get('filename')} from {ctx.get('url')} ---")

    my_node.on_message_received = handle_incoming
    
    # 3. Connect and Subscribe
    my_node.connect()
    my_node.subscribe("home/nodes/satellite_01")

    # 4. Simulate sending a message
    time.sleep(1) # Wait for connection
    my_node.publish_message("home/server", {"status": "online", "battery": 95})
    
    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        my_node.stop()