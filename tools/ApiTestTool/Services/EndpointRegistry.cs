using System.Collections.Generic;
using ApiTestTool.Models;

namespace ApiTestTool.Services;

/// <summary>
/// Static registry of all AI-Keeper backend API endpoints.
/// Single source of truth — update here when the API changes.
/// </summary>
public static class EndpointRegistry
{
    public static List<ApiDomain> Build()
    {
        return new List<ApiDomain>
        {
            BuildAuth(),
            BuildRooms(),
            BuildPlayer(),
            BuildHost(),
            BuildAdmin(),
            BuildScenarios(),
            BuildMap(),
            BuildRag(),
            BuildRoot(),
        };
    }

    // ── Auth (4 endpoints) ──────────────────────────────────────
    static ApiDomain BuildAuth()
    {
        return new ApiDomain
        {
            Name = "Auth",
            Prefix = "/api/auth",
            Endpoints = new()
            {
                new()
                {
                    Id = "auth.register", Method = "POST", Path = "/api/auth/register",
                    Description = "注册新账号（首个账号自动成为 admin）",
                    AuthType = "none",
                    BodySchema = """{"username":"","password":"","display_name":"","admin_code":""}"""
                },
                new()
                {
                    Id = "auth.login", Method = "POST", Path = "/api/auth/login",
                    Description = "登录获取 Bearer Token",
                    AuthType = "none",
                    BodySchema = """{"username":"","password":""}"""
                },
                new()
                {
                    Id = "auth.me", Method = "GET", Path = "/api/auth/me",
                    Description = "获取当前登录账号信息",
                    AuthType = "bearer"
                },
                new()
                {
                    Id = "auth.me.characters", Method = "GET", Path = "/api/auth/me/characters",
                    Description = "获取当前账号所有角色",
                    AuthType = "bearer"
                },
            }
        };
    }

    // ── Rooms (17 endpoints) ────────────────────────────────────
    static ApiDomain BuildRooms()
    {
        return new ApiDomain
        {
            Name = "Rooms",
            Prefix = "/api/rooms",
            Endpoints = new()
            {
                new() { Id = "rooms.create", Method = "POST", Path = "/api/rooms", Description = "创建房间", AuthType = "bearer", BodySchema = """{"scenario_id":"","spoiler_level":"standard"}""" },
                new() { Id = "rooms.mine", Method = "GET", Path = "/api/rooms/mine", Description = "列出我的房间", AuthType = "bearer" },
                new() { Id = "rooms.get", Method = "GET", Path = "/api/rooms/{room_id}", Description = "获取房间公开信息", AuthType = "none", PathParams = new() { new() { Name = "room_id", Required = true } } },
                new() { Id = "rooms.scenarioOptions", Method = "GET", Path = "/api/rooms/{room_id}/scenario-options", Description = "获取可分配剧本列表", AuthType = "owner-token", PathParams = new() { new() { Name = "room_id", Required = true } } },
                new() { Id = "rooms.assignScenario", Method = "PATCH", Path = "/api/rooms/{room_id}/scenario", Description = "分配剧本到房间", AuthType = "owner-token", PathParams = new() { new() { Name = "room_id", Required = true } }, BodySchema = """{"scenario_id":""}""" },
                new() { Id = "rooms.update", Method = "PATCH", Path = "/api/rooms/{room_id}", Description = "更新房间信息", AuthType = "bearer", PathParams = new() { new() { Name = "room_id", Required = true } }, BodySchema = """{"status":"","scenario_id":"","spoiler_level":""}""" },
                new() { Id = "rooms.start", Method = "POST", Path = "/api/rooms/{room_id}/start", Description = "开始游戏", AuthType = "owner-token", PathParams = new() { new() { Name = "room_id", Required = true } }, BodySchema = """{"force_start":false,"confirm":false,"reason":""}""" },
                new() { Id = "rooms.currentTurn", Method = "GET", Path = "/api/rooms/{room_id}/turns/current", Description = "获取当前回合信息", AuthType = "bearer", PathParams = new() { new() { Name = "room_id", Required = true } } },
                new() { Id = "rooms.skipCharacter", Method = "POST", Path = "/api/rooms/{room_id}/turns/{turn_id}/skip-character", Description = "跳过角色回合", AuthType = "bearer", PathParams = new() { new() { Name = "room_id", Required = true }, new() { Name = "turn_id", Required = true } }, BodySchema = """{"character_id":""}""" },
                new() { Id = "rooms.retryTurn", Method = "POST", Path = "/api/rooms/{room_id}/turns/{turn_id}/retry", Description = "重新结算回合", AuthType = "owner-token", PathParams = new() { new() { Name = "room_id", Required = true }, new() { Name = "turn_id", Required = true } } },
                new() { Id = "rooms.aiStatus", Method = "GET", Path = "/api/rooms/{room_id}/ai-status", Description = "获取 AI 状态", AuthType = "bearer", PathParams = new() { new() { Name = "room_id", Required = true } } },
                new() { Id = "rooms.aiConfigGet", Method = "GET", Path = "/api/rooms/{room_id}/ai-config", Description = "获取 AI 配置覆盖", AuthType = "bearer", PathParams = new() { new() { Name = "room_id", Required = true } } },
                new() { Id = "rooms.aiConfigPatch", Method = "PATCH", Path = "/api/rooms/{room_id}/ai-config", Description = "更新 AI 配置覆盖", AuthType = "bearer", PathParams = new() { new() { Name = "room_id", Required = true } }, BodySchema = "{}" },
                new() { Id = "rooms.events", Method = "GET", Path = "/api/rooms/{room_id}/events", Description = "获取房间事件列表", AuthType = "bearer", PathParams = new() { new() { Name = "room_id", Required = true } } },
                new() { Id = "rooms.publicEvents", Method = "GET", Path = "/api/rooms/{room_id}/events/public", Description = "获取公开事件", AuthType = "room-token", PathParams = new() { new() { Name = "room_id", Required = true } } },
                new() { Id = "rooms.replay", Method = "GET", Path = "/api/rooms/{room_id}/replay", Description = "房间事件回放", AuthType = "owner-token", PathParams = new() { new() { Name = "room_id", Required = true } }, QueryParams = new() { new() { Name = "offset", DefaultValue = "0" }, new() { Name = "limit", DefaultValue = "100" } } },
            }
        };
    }

