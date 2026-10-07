/*
 * ESP32 语音终端。连上 AgentCenter，把一句话交给云端。
 * 确认后的任务由云端调度执行，设备轮询并收回结果。
 *
 * 依赖：ArduinoJson、WiFi、HTTPClient、Preferences（ESP32 核心自带后三项）
 * 串口输入一行文字即发送。麦克风识别接在 say() 之前即可。
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <ArduinoJson.h>

const char *WIFI_SSID = "your-ssid";
const char *WIFI_PASS = "your-pass";
const char *CLOUD_URL = "http://192.168.1.10:8013";
const char *ENROLL_TOKEN = "change-me";
const char *DEVICE_ID = "esp32-room";
const char *DEVICE_NAME = "客厅";
const char *WORKSPACE = "cyber";

Preferences prefs;
String deviceToken;
String pendingAction;
String pendingPrompt;
String pendingAgent;
String pendingName;
String pendingRuntime;

bool postJson(const String &path, const String &body, String &response) {
  HTTPClient http;
  http.setTimeout(20000);
  http.begin(String(CLOUD_URL) + path);
  http.addHeader("Content-Type", "application/json");
  if (deviceToken.length()) {
    http.addHeader("X-Device-Token", deviceToken);
  }
  int code = http.POST(body);
  response = http.getString();
  http.end();
  if (code < 200 || code >= 300) {
    Serial.printf("HTTP %d %s\n", code, response.c_str());
    return false;
  }
  return true;
}

bool getJson(const String &path, String &response) {
  HTTPClient http;
  http.setTimeout(15000);
  http.begin(String(CLOUD_URL) + path);
  http.addHeader("X-Device-Token", deviceToken);
  int code = http.GET();
  response = http.getString();
  http.end();
  return code >= 200 && code < 300;
}

bool enroll() {
  JsonDocument doc;
  doc["enroll_token"] = ENROLL_TOKEN;
  doc["device_id"] = DEVICE_ID;
  doc["name"] = DEVICE_NAME;
  String body;
  serializeJson(doc, body);
  String raw;
  if (!postJson("/api/super-ai/device/enroll", body, raw)) {
    return false;
  }
  JsonDocument res;
  if (deserializeJson(res, raw)) {
    return false;
  }
  deviceToken = res["device_token"].as<String>();
  prefs.putString("token", deviceToken);
  Serial.printf("enrolled %s\n", res["device_id"].as<const char *>());
  return deviceToken.length() > 0;
}

void collectTask(const char *taskId) {
  for (int i = 0; i < 60; i++) {
    delay(2000);
    String raw;
    if (!getJson(String("/api/super-ai/device/tasks/") + taskId, raw)) {
      continue;
    }
    JsonDocument res;
    if (deserializeJson(res, raw)) {
      continue;
    }
    bool done = res["done"].as<bool>();
    const char *reply = res["reply"] | "";
    if (done) {
      Serial.println(reply);
      return;
    }
    Serial.println(reply);
  }
  Serial.println("任务还没有结果，稍后再问进度。");
}

void say(const String &text) {
  JsonDocument doc;
  doc["text"] = text;
  doc["workspace_slug"] = WORKSPACE;
  if (pendingAction.length()) {
    JsonObject pending = doc["pending"].to<JsonObject>();
    pending["action"] = pendingAction;
    pending["prompt"] = pendingPrompt;
    pending["agent_id"] = pendingAgent;
    pending["agent_name"] = pendingName;
    pending["runtime"] = pendingRuntime;
  }
  String body;
  serializeJson(doc, body);
  String raw;
  if (!postJson("/api/super-ai/device/turn", body, raw)) {
    return;
  }
  JsonDocument res;
  if (deserializeJson(res, raw)) {
    Serial.println("回复无法解析");
    return;
  }
  const char *reply = res["reply"] | "";
  Serial.println(reply);
  JsonObject pending = res["pending"];
  if (!pending.isNull()) {
    pendingAction = pending["action"].as<String>();
    pendingPrompt = pending["prompt"].as<String>();
    pendingAgent = pending["agent_id"].as<String>();
    pendingName = pending["agent_name"].as<String>();
    pendingRuntime = pending["runtime"].as<String>();
  } else {
    pendingAction = "";
  }
  const char *taskId = res["task_id"] | "";
  if (taskId[0]) {
    collectTask(taskId);
  }
}

void setup() {
  Serial.begin(115200);
  prefs.begin("super-ai", false);
  deviceToken = prefs.getString("token", "");
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("wifi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(400);
    Serial.print(".");
  }
  Serial.println(" ok");
  if (!deviceToken.length() && !enroll()) {
    Serial.println("注册失败，检查 ENROLL_TOKEN 与云端地址");
  }
  Serial.println("ready");
}

void loop() {
  if (!Serial.available()) {
    return;
  }
  String line = Serial.readStringUntil('\n');
  line.trim();
  if (line.length()) {
    say(line);
  }
}
