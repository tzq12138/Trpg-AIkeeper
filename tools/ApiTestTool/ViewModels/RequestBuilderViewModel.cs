using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.IO;
using System.Threading.Tasks;
using System.Windows.Input;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Microsoft.Win32;
using ApiTestTool.Models;
using ApiTestTool.Services;

namespace ApiTestTool.ViewModels;

/// <summary>
/// Request builder: dynamic form for method, URL, headers, params, and body.
/// </summary>
public partial class RequestBuilderViewModel : ObservableObject
{
    private readonly ApiClientService _api;
    private readonly AuthStateManager _authMgr;
    private readonly ResponseViewerViewModel _responseViewer;
    private readonly RequestHistoryService _historyService;

    [ObservableProperty] private ApiEndpoint? _currentEndpoint;
    [ObservableProperty] private string _methodLabel = "";
    [ObservableProperty] private string _urlPreview = "";
    [ObservableProperty] private string _requestBody = "";
    [ObservableProperty] private string _statusText = "就绪";
    [ObservableProperty] private bool _isSending;
    [ObservableProperty] private bool _hasFileUpload;

    // Dynamic param fields
    public ObservableCollection<ParamField> PathFields { get; } = new();
    public ObservableCollection<ParamField> QueryFields { get; } = new();
    public ObservableCollection<HeaderField> HeaderFields { get; } = new();

    // File upload
    [ObservableProperty] private string? _selectedFilePath;
    private byte[]? _fileBytes;

    public RequestBuilderViewModel(
        ApiClientService api, AuthStateManager authMgr,
        ResponseViewerViewModel responseViewer, RequestHistoryService historyService)
    {
        _api = api;
        _authMgr = authMgr;
        _responseViewer = responseViewer;
        _historyService = historyService;
    }

    public void SetEndpoint(ApiEndpoint ep)
    {
        CurrentEndpoint = ep;
        MethodLabel = $"{ep.Method} {ep.Id}";
        UrlPreview = ep.Path;
        RequestBody = ep.BodySchema;
        HasFileUpload = ep.HasFileUpload;
        StatusText = ep.Description;

        PathFields.Clear();
        foreach (var p in ep.PathParams)
            PathFields.Add(new ParamField { Name = p.Name, Value = p.DefaultValue, Description = p.Description });

        QueryFields.Clear();
        foreach (var p in ep.QueryParams)
            QueryFields.Add(new ParamField { Name = p.Name, Value = p.DefaultValue, Description = p.Description });

        HeaderFields.Clear();
        HeaderFields.Add(new HeaderField { Name = "Content-Type", Value = ep.ContentType, IsReadOnly = true });

        switch (ep.AuthType)
        {
            case "bearer":
                HeaderFields.Add(new HeaderField { Name = "Authorization", Value = $"Bearer {_authMgr.State.BearerToken[..Math.Min(12, _authMgr.State.BearerToken.Length)]}...", IsReadOnly = true });
                break;
            case "room-token":
                HeaderFields.Add(new HeaderField { Name = "X-Room-Token", Value = _authMgr.State.RoomToken[..Math.Min(12, _authMgr.State.RoomToken.Length)] + "...", IsReadOnly = true });
                break;
            case "owner-token":
                HeaderFields.Add(new HeaderField { Name = "X-Owner-Token", Value = _authMgr.State.OwnerToken[..Math.Min(12, _authMgr.State.OwnerToken.Length)] + "...", IsReadOnly = true });
                break;
        }

        SelectedFilePath = null;
        _fileBytes = null;
    }

    [RelayCommand]
    private void PickFile()
    {
        var dlg = new OpenFileDialog
        {
            Title = "选择文件上传",
            Filter = "All files (*.*)|*.*|PDF (*.pdf)|*.pdf|XLSX (*.xlsx)|*.xlsx|Audio (*.wav;*.mp3;*.webm)|*.wav;*.mp3;*.webm|Images (*.png;*.jpg)|*.png;*.jpg",
        };
        if (dlg.ShowDialog() == true)
        {
            SelectedFilePath = dlg.FileName;
            _fileBytes = File.ReadAllBytes(dlg.FileName);
            StatusText = $"已选择: {Path.GetFileName(dlg.FileName)} ({_fileBytes.Length} bytes)";
        }
    }

    [RelayCommand]
    private async Task SendRequest()
    {
        if (CurrentEndpoint == null || IsSending) return;
        IsSending = true;
        StatusText = "发送中...";

        var pathValues = new Dictionary<string, string>();
        foreach (var f in PathFields) pathValues[f.Name] = f.Value;

        var queryValues = new Dictionary<string, string>();
        foreach (var f in QueryFields) queryValues[f.Name] = f.Value;

        var result = await _api.SendAsync(CurrentEndpoint, pathValues, queryValues, RequestBody, _fileBytes, SelectedFilePath);
        _responseViewer.ShowResult(result);

        StatusText = $"{result.StatusCode} ({result.ElapsedMs}ms)";
        IsSending = false;

        // Add to history
        var historyHeaders = "";
        foreach (var h in HeaderFields) historyHeaders += $"{h.Name}: {h.Value}\n";

        _historyService.Add(new RequestHistoryEntry
        {
            Method = CurrentEndpoint.Method,
            Url = _authMgr.State.BaseUrl.TrimEnd('/') + CurrentEndpoint.Path,
            RequestHeaders = historyHeaders,
            RequestBody = RequestBody,
            StatusCode = result.StatusCode,
            ResponseBody = result.Body,
            ElapsedMs = result.ElapsedMs,
        });
    }
}

public class ParamField : ObservableObject
{
    public string Name { get; set; } = "";
    public string Description { get; set; } = "";
    private string _value = "";
    public string Value { get => _value; set => SetProperty(ref _value, value); }
}

public class HeaderField : ObservableObject
{
    public string Name { get; set; } = "";
    public string Value { get; set; } = "";
    public bool IsReadOnly { get; set; }
}
