#if defined _ondemand_vpk_included
    #endinput
#endif
#define _ondemand_vpk_included

/**
 * On-demand VPK bridge API.
 * The bridge only writes small request files; the host controller moves VPKs.
 */
native int ODVPK_GetCampaignCount();
native bool ODVPK_GetCampaignInfo(int index, char[] campaign, int campaignLen, char[] display, int displayLen, int &chapterCount);
native bool ODVPK_GetChapterInfo(int campaignIndex, int chapterIndex, char[] mapName, int mapLen, char[] display, int displayLen);
native int ODVPK_GetCampaignChapterCount(const char[] campaign);
native bool ODVPK_GetCampaignChapterInfo(const char[] campaign, int chapterIndex, char[] mapName, int mapLen, char[] display, int displayLen);
native bool ODVPK_IsOnDemandCampaign(const char[] campaign);
native bool ODVPK_IsOnDemandMap(const char[] mapName, char[] campaign, int maxlen);
native bool ODVPK_IsMapStaged(const char[] campaign);
native int ODVPK_RequestStage(const char[] campaign, const char[] mapName, int client);
native int ODVPK_GetRequestStatus(int requestId);
native bool ODVPK_GetRequestTarget(int requestId, char[] campaign, int campaignLen, char[] mapName, int mapLen);

forward void OnDemandVPKStageResult(int requestId, const char[] campaign, const char[] mapName, int client, bool success);

public SharedPlugin __pl_ondemand_vpk_bridge =
{
    name = "ondemand_vpk_bridge",
    file = "ondemand_vpk_bridge.smx",
    required = 0,
};

#if !defined REQUIRE_PLUGIN
public void __pl_ondemand_vpk_bridge_SetNTVOptional()
{
    MarkNativeAsOptional("ODVPK_GetCampaignCount");
    MarkNativeAsOptional("ODVPK_GetCampaignInfo");
    MarkNativeAsOptional("ODVPK_GetChapterInfo");
    MarkNativeAsOptional("ODVPK_GetCampaignChapterCount");
    MarkNativeAsOptional("ODVPK_GetCampaignChapterInfo");
    MarkNativeAsOptional("ODVPK_IsOnDemandCampaign");
    MarkNativeAsOptional("ODVPK_IsOnDemandMap");
    MarkNativeAsOptional("ODVPK_IsMapStaged");
    MarkNativeAsOptional("ODVPK_RequestStage");
    MarkNativeAsOptional("ODVPK_GetRequestStatus");
    MarkNativeAsOptional("ODVPK_GetRequestTarget");
}
#endif
