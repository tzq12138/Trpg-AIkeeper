using CommunityToolkit.Mvvm.ComponentModel;
using ApiTestTool.Models;
using ApiTestTool.Services;

namespace ApiTestTool.ViewModels;

/// <summary>
/// Top auth bar: base URL and token management.
/// </summary>
public partial class AuthManagerViewModel : ObservableObject
{
    private readonly AuthStateManager _mgr;

    public AuthState State => _mgr.State;

    [ObservableProperty] private string _bearerPreview = "";
    [ObservableProperty] private string _roomTokenPreview = "";
    [ObservableProperty] private string _ownerTokenPreview = "";

    public AuthManagerViewModel(AuthStateManager mgr)
    {
        _mgr = mgr;
        Refresh();
    }

    public void Refresh()
    {
        BearerPreview = Truncate(_mgr.State.BearerToken);
        RoomTokenPreview = Truncate(_mgr.State.RoomToken);
        OwnerTokenPreview = Truncate(_mgr.State.OwnerToken);
    }

    public void Save() => _mgr.Save();

    private static string Truncate(string s)
        => string.IsNullOrEmpty(s) ? "(无)" : s.Length <= 16 ? s : s[..16] + "...";
}
