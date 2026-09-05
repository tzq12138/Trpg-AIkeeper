using System.Windows;
using Microsoft.Extensions.DependencyInjection;
using ApiTestTool.Services;
using ApiTestTool.ViewModels;

namespace ApiTestTool;

public partial class App : Application
{
    private readonly ServiceProvider _services;

    public App()
    {
        _services = ConfigureServices();
    }

    private static ServiceProvider ConfigureServices()
    {
        var services = new ServiceCollection();

        // Models — singleton auth state
        var authStateMgr = new AuthStateManager();
        services.AddSingleton(authStateMgr);
        services.AddSingleton(authStateMgr.State);

        // Services
        services.AddSingleton<ApiClientService>();
        services.AddSingleton<WebSocketService>();
        services.AddSingleton<RequestHistoryService>();
        services.AddSingleton<FlowService>();

        // ViewModels
        services.AddSingleton<MainViewModel>();
        services.AddSingleton<EndpointTreeViewModel>();
        services.AddSingleton<RequestBuilderViewModel>();
        services.AddSingleton<ResponseViewerViewModel>();
        services.AddSingleton<AuthManagerViewModel>();
        services.AddSingleton<WebSocketViewModel>();
        services.AddSingleton<HistoryViewModel>();
        services.AddSingleton<FlowRunnerViewModel>();

        return services.BuildServiceProvider();
    }

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);

        // Prevent StartupUri from auto-creating MainWindow — we create it manually
        var mainVm = _services.GetRequiredService<MainViewModel>();
        var window = new MainWindow { DataContext = mainVm };
        MainWindow = window;
        window.Show();
    }
}
