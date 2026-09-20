#pragma semicolon 1
#pragma newdecls required

#include <files>

#define PLUGIN_NAME "On-demand VPK Bridge"
#define PLUGIN_VERSION "0.5.1"
#define CONFIG_FILE "configs/ondemand_vpk.cfg"
#define REQUEST_DIR "data/ondemand_vpk_requests"
#define MAX_PARTS 16
#define MAX_CAMPAIGNS 1024
#define MAX_CHAPTERS 128

public Plugin myinfo =
{
    name = PLUGIN_NAME,
    author = "Hermes Agent",
    description = "按需多Part VPK目录、宿主加载请求与状态桥接",
    version = PLUGIN_VERSION,
    url = ""
};

ConVar g_cvConfig;
ConVar g_cvInstance;
KeyValues g_kvCfg;
int g_iCfgMtime;
int g_iNextRequest = 1;
GlobalForward g_fStageResult;
int g_iRequestIds[MAXPLAYERS + 1];
int g_iRequestClients[MAXPLAYERS + 1];
char g_sRequestCampaign[MAXPLAYERS + 1][128];
char g_sRequestMap[MAXPLAYERS + 1][128];
Handle g_hPollTimer = INVALID_HANDLE;
int g_iPollHeartbeat;
bool g_bPollActive;

void EnsurePollTimer()
{
    if (!g_bPollActive)
    {
        g_bPollActive = true;
        g_hPollTimer = CreateTimer(2.0, TimerCheckStageRequests, _, TIMER_REPEAT | TIMER_FLAG_NO_MAPCHANGE);
        LogMessage("[OnDemandVPK] poll timer created");
    }
}

public void OnPluginStart()
{
    g_cvConfig = CreateConVar("ondemand_vpk_config", CONFIG_FILE, "按需多Part VPK配置，相对left4dead2/", FCVAR_NOTIFY);
    g_cvInstance = CreateConVar("ondemand_vpk_instance", "", "实例标识（如 57406）。多服共享请求目录时作为请求/res 文件名前缀，为空则单服模式。", FCVAR_NOTIFY);
    g_kvCfg = new KeyValues("OnDemandVPK");
    g_iCfgMtime = -1;
    RegAdminCmd("sm_ondemand_status", CommandStatus, ADMFLAG_ROOT, "显示按需战役组状态");
        RegAdminCmd("sm_ondemand_refresh", CommandRefresh, ADMFLAG_ROOT, "刷新Addon搜索路径和Mission列表");
        RegAdminCmd("sm_ondemand_requests", CommandRequests, ADMFLAG_ROOT, "显示按需请求目录状态");
        RegAdminCmd("sm_ondemand_notify", CommandNotify, ADMFLAG_ROOT, "宿主 RCON 回调：stage 结果主动通知（实时主通道）");
    g_fStageResult = new GlobalForward("OnDemandVPKStageResult", ET_Ignore, Param_Cell, Param_String, Param_String, Param_Cell, Param_Cell);
        EnsurePollTimer();
        LogMessage("[OnDemandVPK] bridge loaded version=%s config=%s", PLUGIN_VERSION, CONFIG_FILE);
    }

    public void OnPluginEnd()
    {
        // Timer 由 SourceMod 在插件卸载时自动清理，不手动 delete（mapchange/卸载帧 delete 会报错，2026-09-19 实测）
        delete g_fStageResult;
        delete g_kvCfg;
    }

    public void OnClientPutInServer(int client)
    {
        // 玩家进服：心跳检测轮询定时器是否存活（hibernating 冷启动等场景 Timer 可能失效）
        int before = g_iPollHeartbeat;
        CreateTimer(5.0, TimerCheckHeartbeat, before, TIMER_FLAG_NO_MAPCHANGE);
    }

    public Action TimerCheckHeartbeat(Handle timer, int before)
    {
        if (g_iPollHeartbeat == before)
        {
            // 心跳死 → 重置 flag 重建（不手动 delete Timer——delete 在部分 SM 版本/帧会报错，2026-09-19 实测）
            g_bPollActive = false;
            g_hPollTimer = INVALID_HANDLE;
            EnsurePollTimer();
            LogMessage("[OnDemandVPK] poll timer heartbeat dead, re-armed");
        }
        return Plugin_Continue;
    }

    public Action TimerCheckStageRequests(Handle timer)
    {
        g_iPollHeartbeat++;
        for (int slot = 1; slot <= MaxClients; slot++)
        {
            int requestId = g_iRequestIds[slot];
            if (requestId <= 0)
                continue;
            int status = ReadRequestResult(requestId);
            if (status == 0)
                continue;
            LogMessage("[OnDemandVPK] poll res read slot=%d id=%d status=%d camp=%s map=%s client=%d", slot, requestId, status, g_sRequestCampaign[slot], g_sRequestMap[slot], g_iRequestClients[slot]);

        if (g_fStageResult != null)
        {
            Call_StartForward(g_fStageResult);
            Call_PushCell(requestId);
            Call_PushString(g_sRequestCampaign[slot]);
            Call_PushString(g_sRequestMap[slot]);
            Call_PushCell(g_iRequestClients[slot]);
            Call_PushCell(status == 1);
            Call_Finish();
        }
        char reqPath[PLATFORM_MAX_PATH], resPath[PLATFORM_MAX_PATH];
        BuildRequestPath(requestId, "req", reqPath, sizeof(reqPath));
        BuildRequestPath(requestId, "res", resPath, sizeof(resPath));
        // DeleteFile/RenameFile 相对路径在容器 CWD=/root/steamcmd 下解析不到游戏根而失败
        // （2026-09-18 实测），res 残留会每 2s 重复触发 StageResult 回调。
        // 改用 OpenFile("w") 把 res 清成空文件 → ReadRequestResult 返回 0，不再重复触发；
        // .req/.req.part 由宿主控制器轮询清理，这里不再依赖 DeleteFile。
        File fRes = OpenFile(resPath, "w");
        if (fRes != null)
            delete fRes;
        g_iRequestIds[slot] = 0;
        g_iRequestClients[slot] = 0;
        g_sRequestCampaign[slot][0] = '\0';
        g_sRequestMap[slot][0] = '\0';
    }
    return Plugin_Continue;
}

