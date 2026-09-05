using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Threading.Tasks;
using ApiTestTool.Models;

namespace ApiTestTool.Services;

/// <summary>
/// Executes pre-built multi-step API test flows.
/// </summary>
public class FlowService
{
    private readonly ApiClientService _api;
    private readonly AuthState _auth;

    public FlowService(ApiClientService api, AuthState auth)
    {
        _api = api;
        _auth = auth;
    }

    public static List<FlowDefinition> GetFlows()
    {
        return new List<FlowDefinition>
        {
            new()
            {
                Name = "快速开始 (Quick Start)",
                Description = "注册 → 登录 → 创建房间 → 玩家加入 → 开始游戏",
                Steps = new List<FlowStep>
                {
                    new("1. 注册", "auth.register", "POST", "/api/auth/register",
                        """{"username":"testuser","password":"test1234","display_name":"Test User"}""",
                        extractToken: "token", key: "bearerToken"),
                    new("2. 登录", "auth.login", "POST", "/api/auth/login",
                        """{"username":"testuser","password":"test1234"}""",
                        extractToken: "token", key: "bearerToken"),
                    new("3. 创建房间", "rooms.create", "POST", "/api/rooms",
                        """{"scenario_id":"","spoiler_level":"standard"}""",
                        extractToken: "owner_token", key: "ownerToken", extractVar: "room_id", varKey: "room_id"),
                    new("4. 玩家加入", "player.join", "POST", "/api/player/rooms/${room_id}/join",
                        "",
                        extractToken: "player_token", key: "roomToken", extractVar: "character_id", varKey: "character_id"),
                    new("5. 开始游戏", "rooms.start", "POST", "/api/rooms/${room_id}/start",
                        """{"force_start":true,"confirm":true,"reason":"quick test"}""",
                        authType: "owner-token"),
                }
            },
            new()
            {
                Name = "完整测试 (Full Test)",
                Description = "快速开始 + 玩家意图 + 技能检定 + 线索分享",
                Steps = new List<FlowStep>
                {
                    new("1. 注册", "auth.register", "POST", "/api/auth/register",
                        """{"username":"fulltest","password":"test1234","display_name":"Full Test"}""",
                        extractToken: "token", key: "bearerToken"),
                    new("2. 登录", "auth.login", "POST", "/api/auth/login",
                        """{"username":"fulltest","password":"test1234"}""",
                        extractToken: "token", key: "bearerToken"),
                    new("3. 创建房间", "rooms.create", "POST", "/api/rooms",
                        """{"scenario_id":"","spoiler_level":"standard"}""",
                        extractToken: "owner_token", key: "ownerToken", extractVar: "room_id", varKey: "room_id"),
                    new("4. 玩家加入", "player.join", "POST", "/api/player/rooms/${room_id}/join",
                        "",
                        extractToken: "player_token", key: "roomToken", extractVar: "character_id", varKey: "character_id"),
                    new("5. 玩家同步", "player.sync", "GET", "/api/player/sync", "", authType: "room-token"),
                    new("6. 角色卡", "player.character", "GET", "/api/player/character", "", authType: "room-token"),
                    new("7. 技能检定", "player.skillCheck", "POST", "/api/player/skill-check",
                        """{"skill_name":"侦察","skill_value":50,"difficulty":"regular","bonus_dice":0}""",
                        authType: "room-token"),
                    new("8. 提交意图", "player.intent", "POST", "/api/player/intent",
                        """{"action_id":"","intent_type":"dialogue","declared_intent":"我想观察一下周围环境","base_state_version":0,"params":{}}""",
                        authType: "room-token"),
                    new("9. 开始游戏", "rooms.start", "POST", "/api/rooms/${room_id}/start",
                        """{"force_start":true,"confirm":true,"reason":"full test"}""",
                        authType: "owner-token"),
                    new("10. Host HUD", "host.hud", "GET", "/api/host/${room_id}/hud", "", authType: "owner-token"),
                }
            },
        };
    }

