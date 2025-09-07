import network
import machine
import time
import json
import requests

from ota import OTAUpdater

from machine import I2C, Pin
from i2c_lcd import I2cLcd

# LCD Configuration
I2C_ADDR = 0x27
I2C_NUM_ROWS = 2
I2C_NUM_COLS = 16

# Initialize I2C and LCD
i2c = I2C(1, scl=Pin(15), sda=Pin(14), freq=400000)
lcd = I2cLcd(i2c, I2C_ADDR, I2C_NUM_ROWS, I2C_NUM_COLS)

# Initialize UART for weight sensor communication
uart = machine.UART(0, baudrate=9600, tx=machine.Pin(0), rx=machine.Pin(1))

# Initialize UART1 for barcode scanner (e.g., TX=Pin(4), RX=Pin(5))
barcode_uart = machine.UART(1, baudrate=115200, tx=machine.Pin(4), rx=machine.Pin(5))

# Helper to clear a specific LCD line
def lcd_clear_line(line):
    lcd.move_to(line, 0)
    lcd.putstr(" " * I2C_NUM_COLS)
    lcd.move_to(line, 0)

# Display welcome message
#
#  ----------------
# |Ta4feya         |
# |                |
#  ----------------
lcd_clear_line(0)
lcd.putstr("Ta4feya")

# Load and display version from JSON file
try:
    import json
    with open('version.json', 'r') as f:
        version_data = json.load(f)
        version = str(version_data.get('version', 'Unknown'))
    #
    #  ----------------
    # |                |
    # |Version: <ver>  |
    #  ----------------
    lcd_clear_line(1)
    lcd.putstr(f"Version: {version}")
except Exception as e:
    #
    #  ----------------
    # |                |
    # |Version: Unknown|
    #  ----------------
    lcd_clear_line(1)
    lcd.putstr("Version: Unknown")

time.sleep(2)
# Clear LCD for main operation
#
#  ----------------
# |                |
# |                |
#  ----------------
lcd_clear_line(0)
lcd.putstr("                ")
lcd_clear_line(1)
lcd.putstr("                ")

# WiFi Configuration
SSID = "SYS-Horizon"
PASSWORD = "9078@horiz"

# 4x4 Keypad Configuration
ROW_PINS = [9, 8, 7, 6]
COL_PINS = [13, 12, 11, 10]
# COL_PINS = [6, 7, 8, 9]
# ROW_PINS = [10, 11, 12, 13]
KEYS = [
    ['1', '4', '7', '*'],
    ['2', '5', '8', '0'],
    ['3', '6', '9', '#'],
    ['A', 'B', 'C', 'D']
]
rows = [machine.Pin(pin, machine.Pin.OUT) for pin in ROW_PINS]
cols = [machine.Pin(pin, machine.Pin.IN, machine.Pin.PULL_UP) for pin in COL_PINS]

# Initialize WiFi
wlan = network.WLAN(network.STA_IF)
wlan.active(True)

last_status = None

def connect_wifi():
    """Connect to WiFi network"""
    if not wlan.isconnected():
        wlan.connect(SSID, PASSWORD)
        for _ in range(20):
            if wlan.isconnected():
                break
            time.sleep(0.5)
    update_wifi_status(force=True)

def update_wifi_status(force=False):
    """Update WiFi connection status on LCD"""
    global last_status
    status = wlan.isconnected()

    # Auto-reconnect if disconnected
    if not status:
        wlan.connect(SSID, PASSWORD)
        retries = 10
        while not wlan.isconnected() and retries > 0:
            #
            #  ----------------
            # |                |
            # |WiFi: Reconnect.|
            #  ----------------
            lcd_clear_line(1)
            lcd.putstr("WiFi: Reconnecting")
            time.sleep(0.5)
            retries -= 1

    status = wlan.isconnected()
    if force or status != last_status:
        #
        #  ----------------
        # |                |
        # |WiFi: Connected |
        #  ----------------
        # or
        #  ----------------
        # |                |
        # |WiFi: Disconn.  |
        #  ----------------
        lcd_clear_line(1)
        lcd.putstr("                ")
        if status:
            lcd.putstr("WiFi: Connected")
        else:
            lcd.putstr("WiFi: Disconn.")
        last_status = status