public APLRes AskPluginLoad2(Handle myself, bool late, char[] error, int err_max)
{
    RegPluginLibrary("ondemand_vpk_bridge");
    CreateNative("ODVPK_GetCampaignCount", NativeGetCampaignCount);
    CreateNative("ODVPK_GetCampaignInfo", NativeGetCampaignInfo);
    CreateNative("ODVPK_GetChapterInfo", NativeGetChapterInfo);
    CreateNative("ODVPK_GetCampaignChapterCount", NativeGetCampaignChapterCount);
    CreateNative("ODVPK_GetCampaignChapterInfo", NativeGetCampaignChapterInfo);
    CreateNative("ODVPK_IsOnDemandCampaign", NativeIsOnDemandCampaign);
    CreateNative("ODVPK_IsOnDemandMap", NativeIsOnDemandMap);
    CreateNative("ODVPK_IsMapStaged", NativeIsMapStaged);
    CreateNative("ODVPK_RequestStage", NativeRequestStage);
    CreateNative("ODVPK_GetRequestStatus", NativeGetRequestStatus);
    CreateNative("ODVPK_GetRequestTarget", NativeGetRequestTarget);
    return APLRes_Success;
}

bool LoadConfig()
{
    char relative[PLATFORM_MAX_PATH];
    char path[PLATFORM_MAX_PATH];
    g_cvConfig.GetString(relative, sizeof(relative));
    BuildPath(Path_SM, path, sizeof(path), "%s", relative);
    int mtime = GetFileTime(path, FileTime_LastChange);
    if (mtime != g_iCfgMtime)
    {
        // Rewind() 不清空 KeyValues、ImportFromFile 是追加——必须先重建实例，否则每次 cfg 变化都累积旧内容
        delete g_kvCfg;
        g_kvCfg = new KeyValues("OnDemandVPK");
        if (!g_kvCfg.ImportFromFile(path))
        {
            LogError("[OnDemandVPK] cannot import config: %s", path);
            return false;
        }
        g_iCfgMtime = mtime;
        LogMessage("[OnDemandVPK] config loaded: %s (mtime=%d)", path, mtime);
    }
    else
    {
        g_kvCfg.Rewind();
    }
    return true;
}