    // ── Player (27 endpoints) ───────────────────────────────────
    static ApiDomain BuildPlayer()
    {
        return new ApiDomain
        {
            Name = "Player",
            Prefix = "/api/player",
            Endpoints = new()
            {
                new() { Id = "player.join", Method = "POST", Path = "/api/player/rooms/{room_id}/join", Description = "匿名加入房间", AuthType = "none", PathParams = new() { new() { Name = "room_id", Required = true } } },
                new() { Id = "player.joinInfo", Method = "GET", Path = "/api/player/rooms/{room_id}/join-info", Description = "获取加入页面信息", AuthType = "none", PathParams = new() { new() { Name = "room_id", Required = true } } },
                new() { Id = "player.me.characters", Method = "GET", Path = "/api/player/me/characters", Description = "获取账号角色列表", AuthType = "bearer" },
                new() { Id = "player.restoreSession", Method = "POST", Path = "/api/player/characters/{character_id}/restore-session", Description = "恢复玩家 Token", AuthType = "bearer", PathParams = new() { new() { Name = "character_id", Required = true } } },
                new() { Id = "player.presets", Method = "GET", Path = "/api/player/character/presets", Description = "获取角色预设列表", AuthType = "none", QueryParams = new() { new() { Name = "room_id", Required = false } } },
                new() { Id = "player.previewXlsx", Method = "POST", Path = "/api/player/character/preview-xlsx", Description = "预览角色 XLSX", AuthType = "none", HasFileUpload = true, ContentType = "multipart/form-data" },
                new() { Id = "player.joinWithCharacter", Method = "POST", Path = "/api/player/rooms/{room_id}/join-with-character", Description = "带角色加入房间", AuthType = "none", PathParams = new() { new() { Name = "room_id", Required = true } }, HasFileUpload = true, ContentType = "multipart/form-data", BodySchema = "form: player_name, preset_id | file | character_data | template_id | copy_character_id" },
                new() { Id = "player.importXlsx", Method = "POST", Path = "/api/player/character/import-xlsx", Description = "导入角色 XLSX", AuthType = "room-token", HasFileUpload = true, ContentType = "multipart/form-data" },
                new() { Id = "player.speechToText", Method = "POST", Path = "/api/player/speech-to-text", Description = "语音转文本", AuthType = "room-token", HasFileUpload = true, ContentType = "multipart/form-data", BodySchema = "form: audio (file), durationMs (int)" },
                new() { Id = "player.teamMessage", Method = "POST", Path = "/api/player/team-message", Description = "发送队伍消息", AuthType = "room-token", BodySchema = """{"text":"","source":"text"}""" },
                new() { Id = "player.intent", Method = "POST", Path = "/api/player/intent", Description = "提交玩家意图/行动", AuthType = "room-token", BodySchema = """{"action_id":"","intent_type":"dialogue","declared_intent":"","base_state_version":0,"params":{}}""" },
                new() { Id = "player.sync", Method = "GET", Path = "/api/player/sync", Description = "完整玩家状态同步", AuthType = "room-token" },
                new() { Id = "player.character", Method = "GET", Path = "/api/player/character", Description = "获取角色卡（含运行时 HP/SAN）", AuthType = "room-token" },
                new() { Id = "player.inventory", Method = "GET", Path = "/api/player/inventory", Description = "获取背包", AuthType = "room-token" },
                new() { Id = "player.skillCheck", Method = "POST", Path = "/api/player/skill-check", Description = "技能检定（掷骰）", AuthType = "room-token", BodySchema = """{"skill_name":"","skill_value":50,"difficulty":"regular","bonus_dice":0}""" },
                new() { Id = "player.clues.list", Method = "GET", Path = "/api/player/clues", Description = "列出线索", AuthType = "room-token" },
                new() { Id = "player.clues.share", Method = "POST", Path = "/api/player/clues/{clue_id}/share", Description = "分享线索", AuthType = "room-token", PathParams = new() { new() { Name = "clue_id", Required = true } }, BodySchema = """{"share_full_text":false,"public_version":"","note":""}""" },
                new() { Id = "player.objectives", Method = "GET", Path = "/api/player/objectives", Description = "列出目标", AuthType = "room-token" },
                new() { Id = "player.clarification.create", Method = "POST", Path = "/api/player/clarification", Description = "提交澄清请求", AuthType = "room-token", BodySchema = """{"targetActionId":"","text":"","evidence":""}""" },
                new() { Id = "player.clarification.get", Method = "GET", Path = "/api/player/clarification/{clarification_id}", Description = "获取澄清状态", AuthType = "room-token", PathParams = new() { new() { Name = "clarification_id", Required = true } } },
                new() { Id = "player.reconnect", Method = "GET", Path = "/api/player/reconnect", Description = "断线重连", AuthType = "room-token" },
                new() { Id = "player.actionStatus", Method = "GET", Path = "/api/player/actions/{action_id}", Description = "查询动作状态", AuthType = "room-token", PathParams = new() { new() { Name = "action_id", Required = true } } },
                new() { Id = "player.archive", Method = "GET", Path = "/api/player/archive", Description = "查询归档事件", AuthType = "room-token", QueryParams = new() { new() { Name = "type", DefaultValue = "all" }, new() { Name = "keyword", DefaultValue = "" }, new() { Name = "offset", DefaultValue = "0" }, new() { Name = "limit", DefaultValue = "50" } } },
                new() { Id = "player.archive.actions", Method = "GET", Path = "/api/player/archive/actions", Description = "列出所有动作", AuthType = "room-token" },
                new() { Id = "player.archive.clues", Method = "GET", Path = "/api/player/archive/clues", Description = "列出线索事件", AuthType = "room-token" },
                new() { Id = "player.archive.skillChecks", Method = "GET", Path = "/api/player/archive/skill-checks", Description = "列出技能检定", AuthType = "room-token" },
                new() { Id = "player.teamMessage", Method = "POST", Path = "/api/player/team-message", Description = "队伍聊天消息", AuthType = "room-token", BodySchema = """{"text":"","source":"text"}""" },
            }
        };
    }

