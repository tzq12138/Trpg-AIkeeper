using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using ApiTestTool.Models;

namespace ApiTestTool.Services;

/// <summary>
/// Central HTTP client that injects auth headers based on endpoint's AuthType.
/// </summary>
public class ApiClientService
{
    private readonly HttpClient _http;
    private readonly AuthState _auth;

    public ApiClientService(AuthState auth)
    {
        _auth = auth;
        _http = new HttpClient { Timeout = TimeSpan.FromSeconds(60) };
    }

    public async Task<HttpResponseResult> SendAsync(
        ApiEndpoint endpoint,
        Dictionary<string, string> pathValues,
        Dictionary<string, string> queryValues,
        string body,
        byte[]? fileBytes = null,
        string? fileName = null)
    {
        var result = new HttpResponseResult();
        var sw = Stopwatch.StartNew();

        // Build URL
        var url = _auth.BaseUrl.TrimEnd('/') + endpoint.Path;
        foreach (var pp in endpoint.PathParams)
        {
            var val = pathValues.GetValueOrDefault(pp.Name, pp.DefaultValue);
            url = url.Replace($"{{{pp.Name}}}", Uri.EscapeDataString(val));
        }

        // Append query string
        if (queryValues.Count > 0)
        {
            var qs = new List<string>();
            foreach (var kv in queryValues)
            {
                if (!string.IsNullOrWhiteSpace(kv.Value))
                    qs.Add($"{Uri.EscapeDataString(kv.Key)}={Uri.EscapeDataString(kv.Value)}");
            }
            if (qs.Count > 0) url += "?" + string.Join("&", qs);
        }

        HttpRequestMessage request;
        if (endpoint.HasFileUpload && fileBytes != null)
        {
            // Multipart form upload
            var content = new MultipartFormDataContent();
            var fileContent = new ByteArrayContent(fileBytes);
            fileContent.Headers.ContentType = new MediaTypeHeaderValue(
                fileName?.EndsWith(".xlsx") == true
                    ? "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    : fileName?.EndsWith(".pdf") == true ? "application/pdf" : "application/octet-stream");
            content.Add(fileContent, "file", fileName ?? "file.bin");

            // If body contains form fields, parse as JSON and add as string content
            if (!string.IsNullOrWhiteSpace(body))
            {
                try
                {
                    var formFields = JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(body);
                    if (formFields != null)
                    {
                        foreach (var kv in formFields)
                        {
                            content.Add(new StringContent(kv.Value.ToString()), kv.Key);
                        }
                    }
                }
                catch { /* not JSON, skip */ }
            }

            request = new HttpRequestMessage(new HttpMethod(endpoint.Method), url) { Content = content };
        }
        else
        {
            request = new HttpRequestMessage(new HttpMethod(endpoint.Method), url);
            if (!string.IsNullOrWhiteSpace(body) && endpoint.Method != "GET")
            {
                request.Content = new StringContent(body, Encoding.UTF8, "application/json");
            }
        }

        // Inject auth headers
        switch (endpoint.AuthType)
        {
            case "bearer":
                if (!string.IsNullOrWhiteSpace(_auth.BearerToken))
                    request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _auth.BearerToken);
                break;
            case "room-token":
                if (!string.IsNullOrWhiteSpace(_auth.RoomToken))
                    request.Headers.Add("X-Room-Token", _auth.RoomToken);
                break;
            case "owner-token":
                if (!string.IsNullOrWhiteSpace(_auth.OwnerToken))
                    request.Headers.Add("X-Owner-Token", _auth.OwnerToken);
                break;
        }

        try
        {
            var response = await _http.SendAsync(request);
            sw.Stop();

            result.StatusCode = (int)response.StatusCode;
            result.StatusText = response.StatusCode.ToString();
            result.ElapsedMs = sw.ElapsedMilliseconds;

            foreach (var h in response.Headers)
                result.ResponseHeaders[h.Key] = string.Join(", ", h.Value);
            foreach (var h in response.Content.Headers)
                result.ResponseHeaders[h.Key] = string.Join(", ", h.Value);

            result.Body = await response.Content.ReadAsStringAsync();

            // Pretty-print JSON body
            try
            {
                var doc = JsonDocument.Parse(result.Body);
                result.Body = JsonSerializer.Serialize(doc.RootElement, new JsonSerializerOptions { WriteIndented = true });
            }
            catch { /* not JSON, leave as-is */ }
        }
        catch (TaskCanceledException)
        {
            sw.Stop();
            result.StatusCode = 0;
            result.StatusText = "Timeout";
            result.ElapsedMs = sw.ElapsedMilliseconds;
            result.Body = "Request timed out after 60 seconds.";
        }
        catch (Exception ex)
        {
            sw.Stop();
            result.StatusCode = 0;
            result.StatusText = "Error";
            result.ElapsedMs = sw.ElapsedMilliseconds;
            result.Body = $"Request failed: {ex.Message}";
        }

        return result;
    }
}
