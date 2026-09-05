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
        // Sanitize secrets before persisting
        entry.RequestHeaders = SanitizeHeaders(entry.RequestHeaders);
        entry.RequestBody = SanitizeBody(entry.RequestBody);
        entry.Url = SanitizeUrl(entry.Url);

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
            @"^(Authorization|X-Room-Token|X-Owner-Token|X-Account-Token):\s*.+$",
            "$1: [REDACTED]",
            RegexOptions.Multiline | RegexOptions.IgnoreCase);
        return redacted;
    }

    /// <summary>
    /// Redact password/token fields from JSON request bodies.
    /// </summary>
    private static string SanitizeBody(string body)
    {
        if (string.IsNullOrWhiteSpace(body)) return body;
        try
        {
            // Only sanitize if it looks like JSON
            body = body.Trim();
            if (!body.StartsWith("{")) return body;

            var doc = JsonDocument.Parse(body);
            using var stream = new MemoryStream();
            using var writer = new Utf8JsonWriter(stream, new JsonWriterOptions { Indented = false });

            writer.WriteStartObject();
            foreach (var prop in doc.RootElement.EnumerateObject())
            {
                if (IsSensitiveField(prop.Name))
                    writer.WriteString(prop.Name, "[REDACTED]");
                else
                    prop.WriteTo(writer);
            }
            writer.WriteEndObject();
            writer.Flush();

            return System.Text.Encoding.UTF8.GetString(stream.ToArray());
        }
        catch
        {
            return body;
        }
    }

    /// <summary>
    /// Redact token query parameters from URLs.
    /// </summary>
    private static string SanitizeUrl(string url)
    {
        if (string.IsNullOrWhiteSpace(url)) return url;
        // Redact token values in query strings
        var redacted = Regex.Replace(url,
            @"([?&](?:token|ownerToken|player_token|owner_token|lastSequence)=\s*)[^&\s]+",
            "$1[REDACTED]",
            RegexOptions.IgnoreCase);
        return redacted;
    }

    private static bool IsSensitiveField(string name)
    {
        var lower = name.ToLowerInvariant();
        return lower.Contains("password") || lower.Contains("token")
            || lower.Contains("secret") || lower.Contains("api_key")
            || lower.Contains("admin_code");
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
