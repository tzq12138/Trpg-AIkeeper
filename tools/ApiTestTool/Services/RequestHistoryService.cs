using System;
using System.Collections.ObjectModel;
using System.IO;
using System.Text.Json;
using System.Text.RegularExpressions;
using ApiTestTool.Models;

namespace ApiTestTool.Services;

/// <summary>
/// Persists request history to a JSON Lines file in %APPDATA%.
/// Auth tokens, passwords, and other secrets are redacted before writing.
/// </summary>
public class RequestHistoryService
{
    private static readonly string HistoryDir = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
        "ApiTestTool", "history");

    public ObservableCollection<RequestHistoryEntry> Entries { get; } = new();
    private readonly string _todayFile;

    public RequestHistoryService()
    {
        Directory.CreateDirectory(HistoryDir);
        _todayFile = Path.Combine(HistoryDir, $"history-{DateTime.Now:yyyy-MM-dd}.jsonl");
        LoadToday();
    }

    public void Add(RequestHistoryEntry entry)
    {
        // Sanitize secrets before persisting (request and response side)
        entry.RequestHeaders = SanitizeHeaders(entry.RequestHeaders);
        entry.RequestBody = SanitizeBody(entry.RequestBody);
        entry.Url = SanitizeUrl(entry.Url);
        entry.ResponseBody = SanitizeBody(entry.ResponseBody);

        Entries.Insert(0, entry);
        while (Entries.Count > 1000) Entries.RemoveAt(Entries.Count - 1);

        try
        {
            var json = JsonSerializer.Serialize(entry);
            File.AppendAllText(_todayFile, json + Environment.NewLine);
        }
        catch { /* silently ignore */ }
    }

    public void Clear()
    {
        Entries.Clear();
    }

    /// <summary>
    /// Redact auth header values, leaving only the header name.
    /// </summary>
    private static string SanitizeHeaders(string headers)
    {
        if (string.IsNullOrWhiteSpace(headers)) return headers;
        // Redact full header values for known sensitive headers
        var redacted = Regex.Replace(headers,
            @"^(Authorization|Proxy-Authorization|X-Room-Token|X-Owner-Token|X-Account-Token|X-Api-Key|Cookie):\s*.+$",
            "$1: [REDACTED]",
            RegexOptions.Multiline | RegexOptions.IgnoreCase);
        return redacted;
    }

    /// <summary>
    /// Recursively redact password/token/secret fields from JSON request or
    /// response bodies. Non-JSON text gets a conservative credential-pattern pass.
    /// </summary>
    private static string SanitizeBody(string body)
    {
        if (string.IsNullOrWhiteSpace(body)) return body;
        body = body.Trim();
        if (!body.StartsWith("{") && !body.StartsWith("["))
            return RedactCredentialPatterns(body);
        try
        {
            var doc = JsonDocument.Parse(body);
            using var stream = new MemoryStream();
            using (var writer = new Utf8JsonWriter(stream, new JsonWriterOptions { Indented = false }))
            {
                WriteRedacted(writer, doc.RootElement);
                writer.Flush();
            }
            return System.Text.Encoding.UTF8.GetString(stream.ToArray());
        }
        catch
        {
            // Not valid JSON — fall back to conservative pattern redaction
            return RedactCredentialPatterns(body);
        }
    }

    /// <summary>
    /// Clone a JSON element while redacting sensitive property names at any depth.
    /// </summary>
    private static void WriteRedacted(Utf8JsonWriter writer, JsonElement element)
    {
        if (element.ValueKind == JsonValueKind.Object)
        {
            writer.WriteStartObject();
            foreach (var prop in element.EnumerateObject())
            {
                if (IsSensitiveField(prop.Name))
                {
                    writer.WriteString(prop.Name, "[REDACTED]");
                }
                else
                {
                    writer.WritePropertyName(prop.Name);
                    WriteRedacted(writer, prop.Value);
                }
            }
            writer.WriteEndObject();
        }
        else if (element.ValueKind == JsonValueKind.Array)
        {
            writer.WriteStartArray();
            foreach (var item in element.EnumerateArray())
                WriteRedacted(writer, item);
            writer.WriteEndArray();
        }
        else
        {
            element.WriteTo(writer);
        }
    }

    /// <summary>
    /// Conservative fallback for non-JSON bodies: redact name=value and
    /// "name": "value" forms of known secret fields, plus Bearer tokens.
    /// </summary>
    private static string RedactCredentialPatterns(string text)
    {
        const string names = "(?:password|passwd|token|ownerToken|secret|api[_-]?key|admin_code|credential|jwt)";
        var redacted = Regex.Replace(text,
            $@"(?i)({names}\s*=\s*)[^&\s]+",
            "$1[REDACTED]");
        redacted = Regex.Replace(redacted,
            $@"(?i)(\x22{names}\x22\s*:\s*\x22)[^\x22]*(\x22)",
            "$1[REDACTED]$2");
        redacted = Regex.Replace(redacted,
            @"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+",
            "$1[REDACTED]");
        return redacted;
    }

    /// <summary>
    /// Redact token query parameters from URLs.
    /// </summary>
    private static string SanitizeUrl(string url)
    {
        if (string.IsNullOrWhiteSpace(url)) return url;
        // Redact token/secret values in query strings
        var redacted = Regex.Replace(url,
            @"([?&](?:token|ownerToken|player_token|owner_token|password|api_key|apikey|session|lastSequence)=\s*)[^&\s]+",
            "$1[REDACTED]",
            RegexOptions.IgnoreCase);
        return redacted;
    }

    private static bool IsSensitiveField(string name)
    {
        var lower = name.ToLowerInvariant();
        return lower.Contains("password") || lower.Contains("passwd")
            || lower.Contains("token") || lower.Contains("secret")
            || lower.Contains("api_key") || lower.Contains("apikey")
            || lower.Contains("admin_code") || lower.Contains("credential")
            || lower.Contains("jwt");
    }

    private void LoadToday()
    {
        try
        {
            if (!File.Exists(_todayFile)) return;
            var lines = File.ReadAllLines(_todayFile);
            for (int i = lines.Length - 1; i >= 0 && Entries.Count < 500; i--)
            {
                try
                {
                    var entry = JsonSerializer.Deserialize<RequestHistoryEntry>(lines[i]);
                    if (entry != null) Entries.Add(entry);
                }
                catch { /* skip malformed lines */ }
            }
        }
        catch { /* silently ignore */ }
    }
}
