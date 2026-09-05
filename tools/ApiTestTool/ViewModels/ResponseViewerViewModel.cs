using System.Collections.Generic;
using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using ApiTestTool.Models;

namespace ApiTestTool.ViewModels;

/// <summary>
/// Response viewer: status code, response headers, and formatted body.
/// </summary>
public partial class ResponseViewerViewModel : ObservableObject
{
    [ObservableProperty] private int _statusCode;
    [ObservableProperty] private string _statusText = "";
    [ObservableProperty] private string _elapsedText = "";
    [ObservableProperty] private string _responseBody = "";
    [ObservableProperty] private bool _hasResponse;
    [ObservableProperty] private string _statusColor = "#888";

    public ObservableCollection<KeyValuePair<string, string>> ResponseHeaders { get; } = new();

    public void ShowResult(HttpResponseResult result)
    {
        StatusCode = result.StatusCode;
        StatusText = result.StatusText;
        ElapsedText = $"{result.ElapsedMs}ms";
        ResponseBody = result.Body;
        HasResponse = true;

        StatusColor = result.StatusCode switch
        {
            >= 200 and < 300 => "#4CAF50",
            >= 300 and < 400 => "#FF9800",
            >= 400 and < 500 => "#F44336",
            _ => "#9C27B0"
        };

        ResponseHeaders.Clear();
        foreach (var h in result.ResponseHeaders)
            ResponseHeaders.Add(h);
    }

    public void Clear()
    {
        HasResponse = false;
        ResponseBody = "";
        ResponseHeaders.Clear();
    }
}
