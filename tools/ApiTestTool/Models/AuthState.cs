using CommunityToolkit.Mvvm.ComponentModel;

namespace ApiTestTool.Models;

/// <summary>
/// Observable authentication state shared across the application.
/// Persisted to %APPDATA%/ApiTestTool/environments.json.
/// </summary>
public partial class AuthState : ObservableObject
{
    [ObservableProperty]
    private string _baseUrl = "http://127.0.0.1:3001";

    [ObservableProperty]
    private string _bearerToken = "";

    [ObservableProperty]
    private string _roomToken = "";     // X-Room-Token

    [ObservableProperty]
    private string _ownerToken = "";    // X-Owner-Token

    [ObservableProperty]
    private string _profileName = "Local Dev";

    [ObservableProperty]
    private string _username = "";

    [ObservableProperty]
    private string _password = "";
}
