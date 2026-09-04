import Foundation

private enum TestFailure: Error {
    case assertion(String)
}

private func expect(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    if !condition() { throw TestFailure.assertion(message) }
}

@main
struct ProviderCredentialStoreCheck {
    static func main() throws {
        let first = "tokei-provider-test-" + UUID().uuidString
        let second = first + "-updated"
        ProviderCredentialStore.purgeTestItems()
        defer {
            ProviderCredentialStore.purgeTestItems()
            ProviderCredentialStore.destroyTestKeychain()
        }

        for provider in [ProviderSecret.sub2api, .zai] {
            try expect(ProviderCredentialStore.setToken(first, for: provider),
                       "initial save failed for " + provider.rawValue)
            try expect(ProviderCredentialStore.token(for: provider) == first,
                       "initial read failed for " + provider.rawValue)
            try expect(ProviderCredentialStore.setToken(second, for: provider),
                       "update failed for " + provider.rawValue)
            try expect(ProviderCredentialStore.token(for: provider) == second,
                       "updated read failed for " + provider.rawValue)
            try expect(ProviderCredentialStore.setToken("", for: provider),
                       "delete failed for " + provider.rawValue)
            try expect(ProviderCredentialStore.token(for: provider) == nil,
                       "deleted item is still readable for " + provider.rawValue)
        }

        print("provider credential keychain checks passed")
    }
}
