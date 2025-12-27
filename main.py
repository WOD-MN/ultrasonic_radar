import sys
import math
import time
import serial
import serial.tools.list_ports
from collections import deque
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import QTimer, Qt, QThread, pyqtSignal
from PyQt5.QtGui import QPainter, QColor, QPen, QFont, QBrush
import platform


# ================================
# CROSS-PLATFORM AUDIO SUPPORT
# ================================
AUDIO_AVAILABLE = False
AUDIO_METHOD = "none"

try:
    import winsound
    AUDIO_AVAILABLE = True
    AUDIO_METHOD = "winsound"
except ImportError:
    pass

if not AUDIO_AVAILABLE:
    try:
        import pygame
        pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
        AUDIO_AVAILABLE = True
        AUDIO_METHOD = "pygame"
    except ImportError:
        pass

if not AUDIO_AVAILABLE:
    try:
        if platform.system() == "Darwin":
            import os
            AUDIO_AVAILABLE = True
            AUDIO_METHOD = "afplay"
        elif platform.system() == "Linux":
            import os
            AUDIO_AVAILABLE = True
            AUDIO_METHOD = "aplay"
    except:
        pass

print(f"🔊 Audio: {AUDIO_METHOD}")


def play_beep(frequency, duration_ms):
    """Cross-platform beep function"""
    if AUDIO_METHOD == "winsound":
        try:
            winsound.Beep(int(frequency), int(duration_ms))
        except:
            pass
    elif AUDIO_METHOD == "pygame":
        try:
            import numpy as np
            sample_rate = 22050
            duration_sec = duration_ms / 1000.0
            samples = int(sample_rate * duration_sec)
            wave = np.sin(2 * np.pi * frequency * np.linspace(0, duration_sec, samples))
            wave = (wave * 32767).astype(np.int16)
            stereo_wave = np.column_stack((wave, wave))
            sound = pygame.sndarray.make_sound(stereo_wave)
            sound.play()
        except:
            pass
    elif AUDIO_METHOD == "afplay":
        try:
            os.system('afplay /System/Library/Sounds/Tink.aiff &')
        except:
            pass
    elif AUDIO_METHOD == "aplay":
        try:
            os.system(f'beep -f {int(frequency)} -l {int(duration_ms)} &')
        except:
            pass


class SerialReaderThread(QThread):
    dataReceived = pyqtSignal(float, float)
    errorOccurred = pyqtSignal(str)
    
    def __init__(self, port, baudrate=115200):
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.running = True
        self.ser = None
        
    def run(self):
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=0.1)
            time.sleep(0.5)
            
            while self.running:
                try:
                    if self.ser.in_waiting:
                        line = self.ser.readline().decode("utf-8", errors='ignore').strip()
                        if "," in line:
                            parts = line.split(",")
                            angle = float(parts[0])
                            distance = float(parts[1])
                            self.dataReceived.emit(angle, distance)
                except ValueError:
                    pass
                except Exception as e:
                    self.errorOccurred.emit(f"Serial error: {str(e)}")
        except Exception as e:
            self.errorOccurred.emit(f"Failed to open port: {str(e)}")
    
    def stop(self):
        self.running = False
        if self.ser and self.ser.is_open:
            self.ser.close()


def auto_detect_port():
    ports = list(serial.tools.list_ports.comports())
    keywords = ["CH340", "CP210", "USB", "UART", "Serial", "Wemos", "Silicon Labs", "D1 Mini", "Arduino"]
    
    print(f"📡 Serial ports found: {len(ports)}")
    
    for p in ports:
        for k in keywords:
            if k.lower() in p.description.lower():
                print(f"✅ Auto-selected: {p.device}")
                return p.device
    
    if ports:
        print(f"✅ Using: {ports[0].device}")
        return ports[0].device
    
    return None