bool GotoCampaignByIndex(KeyValues g_kvCfg, int wanted, char[] campaign, int maxlen)
{
    g_kvCfg.Rewind();
    if (!g_kvCfg.GotoFirstSubKey())
        return false;
    int index;
    do
    {
        if (index == wanted)
        {
            g_kvCfg.GetSectionName(campaign, maxlen);
            return true;
        }
        index++;
    }
    while (g_kvCfg.GotoNextKey());
    return false;
}

bool GotoCampaign(KeyValues g_kvCfg, const char[] campaign)
{
    g_kvCfg.Rewind();
    return g_kvCfg.JumpToKey(campaign, false);
}

int GetPartCount(KeyValues g_kvCfg)
{
    int count = g_kvCfg.GetNum("part_count", 0);
    if (count < 0 || count > MAX_PARTS)
        return 0;
    return count;
}

void GetValue(KeyValues g_kvCfg, const char[] key, char[] value, int maxlen)
{
    g_kvCfg.GetString(key, value, maxlen, "");
}

bool GetChapter(KeyValues g_kvCfg, int chapterIndex, char[] mapName, int mapLen, char[] display, int displayLen)
{
    char key[32];
    FormatEx(key, sizeof(key), "chapter_%d", chapterIndex + 1);
    g_kvCfg.GetString(key, mapName, mapLen, "");
    if (mapName[0] == '\0')
        return false;
    FormatEx(key, sizeof(key), "chapter_display_%d", chapterIndex + 1);
    g_kvCfg.GetString(key, display, displayLen, mapName);
    return true;
}

bool IsCampaignStaged(KeyValues g_kvCfg)
{
    int count = GetPartCount(g_kvCfg);
    if (count < 1)
        return false;
    for (int i = 1; i <= count; i++)
    {
        char key[32], target[PLATFORM_MAX_PATH];
        FormatEx(key, sizeof(key), "target_%d", i);
        g_kvCfg.GetString(key, target, sizeof(target), "");
        if (target[0] == '\0' || FileSize(target) <= 0)
            return false;
    }
    return true;
}

bool IsMapInCampaign(KeyValues g_kvCfg, const char[] mapName)
{
    int count = g_kvCfg.GetNum("chapter_count", 0);
    for (int i = 0; i < count && i < MAX_CHAPTERS; i++)
    {
        char map[128], display[128];
        if (GetChapter(g_kvCfg, i, map, sizeof(map), display, sizeof(display)) && !strcmp(map, mapName))
            return true;
    }
    return false;
}

bool FindCampaignForMap(const char[] mapName, char[] campaign, int campaignLen)
{
        if (!LoadConfig())
    {
        return false;
    }
    if (!g_kvCfg.GotoFirstSubKey())
    {
        return false;
    }
    do
    {
        if (IsMapInCampaign(g_kvCfg, mapName))
        {
            g_kvCfg.GetSectionName(campaign, campaignLen);
            return true;
        }
    }
    while (g_kvCfg.GotoNextKey());
    return false;
}

void BuildRequestPath(int requestId, const char[] suffix, char[] path, int maxlen)
{
    char dir[PLATFORM_MAX_PATH];
    BuildPath(Path_SM, dir, sizeof(dir), REQUEST_DIR);
    CreateDirectory(dir, 511);
    char instance[64];
    g_cvInstance.GetString(instance, sizeof(instance));
    if (instance[0] == '\0')
    {
        // 共享 addons 下自动用 hostport 作为实例前缀（每服唯一，零配置）
        ConVar cvHostPort = FindConVar("hostport");
        if (cvHostPort != null)
            IntToString(cvHostPort.IntValue, instance, sizeof(instance));
    }
    if (instance[0] != '\0')
        FormatEx(path, maxlen, "%s/%s_%d.%s", dir, instance, requestId, suffix);
    else
        FormatEx(path, maxlen, "%s/%d.%s", dir, requestId, suffix);
}

