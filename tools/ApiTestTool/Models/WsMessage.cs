using System;

namespace ApiTestTool.Models;

/// <summary>
/// A timestamped WebSocket message record.
/// </summary>
public class WsMessage
{
    public DateTime Timestamp { get; set; } = DateTime.Now;
    public string Direction { get; set; } = "in"; // "in" or "out"
    public string Payload { get; set; } = "";
    public string EventType { get; set; } = "";

    public string TimeStr => Timestamp.ToString("HH:mm:ss.fff");
    public string Arrow => Direction == "in" ? "←" : "→";
    public string Summary => $"{TimeStr} {Arrow} {EventType}";
}
