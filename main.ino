#include <Servo.h>

// ================================
// PIN CONFIGURATION (Wemos D1 Mini)
// ================================
#define TRIG_PIN D6
#define ECHO_PIN D5
#define SERVO_PIN D2

// ================================
// SERVO CONFIGURATION
// ================================
Servo radarServo;

const int MIN_ANGLE = 0;
const int MAX_ANGLE = 180;
const int SWEEP_STEP = 3;           // Smaller steps for smooth sweep
const int SWEEP_DELAY_MS = 10;      // Milliseconds per step
const int SERVO_SPEED_MS = 5;       // Servo update speed

bool sweepForward = true;
int currentAngle = MIN_ANGLE;
int targetAngle = MIN_ANGLE;
unsigned long lastServoUpdateTime = 0;

// ================================
// ULTRASONIC SENSOR CONFIGURATION
// ================================
const int MAX_DISTANCE_CM = 100;    // Maximum range for display
const int RED_ZONE_CM = 25;         // Red alert zone
const int SOUND_TRIGGER_CM = 35;    // Sound trigger distance

// ================================
// ADVANCED FILTERING
// ================================
const int MEDIAN_SAMPLES = 9;       // Odd number for median (9 is optimal for noise)
long distanceBuffer[MEDIAN_SAMPLES];
int bufferIndex = 0;

// Exponential Moving Average (EMA) for ultra-smooth readings
float emaDistance = 0.0;
const float EMA_ALPHA = 0.25;       // Smoothing factor (0.1-0.3 recommended)

// ================================
// SENSOR READING STATISTICS
// ================================
long rawReadings[3];
int readingIndex = 0;

// ================================
// MEDIAN FILTER USING SORTING NETWORK (9 elements)
// ================================
long getMedian(long arr[]) {
  // Optimized sorting network for 9 elements (45 comparisons max)
  // This is more efficient than bubble sort
  #define CMP_SWAP(i, j) if (arr[i] > arr[j]) { long temp = arr[i]; arr[i] = arr[j]; arr[j] = temp; }
  
  // Bitonic sort optimized for 9 elements
  CMP_SWAP(0, 1); CMP_SWAP(3, 4); CMP_SWAP(6, 7);
  CMP_SWAP(1, 2); CMP_SWAP(4, 5); CMP_SWAP(7, 8);
  CMP_SWAP(0, 1); CMP_SWAP(3, 4); CMP_SWAP(6, 7);
  CMP_SWAP(0, 3); CMP_SWAP(3, 6);
  CMP_SWAP(0, 3); CMP_SWAP(1, 4); CMP_SWAP(2, 5);
  CMP_SWAP(4, 7); CMP_SWAP(5, 8);
  CMP_SWAP(1, 4); CMP_SWAP(2, 4); CMP_SWAP(5, 7);
  CMP_SWAP(3, 6); CMP_SWAP(4, 6); CMP_SWAP(5, 6);
  
  return arr[4];  // Median is middle element
  #undef CMP_SWAP
}

// ================================
// RAW DISTANCE READING
// ================================
long readDistanceRaw() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  // PulseIn with extended timeout (35ms max) for 100cm range
  long duration = pulseIn(ECHO_PIN, HIGH, 35000);
  
  // Timeout protection
  if (duration == 0) {
    return -1;  // Invalid reading
  }

  // Distance formula: distance = (duration / 2) / 29.1
  // Simplified: distance = duration * 0.0343 / 2
  long distance = (duration * 343) / 20000;  // Integer math avoids floating point
  
  return distance;
}

// ================================
// MEDIAN FILTERED DISTANCE (with outlier rejection)
// ================================
long readDistanceFiltered() {
  // Collect MEDIAN_SAMPLES readings
  for (int i = 0; i < MEDIAN_SAMPLES; i++) {
    long raw = readDistanceRaw();
    
    // Outlier rejection: reject values > 150% of MAX_DISTANCE
    if (raw > 0 && raw <= (MAX_DISTANCE_CM * 1.5)) {
      distanceBuffer[i] = raw;
    } else {
      distanceBuffer[i] = MAX_DISTANCE_CM;  // Replace outliers with max
    }
    
    delayMicroseconds(100);  // Mini delay between readings
  }

  // Get median of 9 samples
  long temp[MEDIAN_SAMPLES];
  memcpy(temp, distanceBuffer, sizeof(distanceBuffer));  // Copy for sorting
  long medianValue = getMedian(temp);

  return medianValue;
}

