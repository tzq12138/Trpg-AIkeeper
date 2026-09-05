using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using ApiTestTool.Models;

namespace ApiTestTool.Services;

/// <summary>
/// Manages authentication state with persistence to %APPDATA%/ApiTestTool/.
/// Tokens are encrypted at rest using Windows DPAPI (per-user, per-machine).
/// </summary>
public class AuthStateManager
{
    private readonly AuthState _state;
    private static readonly string AppDataDir = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
        "ApiTestTool");
    private static readonly string EnvFilePath = Path.Combine(AppDataDir, "environments.json");

    // Additional entropy for DPAPI — ties encrypted data to this application
    private static readonly byte[] DpapiEntropy = Encoding.UTF8.GetBytes("AI-Keeper.ApiTestTool.v1");

    public AuthState State => _state;

    public AuthStateManager()
    {
        _state = Load();
    }

    public void Save()
    {
        try
        {
            Directory.CreateDirectory(AppDataDir);
            var profiles = LoadAllProfiles();
            profiles[_state.ProfileName] = new ProfileData
            {
                BaseUrl = _state.BaseUrl,
                BearerToken = Encrypt(_state.BearerToken),
                RoomToken = Encrypt(_state.RoomToken),
                OwnerToken = Encrypt(_state.OwnerToken),
                Username = _state.Username,
                Password = Encrypt(_state.Password),
            };
            var json = JsonSerializer.Serialize(profiles, new JsonSerializerOptions { WriteIndented = true });
            File.WriteAllText(EnvFilePath, json);
        }
        catch (Exception)
        {
            // silently ignore save failures
        }
    }

    private AuthState Load()
    {
        try
        {
            var profiles = LoadAllProfiles();
            if (profiles.TryGetValue("Local Dev", out var profile))
            {
                return new AuthState
                {
                    ProfileName = "Local Dev",
                    BaseUrl = profile.BaseUrl ?? "http://127.0.0.1:3001",
                    BearerToken = Decrypt(profile.BearerToken) ?? "",
                    RoomToken = Decrypt(profile.RoomToken) ?? "",
                    OwnerToken = Decrypt(profile.OwnerToken) ?? "",
                    Username = profile.Username ?? "",
                    Password = Decrypt(profile.Password) ?? "",
                };
            }
        }
        catch (Exception) { }

        return new AuthState { ProfileName = "Local Dev" };
    }

    private Dictionary<string, ProfileData> LoadAllProfiles()
    {
        try
        {
            if (File.Exists(EnvFilePath))
            {
                var json = File.ReadAllText(EnvFilePath);
                return JsonSerializer.Deserialize<Dictionary<string, ProfileData>>(json) ?? new();
            }
        }
        catch (Exception) { }
        return new();
    }

    /// <summary>
    /// Encrypt a string with DPAPI. Returns Base64-encoded ciphertext.
    /// Empty/whitespace strings are returned as-is (not encrypted).
    /// </summary>
    private static string? Encrypt(string? plaintext)
    {
        if (string.IsNullOrWhiteSpace(plaintext)) return plaintext;
        try
        {
            var plainBytes = Encoding.UTF8.GetBytes(plaintext);
            var cipherBytes = ProtectedData.Protect(plainBytes, DpapiEntropy, DataProtectionScope.CurrentUser);
            return Convert.ToBase64String(cipherBytes);
        }
        catch
        {
            // Fallback: prefix with marker so we know it's NOT encrypted
            return "plain:" + plaintext;
        }
    }

    /// <summary>
    /// Decrypt a DPAPI-encrypted Base64 string. Returns null on failure.
    /// Falls back to "plain:" prefix if present (legacy unencrypted data).
    /// </summary>
    private static string? Decrypt(string? ciphertext)
    {
        if (string.IsNullOrWhiteSpace(ciphertext)) return ciphertext;
        try
        {
            // Legacy fallback: if prefixed with "plain:", it was saved before encryption was added
            if (ciphertext.StartsWith("plain:"))
                return ciphertext[6..];

            var cipherBytes = Convert.FromBase64String(ciphertext);
            var plainBytes = ProtectedData.Unprotect(cipherBytes, DpapiEntropy, DataProtectionScope.CurrentUser);
            return Encoding.UTF8.GetString(plainBytes);
        }
        catch (FormatException)
        {
            // Not Base64 — likely legacy plaintext; return as-is for this session
            // (will be encrypted on next Save)
            return ciphertext;
        }
        catch
        {
            return null;
        }
    }

    private class ProfileData
    {
        public string? BaseUrl { get; set; }
        public string? BearerToken { get; set; }
        public string? RoomToken { get; set; }
        public string? OwnerToken { get; set; }
        public string? Username { get; set; }
        public string? Password { get; set; }
    }
}