    // ── Host (14 endpoints + WebSocket) ─────────────────────────
    static ApiDomain BuildHost()
    {
        return new ApiDomain
        {
            Name = "Host",
            Prefix = "/api/host",
            Endpoints = new()
            {
                new() { Id = "host.hud", Method = "GET", Path = "/api/host/{room_id}/hud", Description = "获取 Host HUD", AuthType = "owner-token", PathParams = new() { new() { Name = "room_id", Required = true } } },
                new() { Id = "host.reset", Method = "POST", Path = "/api/host/{room_id}/reset", Description = "紧急重置 Host 状态", AuthType = "owner-token", PathParams = new() { new() { Name = "room_id", Required = true } } },
                new() { Id = "host.pause", Method = "POST", Path = "/api/host/{room_id}/pause", Description = "暂停/恢复游戏", AuthType = "owner-token", PathParams = new() { new() { Name = "room_id", Required = true } } },
                new() { Id = "host.retryTurn", Method = "POST", Path = "/api/host/{room_id}/retry-turn", Description = "重试揭示交易", AuthType = "owner-token", PathParams = new() { new() { Name = "room_id", Required = true } } },
                new() { Id = "host.approve", Method = "POST", Path = "/api/host/{room_id}/approve/{character_id}", Description = "批准玩家加入", AuthType = "owner-token", PathParams = new() { new() { Name = "room_id", Required = true }, new() { Name = "character_id", Required = true } } },
                new() { Id = "host.reject", Method = "POST", Path = "/api/host/{room_id}/reject/{character_id}", Description = "拒绝玩家加入", AuthType = "owner-token", PathParams = new() { new() { Name = "room_id", Required = true }, new() { Name = "character_id", Required = true } } },
                new() { Id = "host.map.full", Method = "GET", Path = "/api/host/{room_id}/map/full", Description = "获取完整地图", AuthType = "owner-token", PathParams = new() { new() { Name = "room_id", Required = true } } },
                new() { Id = "host.map.reveal", Method = "POST", Path = "/api/host/{room_id}/map/reveal", Description = "揭示/隐藏地图节点", AuthType = "owner-token", PathParams = new() { new() { Name = "room_id", Required = true } }, BodySchema = """{"node_id":"","visible":true}""" },
                new() { Id = "host.map.move", Method = "POST", Path = "/api/host/{room_id}/map/move-character", Description = "强制移动角色", AuthType = "owner-token", PathParams = new() { new() { Name = "room_id", Required = true } }, BodySchema = """{"character_id":"","node_id":"","reason":""}""" },
                new() { Id = "host.encounter.get", Method = "GET", Path = "/api/host/{room_id}/encounter", Description = "获取当前遭遇", AuthType = "owner-token", PathParams = new() { new() { Name = "room_id", Required = true } } },
                new() { Id = "host.encounter.confirm", Method = "POST", Path = "/api/host/{room_id}/encounter/confirm", Description = "确认遭遇", AuthType = "owner-token", PathParams = new() { new() { Name = "room_id", Required = true } }, BodySchema = """{"encounter_id":"","type":"combat","participants":[],"reason":""}""" },
                new() { Id = "host.encounter.reject", Method = "POST", Path = "/api/host/{room_id}/encounter/reject", Description = "拒绝遭遇", AuthType = "owner-token", PathParams = new() { new() { Name = "room_id", Required = true } }, BodySchema = """{"encounter_id":""}""" },
                new() { Id = "host.encounter.nextRound", Method = "POST", Path = "/api/host/{room_id}/encounter/next-round", Description = "遭遇下一轮", AuthType = "owner-token", PathParams = new() { new() { Name = "room_id", Required = true } } },
                new() { Id = "host.encounter.resolve", Method = "POST", Path = "/api/host/{room_id}/encounter/resolve", Description = "结束遭遇", AuthType = "owner-token", PathParams = new() { new() { Name = "room_id", Required = true } } },
                new() { Id = "host.encounter.npc", Method = "POST", Path = "/api/host/{room_id}/encounter/npc", Description = "快速创建 NPC 参与者", AuthType = "owner-token", PathParams = new() { new() { Name = "room_id", Required = true } }, BodySchema = """{"encounter_id":"","name":"","side":"enemy","hp":10,"dex":50,"mov":7,"weapon_name":"","damage_expression":"1d3"}""" },
            }
        };
    }

