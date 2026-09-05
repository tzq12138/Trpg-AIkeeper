using System.Collections.ObjectModel;
using System.Linq;
using ApiTestTool.Models;
using ApiTestTool.Services;

namespace ApiTestTool.ViewModels;

/// <summary>
/// Root ViewModel that owns all child VMs and coordinates the application.
/// </summary>
public partial class MainViewModel
{
    public EndpointTreeViewModel EndpointTree { get; }
    public RequestBuilderViewModel RequestBuilder { get; }
    public ResponseViewerViewModel ResponseViewer { get; }
    public AuthManagerViewModel AuthManager { get; }
    public WebSocketViewModel WebSocket { get; }
    public HistoryViewModel History { get; }
    public FlowRunnerViewModel FlowRunner { get; }

    public MainViewModel(
        AuthStateManager authMgr,
        ApiClientService apiClient,
        WebSocketService wsService,
        RequestHistoryService historyService,
        FlowService flowService)
    {
        AuthManager = new AuthManagerViewModel(authMgr);
        EndpointTree = new EndpointTreeViewModel();
        ResponseViewer = new ResponseViewerViewModel();
        History = new HistoryViewModel(historyService);
        FlowRunner = new FlowRunnerViewModel(flowService, authMgr, apiClient, historyService);
        RequestBuilder = new RequestBuilderViewModel(apiClient, authMgr, ResponseViewer, historyService);
        WebSocket = new WebSocketViewModel(wsService, authMgr);

        // Wire up endpoint selection -> request builder
        EndpointTree.SelectedEndpointChanged += ep => RequestBuilder.SetEndpoint(ep);

        // Wire up flow completion to refresh auth state
        FlowRunner.FlowCompleted += () => AuthManager.Refresh();
    }
}
