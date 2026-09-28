# FunHouse: sensor node for the house hub (Batch 2). Publishes temp, humidity,
# pressure, light, motion and RSSI to the P4's hub every 2 s and shows a status
# on the screen. The DotStars are switched off. Ctrl-C at the REPL stops it.
HUB = "192.168.1.147"
NODE = "funhouse"

from sensor_hub import funhouse_node

funhouse_node.run(HUB, node=NODE)
