using System;
using System.Collections.ObjectModel;
using System.Linq;
using System.Threading.Tasks;
using System.Windows.Input;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using ApiTestTool.Models;
using ApiTestTool.Services;

namespace ApiTestTool.ViewModels;

/// <summary>
/// Pre-built flow execution panel.
/// </summary>
public partial class FlowRunnerViewModel : ObservableObject
{
    private readonly FlowService _flowService;
    private readonly AuthStateManager _authMgr;
    private readonly ApiClientService _api;
    private readonly RequestHistoryService _history;

    [ObservableProperty] private FlowDefinition? _selectedFlow;
    [ObservableProperty] private bool _isRunning;
    [ObservableProperty] private string _progressText = "";

    public ObservableCollection<FlowDefinition> Flows { get; }
    public ObservableCollection<FlowStepResult> Results { get; } = new();

    public event Action? FlowCompleted;

    public FlowRunnerViewModel(FlowService flowService, AuthStateManager authMgr,
        ApiClientService api, RequestHistoryService history)
    {
        _flowService = flowService;
        _authMgr = authMgr;
        _api = api;
        _history = history;
        Flows = new ObservableCollection<FlowDefinition>(FlowService.GetFlows());
        SelectedFlow = Flows.FirstOrDefault();
    }

    [RelayCommand]
    private async Task RunFlow()
    {
        if (SelectedFlow == null || IsRunning) return;
        IsRunning = true;
        Results.Clear();
        ProgressText = $"开始执行: {SelectedFlow.Name}\n";

        var progress = new Progress<string>(msg =>
        {
            ProgressText += msg + "\n";
        });

        var results = await _flowService.ExecuteFlowAsync(SelectedFlow, progress);
        foreach (var r in results) Results.Add(r);

        // Save auth state after flow
        _authMgr.Save();
        FlowCompleted?.Invoke();

        var successCount = results.Count(r => r.Success);
        ProgressText += $"\n完成: {successCount}/{results.Count} 成功";
        IsRunning = false;
    }
}
