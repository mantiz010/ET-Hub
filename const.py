DOMAIN = "etbus"

MULTICAST_GROUP = "239.10.0.1"
MULTICAST_PORT = 5555

PING_INTERVAL = 30
OFFLINE_TIMEOUT = 60

# QoS retry timing (fast but bounded)
# 0ms, 40ms, 80ms, 150ms, 300ms, 600ms, 1s
QOS_RETRY_DELAYS_S = (0.00, 0.04, 0.08, 0.15, 0.30, 0.60, 1.00)
QOS_MAX_TOTAL_S = 2.0