class AdvancedRadarWindow(QWidget):
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("Advanced Radar System")
        self.setGeometry(50, 50, 1800, 1350)
        self.setStyleSheet("background-color: #0a0e27;")
        
        # Radar configuration
        self.max_distance = 100
        self.radar_radius = 450
        self.scale_factor = 1.5
        
        self.red_zone = 25
        self.yellow_zone = 35
        
        # Current data
        self.current_angle = 0.0
        self.current_distance = self.max_distance
        self.smoothed_distance = self.max_distance
        
        # Data trails
        self.point_trail = deque(maxlen=180)
        self.fade_speed = 3
        
        # Threat tracking
        self.threat_log = deque(maxlen=20)
        self.is_danger = False
        self.is_warning = False
        
        # Audio control
        self.last_beep_time = 0
        self.beep_cooldown = 0.3
        self.audio_enabled = AUDIO_AVAILABLE
        
        # Performance metrics
        self.fps_counter = 0
        self.fps_timer = time.time()
        self.current_fps = 0
        self.packet_count = 0
        self.error_count = 0
        
        # Serial communication
        self.serial_port = auto_detect_port()
        if not self.serial_port:
            if platform.system() == "Darwin":
                self.serial_port = "/dev/cu.usbserial-0001"
            elif platform.system() == "Linux":
                self.serial_port = "/dev/ttyUSB0"
            else:
                self.serial_port = "COM3"
        
        self.serial_reader = SerialReaderThread(self.serial_port)
        self.serial_reader.dataReceived.connect(self.on_radar_data)
        self.serial_reader.errorOccurred.connect(self.on_serial_error)
        self.serial_reader.start()
        
        # Smoothing filter
        self.ema_alpha = 0.2
        
        # Update timer
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_radar)
        self.timer.start(16)
    
    def on_radar_data(self, angle, distance):
        self.current_angle = angle
        self.packet_count += 1
        
        self.smoothed_distance = (distance * self.ema_alpha) + (self.smoothed_distance * (1 - self.ema_alpha))
        self.smoothed_distance = min(self.smoothed_distance, self.max_distance)
        self.current_distance = self.smoothed_distance
        
        self.is_danger = self.current_distance <= self.red_zone
        self.is_warning = self.current_distance <= self.yellow_zone
        
        if self.is_warning and self.audio_enabled:
            self.play_threat_alert(self.current_distance)
        
        if self.is_danger:
            self.threat_log.append({
                'angle': angle,
                'distance': self.current_distance,
                'time': time.time(),
                'severity': 'CRITICAL'
            })
        elif self.is_warning:
            self.threat_log.append({
                'angle': angle,
                'distance': self.current_distance,
                'time': time.time(),
                'severity': 'WARNING'
            })
        
        # FLIP: 0° at LEFT (add 180 to angle)
        flipped_angle = (self.current_angle + 180) % 360
        r = (self.current_distance / self.max_distance) * self.radar_radius
        x = r * math.cos(math.radians(flipped_angle))
        y = r * math.sin(math.radians(flipped_angle))
        
        color = QColor(255, 0, 0, 255) if self.is_danger else QColor(0, 255, 100, 255)
        self.point_trail.append({
            'x': x,
            'y': y,
            'alpha': 255,
            'color': color,
            'is_danger': self.is_danger
        })
    
    def on_serial_error(self, error_msg):
        self.error_count += 1
        if self.error_count < 5:
            print(f"❌ Error: {error_msg}")
    
    def play_threat_alert(self, distance):
        now = time.time()
        
        if self.is_danger:
            cooldown = 0.05 + (distance / self.red_zone) * 0.1
            freq = 1500 + (1 - distance / self.red_zone) * 500
        else:
            cooldown = 0.2 + (distance / self.yellow_zone) * 0.3
            freq = 1000 + (1 - distance / self.yellow_zone) * 400
        
        if now - self.last_beep_time > cooldown:
            duration = int(50 + (self.yellow_zone - distance) * 10)
            duration = max(30, min(duration, 200))
            
            try:
                play_beep(int(freq), duration)
            except Exception as e:
                pass
                
            self.last_beep_time = now
    
    def update_radar(self):
        for point in self.point_trail:
            point['alpha'] -= self.fade_speed
        
        self.fps_counter += 1
        current_time = time.time()
        if current_time - self.fps_timer >= 1.0:
            self.current_fps = self.fps_counter
            self.fps_counter = 0
            self.fps_timer = current_time
        
        self.update()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        
        w = self.width()
        h = self.height()
        cx = w // 2
        cy = h // 2 - int(45 * self.scale_factor)
        
        self.draw_grid(painter, cx, cy)
        self.draw_threat_zones(painter, cx, cy)
        self.draw_radar_circles(painter, cx, cy)
        self.draw_angle_lines(painter, cx, cy)
        self.draw_sweep_glow(painter, cx, cy)
        self.draw_point_trail(painter, cx, cy)
        self.draw_crosshair(painter, cx, cy)
        self.draw_hud_display(painter)
        self.draw_threat_log(painter)
        self.draw_status_bar(painter, w, h)
    
    def draw_grid(self, painter, cx, cy):
        """Draw subtle grid background"""
        painter.fillRect(0, 0, self.width(), self.height(), QColor(10, 14, 39))
        
        grid_spacing = int(50 * self.scale_factor)
        grid_color = QColor(50, 60, 100, 30)
        
        painter.setPen(QPen(grid_color, 1))
        for x in range(0, self.width(), grid_spacing):
            painter.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), grid_spacing):
            painter.drawLine(0, y, self.width(), y)
    
    def draw_threat_zones(self, painter, cx, cy):
        """Draw colored threat zones"""
        red_radius = (self.red_zone / self.max_distance) * self.radar_radius
        red_color = QColor(255, 0, 0, 15)
        painter.setBrush(QBrush(red_color))
        painter.setPen(QPen(QColor(255, 0, 0, 100), int(2 * self.scale_factor)))
        painter.drawEllipse(int(cx - red_radius), int(cy - red_radius), 
                          int(red_radius * 2), int(red_radius * 2))
        
        yellow_radius = (self.yellow_zone / self.max_distance) * self.radar_radius
        yellow_color = QColor(255, 200, 0, 10)
        painter.setBrush(QBrush(yellow_color))
        painter.setPen(QPen(QColor(255, 180, 0, 80), int(2 * self.scale_factor)))
        painter.drawEllipse(int(cx - yellow_radius), int(cy - yellow_radius),
                          int(yellow_radius * 2), int(yellow_radius * 2))
    
    def draw_radar_circles(self, painter, cx, cy):
        """Draw main radar circles"""
        green = QColor(0, 255, 150)
        painter.setPen(QPen(green, int(3 * self.scale_factor)))
        painter.drawEllipse(cx - self.radar_radius, cy - self.radar_radius,
                          self.radar_radius * 2, self.radar_radius * 2)
        
        for distance in range(20, int(self.max_distance), 20):
            r = (distance / self.max_distance) * self.radar_radius
            painter.setPen(QPen(QColor(0, 200, 120, 60), int(1.5 * self.scale_factor)))
            painter.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))
    
    def draw_angle_lines(self, painter, cx, cy):
        """Draw angle reference lines - 0° at LEFT"""
        painter.setFont(QFont("Courier New", int(14 * self.scale_factor)))
        
        for angle in range(0, 360, 30):
            # FLIP: 0° at LEFT (add 180)
            flipped_angle = (angle + 180) % 360
            rad = math.radians(flipped_angle)
            
            x = cx + self.radar_radius * math.cos(rad)
            y = cy + self.radar_radius * math.sin(rad)
            
            painter.setPen(QPen(QColor(0, 200, 120, 50), int(1.5 * self.scale_factor)))
            painter.drawLine(cx, cy, int(x), int(y))
            
            label_distance = self.radar_radius + int(45 * self.scale_factor)
            label_x = cx + label_distance * math.cos(rad)
            label_y = cy + label_distance * math.sin(rad)
            
            painter.setPen(QColor(0, 255, 150))
            text = f"{angle}°"
            fm = painter.fontMetrics()
            text_width = fm.horizontalAdvance(text)
            text_height = fm.height()
            
            painter.drawText(int(label_x - text_width/2), int(label_y + text_height/4), text)
    
    def draw_sweep_glow(self, painter, cx, cy):
        """Draw animated sweep beam with glow"""
        # FLIP: Add 180 to current angle
        flipped_angle = (self.current_angle + 180) % 360
        angle_rad = math.radians(flipped_angle)
        x = cx + self.radar_radius * math.cos(angle_rad)
        y = cy + self.radar_radius * math.sin(angle_rad)
        
        for i in range(30, 0, -1):
            alpha = int(150 * (1 - i / 30))
            painter.setPen(QPen(QColor(0, 255, 150, alpha), int((4.5 - i/7) * self.scale_factor)))
            glow_angle = angle_rad - math.radians(i * 0.8)
            gx = cx + self.radar_radius * math.cos(glow_angle)
            gy = cy + self.radar_radius * math.sin(glow_angle)
            painter.drawLine(int(cx), int(cy), int(gx), int(gy))
        
        painter.setPen(QPen(QColor(0, 255, 100), int(4.5 * self.scale_factor)))
        painter.drawLine(int(cx), int(cy), int(x), int(y))
    
    def draw_point_trail(self, painter, cx, cy):
        """Draw detected object trails"""
        for point in list(self.point_trail):
            if point['alpha'] > 0:
                size = int(12 * self.scale_factor) if point['is_danger'] else int(9 * self.scale_factor)
                painter.setPen(QPen(QColor(
                    point['color'].red(),
                    point['color'].green(),
                    point['color'].blue(),
                    int(point['alpha'])
                ), size))
                painter.drawPoint(int(cx + point['x']), int(cy + point['y']))
    
    def draw_crosshair(self, painter, cx, cy):
        """Draw center crosshair"""
        painter.setPen(QPen(QColor(0, 255, 150, 200), int(3 * self.scale_factor)))
        painter.drawEllipse(cx - int(12 * self.scale_factor), cy - int(12 * self.scale_factor), 
                           int(24 * self.scale_factor), int(24 * self.scale_factor))
        painter.drawLine(cx - int(22.5 * self.scale_factor), cy, cx + int(22.5 * self.scale_factor), cy)
        painter.drawLine(cx, cy - int(22.5 * self.scale_factor), cx, cy + int(22.5 * self.scale_factor))
    
    def draw_hud_display(self, painter):
        """Draw HUD information panel - REDUCED BY 20%"""
        # Reduced by 20%: 16pt * 0.8 = 12.8pt
        painter.setFont(QFont("Courier New", int(16 * self.scale_factor * 0.8)))
        painter.setPen(QColor(0, 255, 150))
        
        # Reduced positions by 20%
        hud_y = int(45 * self.scale_factor * 0.8)
        hud_x = int(30 * self.scale_factor * 0.8)
        line_height = int(37.5 * self.scale_factor * 0.8)
        
        # Compact professional HUD - removed unnecessary elements
        painter.drawText(hud_x, hud_y, "╔═══════════════════════════════╗")
        hud_y += line_height
        painter.drawText(hud_x, hud_y, "║ RADAR SYSTEM                ║")
        hud_y += line_height
        painter.drawText(hud_x, hud_y, "╠═══════════════════════════════╣")
        hud_y += line_height
        
        painter.drawText(hud_x, hud_y, f"║ ANGLE: {self.current_angle:6.1f}°        ║")
        hud_y += line_height
        
        painter.drawText(hud_x, hud_y, f"║ DISTANCE: {self.current_distance:5.1f} cm      ║")
        hud_y += line_height
        
        painter.drawText(hud_x, hud_y, "╠═══════════════════════════════╣")
        hud_y += line_height
        
        if self.is_danger:
            painter.setPen(QColor(255, 0, 0))
            painter.drawText(hud_x, hud_y, "║ ⚠ CRITICAL THREAT         ║")
        elif self.is_warning:
            painter.setPen(QColor(255, 165, 0))
            painter.drawText(hud_x, hud_y, "║ ⚠ WARNING                  ║")
        else:
            painter.setPen(QColor(0, 255, 150))
            painter.drawText(hud_x, hud_y, "║ ✓ NORMAL                   ║")
        
        hud_y += line_height
        painter.setPen(QColor(0, 255, 150))
        painter.drawText(hud_x, hud_y, "╚═══════════════════════════════╝")
    
    def draw_threat_log(self, painter):
        """Draw recent threat log"""
        painter.setFont(QFont("Courier New", int(13.5 * self.scale_factor)))
        painter.setPen(QColor(100, 150, 255))
        
        log_y = self.height() - int(180 * self.scale_factor)
        painter.drawText(int(30 * self.scale_factor), log_y, "THREATS:")
        log_y += int(30 * self.scale_factor)
        
        for threat in list(self.threat_log)[-5:]:
            if threat['severity'] == 'CRITICAL':
                painter.setPen(QColor(255, 0, 0))
            else:
                painter.setPen(QColor(255, 165, 0))
            
            painter.drawText(int(30 * self.scale_factor), log_y, 
                           f"  {threat['angle']:3.0f}° @ {threat['distance']:5.1f}cm")
            log_y += int(27 * self.scale_factor)
    
    def draw_status_bar(self, painter, w, h):
        """Draw bottom status bar"""
        painter.setFont(QFont("Courier New", int(15 * self.scale_factor * 0.7)))
        
        bar_color = QColor(30, 40, 80)
        bar_height = int(60 * self.scale_factor)
        painter.fillRect(0, h - bar_height, w, bar_height, bar_color)
        painter.setPen(QPen(QColor(0, 200, 120), int(1.5 * self.scale_factor)))
        painter.drawLine(0, h - bar_height, w, h - bar_height)
        
        painter.setPen(QColor(0, 255, 150))
        y_offset = int(22.5 * self.scale_factor * 0.7)
        painter.drawText(int(30 * self.scale_factor), h - y_offset, 
                        f"FPS: {self.current_fps} | Packets: {self.packet_count}")
        painter.drawText(w - int(400 * self.scale_factor * 0.7), h - y_offset, 
                        f"{platform.system()}")
    
    def closeEvent(self, event):
        """Cleanup on close"""
        self.serial_reader.stop()
        self.serial_reader.wait()
        self.timer.stop()
        event.accept()


if __name__ == "__main__":
    print("\n" + "="*50)
    print("🛰️  ADVANCED RADAR SYSTEM - PROFESSIONAL")
    print("="*50)
    print(f"OS: {platform.system()}")
    print(f"Display: 1800x1350")
    print(f"0° Position: LEFT (FLIPPED)")
    print(f"HUD Panel: Reduced 20%")
    print("="*50 + "\n")
    
    app = QApplication(sys.argv)
    window = AdvancedRadarWindow()
    window.show()
    sys.exit(app.exec_())
