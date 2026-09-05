using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using ApiTestTool.Models;
using ApiTestTool.Services;

namespace ApiTestTool.ViewModels;

/// <summary>
/// Request history panel.
/// </summary>
public partial class HistoryViewModel : ObservableObject
{
    private readonly RequestHistoryService _service;

    [ObservableProperty] private RequestHistoryEntry? _selectedEntry;

    public ObservableCollection<RequestHistoryEntry> Entries => _service.Entries;

    public HistoryViewModel(RequestHistoryService service)
    {
        _service = service;
    }

    public void Clear() => _service.Clear();
}