    // ── Admin (27 endpoints) ────────────────────────────────────
    static ApiDomain BuildAdmin()
    {
        return new ApiDomain
        {
            Name = "Admin",
            Prefix = "/api/admin",
            Endpoints = new()
            {
                new() { Id = "admin.overview", Method = "GET", Path = "/api/admin/overview", Description = "管理后台概览", AuthType = "bearer" },
                new() { Id = "admin.rooms", Method = "GET", Path = "/api/admin/rooms", Description = "列出所有房间", AuthType = "bearer" },
                new() { Id = "admin.rooms.get", Method = "GET", Path = "/api/admin/rooms/{room_id}", Description = "获取房间详情", AuthType = "bearer", PathParams = new() { new() { Name = "room_id", Required = true } } },
                new() { Id = "admin.rooms.update", Method = "PATCH", Path = "/api/admin/rooms/{room_id}", Description = "更新房间（admin 覆盖）", AuthType = "bearer", PathParams = new() { new() { Name = "room_id", Required = true } }, BodySchema = """{"status":"","scenario_id":"","spoiler_level":""}""" },
                new() { Id = "admin.accounts", Method = "GET", Path = "/api/admin/accounts", Description = "列出所有账号", AuthType = "bearer" },
                new() { Id = "admin.accounts.update", Method = "PATCH", Path = "/api/admin/accounts/{account_id}", Description = "更新账号", AuthType = "bearer", PathParams = new() { new() { Name = "account_id", Required = true } }, BodySchema = """{"role":"","display_name":""}""" },
                new() { Id = "admin.characters", Method = "GET", Path = "/api/admin/characters", Description = "列出所有角色", AuthType = "bearer", QueryParams = new() { new() { Name = "room_id", Required = false } } },
                new() { Id = "admin.characters.update", Method = "PATCH", Path = "/api/admin/characters/{character_id}", Description = "更新角色属性", AuthType = "bearer", PathParams = new() { new() { Name = "character_id", Required = true } }, BodySchema = """{"hp":10,"max_hp":10,"san":50,"max_san":50,"is_ready":false}""" },
                new() { Id = "admin.scenarios", Method = "GET", Path = "/api/admin/scenarios", Description = "列出所有剧本", AuthType = "bearer" },
                new() { Id = "admin.scenarios.assets", Method = "GET", Path = "/api/admin/scenarios/{scenario_id}/assets", Description = "剧本素材列表", AuthType = "bearer", PathParams = new() { new() { Name = "scenario_id", Required = true } } },
                new() { Id = "admin.scenarios.uploadAsset", Method = "POST", Path = "/api/admin/scenarios/{scenario_id}/assets", Description = "上传剧本素材", AuthType = "bearer", PathParams = new() { new() { Name = "scenario_id", Required = true } }, HasFileUpload = true, ContentType = "multipart/form-data", BodySchema = "form: file, visibility (host_only|party|private|admin_only)" },
                new() { Id = "admin.scenarios.deleteAsset", Method = "DELETE", Path = "/api/admin/scenarios/{scenario_id}/assets/{asset_id}", Description = "删除剧本素材", AuthType = "bearer", PathParams = new() { new() { Name = "scenario_id", Required = true }, new() { Name = "asset_id", Required = true } }, BodySchema = """{"force":false,"confirm":false,"reason":""}""" },
                new() { Id = "admin.scenarios.importPdf", Method = "POST", Path = "/api/admin/scenarios/import-pdf", Description = "导入剧本 PDF", AuthType = "bearer", HasFileUpload = true, ContentType = "multipart/form-data" },
                new() { Id = "admin.scenarios.classify", Method = "POST", Path = "/api/admin/scenarios/{scenario_id}/classify", Description = "生成剧本分类", AuthType = "bearer", PathParams = new() { new() { Name = "scenario_id", Required = true } } },
                new() { Id = "admin.scenarios.generateMap", Method = "POST", Path = "/api/admin/scenarios/{scenario_id}/map/generate", Description = "AI 生成地图草稿", AuthType = "bearer", PathParams = new() { new() { Name = "scenario_id", Required = true } } },
                new() { Id = "admin.scenarios.getMap", Method = "GET", Path = "/api/admin/scenarios/{scenario_id}/map", Description = "获取地图草稿", AuthType = "bearer", PathParams = new() { new() { Name = "scenario_id", Required = true } } },
                new() { Id = "admin.scenarios.editMap", Method = "PATCH", Path = "/api/admin/scenarios/{scenario_id}/map", Description = "编辑地图草稿", AuthType = "bearer", PathParams = new() { new() { Name = "scenario_id", Required = true } }, BodySchema = """{"nodes":[],"edges":[]}""" },
                new() { Id = "admin.scenarios.confirmMap", Method = "POST", Path = "/api/admin/scenarios/{scenario_id}/map/confirm", Description = "确认/锁定地图", AuthType = "bearer", PathParams = new() { new() { Name = "scenario_id", Required = true } } },
                new() { Id = "admin.ai.configGet", Method = "GET", Path = "/api/admin/ai/config", Description = "获取全局 AI 配置", AuthType = "bearer" },
                new() { Id = "admin.ai.configUpdate", Method = "PATCH", Path = "/api/admin/ai/config", Description = "更新全局 AI 配置", AuthType = "bearer", BodySchema = "{}" },
                new() { Id = "admin.ai.healthCheck", Method = "POST", Path = "/api/admin/ai/health-check", Description = "AI 网关健康检查", AuthType = "bearer" },
                new() { Id = "admin.ai.logs", Method = "GET", Path = "/api/admin/ai/logs", Description = "查询 AI 调用日志", AuthType = "bearer", QueryParams = new() { new() { Name = "room_id", Required = false }, new() { Name = "task_type", Required = false }, new() { Name = "status", Required = false }, new() { Name = "limit", DefaultValue = "50" } } },
                new() { Id = "admin.ai.query", Method = "POST", Path = "/api/admin/ai/query", Description = "测试知识查询", AuthType = "bearer", BodySchema = """{"query":"","room_id":"","sources":"both"}""" },
                new() { Id = "admin.rag.contextPreview", Method = "POST", Path = "/api/admin/rag/context-preview", Description = "预览 RAG 上下文", AuthType = "bearer", BodySchema = """{"room_id":"","action_text":"","character_id":"","scenario_id":""}""" },
                new() { Id = "admin.rag.reindex", Method = "POST", Path = "/api/admin/rag/reindex", Description = "重建 RAG 索引", AuthType = "bearer", BodySchema = """{"kinds":["scenarios","characters","events","rules"]}""" },
                new() { Id = "admin.spoilerAudits", Method = "GET", Path = "/api/admin/rooms/{room_id}/spoiler-audits", Description = "查看剧透审计日志", AuthType = "bearer", PathParams = new() { new() { Name = "room_id", Required = true } }, QueryParams = new() { new() { Name = "limit", DefaultValue = "50" } } },
                new() { Id = "admin.spoilerRebuild", Method = "POST", Path = "/api/admin/scenarios/{scenario_id}/spoiler-index/rebuild", Description = "重建剧透敏感词索引", AuthType = "bearer", PathParams = new() { new() { Name = "scenario_id", Required = true } } },
            }
        };
    }