def scan_keypad():
    """Scan 4x4 keypad and return pressed key"""
    for r_idx, row in enumerate(rows):
        # Set all rows high
        for r in rows:
            r.value(1)
        # Set current row low
        row.value(0)
        # Check each column
        for c_idx, col in enumerate(cols):
            if col.value() == 0:
                time.sleep_ms(20)  # Debounce
                if col.value() == 0:
                    return KEYS[r_idx][c_idx]
    return None

def flush_uart():
    """Clear UART buffer"""
    while uart.any():
        uart.read()

# For this data : ST,GS,       0.00,kg
def receive_number():
    """Receive weight data from UART sensor"""
    flush_uart()
    buffer = b""
    while True:
        if uart.any():
            char = uart.read(1)
            if char == b'\r':  # End of transmission
                break
            buffer += char
        time.sleep_ms(10)
    
    # Parse weight from format "ST,GS,       0.00,kg" to extract the number
    whole_weight = buffer.decode().strip()
    
    # Split by comma and get the third element (index 2) which contains the weight
    parts = whole_weight.split(',')
    if len(parts) >= 3:
        weight_part = parts[2].strip()  # Remove whitespace
        # Extract only the numeric part (remove 'kg', '+', ' ' if present)
        weight = weight_part.replace('kg', '').replace('+', '').replace(' ', '').strip()
        return weight
    else:
        return "0.00"  # Default if parsing fails

def extract_between_plus_and_k(text = "+ k"):
    """Extract value between '+' and 'k' characters"""
    try:
        start = text.index('+') + 1
        end = text.index('k', start)
        return text[start:end].strip()
    except ValueError:
        return ''
    
# firmware_url = "https://github.com/mahmoudrizkk/Ta4feya-M1/"
def trigger_ota_update():
    """Handle OTA update process with password protection"""
    time.sleep(0.5)
    lcd_clear_line(0)
    lcd.putstr("                ")
    lcd_clear_line(0)
    lcd.putstr("Enter Password:")
    lcd_clear_line(1)
    lcd.putstr("                ")  # Clear the second line
    lcd.putstr("*")
    
    password_buffer = ""
    last_key = None
    
    while True:
        update_wifi_status()
        key = scan_keypad()
        
        if key and key != last_key:
            if key == '#':  # Enter key
                if password_buffer == "1234":  # OTA password
                    lcd_clear_line(0)
                    lcd.putstr("Starting OTA...")
                    try:
                        firmware_url = "https://github.com/mahmoudrizkk/Ta4feya-M1/"                        
                        ota_updater = OTAUpdater(SSID, PASSWORD, firmware_url, "main.py")
                        ota_updater.download_and_install_update_if_available()
                        lcd_clear_line(0)
                        lcd.putstr("OTA Success")
                        time.sleep(3)
                    except Exception as e:
                        lcd_clear_line(0)
                        lcd.putstr("OTA Failed")
                        lcd_clear_line(1)
                        lcd.putstr(str(e)[:6])
                        time.sleep(3)
                    return
                else:
                    lcd_clear_line(0)
                    lcd.putstr("Wrong Password!")
                    time.sleep(2)
                    password_buffer = ""
                    lcd_clear_line(0)
                    lcd.putstr("Enter Password:")
                    lcd_clear_line(1)
                    lcd.putstr("                ")
                    lcd.putstr("*")
            elif key == '*':  # Cancel key
                lcd_clear_line(0)
                lcd.putstr("                ")
                lcd_clear_line(0)
                lcd.putstr("Update Cancelled")
                time.sleep(2)
                lcd_clear_line(0)
                lcd.putstr("                ")
                lcd_clear_line(0)
                lcd.putstr("Enter Type:")
                lcd_clear_line(1)
                lcd.putstr("Press # to confirm")
                return
            elif key in '0123456789ABC':  # Password digits
                password_buffer += key
                lcd_clear_line(0)
                lcd.putstr("                ")
                lcd_clear_line(0)
                lcd.putstr("Enter Password:")
                lcd_clear_line(1)
                lcd.putstr("                ")
                lcd.putstr("*" * min(len(password_buffer), 1))
            last_key = key
        elif not key:
            last_key = None
        
        time.sleep_ms(100)