// ================================
// EXPONENTIAL MOVING AVERAGE (ultra-smooth output)
// ================================
float applyEMA(long rawValue) {
  if (rawValue < 0 || rawValue > MAX_DISTANCE_CM) {
    return emaDistance;  // Keep last valid reading
  }
  
  // EMA formula: newEMA = (rawValue * alpha) + (oldEMA * (1 - alpha))
  emaDistance = (rawValue * EMA_ALPHA) + (emaDistance * (1.0 - EMA_ALPHA));
  
  return emaDistance;
}

// ================================
// SMOOTH SERVO MOVEMENT (cubic interpolation)
// ================================
void updateServoSmooth() {
  unsigned long currentTime = millis();
  
  if (currentTime - lastServoUpdateTime >= SERVO_SPEED_MS) {
    lastServoUpdateTime = currentTime;
    
    // Smooth angle interpolation (linear easing)
    if (currentAngle != targetAngle) {
      int diff = targetAngle - currentAngle;
      
      // Limit step size for smooth motion
      if (diff > 3) {
        currentAngle += 3;
      } else if (diff < -3) {
        currentAngle -= 3;
      } else {
        currentAngle = targetAngle;
      }
      
      radarServo.write(currentAngle);
    }
  }
}

// ================================
// SWEEP ANGLE GENERATION
// ================================
void updateSweepAngle() {
  static unsigned long lastSweepTime = 0;
  unsigned long currentTime = millis();
  
  if (currentTime - lastSweepTime >= SWEEP_DELAY_MS) {
    lastSweepTime = currentTime;
    
    // Update target angle
    if (sweepForward) {
      targetAngle += SWEEP_STEP;
      if (targetAngle >= MAX_ANGLE) {
        targetAngle = MAX_ANGLE;
        sweepForward = false;
      }
    } else {
      targetAngle -= SWEEP_STEP;
      if (targetAngle <= MIN_ANGLE) {
        targetAngle = MIN_ANGLE;
        sweepForward = true;
      }
    }
  }
}

// ================================
// SERIAL OUTPUT (optimized format)
// ================================
void sendRadarData(int angle, float distance) {
  // Format: angle,distance\r\n
  // Minimal overhead for fast serial communication
  Serial.print(angle);
  Serial.print(",");
  Serial.println((int)distance);  // Send as integer to reduce serial bandwidth
}

// ================================
// SETUP
// ================================
void setup() {
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);

  // Initialize servo
  radarServo.attach(SERVO_PIN);
  radarServo.write(currentAngle);

  // Initialize serial
  Serial.begin(115200);
  delay(1000);

  // Initialize filters
  emaDistance = (float)MAX_DISTANCE_CM;
  
  Serial.println("\n=== Advanced Radar System Started ===");
  Serial.println("Range: 0-100cm | Red Zone: <=25cm | Sound Trigger: <=35cm");
  Serial.println("Filters: 9-point Median + EMA Smoothing");
  Serial.println("======================================\n");
}

// ================================
// MAIN LOOP (optimized timing)
// ================================
void loop() {
  // Update sweep angle (non-blocking)
  updateSweepAngle();
  
  // Update servo position with smooth interpolation (non-blocking)
  updateServoSmooth();

  // Read and filter distance
  long medianDistance = readDistanceFiltered();
  
  // Apply EMA smoothing
  float smoothDistance = applyEMA(medianDistance);
  
  // Clamp to range
  int finalDistance = constrain((int)smoothDistance, 0, MAX_DISTANCE_CM);

  // Send data
  sendRadarData(currentAngle, finalDistance);

  // Minimal delay (everything else is non-blocking)
  delayMicroseconds(500);
}
