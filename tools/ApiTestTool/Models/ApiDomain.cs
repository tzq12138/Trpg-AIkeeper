using System.Collections.Generic;
using System.Collections.ObjectModel;

namespace ApiTestTool.Models;

/// <summary>
/// Groups API endpoints into a domain (tab category).
/// </summary>
public class ApiDomain
{
    public string Name { get; set; } = "";
    public string Prefix { get; set; } = "";
    public ObservableCollection<ApiEndpoint> Endpoints { get; set; } = new();

    public override string ToString() => $"{Name} ({Endpoints.Count})";
}