    // ── Scenarios (5 endpoints) ─────────────────────────────────
    static ApiDomain BuildScenarios()
    {
        return new ApiDomain
        {
            Name = "Scenarios",
            Prefix = "/api/scenarios",
            Endpoints = new()
            {
                new() { Id = "scenarios.available", Method = "GET", Path = "/api/scenarios/available", Description = "获取可用剧本列表", AuthType = "bearer" },
                new() { Id = "scenarios.importPdf", Method = "POST", Path = "/api/scenarios/import-pdf", Description = "上传并结构化剧本 PDF", AuthType = "bearer", HasFileUpload = true, ContentType = "multipart/form-data" },
                new() { Id = "scenarios.importJob", Method = "GET", Path = "/api/scenarios/import-jobs/{job_id}", Description = "查询导入任务状态", AuthType = "none", PathParams = new() { new() { Name = "job_id", Required = true } } },
                new() { Id = "scenarios.qualityReport", Method = "GET", Path = "/api/scenarios/{scenario_id}/quality-report", Description = "获取剧本质量报告", AuthType = "none", PathParams = new() { new() { Name = "scenario_id", Required = true } } },
                new() { Id = "scenarios.createRoom", Method = "POST", Path = "/api/scenarios/{scenario_id}/create-room", Description = "从剧本创建房间", AuthType = "bearer", PathParams = new() { new() { Name = "scenario_id", Required = true } }, BodySchema = """{"confirm_quality_risk":false}""" },
            }
        };
    }

