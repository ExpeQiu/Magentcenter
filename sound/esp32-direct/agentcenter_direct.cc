#include "agentcenter_direct.h"
#include "sdkconfig.h"
#ifdef CONFIG_AGENTCENTER_DIRECT
#include <esp_http_client.h>
#include <esp_log.h>
#include <esp_wifi.h>
#include <cJSON.h>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include "agentcenter_credentials.h"
#include "application.h"
#include "board.h"
#include "display/display.h"
#include "mcp_server.h"
#include "settings.h"

namespace {
constexpr auto TAG = "AgentCenterDirect";
using Json = std::unique_ptr<cJSON, decltype(&cJSON_Delete)>;
std::mutex state_mutex;
std::string pending_json;
std::string confirmation_id;
std::string last_task_id;

std::string StringField(cJSON* object, const char* key) {
    auto* value = cJSON_GetObjectItemCaseSensitive(object, key);
    return cJSON_IsString(value) && value->valuestring ? value->valuestring : "";
}
std::string EncodeJson(cJSON* json) {
    char* encoded = cJSON_PrintUnformatted(json);
    if (!encoded)
        throw std::runtime_error("JSON encoding failed");
    std::string text(encoded);
    cJSON_free(encoded);
    return text;
}
struct Response {
    std::string body;
    bool too_large = false;
};
esp_err_t OnHttpEvent(esp_http_client_event_t* event) {
    if (event->event_id == HTTP_EVENT_ON_DATA) {
        auto* response = static_cast<Response*>(event->user_data);
        if (response->body.size() + event->data_len > 32768) {
            response->too_large = true;
            return ESP_FAIL;
        }
        response->body.append(static_cast<const char*>(event->data), event->data_len);
    }
    return ESP_OK;
}
Json Request(const std::string& path, const std::string& body = "") {
    Settings settings("agentcenter");
    auto token = settings.GetString("token");
    if (token.empty())
        throw std::runtime_error("超级AI设备未绑定");
    std::string url = std::string(AGENTCENTER_URL) + path;
    Response response;
    esp_http_client_config_t config = {};
    config.url = url.c_str();
    config.timeout_ms = 20000;
    config.event_handler = OnHttpEvent;
    config.user_data = &response;
    config.disable_auto_redirect = true;
    auto client = esp_http_client_init(&config);
    if (!client)
        throw std::runtime_error("无法创建超级AI连接");
    esp_http_client_set_header(client, "X-Device-Token", token.c_str());
    esp_http_client_set_header(client, "Content-Type", "application/json");
    if (!body.empty()) {
        esp_http_client_set_method(client, HTTP_METHOD_POST);
        esp_http_client_set_post_field(client, body.data(), body.size());
    }
    auto error = esp_http_client_perform(client);
    const int status = esp_http_client_get_status_code(client);
    esp_http_client_cleanup(client);
    ESP_LOGI(TAG, "device -> AgentCenter %s: HTTP %d, transport=%s", path.c_str(), status,
             esp_err_to_name(error));
    if (response.too_large)
        throw std::runtime_error("超级AI回复过长");
    if (error != ESP_OK)
        throw std::runtime_error("超级AI连接失败，请稍后重试");
    if (status < 200 || status >= 300)
        throw std::runtime_error("超级AI请求失败 HTTP " + std::to_string(status));
    Json json(cJSON_Parse(response.body.c_str()), cJSON_Delete);
    if (!json || !cJSON_IsObject(json.get()))
        throw std::runtime_error("超级AI回复无法解析");
    return json;
}
void ShowReply(const std::string& reply) {
    Application::GetInstance().Schedule([reply]() {
        auto* display = Board::GetInstance().GetDisplay();
        if (display)
            display->SetChatMessage("assistant", reply.c_str());
    });
}
std::string Ask(const std::string& text) {
    if (text.empty() || text.size() > 8000)
        throw std::runtime_error("请求文字长度无效");
    std::lock_guard<std::mutex> guard(state_mutex);
    Json body(cJSON_CreateObject(), cJSON_Delete);
    cJSON_AddStringToObject(body.get(), "text", text.c_str());
    cJSON_AddStringToObject(body.get(), "workspace_slug", "cyber");
    cJSON_AddStringToObject(body.get(), "channel", "voice");
    cJSON_AddStringToObject(body.get(), "session_id", AGENTCENTER_DEVICE_ID "-direct");
    if (!pending_json.empty() && !confirmation_id.empty()) {
        auto* pending = cJSON_Parse(pending_json.c_str());
        if (!pending)
            throw std::runtime_error("确认信息无法解析");
        cJSON_AddItemToObject(body.get(), "pending", pending);
        cJSON_AddStringToObject(body.get(), "confirmation_id", confirmation_id.c_str());
    }
    auto result = Request("/api/super-ai/device/turn", EncodeJson(body.get()));
    auto reply = StringField(result.get(), "reply");
    if (reply.empty())
        throw std::runtime_error("超级AI未返回文字回复");
    auto* pending = cJSON_GetObjectItemCaseSensitive(result.get(), "pending");
    pending_json = cJSON_IsObject(pending) ? EncodeJson(pending) : "";
    confirmation_id = StringField(result.get(), "confirmation_id");
    last_task_id = StringField(result.get(), "task_id");
    ShowReply(reply);
    return EncodeJson(result.get());
}
std::string Task(const std::string& task_id) {
    std::lock_guard<std::mutex> guard(state_mutex);
    auto id = task_id.empty() ? last_task_id : task_id;
    if (id.empty() || id.size() > 200 ||
        id.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_") !=
            std::string::npos)
        throw std::runtime_error("请提供超级AI返回的有效任务编号");
    auto result = Request("/api/super-ai/device/tasks/" + id);
    auto reply = StringField(result.get(), "reply");
    if (!reply.empty())
        ShowReply(reply);
    return EncodeJson(result.get());
}
void AddNetworkTool(const std::string& name, const std::string& description,
                    const PropertyList& properties,
                    std::function<ReturnValue(const PropertyList&)> callback) {
    auto* tool = new McpTool(name, description, properties, std::move(callback));
    tool->set_background(true);
    McpServer::GetInstance().AddTool(tool);
}
}  // namespace
void RegisterAgentCenterDirectTools() {
    Settings settings("agentcenter", true);
    if (settings.GetString("token").empty())
        settings.SetString("token", AGENTCENTER_BOOTSTRAP_TOKEN);
    AddNetworkTool("self.agentcenter.ask",
                   "用户要求调用超级AI、查询AgentCenter知识或安排任务时调用。ESP32直接请求云端，无"
                   "需电脑。text必须是用户原始请求。朗读reply；若要求确认，先询问用户，只有收到用户"
                   "明确回答后才能再次调用，不得自行确认。普通闲聊由小智处理。",
                   PropertyList({Property("text", kPropertyTypeString)}),
                   [](const PropertyList& props) -> ReturnValue {
                       return Ask(props["text"].value<std::string>());
                   });
    AddNetworkTool("self.agentcenter.task",
                   "查询超级AI先前返回任务的执行进度和结果。任务未完成时如实说明状态。task_"
                   "id留空可查询最近任务。",
                   PropertyList({Property("task_id", kPropertyTypeString, std::string(""))}),
                   [](const PropertyList& props) -> ReturnValue {
                       return Task(props["task_id"].value<std::string>());
                   });
    ESP_LOGI(TAG, "Direct AgentCenter tools registered: %s", AGENTCENTER_URL);
    // One read-only connectivity check after Wi-Fi is ready, outside audio/UI tasks.
    if (xTaskCreate(
            [](void*) {
                vTaskDelay(pdMS_TO_TICKS(15000));
                wifi_ap_record_t ap = {};
                for (int i = 0; i < 120; ++i) {
                    if (esp_wifi_sta_get_ap_info(&ap) == ESP_OK) {
                        try {
                            auto result = Ask("查询系统状态");
                            ESP_LOGI(TAG, "Direct cloud probe OK: %s", result.c_str());
                        } catch (const std::exception& e) {
                            ESP_LOGW(TAG, "Direct cloud probe: %s", e.what());
                        }
                        break;
                    }
                    vTaskDelay(pdMS_TO_TICKS(1000));
                }
                vTaskDelete(nullptr);
            },
            "ac_probe", 8192, nullptr, 2, nullptr) != pdPASS) {
        ESP_LOGW(TAG, "Connectivity check worker unavailable; voice tools remain registered");
    }
}
#endif
