import machine
import time
from machine import Pin, PWM, I2C
import neopixel
import ssd1306
import bluetooth
import ble_library

# ==========================================
# 0. 테스트 모드 설정
# ==========================================
# True : 10초 간격 속성 테스트 (10s / 20s / 30s / 40s)
# False: 실제 분 단위 동작 (3분 / 4분 / 5분 / 6분)
TEST_MODE = True  

if TEST_MODE:
    T_GREEN  = 10     # 10초: 초록 시작
    T_YELLOW = 20     # 20초: 노랑 시작
    T_RED    = 30     # 30초: 빨강 시작
    T_DIM    = 40     # 40초: 즉시 완전 소등 & GET OUT (이때 경고음 울림!)
    TRANSITION_SEC = 10.0  # 10초 동안 부드럽게 전환
    print("⚠️ [테스트 모드] 10초 간격 동작 (10s -> 20s -> 30s -> 40s)")
else:
    T_GREEN  = 3 * 60  # 180초 (3분)
    T_YELLOW = 4 * 60  # 240초 (4분)
    T_RED    = 5 * 60  # 300초 (5분)
    T_DIM    = 6 * 60  # 360초 (6분 - 이때 경고음 울림!)
    TRANSITION_SEC = 10.0 # 실제 10초간 색상 전환
    print("🚀 [실제 모드] 분 단위 동작")

# ==========================================
# 1. 핀 및 장치 초기화
# ==========================================
NUM_LEDS = 12                          # 네오픽셀 12구
btn = Pin(4, Pin.IN, Pin.PULL_UP)       # D4: 버튼 (풀업)
np = neopixel.NeoPixel(Pin(18), NUM_LEDS) # D18: 네오픽셀 12구
buzzer = PWM(Pin(19), freq=2000, duty=0)   # D19: 패시브 부저

# OLED 설정
try:
    i2c = I2C(0, scl=Pin(22), sda=Pin(21))
    oled = ssd1306.SSD1306_I2C(128, 64, i2c)
    oled_ok = True
except Exception as e:
    oled_ok = False
    print("OLED 연결 실패:", e)

# ==========================================
# 2. 보조 함수 정의
# ==========================================
def set_led(r, g, b):
    """네오픽셀 전체 색상 일괄 변경"""
    r_val, g_val, b_val = int(r), int(g), int(b)
    for i in range(NUM_LEDS):
        np[i] = (r_val, g_val, b_val)
    np.write()

def lerp_color(c1, c2, ratio):
    """두 RGB 색상을 ratio(0.0 ~ 1.0) 비율로 보간"""
    ratio = max(0.0, min(1.0, ratio))
    r = c1[0] + (c2[0] - c1[0]) * ratio
    r = max(0, min(255, int(r)))
    g = c1[1] + (c2[1] - c1[1]) * ratio
    g = max(0, min(255, int(g)))
    b = c1[2] + (c2[2] - c1[2]) * ratio
    b = max(0, min(255, int(b)))
    return (r, g, b)

def play_beep():
    """경고음"""
    buzzer.freq(2000)
    buzzer.duty(512)
    time.sleep(0.2)
    buzzer.duty(0)

def display_text(line1, line2=""):
    """일반 타이머 화면"""
    if not oled_ok: return
    oled.fill(0)
    oled.text(line1, 10, 20)
    if line2:
        oled.text(line2, 10, 40)
    oled.show()

def display_get_out():
    """6분(테스트시 40초) 초과 시 GET OUT 화면"""
    if not oled_ok: return
    oled.fill(0)
    oled.text("=================", 0, 10)
    oled.text("  !! GET OUT !!  ", 0, 28)
    oled.text("=================", 0, 46)
    oled.show()

# ==========================================
# 3. 주요 색상 정의 (RGB)
# ==========================================
COLOR_OFF    = (0, 0, 0)
COLOR_GREEN  = (0, 255, 0)
COLOR_YELLOW = (255, 200, 0)
COLOR_RED    = (255, 0, 0)

# ==========================================
# 4. 변수 및 BLE 초기화
# ==========================================
is_running = False
start_time = 0.0
beep_played = False
last_btn_state = 1

# 전송 딜레이 제어 변수 (1초 주기로 전송을 제한하기 위함)
last_sent_sec = -1
current_color_name = "OFF"

set_led(0, 0, 0)
display_text("Press Button")