    public async Task<List<FlowStepResult>> ExecuteFlowAsync(FlowDefinition flow, IProgress<string> progress)
    {
        var results = new List<FlowStepResult>();
        var variables = new Dictionary<string, string>();

        foreach (var step in flow.Steps)
        {
            progress.Report($"执行: {step.Label}");

            // Replace variables in URL and body
            var url = step.Path;
            var body = step.Body;
            foreach (var v in variables)
            {
                url = url.Replace($"${{{v.Key}}}", v.Value);
                body = body.Replace($"${{{v.Key}}}", v.Value);
            }

            // Find endpoint definition
            var endpoint = FindEndpoint(step.EndpointId);
            if (endpoint == null)
            {
                results.Add(new FlowStepResult { Label = step.Label, Success = false, Error = "Endpoint not found: " + step.EndpointId });
                continue;
            }

            // Override auth type if flow step specifies it
            var effectiveEndpoint = new ApiEndpoint
            {
                Id = endpoint.Id, Method = step.Method, Path = url,
                Description = endpoint.Description,
                AuthType = step.AuthType ?? endpoint.AuthType,
                PathParams = endpoint.PathParams, QueryParams = endpoint.QueryParams,
                BodySchema = body, HasFileUpload = endpoint.HasFileUpload,
                ContentType = endpoint.ContentType,
            };

            var result = await _api.SendAsync(effectiveEndpoint, new(), new(), body);
            var stepResult = new FlowStepResult
            {
                Label = step.Label,
                StatusCode = result.StatusCode,
                Body = result.Body,
                ElapsedMs = result.ElapsedMs,
                Success = result.IsSuccess,
            };
            results.Add(stepResult);

            if (result.IsSuccess)
            {
                progress.Report($"  ✓ {step.Label} → {result.StatusCode} ({result.ElapsedMs}ms)");

                // Extract tokens and variables from response
                if (!string.IsNullOrEmpty(step.ExtractToken))
                {
                    try
                    {
                        var doc = JsonDocument.Parse(result.Body);
                        if (doc.RootElement.TryGetProperty(step.ExtractToken, out var tokenProp))
                        {
                            var tokenValue = tokenProp.GetString() ?? "";
                            if (!string.IsNullOrEmpty(tokenValue))
                            {
                                switch (step.Key)
                                {
                                    case "bearerToken": _auth.BearerToken = tokenValue; break;
                                    case "roomToken": _auth.RoomToken = tokenValue; break;
                                    case "ownerToken": _auth.OwnerToken = tokenValue; break;
                                }
                                if (!string.IsNullOrEmpty(step.VarKey))
                                    variables[step.VarKey] = tokenValue;
                            }
                        }
                    }
                    catch { }
                }
                if (!string.IsNullOrEmpty(step.ExtractVar))
                {
                    try
                    {
                        var doc = JsonDocument.Parse(result.Body);
                        if (doc.RootElement.TryGetProperty(step.ExtractVar, out var varProp))
                        {
                            var varValue = varProp.GetString() ?? varProp.ToString();
                            if (!string.IsNullOrEmpty(varValue) && !string.IsNullOrEmpty(step.VarKey))
                                variables[step.VarKey] = varValue;
                        }
                    }
                    catch { }
                }
            }
            else
            {
                progress.Report($"  ✗ {step.Label} → {result.StatusCode} — may stop here");
                if (!step.ContinueOnError) break;
            }
        }

        return results;
    }

    private ApiEndpoint? FindEndpoint(string id)
    {
        foreach (var domain in EndpointRegistry.Build())
            foreach (var ep in domain.Endpoints)
                if (ep.Id == id) return ep;
        return null;
    }
}

public class FlowDefinition
{
    public string Name { get; set; } = "";
    public string Description { get; set; } = "";
    public List<FlowStep> Steps { get; set; } = new();
}

public class FlowStep
{
    public string Label { get; set; } = "";
    public string EndpointId { get; set; } = "";
    public string Method { get; set; } = "GET";
    public string Path { get; set; } = "";
    public string Body { get; set; } = "";
    public string? AuthType { get; set; }
    public string? ExtractToken { get; set; }
    public string? Key { get; set; }
    public string? ExtractVar { get; set; }
    public string? VarKey { get; set; }
    public bool ContinueOnError { get; set; }

    public FlowStep() { }
    public FlowStep(string label, string endpointId, string method, string path, string body,
        string? authType = null, string? extractToken = null, string? key = null,
        string? extractVar = null, string? varKey = null, bool continueOnError = false)
    {
        Label = label; EndpointId = endpointId; Method = method; Path = path;
        Body = body; AuthType = authType;
        ExtractToken = extractToken; Key = key;
        ExtractVar = extractVar; VarKey = varKey;
        ContinueOnError = continueOnError;
    }
}

public class FlowStepResult
{
    public string Label { get; set; } = "";
    public int StatusCode { get; set; }
    public string Body { get; set; } = "";
    public long ElapsedMs { get; set; }
    public bool Success { get; set; }
    public string? Error { get; set; }
}
