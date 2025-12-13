#!/bin/bash
# Apply JuhRadial MX settings to logiops
# This script generates logid.cfg and reloads the service

CONFIG_JSON="${HOME}/.config/juhradial/config.json"
LOGID_CFG="/etc/logid.cfg"

# Read settings from JSON config
if [ ! -f "$CONFIG_JSON" ]; then
    echo "Config file not found: $CONFIG_JSON"
    exit 1
fi

# Parse JSON values using jq
SMARTSHIFT_ENABLED=$(jq -r '.scroll.smartshift // true' "$CONFIG_JSON")
SMARTSHIFT_THRESHOLD=$(jq -r '.scroll.smartshift_threshold // 50' "$CONFIG_JSON")
NATURAL_SCROLL=$(jq -r '.scroll.natural // false' "$CONFIG_JSON")
SMOOTH_SCROLL=$(jq -r '.scroll.smooth // true' "$CONFIG_JSON")
POINTER_SPEED=$(jq -r '.pointer.speed // 10' "$CONFIG_JSON")

# Convert pointer speed (1-20) to DPI (400-4000)
# Speed 1 = 400 DPI, Speed 20 = 4000 DPI
DPI=$((200 + POINTER_SPEED * 190))

# Convert smartshift to on/off string
if [ "$SMARTSHIFT_ENABLED" = "true" ]; then
    SMARTSHIFT_ON="true"
else
    SMARTSHIFT_ON="false"
fi

# Convert hires scroll setting
if [ "$SMOOTH_SCROLL" = "true" ]; then
    HIRES="true"
else
    HIRES="false"
fi

# Convert natural scroll to invert
if [ "$NATURAL_SCROLL" = "true" ]; then
    INVERT="true"
else
    INVERT="false"
fi

# Generate logid.cfg content
cat > /tmp/logid.cfg.new << EOF
devices: ({
    name: "MX Master 4";

    smartshift: {
        on: ${SMARTSHIFT_ON};
        threshold: ${SMARTSHIFT_THRESHOLD};
        torque: 50;
    };

    hiresscroll: {
        hires: ${HIRES};
        invert: ${INVERT};
        target: false;
    };

    dpi: ${DPI};

    buttons: (
        // Gesture Button (CID 0x1a0) - diverted for radial menu
        {
            cid: 0x1a0;
            action = {
                type: "Keypress";
                keys: ["KEY_F19"];
            };
            divert: true;
        }
    );
});
EOF

echo "Generated logiops config:"
echo "  SmartShift: ${SMARTSHIFT_ON} (threshold: ${SMARTSHIFT_THRESHOLD})"
echo "  HiRes Scroll: ${HIRES}"
echo "  Natural Scroll: ${INVERT}"
echo "  DPI: ${DPI}"

# Check if we need to update (compare configs)
if [ -f "$LOGID_CFG" ]; then
    if diff -q /tmp/logid.cfg.new "$LOGID_CFG" > /dev/null 2>&1; then
        echo "Config unchanged, no update needed."
        rm /tmp/logid.cfg.new
        exit 0
    fi
fi

# Copy to /etc and reload logid
echo "Applying settings (requires sudo)..."
sudo cp /tmp/logid.cfg.new "$LOGID_CFG"
sudo systemctl restart logid

rm /tmp/logid.cfg.new
echo "Settings applied successfully!"