int ReadRequestResult(int requestId)
{
    char path[PLATFORM_MAX_PATH];
    BuildRequestPath(requestId, "res", path, sizeof(path));
    if (!FileExists(path))
        return 0;
    File file = OpenFile(path, "r");
    if (file == null)
        return 0;
    char line[32];
    bool read = file.ReadLine(line, sizeof(line));
    delete file;
    if (!read)
        return 0;
    TrimString(line);
    if (!strcmp(line, "OK"))
        return 1;
    if (!strcmp(line, "FAIL"))
        return 2;
    return 2;
}

int NativeGetCampaignCount(Handle plugin, int numParams)
{
        if (!LoadConfig())
    {
        return 0;
    }
    int count;
    g_kvCfg.Rewind();
    if (g_kvCfg.GotoFirstSubKey())
    {
        do { count++; } while (g_kvCfg.GotoNextKey());
    }
    return count;
}

any NativeGetCampaignInfo(Handle plugin, int numParams)
{
    int index = GetNativeCell(1);
    int campaignLen = GetNativeCell(3);
    int displayLen = GetNativeCell(5);
    char campaign[128], display[256];
        if (!LoadConfig() || !GotoCampaignByIndex(g_kvCfg, index, campaign, sizeof(campaign)))
    {
        return false;
    }
    GetValue(g_kvCfg, "display", display, sizeof(display));
    SetNativeString(2, campaign, campaignLen);
    SetNativeString(4, display, displayLen);
    SetNativeCellRef(6, g_kvCfg.GetNum("chapter_count", 0));
    return true;
}

any NativeGetChapterInfo(Handle plugin, int numParams)
{
    int campaignIndex = GetNativeCell(1);
    int chapterIndex = GetNativeCell(2);
    int mapLen = GetNativeCell(4);
    int displayLen = GetNativeCell(6);
    char campaign[128], mapName[128], display[256];
        if (!LoadConfig() || !GotoCampaignByIndex(g_kvCfg, campaignIndex, campaign, sizeof(campaign)) || !GetChapter(g_kvCfg, chapterIndex, mapName, sizeof(mapName), display, sizeof(display)))
    {
        return false;
    }
    SetNativeString(3, mapName, mapLen);
    SetNativeString(5, display, displayLen);
    return true;
}

any NativeGetCampaignChapterCount(Handle plugin, int numParams)
{
    char campaign[128];
    GetNativeString(1, campaign, sizeof(campaign));
        bool ok = LoadConfig() && GotoCampaign(g_kvCfg, campaign);
    int count = ok ? g_kvCfg.GetNum("chapter_count", 0) : 0;
    return count;
}

any NativeGetCampaignChapterInfo(Handle plugin, int numParams)
{
    char campaign[128], mapName[128], display[256];
    GetNativeString(1, campaign, sizeof(campaign));
    int chapterIndex = GetNativeCell(2);
        if (!LoadConfig() || !GotoCampaign(g_kvCfg, campaign) || !GetChapter(g_kvCfg, chapterIndex, mapName, sizeof(mapName), display, sizeof(display)))
    {
        return false;
    }
    SetNativeString(3, mapName, GetNativeCell(4));
    SetNativeString(5, display, GetNativeCell(6));
    return true;
}

any NativeIsOnDemandCampaign(Handle plugin, int numParams)
{
    char campaign[128];
    GetNativeString(1, campaign, sizeof(campaign));
        bool result = LoadConfig() && GotoCampaign(g_kvCfg, campaign);
    return result;
}

