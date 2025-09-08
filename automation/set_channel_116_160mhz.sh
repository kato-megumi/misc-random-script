#!/bin/sh

# Configure Wi-Fi 6 (802.11ax) settings on radio0 (usually 5GHz)
uci batch <<EOF
set wireless.radio1.country='BR'
set wireless.radio1.channel='114'
set wireless.radio1.htmode='HE160'
set wireless.radio1.txpower='27'
EOF

# Commit changes and reload Wi-Fi
uci commit wireless
wifi reload