# BLE NUS 프로페럴 초기화 (기기명: ESP_KJ)
ble = bluetooth.BLE()
p = ble_library.BLESimplePeripheral(ble, "ESP_KJ")

# 블루투스 수신 명령어 처리
def on_rx(v):
    global is_running, start_time, beep_played
    print("BLE Received Command:", v)
    
    if v == '1': # 타이머 시작 / 정지 토글
        is_running = not is_running
        if is_running:
            start_time = time.time()
            beep_played = False
            p.send("status:RUNNING\n")
            print("▶️ BLE 명령: 타이머 시작!")
        else:
            set_led(0, 0, 0)
            display_text("Press Button")
            p.send("status:STOPPED\n")
            p.send("color:OFF\n")
            print("⏹️ BLE 명령: 타이머 정지!")
            
    elif v == '2': # 타이머 리셋 및 완전 초기화
        is_running = False
        beep_played = False
        set_led(0, 0, 0)
        display_text("Press Button")
        buzzer.duty(0)
        p.send("status:STOPPED\n")
        p.send("color:OFF\n")
        p.send("time:00:00\n")
        print("🔄 BLE 명령: 타이머 리셋!")
        
    elif v == '3': # 수동 경고음(부저) 끄기
        buzzer.duty(0)
        print("🔕 BLE 명령: 경고음 음소거")

p.on_write(on_rx)

# ==========================================
# 5. 메인 루프
# ==========================================
while True:
    current_btn = btn.value()

    # [버튼 입력 처리 - 원터치 토글]
    if last_btn_state == 1 and current_btn == 0:
        time.sleep(0.05)  # 디바운싱
        
        is_running = not is_running
        
        if is_running:
            start_time = time.time()
            beep_played = False
            p.send("status:RUNNING\n")
            print("▶️ 하드웨어 버튼: 타이머 시작!")
        else:
            set_led(0, 0, 0)
            display_text("Press Button")
            p.send("status:STOPPED\n")
            p.send("color:OFF\n")
            print("⏹️ 하드웨어 버튼: 타이머 정지!")

    last_btn_state = current_btn

    # [타이머 동작 영역]
    if is_running:
        elapsed = time.time() - start_time
        mins = int(elapsed) // 60
        secs = int(elapsed) % 60
        total_secs = int(elapsed)

        # --- 1. 부드러운 네오픽셀 색상 제어 ---
        if elapsed < T_GREEN:
            # 0초 ~ 10초 미만: Off
            set_led(*COLOR_OFF)
            current_color_name = "OFF"

        elif T_GREEN <= elapsed < T_YELLOW:
            # 10초 ~ 20초: Off -> GREEN
            ratio = (elapsed - T_GREEN) / TRANSITION_SEC
            col = lerp_color(COLOR_OFF, COLOR_GREEN, ratio)
            set_led(*col)
            current_color_name = "GREEN"

        elif T_YELLOW <= elapsed < T_RED:
            # 20초 ~ 30초: GREEN -> YELLOW
            ratio = (elapsed - T_YELLOW) / TRANSITION_SEC
            col = lerp_color(COLOR_GREEN, COLOR_YELLOW, ratio)
            set_led(*col)
            current_color_name = "YELLOW"

        elif T_RED <= elapsed < T_DIM:
            # 30초 ~ 40초: YELLOW -> RED
            ratio = (elapsed - T_RED) / TRANSITION_SEC
            col = lerp_color(COLOR_YELLOW, COLOR_RED, ratio)
            set_led(*col)
            current_color_name = "RED"

        else:
            # 40초 이상 (실제 6분 이상): 즉시 완전 소등(OFF)
            set_led(*COLOR_OFF)
            current_color_name = "OFF"
            
            # 🔔 6분(테스트 모드 40초) 초과 시점에 경고음 1회 발생
            if not beep_played:
                play_beep()
                p.send("beep:ON\n")
                beep_played = True

        # --- 2. OLED 화면 제어 ---
        if elapsed >= T_DIM:
            display_get_out()
        else:
            display_text("Toilet Timer", "TIME: {:02d}:{:02d}".format(mins, secs))

        # --- 3. BLE 웹 대시보드 데이터 송신 (매 1초 주기로 전송) ---
        if total_secs != last_sent_sec:
            time_str = "{:02d}:{:02d}".format(mins, secs)
            p.send("time:{}\n".format(time_str))
            p.send("color:{}\n".format(current_color_name))
            last_sent_sec = total_secs

    time.sleep(0.03)