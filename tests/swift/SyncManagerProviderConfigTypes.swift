import Foundation

struct DailyCost: Codable {}
struct WrappedData: Codable {}

func providerConfigTypesCompile() {
    _ = SyncManager.setProviderQuotaEnabled("cursor", enabled: true)
    _ = SyncManager.providerSetting("sub2api_base_url")
    _ = SyncManager.setProviderSetting("https://api.example.com", forKey: "sub2api_base_url")
}