def send_number(weight, cuttingId, status):
    # http://shatat-ue.runasp.net/api/Devices/ScanForDevice3?pieceId=123&weight=-45&TechId=123&status=1&MachId=1
    url = f"http://shatat-ue.runasp.net/api/Devices/ScanForDevice3?pieceId={cuttingId}&weight={weight}&TechId=123&status={status}&MachId=1"
    
    try:
        update_wifi_status()
        #
        #  ----------------
        # |                |
        # |Sending:<weight>|
        #  ----------------
        lcd_clear_line(0)
        lcd.putstr(" " * 16)
        lcd.putstr(f"Sending:{weight}")

        # Send the POST request
        response = requests.post(url, json={})
        try:
            response_json = response.json()
        except Exception:
            response_json = None

        if response.status_code == 200 and response_json:
            #
            #  ----------------
            # |Success         |
            # |InZ:xxxxx       |
            #  ----------------
            lcd_clear_line(0)
            lcd.putstr("Success")
            lcd_clear_line(1)
            lcd.putstr(f"InZ:{response_json.get('pieceWeight_InZ', '')}")
            time.sleep(2)
            #
            #  ----------------
            # |In:xxxxx        |
            # |Out:yyyyy       |
            #  ----------------
            lcd_clear_line(0)
            lcd.putstr(f"In:{response_json.get('pieceWeight_InZ', '')}")
            lcd_clear_line(1)
            lcd.putstr(f"Out:{weight}")
            time.sleep(2)
        elif response_json:
            # Error with known statusCode/message
            code = str(response_json.get('statusCode', response.status_code))
            msg = str(response_json.get('message', 'Error'))
            #
            #  ----------------
            # |Err:code        |
            # |<error message> |
            #  ----------------
            lcd_clear_line(0)
            lcd.putstr(f"Err:{code}")
            lcd_clear_line(1)
            # Map known error codes/messages to user-friendly text
            if msg == "NO3":
                #
                #  ----------------
                # |Err:code        |
                # |Not found       |
                #  ----------------
                lcd.putstr("Not found")
            elif msg == "NO1":
                #
                #  ----------------
                # |Err:code        |
                # |Wrong type(1)   |
                #  ----------------
                lcd.putstr("Wrong type(1)")
            elif msg == "NO2":
                #
                #  ----------------
                # |Err:code        |
                # |Wrong type(2)   |
                #  ----------------
                lcd.putstr("Wrong type(2)")
            elif msg == "Insufficient stock in store":
                #
                #  ----------------
                # |Err:code        |
                # |No stock        |
                #  ----------------
                lcd.putstr("No stock")
            else:
                #
                #  ----------------
                # |Err:code        |
                # |<custom error>  |
                #  ----------------
                lcd.putstr(msg)
            time.sleep(2)
        else:
            # Unknown error
            #
            #  ----------------
            # |Unknown error    |
            # |<status code>    |
            #  ----------------
            lcd_clear_line(0)
            lcd.putstr("Unknown error")
            lcd_clear_line(1)
            lcd.putstr(str(response.status_code))
            time.sleep(2)
        response.close()
        time.sleep(3)
    except Exception as e:
        #
        #  ----------------
        # |fail<err>        |
        # |                |
        #  ----------------
        lcd_clear_line(0)
        lcd.putstr("fail" + str(e)[:12])
        lcd_clear_line(1)
        lcd.putstr("")
        time.sleep(2)

def receive_barcode():
    """Receive barcode data from UART1 (barcode_uart), ending with '='"""
    flush_uart()
    buffer = b""
    while True:
        if barcode_uart.any():
            char = barcode_uart.read(1)
            if char == b'=':
                break
            buffer += char
        time.sleep_ms(10)
    try:
        return buffer.decode().strip()
    except Exception:
        return ""

# Rename menu_select_type to select_piece_type
# Rename menu_choose_input_method to select_input_method
# Rename menu_enter_piece_id_with_b to enter_piece_id
# Rename menu_take_weight_with_b to enter_weight
# Update all references in main and elsewhere accordingly

def select_piece_type():
    """Menu for selecting Out or Cutting."""
    lcd_clear_line(0)
    lcd.putstr("Select Type:")
    lcd_clear_line(1)
    lcd.putstr("1:Out 2:Cutting")
    while True:
        key = scan_keypad()
        if key in ('1', '2'):
            return key
        elif key == '*':
            trigger_ota_update()