any NativeIsOnDemandMap(Handle plugin, int numParams)
{
    char mapName[128], campaign[128];
    GetNativeString(1, mapName, sizeof(mapName));
    bool result = FindCampaignForMap(mapName, campaign, sizeof(campaign));
    if (result)
        SetNativeString(2, campaign, GetNativeCell(3));
    return result;
}

any NativeIsMapStaged(Handle plugin, int numParams)
{
    char campaign[128];
    GetNativeString(1, campaign, sizeof(campaign));
        bool result = LoadConfig() && GotoCampaign(g_kvCfg, campaign) && IsCampaignStaged(g_kvCfg);
    return result;
}

any NativeRequestStage(Handle plugin, int numParams)
{
    char campaign[128], mapName[128];
    GetNativeString(1, campaign, sizeof(campaign));
    GetNativeString(2, mapName, sizeof(mapName));
    int client = GetNativeCell(3);

    int slot = (client >= 1 && client <= MaxClients) ? client : 1;
    if (g_iRequestIds[slot] > 0)
        return -1;

        if (!LoadConfig() || !GotoCampaign(g_kvCfg, campaign) || !IsMapInCampaign(g_kvCfg, mapName))
    {
        return -1;
    }
    if (IsCampaignStaged(g_kvCfg))
    {
        return 0;
    }

    int requestId = g_iNextRequest++;
    if (g_iNextRequest < 1)
        g_iNextRequest = 1;
    char reqPath[PLATFORM_MAX_PATH];
    char tmpPath[PLATFORM_MAX_PATH];
    BuildRequestPath(requestId, "req", reqPath, sizeof(reqPath));
    FormatEx(tmpPath, sizeof(tmpPath), "%s.part", reqPath);
    // 请求开始前清空同 id 旧 .res（requestId 重启后可能复用，防止 poll 兜底读到旧 FAIL/OK）
    char resPath[PLATFORM_MAX_PATH];
    BuildRequestPath(requestId, "res", resPath, sizeof(resPath));
    File fOldRes = OpenFile(resPath, "w");
    if (fOldRes != null)
        delete fOldRes;
    File file = OpenFile(tmpPath, "w");
    if (file == null)
        return -1;
    file.WriteLine("campaign=%s", campaign);
    file.WriteLine("map=%s", mapName);
    file.WriteLine("client=%d", client);
    delete file;
    RenameFile(tmpPath, reqPath);
    LogMessage("[OnDemandVPK] stage request id=%d campaign=%s map=%s client=%d", requestId, campaign, mapName, client);
    g_iRequestIds[slot] = requestId;
    g_iRequestClients[slot] = client;
    strcopy(g_sRequestCampaign[slot], sizeof(g_sRequestCampaign[]), campaign);
    strcopy(g_sRequestMap[slot], sizeof(g_sRequestMap[]), mapName);
    return requestId;
}

any NativeGetRequestStatus(Handle plugin, int numParams)
{
    return ReadRequestResult(GetNativeCell(1));
}

any NativeGetRequestTarget(Handle plugin, int numParams)
{
    int requestId = GetNativeCell(1);
    char campaign[128], mapName[128];
    char path[PLATFORM_MAX_PATH];
    BuildRequestPath(requestId, "req", path, sizeof(path));
    File file = OpenFile(path, "r");
    if (file == null)
        return false;
    char line[256];
    while (file.ReadLine(line, sizeof(line)))
    {
        TrimString(line);
        if (!strncmp(line, "campaign=", 9))
            strcopy(campaign, sizeof(campaign), line[9]);
        else if (!strncmp(line, "map=", 4))
            strcopy(mapName, sizeof(mapName), line[4]);
    }
    delete file;
    SetNativeString(2, campaign, GetNativeCell(3));
    SetNativeString(4, mapName, GetNativeCell(5));
    return campaign[0] != '\0' && mapName[0] != '\0';
}

