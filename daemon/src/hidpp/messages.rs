//! HID++ message types and connection type

use std::fmt;

use super::constants::report_type;

/// HID++ 2.0 short message (7 bytes)
#[derive(Debug, Clone, Copy)]
pub struct HidppShortMessage {
    /// Report type (0x10 for short)
    pub report_type: u8,
    /// Device index (0xFF for receiver, 0x01-0x06 for paired devices)
    pub device_index: u8,
    /// Feature index in device's feature table
    pub feature_index: u8,
    /// Function ID (upper nibble) | Software ID (lower nibble)
    pub function_sw_id: u8,
    /// Parameters (3 bytes)
    pub params: [u8; 3],
}

impl HidppShortMessage {
    /// Create a new short message
    pub fn new(device_index: u8, feature_index: u8, function_id: u8, sw_id: u8) -> Self {
        Self {
            report_type: report_type::SHORT,
            device_index,
            feature_index,
            function_sw_id: (function_id << 4) | (sw_id & 0x0F),
            params: [0; 3],
        }
    }

    /// Set parameters
    pub fn with_params(mut self, params: [u8; 3]) -> Self {
        self.params = params;
        self
    }

    /// Convert to bytes for sending
    pub fn to_bytes(&self) -> [u8; 7] {
        [
            self.report_type,
            self.device_index,
            self.feature_index,
            self.function_sw_id,
            self.params[0],
            self.params[1],
            self.params[2],
        ]
    }

    /// Parse from bytes
    pub fn from_bytes(bytes: &[u8]) -> Option<Self> {
        if bytes.len() < 7 || bytes[0] != report_type::SHORT {
            return None;
        }
        Some(Self {
            report_type: bytes[0],
            device_index: bytes[1],
            feature_index: bytes[2],
            function_sw_id: bytes[3],
            params: [bytes[4], bytes[5], bytes[6]],
        })
    }

    /// Extract function ID from function_sw_id
    pub fn function_id(&self) -> u8 {
        self.function_sw_id >> 4
    }

    /// Extract software ID from function_sw_id
    pub fn sw_id(&self) -> u8 {
        self.function_sw_id & 0x0F
    }
}

/// HID++ 2.0 long message (20 bytes)
#[derive(Debug, Clone)]
pub struct HidppLongMessage {
    /// Report type (0x11 for long)
    pub report_type: u8,
    /// Device index
    pub device_index: u8,
    /// Feature index
    pub feature_index: u8,
    /// Function ID | Software ID
    pub function_sw_id: u8,
    /// Parameters (16 bytes)
    pub params: [u8; 16],
}

impl HidppLongMessage {
    /// Create a new long message
    pub fn new(device_index: u8, feature_index: u8, function_id: u8, sw_id: u8) -> Self {
        Self {
            report_type: report_type::LONG,
            device_index,
            feature_index,
            function_sw_id: (function_id << 4) | (sw_id & 0x0F),
            params: [0; 16],
        }
    }

    /// Set parameters
    pub fn with_params(mut self, params: &[u8]) -> Self {
        let len = params.len().min(16);
        self.params[..len].copy_from_slice(&params[..len]);
        self
    }

    /// Convert to bytes for sending
    pub fn to_bytes(&self) -> [u8; 20] {
        let mut bytes = [0u8; 20];
        bytes[0] = self.report_type;
        bytes[1] = self.device_index;
        bytes[2] = self.feature_index;
        bytes[3] = self.function_sw_id;
        bytes[4..20].copy_from_slice(&self.params);
        bytes
    }

    /// Parse from bytes
    pub fn from_bytes(bytes: &[u8]) -> Option<Self> {
        if bytes.len() < 20 || bytes[0] != report_type::LONG {
            return None;
        }
        let mut params = [0u8; 16];
        params.copy_from_slice(&bytes[4..20]);
        Some(Self {
            report_type: bytes[0],
            device_index: bytes[1],
            feature_index: bytes[2],
            function_sw_id: bytes[3],
            params,
        })
    }
}

/// Type of connection to the MX Master 4
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConnectionType {
    /// Direct USB connection
    Usb,
    /// Via Logitech Bolt receiver (wireless)
    Bolt,
    /// Direct Bluetooth connection
    Bluetooth,
    /// Via Unifying receiver
    Unifying,
}

impl fmt::Display for ConnectionType {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ConnectionType::Usb => write!(f, "USB"),
            ConnectionType::Bolt => write!(f, "Bolt"),
            ConnectionType::Bluetooth => write!(f, "Bluetooth"),
            ConnectionType::Unifying => write!(f, "Unifying"),
        }
    }
}
