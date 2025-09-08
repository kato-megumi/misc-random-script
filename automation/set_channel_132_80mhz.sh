#!/bin/sh

# Configure Wi-Fi 6 (802.11ax) settings on radio0 (usually 5GHz)
uci batch <<EOF
set wireless.radio1.country='PA'
set wireless.radio1.channel='132'
set wireless.radio1.htmode='HE80'
set wireless.radio1.txpower='27'
EOF

# Commit changes and reload Wi-Fi
uci commit wireless
wifi reload
