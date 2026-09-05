using System;
using System.Collections.ObjectModel;
using System.Threading.Tasks;
using System.Windows.Input;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using ApiTestTool.Models;
using ApiTestTool.Services;

namespace ApiTestTool.ViewModels;

/// <summary>
/// WebSocket test panel: connect, view messages, send text.
/// </summary>
public partial class WebSocketViewModel : ObservableObject
{
    private readonly WebSocketService _ws;
    private readonly AuthStateManager _authMgr;

    [ObservableProperty] private string _roomId = "";
    [ObservableProperty] private string _role = "player";
    [ObservableProperty] private bool _isConnected;
    [ObservableProperty] private string _sendMessage = "";
    [ObservableProperty] private string _connectStatus = "未连接";

    public ObservableCollection<WsMessage> Messages => _ws.Messages;

    public WebSocketViewModel(WebSocketService ws, AuthStateManager authMgr)
    {
        _ws = ws;
        _authMgr = authMgr;
        _ws.ConnectionChanged += connected =>
        {
            IsConnected = connected;
            ConnectStatus = connected ? "已连接" : "未连接";
        };
        _ws.ErrorOccurred += err => ConnectStatus = $"错误: {err}";
    }

    [RelayCommand]
    private async Task Connect()
    {
        ConnectStatus = "连接中...";
        await _ws.ConnectAsync(RoomId, Role);
    }

    [RelayCommand]
    private async Task Disconnect()
    {
        await _ws.DisconnectAsync();
        ConnectStatus = "已断开";
    }

    [RelayCommand]
    private async Task Send()
    {
        if (string.IsNullOrWhiteSpace(SendMessage)) return;
        await _ws.SendAsync(SendMessage);
        SendMessage = "";
    }

    [RelayCommand]
    private void ClearMessages()
    {
        Messages.Clear();
    }
}
