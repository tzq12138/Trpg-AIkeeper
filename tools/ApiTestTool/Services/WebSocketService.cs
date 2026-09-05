using System;
using System.Collections.ObjectModel;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using ApiTestTool.Models;

namespace ApiTestTool.Services;

/// <summary>
/// WebSocket client for real-time event monitoring.
/// </summary>
public class WebSocketService : IDisposable
{
    private ClientWebSocket? _ws;
    private CancellationTokenSource? _cts;
    private readonly AuthState _auth;

    public ObservableCollection<WsMessage> Messages { get; } = new();
    public bool IsConnected => _ws?.State == WebSocketState.Open;

    public event Action<bool>? ConnectionChanged;
    public event Action<string>? ErrorOccurred;

    public WebSocketService(AuthState auth)
    {
        _auth = auth;
    }

    public async Task ConnectAsync(string roomId, string role)
    {
        await DisconnectAsync();

        _ws = new ClientWebSocket();
        _cts = new CancellationTokenSource();

        var baseWsUrl = _auth.BaseUrl
            .Replace("https://", "wss://")
            .Replace("http://", "ws://")
            .TrimEnd('/');

        string url;
        if (role == "host")
            url = $"{baseWsUrl}/ws?room={roomId}&role=host&ownerToken={Uri.EscapeDataString(_auth.OwnerToken)}";
        else
            url = $"{baseWsUrl}/ws?room={roomId}&role=player&token={Uri.EscapeDataString(_auth.RoomToken)}";

        try
        {
            var actualUrl = url;
            await _ws.ConnectAsync(new Uri(url), _cts.Token);
            ConnectionChanged?.Invoke(true);
            // Log connection URL with tokens redacted
            var displayUrl = System.Text.RegularExpressions.Regex.Replace(
                actualUrl,
                @"([?&](?:token|ownerToken)=\s*)[^&\s]+",
                "$1[REDACTED]",
                System.Text.RegularExpressions.RegexOptions.IgnoreCase);
            AddMessage("system", "Connected to " + displayUrl, "out");

            // Start receive loop
            _ = ReceiveLoop(_cts.Token);
        }
        catch (Exception ex)
        {
            ErrorOccurred?.Invoke($"WebSocket connection failed: {ex.Message}");
            AddMessage("system", $"Connection failed: {ex.Message}", "out");
        }
    }

    public async Task DisconnectAsync()
    {
        _cts?.Cancel();
        if (_ws?.State == WebSocketState.Open)
        {
            try
            {
                await _ws.CloseAsync(WebSocketCloseStatus.NormalClosure, "user disconnect", CancellationToken.None);
            }
            catch { /* ignore */ }
        }
        _ws?.Dispose();
        _ws = null;
        _cts?.Dispose();
        _cts = null;
        ConnectionChanged?.Invoke(false);
        AddMessage("system", "Disconnected", "out");
    }

    public async Task SendAsync(string message)
    {
        if (_ws?.State != WebSocketState.Open) return;
        try
        {
            var bytes = Encoding.UTF8.GetBytes(message);
            await _ws.SendAsync(new ArraySegment<byte>(bytes), WebSocketMessageType.Text, true, CancellationToken.None);
            AddMessage("text", message, "out");
        }
        catch (Exception ex)
        {
            ErrorOccurred?.Invoke($"Send failed: {ex.Message}");
        }
    }

    private async Task ReceiveLoop(CancellationToken ct)
    {
        var buffer = new byte[1024 * 64];
        try
        {
            while (!ct.IsCancellationRequested && _ws?.State == WebSocketState.Open)
            {
                var result = await _ws.ReceiveAsync(new ArraySegment<byte>(buffer), ct);
                if (result.MessageType == WebSocketMessageType.Close)
                {
                    AddMessage("system", "Server closed connection", "in");
                    break;
                }

                var text = Encoding.UTF8.GetString(buffer, 0, result.Count);

                // If it's a multi-part message, accumulate
                while (!result.EndOfMessage)
                {
                    result = await _ws.ReceiveAsync(new ArraySegment<byte>(buffer), ct);
                    text += Encoding.UTF8.GetString(buffer, 0, result.Count);
                }

                var eventType = "raw";
                try
                {
                    var doc = System.Text.Json.JsonDocument.Parse(text);
                    if (doc.RootElement.TryGetProperty("type", out var typeProp))
                        eventType = typeProp.GetString() ?? "raw";
                }
                catch { }

                AddMessage(eventType, text, "in");
            }
        }
        catch (OperationCanceledException) { }
        catch (WebSocketException) { }
        catch (Exception ex)
        {
            ErrorOccurred?.Invoke($"Receive error: {ex.Message}");
        }
        finally
        {
            ConnectionChanged?.Invoke(false);
        }
    }

    private void AddMessage(string eventType, string payload, string direction)
    {
        // Try to pretty-print JSON
        try
        {
            var doc = System.Text.Json.JsonDocument.Parse(payload);
            payload = System.Text.Json.JsonSerializer.Serialize(doc.RootElement,
                new System.Text.Json.JsonSerializerOptions { WriteIndented = true });
        }
        catch { }

        var msg = new WsMessage
        {
            Timestamp = DateTime.Now,
            Direction = direction,
            EventType = eventType,
            Payload = payload,
        };
        System.Windows.Application.Current?.Dispatcher.Invoke(() => Messages.Add(msg));
    }

    public void Dispose()
    {
        _cts?.Cancel();
        _ws?.Dispose();
        _cts?.Dispose();
    }
}
