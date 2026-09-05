using System.Collections.Generic;

namespace ApiTestTool.Models;

/// <summary>
/// Describes a single REST API endpoint.
/// </summary>
public class ApiEndpoint
{
    public string Id { get; set; } = "";
    public string Method { get; set; } = "GET";
    public string Path { get; set; } = "";
    public string Description { get; set; } = "";
    public string AuthType { get; set; } = "none"; // "bearer", "room-token", "owner-token", "none"
    public List<ApiParam> PathParams { get; set; } = new();
    public List<ApiParam> QueryParams { get; set; } = new();
    public string BodySchema { get; set; } = "";
    public bool HasFileUpload { get; set; }
    public string ContentType { get; set; } = "application/json"; // "multipart/form-data" for file uploads
}

public class ApiParam
{
    public string Name { get; set; } = "";
    public string Description { get; set; } = "";
    public bool Required { get; set; }
    public string DefaultValue { get; set; } = "";
}
