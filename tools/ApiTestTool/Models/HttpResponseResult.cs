using System.Collections.Generic;

namespace ApiTestTool.Models;

/// <summary>
/// Captures the result of an HTTP request.
/// </summary>
public class HttpResponseResult
{
    public int StatusCode { get; set; }
    public string StatusText { get; set; } = "";
    public Dictionary<string, string> ResponseHeaders { get; set; } = new();
    public string Body { get; set; } = "";
    public long ElapsedMs { get; set; }
    public bool IsSuccess => StatusCode is >= 200 and < 300;

    public string Summary => $"{StatusCode} ({ElapsedMs}ms)";
}