    // ── Map (2 endpoints) ───────────────────────────────────────
    static ApiDomain BuildMap()
    {
        return new ApiDomain
        {
            Name = "Map",
            Prefix = "/api/map",
            Endpoints = new()
            {
                new() { Id = "map.view", Method = "GET", Path = "/api/map/{room_id}", Description = "玩家地图视图（战争迷雾）", AuthType = "room-token", PathParams = new() { new() { Name = "room_id", Required = true } } },
                new() { Id = "map.move", Method = "POST", Path = "/api/map/{room_id}/move", Description = "玩家移动", AuthType = "room-token", PathParams = new() { new() { Name = "room_id", Required = true } }, BodySchema = """{"target_node_id":"","from_node_id":""}""" },
            }
        };
    }

    // ── RAG (7 endpoints) ───────────────────────────────────────
    static ApiDomain BuildRag()
    {
        return new ApiDomain
        {
            Name = "RAG",
            Prefix = "/api/rag",
            Endpoints = new()
            {
                new() { Id = "rag.index", Method = "POST", Path = "/api/rag/index", Description = "索引剧本到 RAG", AuthType = "bearer", BodySchema = """{"scenario_id":"","room_id":""}""" },
                new() { Id = "rag.indexCharacter", Method = "POST", Path = "/api/rag/index-character", Description = "索引角色数据", AuthType = "bearer", BodySchema = """{"room_id":"","character_id":"","xlsx_data":{}}""" },
                new() { Id = "rag.indexNpc", Method = "POST", Path = "/api/rag/index-npc", Description = "索引 NPC 图谱", AuthType = "bearer", BodySchema = """{"room_id":"","scenario_id":"","knowledge_graph":{}}""" },
                new() { Id = "rag.indexRules", Method = "POST", Path = "/api/rag/index-rules", Description = "索引规则文档（admin only）", AuthType = "bearer", BodySchema = """{"doc_id":"","title":"","category":"","content":""}""" },
                new() { Id = "rag.search", Method = "POST", Path = "/api/rag/search", Description = "搜索 RAG 索引", AuthType = "bearer", BodySchema = """{"query":"","room_id":"","source_types":[],"top_k":5}""" },
                new() { Id = "rag.ruleDocs", Method = "GET", Path = "/api/rag/rule-docs", Description = "列出规则文档", AuthType = "bearer" },
                new() { Id = "rag.stats", Method = "GET", Path = "/api/rag/stats", Description = "RAG 统计信息", AuthType = "bearer" },
            }
        };
    }

    // ── Root / Utility (2 endpoints) ────────────────────────────
    static ApiDomain BuildRoot()
    {
        return new ApiDomain
        {
            Name = "Root",
            Prefix = "/",
            Endpoints = new()
            {
                new() { Id = "root.health", Method = "GET", Path = "/api/health", Description = "健康检查（含各组件状态）", AuthType = "none" },
                new() { Id = "root.aiTurn", Method = "POST", Path = "/api/rooms/{room_id}/ai-turn", Description = "触发 AI 结算回合", AuthType = "bearer", PathParams = new() { new() { Name = "room_id", Required = true } } },
            }
        };
    }
}