Action CommandStatus(int client, int args)
{
    int count = NativeGetCampaignCount(null, 0);
    ReplyToCommand(client, "[OnDemandVPK] campaigns=%d", count);
    for (int i; i < count; i++)
    {
        char campaign[128], display[256];
        int chapterCount;
        if (GetCampaignForStatus(i, campaign, sizeof(campaign), display, sizeof(display), chapterCount))
            ReplyToCommand(client, "  %s display=%s chapters=%d staged=%d", campaign, display, chapterCount, IsCampaignStagedByName(campaign));
    }
    return Plugin_Handled;
}

bool GetCampaignForStatus(int index, char[] campaign, int campaignLen, char[] display, int displayLen, int &chapterCount)
{
        if (!LoadConfig() || !GotoCampaignByIndex(g_kvCfg, index, campaign, campaignLen))
    {
        return false;
    }
    GetValue(g_kvCfg, "display", display, displayLen);
    chapterCount = g_kvCfg.GetNum("chapter_count", 0);
    return true;
}

bool IsCampaignStagedByName(const char[] campaign)
{
        bool result = LoadConfig() && GotoCampaign(g_kvCfg, campaign) && IsCampaignStaged(g_kvCfg);
    return result;
}

Action CommandRefresh(int client, int args)
{
    ServerCommand("update_addon_paths; mission_reload");
    ServerExecute();
    ReplyToCommand(client, "[OnDemandVPK] 已刷新Addon路径和Mission");
    return Plugin_Handled;
}

Action CommandRequests(int client, int args)
{
    char path[PLATFORM_MAX_PATH];
    BuildPath(Path_SM, path, sizeof(path), REQUEST_DIR);
    ReplyToCommand(client, "[OnDemandVPK] request_dir=%s", path);
    return Plugin_Handled;
}

Action CommandNotify(int client, int args)
{
    // sm_ondemand_notify <requestId> <campaign> <map> <client> <success> —— 宿主 RCON 实时回调（主通道）
    if (args < 5)
    {
        ReplyToCommand(client, "[OnDemandVPK] usage: sm_ondemand_notify <requestId> <campaign> <map> <client> <success>");
        return Plugin_Handled;
    }
    char sReq[16], sCampaign[160], sMap[160], sClient[16], sSuccess[4];
    GetCmdArg(1, sReq, sizeof(sReq));
    GetCmdArg(2, sCampaign, sizeof(sCampaign));
    GetCmdArg(3, sMap, sizeof(sMap));
    GetCmdArg(4, sClient, sizeof(sClient));
    GetCmdArg(5, sSuccess, sizeof(sSuccess));
    int requestId = StringToInt(sReq);
    int targetClient = StringToInt(sClient);
    bool success = StringToInt(sSuccess) != 0;

    for (int slot = 1; slot <= MaxClients; slot++)
    {
        if (g_iRequestIds[slot] != requestId)
            continue;

        // 命中登记的请求 → 触发 forward（campaign/map/client 以登记为准，success 以回调为准）
        if (g_fStageResult != null)
        {
            Call_StartForward(g_fStageResult);
            Call_PushCell(requestId);
            Call_PushString(g_sRequestCampaign[slot]);
            Call_PushString(g_sRequestMap[slot]);
            Call_PushCell(g_iRequestClients[slot]);
            Call_PushCell(success);
            Call_Finish();
        }
        g_iRequestIds[slot] = 0;
        g_iRequestClients[slot] = 0;
        g_sRequestCampaign[slot][0] = '\0';
        g_sRequestMap[slot][0] = '\0';
        // 处理完清空 res（保持请求目录干净，防止 requestId 复用读到旧内容）
        char resPath[PLATFORM_MAX_PATH];
        BuildRequestPath(requestId, "res", resPath, sizeof(resPath));
        File fRes = OpenFile(resPath, "w");
        if (fRes != null)
            delete fRes;
        LogMessage("[OnDemandVPK] notify processed slot=%d id=%d success=%d camp=%s", slot, requestId, success, sCampaign);
        return Plugin_Handled;
    }
    LogMessage("[OnDemandVPK] notify no matching slot id=%d", requestId);
    return Plugin_Handled;
}
