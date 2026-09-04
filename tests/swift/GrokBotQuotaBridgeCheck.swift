import Foundation

@main
struct GrokBotQuotaBridgeCheck {
    static func main() {
        let encoded = "djEwWQZAlsI15AYVuYhxWuDnjtvLtdxVhAFCrSG6HezmEw0="
        guard let blob = Data(base64Encoded: encoded),
              let value = GrokBotQuotaBridge.decryptElectronSafeStorage(
                blob,
                password: Data("test-password".utf8)
              ),
              value == "fixture-access-token" else {
            exit(1)
        }
        let fixture = Data(#"""
        {
          "usageEventsDisplay": [
            {
              "timestamp": "1800000000000",
              "model": "grok-code-fast-1",
              "clientType": "sand",
              "userEmail": "private@example.com",
              "conversationId": "private-conversation",
              "tokenUsage": {
                "inputTokens": 120,
                "outputTokens": 30,
                "cacheReadTokens": 400,
                "cacheWriteTokens": 10,
                "totalCents": 1.25
              }
            },
            {
              "timestamp": "1800000001000",
              "model": "cursor-model",
              "clientType": "cursor",
              "tokenUsage": {"inputTokens": 99}
            }
          ]
        }
        """#.utf8)
        guard let events = GrokBotQuotaBridge.sanitizedUsageEvents(from: fixture),
              events.count == 1,
              events[0]["model"] as? String == "grok-code-fast-1",
              events[0]["userEmail"] == nil,
              events[0]["conversationId"] == nil,
              (events[0]["eventKey"] as? String)?.count == 64,
              let usage = events[0]["tokenUsage"] as? [String: Any],
              usage["cacheReadTokens"] as? Int == 400 else {
            exit(1)
        }
        print("ok")
    }
}
