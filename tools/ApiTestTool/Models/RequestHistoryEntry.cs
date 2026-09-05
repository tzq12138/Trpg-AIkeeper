using System;

namespace ApiTestTool.Models;

/// <summary>
/// A timestamped record of a request/response pair for the history log.
/// </summary>
public class RequestHistoryEntry
{
    public DateTime Timestamp { get; set; } = DateTime.Now;
    public string Method { get; set; } = "";
    public string Url { get; set; } = "";
    public string RequestHeaders { get; set; } = "";
    public string RequestBody { get; set; } = "";
    public int StatusCode { get; set; }
    public string ResponseBody { get; set; } = "";
    public long ElapsedMs { get; set; }

    public string Summary => $"{Timestamp:HH:mm:ss}  {Method}  {Url}  → {StatusCode} ({ElapsedMs}ms)";

    public string StatusColor => StatusCode switch
    {
        >= 200 and < 300 => "#4CAF50",
        >= 300 and < 400 => "#FF9800",
        >= 400 and < 500 => "#F44336",
        _ => "#9C27B0"
    };
}
