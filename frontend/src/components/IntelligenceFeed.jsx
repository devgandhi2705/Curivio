import IntelligenceBrief from "./IntelligenceBrief.jsx"
import SectionCard       from "./SectionCard.jsx"
import LearningTrack     from "./LearningTrack.jsx"
import ActionItems       from "./ActionItems.jsx"
import TopicSelector     from "./TopicSelector.jsx"

/**
 * Main container for the intelligence feed.
 * Renders the full personalized brief: executive summary, 3 content sections,
 * learning track, and action items.
 */
export default function IntelligenceFeed({
  feed,
  onFeedback,
  topicFeedback,
  topicLoading,
  onTopicSelect,
  selectionLoading,
  selectionSubmitted,
  selectionError,
}) {
  if (!feed) return null

  const topics = feed.learning_track || feed.learning_topics || []

  return (
    <div className="space-y-5">
      {/* Executive brief */}
      <IntelligenceBrief
        brief={feed.intelligence_brief}
        industryContext={feed.industry_context}
      />

      {/* 3 content sections in a responsive grid */}
      {feed.sections?.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {feed.sections.map(section => (
            <SectionCard key={section.type} section={section} />
          ))}
        </div>
      )}

      {/* Learning track + sidebar */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">
        <div className="lg:col-span-3">
          <LearningTrack
            topics={topics}
            onFeedback={onFeedback}
            topicFeedback={topicFeedback}
            topicLoading={topicLoading}
          />
        </div>

        <div className="lg:col-span-2 space-y-4">
          <ActionItems
            items={feed.action_items}
            nextStep={feed.next_step}
          />
          {topics.length > 0 && (
            <TopicSelector
              topics={topics}
              onSubmit={onTopicSelect}
              loading={selectionLoading}
              submitted={selectionSubmitted}
              error={selectionError}
            />
          )}
        </div>
      </div>
    </div>
  )
}
