using System;
using System.Collections.ObjectModel;
using System.Linq;
using ApiTestTool.Models;
using ApiTestTool.Services;

namespace ApiTestTool.ViewModels;

/// <summary>
/// Left-panel endpoint tree: ApiDomain groups → ApiEndpoint leaves.
/// </summary>
public class EndpointTreeViewModel
{
    public ObservableCollection<ApiDomain> Domains { get; }
    public ApiEndpoint? SelectedEndpoint { get; set; }

    public event Action<ApiEndpoint>? SelectedEndpointChanged;

    public EndpointTreeViewModel()
    {
        Domains = new ObservableCollection<ApiDomain>(EndpointRegistry.Build());
    }

    public void OnSelectedItemChanged(object? selectedItem)
    {
        if (selectedItem is ApiEndpoint ep)
        {
            SelectedEndpoint = ep;
            SelectedEndpointChanged?.Invoke(ep);
        }
    }
}
