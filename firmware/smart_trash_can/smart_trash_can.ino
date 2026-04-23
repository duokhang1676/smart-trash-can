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

unsigned long tsrf = 0;
const unsigned long interval_tsrf = 5000;

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

void warm_up(){
  digitalWrite(whistlePin, HIGH);
  servo1.write(horizontal_2);
  delay(1000);
  servo1.write(horizontal_0);
  digitalWrite(whistlePin, LOW);
}

void throwToBin(uint8_t binIndex) {
  if (binIndex >= BIN_COUNT) {
    return;
  }
  servo1.write(horizontalTargets[binIndex]);
  delay(500);
  servo2.write(verticalTargets[binIndex]);
  delay(1000);

  int target = vertical_0;
  int pos = verticalTargets[binIndex];

  while (true) {
    int diff = abs(target - pos);

    // Deadband: nếu gần đủ thì dừng luôn
    if (diff <= 1) break;

    // Giảm tốc khi gần target
    int step;
    if (diff > 20) step = 3;       // xa → nhanh
    else if (diff > 5) step = 2;   // trung bình
    else step = 1;                 // gần → chậm

    // Cập nhật vị trí
    if (pos < target) pos += step;
    else pos -= step;

    servo2.write(pos);
    delay(15); // đừng để quá nhỏ (tránh rung)
}

  delay(500);
}

int capacity[BIN_COUNT] = {0, 0, 0, 0};
int full[BIN_COUNT] = {0,0,0,0};

void getCapacity(int capacity[], int full[]) {
  for (uint8_t i = 0; i < BIN_COUNT; i++) {
    float d = readDistance(trigPins[i], echoPins[i]);
    if (d < 10) {
      capacity[i] = 100;
      full[i] = 1;
      digitalWrite(ledPins[i], HIGH);
    } else {
      capacity[i] = (int)(((d-10)/35) * 100);
      if (capacity[i]>100){
        capacity[i]=100;
      }
      capacity[i] = 100 - capacity[i];
      full[i] = 0;
      digitalWrite(ledPins[i], LOW);
    }
    delay(50);
  }
}

void sendCapacity(int capacity[]) {
  String send = "";
  for (uint8_t i = 0; i < BIN_COUNT; i++) {
    send += String(capacity[i]);
    if (i < BIN_COUNT - 1) {
      send += ",";
    }
  }
  Serial.println(send);
}

void handleSerialCommand() {
  while (Serial.available() > 0) {
    char cmd = (char)Serial.read();
    if (cmd == '0'){
      warm_up();
      getCapacity(capacity, full);
      sendCapacity(capacity);
    }else if (cmd >= '1' && cmd <= '4') {
      uint8_t binIndex = (uint8_t)(cmd - '1');
      getCapacity(capacity, full);
      if (full[binIndex] == 0) {
        throwToBin(binIndex);
        sendCapacity(capacity);
      }else{
        digitalWrite(whistlePin, HIGH);
        delay(500);
        digitalWrite(whistlePin, LOW);
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
  unsigned long now = millis();

  if (now - tsrf >= interval_tsrf) {
    tsrf = now;
    getCapacity(capacity, full);
    sendCapacity(capacity);
  }
  // Throw trash when receiving a command from serial.
  handleSerialCommand();
  delay(200);
}