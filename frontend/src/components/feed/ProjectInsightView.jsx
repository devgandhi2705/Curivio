/**
 * ProjectInsightView — thin wrapper that passes the daily-package list
 * and read-state props to DailyPackageView.
 */
import DailyPackageView from "./DailyPackageView.jsx"

export default function ProjectInsightView({
  project,
  insights,
  onGenerate,
  onRegenerate,
  generating,
  onOpenInChat,
  readKeys,
  onMarkRead,
  onMarkUnread,
  relatedChatsMap,
  onLoadRelatedChats,
  onOpenChat,
  targetInsightId,
  targetArticleKey,
  onClearQueueTarget,
  onExportReady,
}) {
  return (
    <DailyPackageView
      project={project}
      packages={insights}
      onGenerate={onGenerate}
      onRegenerate={onRegenerate}
      generating={generating}
      onOpenInChat={onOpenInChat}
      readKeys={readKeys}
      onMarkRead={onMarkRead}
      onMarkUnread={onMarkUnread}
      relatedChatsMap={relatedChatsMap}
      onLoadRelatedChats={onLoadRelatedChats}
      onOpenChat={onOpenChat}
      targetInsightId={targetInsightId}
      targetArticleKey={targetArticleKey}
      onClearQueueTarget={onClearQueueTarget}
      onExportReady={onExportReady}
    />
  )
}
