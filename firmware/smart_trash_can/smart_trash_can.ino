#include <Servo.h>

// Servo config
Servo servo1;
Servo servo2;

const uint8_t BIN_COUNT = 4;
const int horizontal_0 = 45;
const int vertical_0 = 87;
const int horizontal_1 = 45;
const int horizontal_2 = 135;
const int vertical_1 = 10;
const int vertical_2 = 160;

const uint8_t trigPins[BIN_COUNT] = {3, 5, 7, 9};
const uint8_t echoPins[BIN_COUNT] = {2, 4, 6, 8};
const uint8_t ledPins[BIN_COUNT] = {A0, A1, A2, A3};
const uint8_t whistlePin = 12;
const int horizontalTargets[BIN_COUNT] = {
  horizontal_1, horizontal_2, horizontal_1, horizontal_2
};
const int verticalTargets[BIN_COUNT] = {
  vertical_1, vertical_1, vertical_2, vertical_2
};

int full[BIN_COUNT] = {0, 0, 0, 0};
int pre_full[BIN_COUNT] = {0, 0, 0, 0};

unsigned long tsrf = 0;
const unsigned long interval_tsrf = 2000;

float readDistance(int trigPin, int echoPin) {
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);

  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);

  // Timeout avoids blocking too long when no echo is received.
  unsigned long duration = pulseIn(echoPin, HIGH, 30000);
  float distance = duration * 0.034 / 2;

  return distance;
}

void throwToBin(uint8_t binIndex) {
  if (binIndex >= BIN_COUNT) {
    return;
  }
  digitalWrite(ledPins[binIndex], HIGH);
  servo1.write(horizontalTargets[binIndex]);
  delay(500);
  servo2.write(verticalTargets[binIndex]);
  delay(1000);

  // if(verticalTargets[binIndex] < vertical_0){
  //   for(int i = verticalTargets[binIndex]; i<= vertical_0; i++){
  //     servo2.write(i);
  //     delay(3);
  //   }
  // }else{
  //   for(int i = verticalTargets[binIndex]; i>= vertical_0; i--){
  //     servo2.write(i);
  //     delay(3);
  //   } 
  // }

int target = vertical_0;
int pos = verticalTargets[binIndex];

while (true) {
  int diff = abs(target - pos);

  // 🔹 Deadband: nếu gần đủ thì dừng luôn
  if (diff <= 1) break;

  // 🔹 Giảm tốc khi gần target
  int step;
  if (diff > 20) step = 3;       // xa → nhanh
  else if (diff > 5) step = 2;   // trung bình
  else step = 1;                 // gần → chậm

  // 🔹 Cập nhật vị trí
  if (pos < target) pos += step;
  else pos -= step;

  servo2.write(pos);
  delay(15); // đừng để quá nhỏ (tránh rung)
}

  delay(500);
  digitalWrite(ledPins[binIndex], LOW);
}

bool updateFullStatusAndLed() {
  bool changed = false;

  for (uint8_t i = 0; i < BIN_COUNT; i++) {
    float d = readDistance(trigPins[i], echoPins[i]);
    Serial.print(d);
    Serial.print("\n");
    if (d < 10) {
      // throwToBin(i);
      digitalWrite(ledPins[i], HIGH);
      full[i] = 1;
    } else {
      digitalWrite(ledPins[i], LOW);
      full[i] = 0;
    }

    if (full[i] != pre_full[i]) {
      changed = true;
    }

    delay(50);
  }
  Serial.print("\n");
  return changed;
}

void sendFullStatusIfChanged() {
  String send = "";
  for (uint8_t i = 0; i < BIN_COUNT; i++) {
    send += String(full[i]) + ",";
  }

  Serial.print(send);

  for (uint8_t i = 0; i < BIN_COUNT; i++) {
    pre_full[i] = full[i];
  }
}

void handleSerialCommand() {
  while (Serial.available() > 0) {
    char cmd = (char)Serial.read();

    if (cmd >= '1' && cmd <= '4') {
      uint8_t binIndex = (uint8_t)(cmd - '1');
      if (full[binIndex] == 0) {
        throwToBin(binIndex);
      }
    }
  }
}

void setup() {
  pinMode(whistlePin, OUTPUT);
  digitalWrite(whistlePin, HIGH);
  delay(500);
  digitalWrite(whistlePin, LOW);

  Serial.begin(9600);

  for (uint8_t i = 0; i < BIN_COUNT; i++) {
    pinMode(trigPins[i], OUTPUT);
    pinMode(echoPins[i], INPUT);
    pinMode(ledPins[i], OUTPUT);
  }

  servo1.attach(10);
  servo2.attach(11);
  servo1.write(horizontal_0);
  servo2.write(vertical_0);
}

void loop() {
  // Check full status by ultrasonic sensors on interval.
  unsigned long now = millis();

  if (now - tsrf >= interval_tsrf) {
    tsrf = now;

    bool changed = updateFullStatusAndLed();
    if (changed) {
      sendFullStatusIfChanged();
    }
  }

  // Throw trash when receiving a command from serial.
  handleSerialCommand();

  delay(200);
}