def select_input_method():
    """Menu for choosing Key or Barcode."""
    lcd_clear_line(0)
    lcd.putstr("ID:1-Key 2-Barc")
    lcd_clear_line(1)
    lcd.putstr("B:Back to Type")
    while True:
        key = scan_keypad()
        if key in ('1', '2'):
            return key
        elif key == 'B':
            # Show message and return to type selection
            return None  # Signal to go back to type selection

def enter_piece_id(input_method):
    if input_method == '1':
        lcd_clear_line(0)
        lcd.putstr("Enter Piece ID")
        lcd_clear_line(1)
        lcd.putstr("End with #:")
        piece_id = ""
        last_key = None
        while True:
            key = scan_keypad()
            if key == 'B':
                return 'B'
            if key and key != last_key:
                if key == '#':
                    break
                elif key in '0123456789ABCD':
                    if len(piece_id) < 16:
                        piece_id += key
                        lcd_clear_line(1)
                        lcd.putstr(piece_id)
                last_key = key
            elif not key:
                last_key = None
            time.sleep_ms(100)
        return piece_id
    else:
        lcd_clear_line(0)
        lcd.putstr("Scan Barcode...")
        lcd_clear_line(1)
        lcd.putstr("")
        buffer = b""
        while True:
            # Check for B press on keypad while waiting for barcode
            key = scan_keypad()
            if key == 'B':
                return 'B'
            if barcode_uart.any():
                char = barcode_uart.read(1)
                if char == b'=':
                    # lcd_clear_line(1)
                    # lcd.putstr(buffer.decode())
                    # time.sleep(2)
                    break
                buffer += char
            time.sleep_ms(10)
        try:
            return buffer.decode().strip()
        except Exception:
            return ""

def enter_weight():
    lcd_clear_line(0)
    lcd.putstr("Reading Weight")
    lcd_clear_line(1)
    lcd.putstr("Please wait...")
    weight = receive_number()
    #weight = "1000"
    lcd_clear_line(0)
    lcd.putstr(f"Weight: {weight}")
    lcd_clear_line(1)
    time.sleep(2)
    # lcd.putstr("Press # to send")
    # while True:
    #     key = scan_keypad()
    #     if key == 'B':
    #         return 'B'
    #     if key == '#':
    #         break
    #     time.sleep_ms(100)
    return weight

def main():
    piece_type = None
    input_method = None

    while True:
        # 1. Inquire type if not set
        if piece_type is None:
            piece_type = select_piece_type()
            if not piece_type:
                continue

        # 2. Inquire input method if not set
        if input_method is None:
            input_method = select_input_method()
            if not input_method:
                piece_type = None
                continue

        # 3. Scanning loop
        while True:
            # Piece ID entry, with B handling
            result = enter_piece_id(input_method)
            if result == 'B':
                input_method = None
                break  # Go back to input method selection
            else:
                piece_id = result

            if piece_type is None or input_method is None:
                break  # Go back to the top of the main loop

            # Weight entry, with B handling
            result = enter_weight()
            lcd_clear_line(1)
            lcd.putstr(piece_id)
            if result == 'B':
                input_method = None
                break  # Go back to input method selection
            else:
                weight = result

            if piece_type is None or input_method is None:
                break  # Go back to the top of the main loop

            # Send data
            send_number(weight, piece_id, piece_type)
            time.sleep(1)
            lcd_clear_line(0)
            lcd_clear_line(1)

if __name__ == "__main__":
    # Ensure WiFi is connected before starting main loop
    lcd_clear_line(0)
    lcd.putstr("Connecting WiFi...")
    lcd_clear_line(1)
    lcd.putstr("")
    connect_wifi()
    while not wlan.isconnected():
        lcd_clear_line(0)
        lcd.putstr("WiFi not ready")
        lcd_clear_line(1)
        lcd.putstr("Retrying...")
        connect_wifi()
        time.sleep(3)
    lcd_clear_line(0)
    lcd.putstr("WiFi Connected")
    lcd_clear_line(1)
    lcd.putstr("")
    time.sleep(1)
    main()
    