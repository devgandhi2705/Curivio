# Chat Routing v2 — pre-existing test baseline

**Date:** 2026-09-12 · **Branch:** `chat-routing-v2` · **Commit under test:** 0b908d8 + Task 1's guard

Everything listed here already failed before this refactor began. Later tasks do not fix
these unless they delete or rewrite the test. A task's suite run is clean when it adds
nothing to this list.

## How to run the suite

```bash
# --continue-on-collection-errors is REQUIRED: two modules fail at import time (below),
# and without the flag pytest aborts the whole run before executing anything.
# Run in chunks: tests/test_generation_orchestrator.py hangs (below), and one silent
# 10-minute run is what stalled two agents.
.venv/Scripts/python.exe -m pytest -q --continue-on-collection-errors tests/test_[a-d]*.py
.venv/Scripts/python.exe -m pytest -q --continue-on-collection-errors tests/test_[e-f]*.py
.venv/Scripts/python.exe -m pytest -q --continue-on-collection-errors tests/test_[g-l]*.py  # see hang below
.venv/Scripts/python.exe -m pytest -q --continue-on-collection-errors tests/test_[m-r]*.py
.venv/Scripts/python.exe -m pytest -q --continue-on-collection-errors tests/test_[s-z]*.py
```

## Totals

| Chunk | Result |
|---|---|
| a-d | 46 failed, 1080 passed, 1 skipped (110s) |
| e-f (excluding feed_v2) | 9 failed, 146 passed (16s) |
| g-l | `tests/test_generation_orchestrator.py` **hangs** and is excluded (see below); the other 6 files: 33 failed, 216 passed, 4 deselected — itemized below (M15) |
| m-r | 11 failed, 619 passed, 22 errors (40s) |
| s-z | 79 failed, 648 passed, 2 errors (36s) |
| feed_v2 | 8 failed, 105 passed (82s) |

**187 failing/erroring test ids**, plus 2 collection errors and 1 hanging module.
(M15: the g-l chunk's 33 were already counted in the total above, but were
originally recorded only as a count — every one is now itemized by test id
in "Failing test ids by file" and the full list below. `tests/test_generation_orchestrator.py`
is excluded from every g-l run in this doc because it hangs — see item 2 below.)

## Three things that block a clean run

1. **Collection errors (2)** — `pytest` aborts the entire run without `--continue-on-collection-errors`:
   - `tests/test_source_metadata_service.py` — `ImportError: cannot import name '_classify_source_type' from 'backend.services.source_metadata_service'`
   - `tests/test_source_ranker.py` — `ImportError: cannot import name 'W_EDUCATION' from 'backend.services.source_ranker'`
   Both come from the TinyFish-migration WIP committed as `aa1a550`, not from this refactor.
2. **Hang** — `tests/test_generation_orchestrator.py::test_a_single_batch_returns_raw_dict` never returns
   (verified: it hangs with the isolation guard removed too, so it is not guard-induced).
3. **Two order-dependent flakes** — `test_domain_resource_service.py::TestActionRouterDomainIntegration::test_find_reports_instruction_mentions_domain`
   and `test_topic_cluster.py::TestEndpointWiring::test_categories_are_valid_values` fail inside a full chunk
   but pass in isolation, with and without the guard.

## Did the isolation guard break anything?

No. The same chunks (a-d, m-r, s-z) were run with the guard stashed out and with it in place:
159 failures in both. The only differences are the two order-dependent flakes above. No test in
this repo was relying on a real provider call to pass — the guard's value is stopping the
*successful* real calls (649 fake `llm_call_log` rows) that ran silently inside passing tests.

## Failing test ids by file

- `   backend.services.action_router_service:action_router_service.py:237 action_router: industry_brief generation failed for 'exports'` — 1
- `   backend.services.action_router_service:action_router_service.py:237 action_router: industry_brief generation failed for 'finance'` — 1
- `   backend.services.action_router_service:action_router_service.py:237 action_router: industry_brief generation failed for 'manufacturing'` — 1
- `   backend.services.chat_service:chat_service.py:735 chat_stream: AI generation failed` — 1
- `   backend.services.feed_v2.llm.call_logger:call_logger.py:80 [feed_v2.call_logger] failed to write log row for run_id=58702d49-4b2d-477e-be64-d9bf3a67f8a0` — 1
- `   backend.services.feed_v2.llm.call_logger:call_logger.py:80 [feed_v2.call_logger] failed to write log row for run_id=5d6d53ef-06ad-41e2-a360-1023aeaa41fe` — 1
- `   backend.services.feed_v2.llm.call_logger:call_logger.py:80 [feed_v2.call_logger] failed to write log row for run_id=96e8dd42-18d5-46f0-94dd-cdf854b089c7` — 1
- `   backend.services.feed_v2.llm.call_logger:call_logger.py:80 [feed_v2.call_logger] failed to write log row for run_id=dde6d363-8251-432b-91f1-34ee42e4e37a` — 1
- `   backend.services.feed_v2.llm.provider:provider.py:437 [feed_v2.provider] agent source_ranker: all legs failed: nemotron-nano-30b (openrouter): RealNetworkCallBlocked: Real request to openrouter.ai blocked by the test isolation guard. Mock the provider call, or mark the test @pytest.mark.integration. | gemini-3.1-flash-lite (google): RealNetworkCallBlocked: Real request to generativelanguage.googleapis.com blocked by the test isolation guard. Mock the provider call, or mark the test @pytest.mark.integration.` — 1
- `plan: rows=0  project={'journey_shape': None, 'journey_status': 'failed'}` — 1
- `tests/test_adaptive_explanation.py` — 3
- `tests/test_admin_search.py` — 4
- `tests/test_api_optimization.py` — 7
- `tests/test_chat_mode_mapping.py` — 3
- `tests/test_chat_router.py` — 4
- `tests/test_chat_upload_r14a.py` — 1
- `tests/test_chat_upload_r2.py` — 2
- `tests/test_crisis_support.py` — 13
- `tests/test_domain_classifier.py` — 6
- `tests/test_domain_resource_service.py` — 3
- `tests/test_feed_cache.py` — 4
- `tests/test_feed_context_note.py` — 1
- `tests/test_feed_pipeline.py` — 4
- `tests/test_feed_v2_corpus_offline.py` — 1
- `tests/test_feed_v2_graph.py` — 3
- `tests/test_feed_v2_ranker_offline.py` — 1
- `tests/test_feed_v2_section_writer.py` — 1
- `tests/test_feed_v2_visual_graph.py` — 2
- `tests/test_github_service.py` — 11 (M15: g-l chunk, itemized below)
- `tests/test_industry_intelligence_service.py` — 1 (M15: `TestAnalyzeIndustryErrors::test_partial_search_failure_continues_with_remaining_articles` —
  confirmed failing identically at `2eaaa97` in a temp worktree; its mock has no `meta` kwarg, which comes from `aa1a550`, not this refactor)
- `tests/test_intelligence_feed.py` — 7 (M15: g-l chunk, itemized below)
- `tests/test_learning_path.py` — 14 (M15: g-l chunk, itemized below)
- `tests/test_model_priority.py` — 1
- `tests/test_phase2_regression.py` — 31
- `tests/test_r19a_embedding_robustness.py` — 1
- `tests/test_scheduler.py` — 22
- `tests/test_session_memory.py` — 11
- `tests/test_source_analyzer.py` — 9
- `tests/test_source_diversity_scorer.py` — 8
- `tests/test_source_grounding_service.py` — 3
- `tests/test_source_intelligence.py` — 1
- `tests/test_source_metadata_service.py` — 1
- `tests/test_source_ranker.py` — 1
- `tests/test_source_ranker_learning.py` — 1
- `tests/test_streaming.py` — 17
- `tests/test_topic_cluster.py` — 3
- `tests/test_topic_expansion.py` — 4

<details><summary>Full list</summary>

- `   backend.services.action_router_service:action_router_service.py:237 action_router: industry_brief generation failed for 'exports'`
- `   backend.services.action_router_service:action_router_service.py:237 action_router: industry_brief generation failed for 'finance'`
- `   backend.services.action_router_service:action_router_service.py:237 action_router: industry_brief generation failed for 'manufacturing'`
- `   backend.services.chat_service:chat_service.py:735 chat_stream: AI generation failed`
- `   backend.services.feed_v2.llm.call_logger:call_logger.py:80 [feed_v2.call_logger] failed to write log row for run_id=58702d49-4b2d-477e-be64-d9bf3a67f8a0`
- `   backend.services.feed_v2.llm.call_logger:call_logger.py:80 [feed_v2.call_logger] failed to write log row for run_id=5d6d53ef-06ad-41e2-a360-1023aeaa41fe`
- `   backend.services.feed_v2.llm.call_logger:call_logger.py:80 [feed_v2.call_logger] failed to write log row for run_id=96e8dd42-18d5-46f0-94dd-cdf854b089c7`
- `   backend.services.feed_v2.llm.call_logger:call_logger.py:80 [feed_v2.call_logger] failed to write log row for run_id=dde6d363-8251-432b-91f1-34ee42e4e37a`
- `   backend.services.feed_v2.llm.provider:provider.py:437 [feed_v2.provider] agent source_ranker: all legs failed: nemotron-nano-30b (openrouter): RealNetworkCallBlocked: Real request to openrouter.ai blocked by the test isolation guard. Mock the provider call, or mark the test @pytest.mark.integration. | gemini-3.1-flash-lite (google): RealNetworkCallBlocked: Real request to generativelanguage.googleapis.com blocked by the test isolation guard. Mock the provider call, or mark the test @pytest.mark.integration.`
- `tests/test_phase2_regression.py::TestBeginnerFeed::test_beginner_calibration_injected`
- `tests/test_phase2_regression.py::TestBeginnerFeed::test_conceptual_laddering_rule_present`
- `tests/test_phase2_regression.py::TestBeginnerFeed::test_prompt_health`
- `tests/test_phase2_regression.py::TestDay1Feed::test_action_design_present`
- `tests/test_phase2_regression.py::TestDay1Feed::test_core_articles_present`
- `tests/test_phase2_regression.py::TestDay1Feed::test_curiosity_section_present`
- `tests/test_phase2_regression.py::TestDay1Feed::test_editorial_philosophy_present`
- `tests/test_phase2_regression.py::TestDay1Feed::test_first_day_no_history_label`
- `tests/test_phase2_regression.py::TestDay1Feed::test_no_unresolved_placeholders`
- `tests/test_phase2_regression.py::TestDay1Feed::test_output_schema_has_required_keys`
- `tests/test_phase2_regression.py::TestDay1Feed::test_persona_present`
- `tests/test_phase2_regression.py::TestDay1Feed::test_project_state_injected`
- `tests/test_phase2_regression.py::TestDay1Feed::test_prompt_health`
- `tests/test_phase2_regression.py::TestDay1Feed::test_section_count_reasonable`
- `tests/test_phase2_regression.py::TestDay1Feed::test_writing_style_standards_present`
- `tests/test_phase2_regression.py::TestDay2Feed::test_continuity_section_present`
- `tests/test_phase2_regression.py::TestDay2Feed::test_explored_concepts_present`
- `tests/test_phase2_regression.py::TestDay2Feed::test_output_schema_present`
- `tests/test_phase2_regression.py::TestDay2Feed::test_prior_insights_embedded`
- `tests/test_phase2_regression.py::TestDay2Feed::test_progression_history_injected`
- `tests/test_phase2_regression.py::TestDay2Feed::test_prompt_health`
- `tests/test_phase2_regression.py::TestDay2Feed::test_unresolved_question_embedded`
- `tests/test_source_metadata_service.py`
- `tests/test_source_ranker.py`
- `plan: rows=0  project={'journey_shape': None, 'journey_status': 'failed'}`
- `tests/test_adaptive_explanation.py::TestExplanationDirectivePrompt::test_directive_appears_before_guidelines_in_prompt`
- `tests/test_adaptive_explanation.py::TestExplanationDirectivePrompt::test_full_prompt_includes_advanced_directive`
- `tests/test_adaptive_explanation.py::TestExplanationDirectivePrompt::test_full_prompt_includes_beginner_directive`
- `tests/test_admin_search.py::TestRealDbSearch::test_baseline_no_search_timing_unaffected`
- `tests/test_admin_search.py::TestRealDbSearch::test_fully_unfiltered_call_unaffected_by_search_being_unused`
- `tests/test_admin_search.py::TestRealDbSearch::test_grouped_search_timing_stays_under_threshold`
- `tests/test_admin_search.py::TestRealDbSearch::test_grouped_search_timing_with_other_filters_active`
- `tests/test_api_optimization.py::TestGrokServiceLogging::test_ask_grok_calls_log_api_call`
- `tests/test_api_optimization.py::TestGrokServiceLogging::test_ask_grok_computes_cost`
- `tests/test_api_optimization.py::TestGrokServiceLogging::test_ask_grok_handles_missing_usage`
- `tests/test_api_optimization.py::TestGrokServiceLogging::test_ask_grok_raises_on_api_error`
- `tests/test_api_optimization.py::TestGrokServiceLogging::test_ask_grok_records_positive_duration`
- `tests/test_api_optimization.py::TestGrokServiceLogging::test_ask_grok_returns_content`
- `tests/test_api_optimization.py::TestGrokServiceLogging::test_ask_grok_truncates_query_hint`
- `tests/test_chat_mode_mapping.py::TestStreamReflectsActualToolUse::test_explicit_web_search_stays_web_search_when_no_tool_called`
- `tests/test_chat_mode_mapping.py::TestStreamReflectsActualToolUse::test_normal_mode_model_calls_web_search_marks_auto`
- `tests/test_chat_mode_mapping.py::TestStreamReflectsActualToolUse::test_normal_mode_no_tool_called_stays_normal`
- `tests/test_chat_router.py::TestMapToTaskType::test_code_execution_wins_first`
- `tests/test_chat_router.py::TestMapToTaskType::test_complex_when_no_tool_no_code`
- `tests/test_chat_router.py::TestMapToTaskType::test_needs_tool_when_no_code_execution`
- `tests/test_chat_router.py::TestMapToTaskType::test_simple_qa_fallback`
- `tests/test_chat_upload_r14a.py::TestImageDualWrite::test_gemini_failure_short_circuits_before_any_r2_call`
- `tests/test_chat_upload_r2.py::TestChatUploadR2Wiring::test_document_upload_calls_r2_upload_and_sets_expires_at`
- `tests/test_chat_upload_r2.py::TestChatUploadR2Wiring::test_r2_upload_failure_returns_502`
- `tests/test_crisis_support.py::TestSectionIsUnconditional::test_locale_flows_from_context_into_the_prompt`
- `tests/test_crisis_support.py::TestSectionIsUnconditional::test_missing_locale_degrades_to_the_honest_branch_not_an_error`
- `tests/test_crisis_support.py::TestSectionIsUnconditional::test_present_even_with_a_completely_empty_context`
- `tests/test_crisis_support.py::TestSectionIsUnconditional::test_present_in_natural_prompt_for_every_mode[layman]`
- `tests/test_crisis_support.py::TestSectionIsUnconditional::test_present_in_natural_prompt_for_every_mode[normal]`
- `tests/test_crisis_support.py::TestSectionIsUnconditional::test_present_in_natural_prompt_for_every_mode[web_search]`
- `tests/test_crisis_support.py::TestSectionIsUnconditional::test_present_in_structured_feed_linked_prompt`
- `tests/test_crisis_support.py::TestSectionIsUnconditional::test_present_regardless_of_what_the_user_said[U motherfucker...]`
- `tests/test_crisis_support.py::TestSectionIsUnconditional::test_present_regardless_of_what_the_user_said[]`
- `tests/test_crisis_support.py::TestSectionIsUnconditional::test_present_regardless_of_what_the_user_said[give me code to for pyramid generation in python, c and c++]`
- `tests/test_crisis_support.py::TestSectionIsUnconditional::test_present_regardless_of_what_the_user_said[hi]`
- `tests/test_crisis_support.py::TestSectionIsUnconditional::test_present_regardless_of_what_the_user_said[than I will do suicide]`
- `tests/test_crisis_support.py::TestSectionIsUnconditional::test_present_regardless_of_what_the_user_said[what's the code to hack google]`
- `tests/test_domain_classifier.py::TestGetDomainContext::test_ai_source_priority_includes_arxiv`
- `tests/test_domain_classifier.py::TestGetDomainContext::test_max_results_is_positive_int`
- `tests/test_domain_classifier.py::TestGetDomainContext::test_pharma_source_priority_includes_pubmed`
- `tests/test_domain_classifier.py::TestGetDomainContext::test_retrieval_has_required_keys`
- `tests/test_domain_classifier.py::TestGetDomainContext::test_retrieval_query_templates_are_strings`
- `tests/test_domain_classifier.py::TestGetDomainContext::test_returns_dict_with_required_keys`
- `tests/test_domain_resource_service.py::TestActionRouterDomainIntegration::test_find_reports_detected_for_industry_analysis`
- `tests/test_domain_resource_service.py::TestActionRouterDomainIntegration::test_find_reports_detected_for_market_analysis`
- `tests/test_domain_resource_service.py::TestActionRouterDomainIntegration::test_find_reports_instruction_mentions_domain`
- `tests/test_feed_cache.py::TestCuratorCacheIntegration::test_cache_hit_returns_cached_feed_unchanged`
- `tests/test_feed_cache.py::TestCuratorCacheIntegration::test_cache_hit_skips_tavily_and_groq`
- `tests/test_feed_cache.py::TestCuratorCacheIntegration::test_cache_miss_calls_tavily_and_groq`
- `tests/test_feed_cache.py::TestCuratorCacheIntegration::test_cache_miss_stores_result`
- `tests/test_feed_context_note.py::test_feed_context_note_preserves_complete_card_content_and_sources`
- `tests/test_feed_pipeline.py::TestSchedulerPipeline::test_job_calls_generate_with_correct_interests`
- `tests/test_feed_pipeline.py::TestSchedulerPipeline::test_job_does_not_crash_on_generate_error`
- `tests/test_feed_pipeline.py::TestSchedulerPipeline::test_job_does_not_crash_on_save_error`
- `tests/test_feed_pipeline.py::TestSchedulerPipeline::test_job_uses_default_interests_when_no_history`
- `tests/test_feed_v2_corpus_offline.py::test_full_graph_with_real_corpus_node`
- `tests/test_feed_v2_graph.py::test_resume_after_crash`
- `tests/test_feed_v2_graph.py::test_run_graph_finalizes_mas_run`
- `tests/test_feed_v2_graph.py::test_sse_reconnect_resumes_not_restarts`
- `tests/test_feed_v2_ranker_offline.py::test_full_graph_real_ranker`
- `tests/test_feed_v2_section_writer.py::test_full_graph_real_writer`
- `tests/test_feed_v2_visual_graph.py::test_full_graph_real_visuals_attached_to_real_beats`
- `tests/test_feed_v2_visual_graph.py::test_full_graph_visual_nodes_stay_stubbed_offline`
- `tests/test_github_service.py::TestStoreAndRetrieve::test_retrieve_returns_stored_repos`
- `tests/test_github_service.py::TestStoreAndRetrieve::test_retrieve_is_case_insensitive`
- `tests/test_github_service.py::TestGetTopicRepos::test_returns_cached_without_github_call`
- `tests/test_github_service.py::TestEndpointPost::test_returns_200`
- `tests/test_github_service.py::TestEndpointPost::test_blank_topic_returns_422`
- `tests/test_github_service.py::TestEndpointPost::test_missing_topic_returns_422`
- `tests/test_github_service.py::TestEndpointPost::test_response_has_topic_and_repositories`
- `tests/test_github_service.py::TestEndpointPost::test_repositories_is_list`
- `tests/test_github_service.py::TestEndpointPost::test_repo_entry_has_required_fields`
- `tests/test_github_service.py::TestEndpointPost::test_empty_repo_list_returns_200`
- `tests/test_github_service.py::TestEndpointPost::test_topic_echoed_in_response`
- `tests/test_industry_intelligence_service.py::TestAnalyzeIndustryErrors::test_partial_search_failure_continues_with_remaining_articles`
- `tests/test_intelligence_feed.py::TestGenerateIntelligenceFeed::test_returns_intelligence_brief`
- `tests/test_intelligence_feed.py::TestGenerateIntelligenceFeed::test_returns_three_sections`
- `tests/test_intelligence_feed.py::TestGenerateIntelligenceFeed::test_sections_have_two_items_each`
- `tests/test_intelligence_feed.py::TestGenerateIntelligenceFeed::test_returns_four_learning_track_items`
- `tests/test_intelligence_feed.py::TestGenerateIntelligenceFeed::test_returns_three_action_items`
- `tests/test_intelligence_feed.py::TestGenerateIntelligenceFeed::test_backward_compat_fields_present`
- `tests/test_intelligence_feed.py::TestGenerateIntelligenceFeed::test_persistence_failure_is_non_fatal`
- `tests/test_learning_path.py::TestStoreAndRetrieve::test_retrieve_returns_stored_result`
- `tests/test_learning_path.py::TestStoreAndRetrieve::test_retrieve_is_case_insensitive`
- `tests/test_learning_path.py::TestStoreAndRetrieve::test_retrieve_strips_whitespace`
- `tests/test_learning_path.py::TestGetLearningPath::test_returns_cached_without_calling_grok`
- `tests/test_learning_path.py::TestEndpointPost::test_returns_200`
- `tests/test_learning_path.py::TestEndpointPost::test_blank_topic_returns_422`
- `tests/test_learning_path.py::TestEndpointPost::test_missing_topic_returns_422`
- `tests/test_learning_path.py::TestEndpointPost::test_response_has_all_fields`
- `tests/test_learning_path.py::TestEndpointPost::test_repositories_is_list`
- `tests/test_learning_path.py::TestEndpointPost::test_beginner_tier_is_list`
- `tests/test_learning_path.py::TestEndpointPost::test_step_has_concept_field`
- `tests/test_learning_path.py::TestEndpointPost::test_resources_is_list`
- `tests/test_learning_path.py::TestEndpointPost::test_topic_trimmed_before_lookup`
- `tests/test_learning_path.py::TestEndpointPost::test_repos_included_in_response`
- `tests/test_model_priority.py::test_get_model_priority_list_returns_correct_order_per_task_type`
- `tests/test_phase2_regression.py::TestBudgetAllocatorIntegration::test_day1_feed_fits_groq_budget`
- `tests/test_phase2_regression.py::TestCompareMode::test_json_schema_present`
- `tests/test_phase2_regression.py::TestCompareMode::test_schema_has_sections_field`
- `tests/test_phase2_regression.py::TestContextPrioritizer::test_day1_feed_priority_distribution`
- `tests/test_phase2_regression.py::TestDay2Feed::test_day2_larger_than_day1`
- `tests/test_phase2_regression.py::TestTokenEfficiency::test_day1_feed_within_reasonable_budget`
- `tests/test_phase2_regression.py::TestTrendAnalysis::test_analysis_format_guidance`
- `tests/test_phase2_regression.py::TestTrendAnalysis::test_json_schema_present`
- `tests/test_phase2_regression.py::TestTrendAnalysis::test_schema_has_next_topics`
- `tests/test_r19a_embedding_robustness.py::TestUploadDocumentErrorHandling::test_store_document_failure_returns_clean_502_not_500`
- `tests/test_scheduler.py::TestAlreadyRanToday::test_returns_false_on_db_error`
- `tests/test_scheduler.py::TestAlreadyRanToday::test_returns_false_when_no_rows`
- `tests/test_scheduler.py::TestAlreadyRanToday::test_returns_true_when_completed_row_exists`
- `tests/test_scheduler.py::TestBuildInterests::test_falls_back_to_default_when_no_topics`
- `tests/test_scheduler.py::TestBuildInterests::test_uses_env_default_on_recommendation_error`
- `tests/test_scheduler.py::TestBuildInterests::test_uses_top_liked_topics`
- `tests/test_scheduler.py::TestDailyFeedJob::test_exhausts_retries_and_marks_failed`
- `tests/test_scheduler.py::TestDailyFeedJob::test_generates_when_not_yet_run`
- `tests/test_scheduler.py::TestDailyFeedJob::test_records_skipped_status_not_failed`
- `tests/test_scheduler.py::TestDailyFeedJob::test_records_started_then_completed`
- `tests/test_scheduler.py::TestDailyFeedJob::test_retries_on_transient_failure_then_succeeds`
- `tests/test_scheduler.py::TestDailyFeedJob::test_retry_count_respects_max_retries_env`
- `tests/test_scheduler.py::TestDailyFeedJob::test_skips_when_already_ran_today`
- `tests/test_scheduler.py::TestDailyMaintenanceJob::test_handles_purge_error_gracefully`
- `tests/test_scheduler.py::TestDailyMaintenanceJob::test_purges_expired_cache_entries`
- `tests/test_scheduler.py::TestGetSchedulerStatus::test_handles_db_error_gracefully`
- `tests/test_scheduler.py::TestGetSchedulerStatus::test_includes_last_run_from_db`
- `tests/test_scheduler.py::TestGetSchedulerStatus::test_returns_correct_shape`
- `tests/test_scheduler.py::TestInitScheduler::test_maintenance_job_runs_5_minutes_after_feed_job`
- `tests/test_scheduler.py::TestInitScheduler::test_midnight_maintenance_wraps_correctly`
- `tests/test_scheduler.py::TestInitScheduler::test_respects_hour_minute_env_vars`
- `tests/test_scheduler.py::TestInitScheduler::test_schedules_feed_and_maintenance_jobs`
- `tests/test_session_memory.py::TestSessionMemoryEndpoints::test_context_has_recommended_next`
- `tests/test_session_memory.py::TestSessionMemoryEndpoints::test_context_returns_200`
- `tests/test_session_memory.py::TestSessionMemoryEndpoints::test_context_returns_dict_even_for_unknown`
- `tests/test_session_memory.py::TestSessionMemoryEndpoints::test_get_topic_activities_is_list`
- `tests/test_session_memory.py::TestSessionMemoryEndpoints::test_get_topic_has_all_fields`
- `tests/test_session_memory.py::TestSessionMemoryEndpoints::test_get_topic_returns_200_on_hit`
- `tests/test_session_memory.py::TestSessionMemoryEndpoints::test_get_topic_returns_404_on_miss`
- `tests/test_session_memory.py::TestSessionMemoryEndpoints::test_list_empty_db_returns_empty`
- `tests/test_session_memory.py::TestSessionMemoryEndpoints::test_list_passes_limit_param`
- `tests/test_session_memory.py::TestSessionMemoryEndpoints::test_list_returns_200`
- `tests/test_session_memory.py::TestSessionMemoryEndpoints::test_list_returns_list`
- `tests/test_source_analyzer.py::TestCuratorAnalysisWiring::test_analyze_sources_called_in_pipeline`
- `tests/test_source_analyzer.py::TestCuratorAnalysisWiring::test_perspectives_in_feed_output`
- `tests/test_source_analyzer.py::TestCuratorAnalysisWiring::test_source_analysis_injected_into_prompt`
- `tests/test_source_analyzer.py::TestIdentifyTrends::test_detects_emerging_keyword`
- `tests/test_source_analyzer.py::TestIdentifyTrends::test_detects_new_keyword`
- `tests/test_source_analyzer.py::TestIdentifyTrends::test_empty_articles_returns_empty`
- `tests/test_source_analyzer.py::TestIdentifyTrends::test_no_trend_signals_returns_empty`
- `tests/test_source_analyzer.py::TestIdentifyTrends::test_returns_list`
- `tests/test_source_analyzer.py::TestIdentifyTrends::test_trend_phrase_contains_surrounding_words`
- `tests/test_source_diversity_scorer.py::TestCanonicalScenarios::test_same_type_but_different_domains_preferred`
- `tests/test_source_diversity_scorer.py::TestDomainSignal::test_new_domain_bonus_is_correct`
- `tests/test_source_diversity_scorer.py::TestDomainSignal::test_second_from_same_domain_mild_penalty`
- `tests/test_source_diversity_scorer.py::TestPerspectiveSignal::test_empty_perspective_not_penalized`
- `tests/test_source_diversity_scorer.py::TestPerspectiveSignal::test_new_perspective_gets_bonus`
- `tests/test_source_diversity_scorer.py::TestPerspectiveSignal::test_third_same_perspective_gets_penalty`
- `tests/test_source_diversity_scorer.py::TestSourceTypeSignal::test_fourth_of_same_type_gets_penalty`
- `tests/test_source_diversity_scorer.py::TestSourceTypeSignal::test_known_type_no_penalty_under_threshold`
- `tests/test_source_grounding_service.py::TestGroundPackageDiscard::test_all_core_cards_dropped_raises_runtime_error`
- `tests/test_source_grounding_service.py::TestGroundPackageDiscard::test_card_with_empty_url_source_dropped`
- `tests/test_source_grounding_service.py::TestLegacySourceLinks::test_legacy_format_invalid_url_discarded`
- `tests/test_source_intelligence.py::test_empty_content_no_crash`
- `tests/test_source_ranker_learning.py::TestFormula::test_breakdown_contains_all_required_fields`
- `tests/test_streaming.py::TestAskGrokChatStream::test_raises_runtime_error_on_api_failure`
- `tests/test_streaming.py::TestAskGrokChatStream::test_reads_usage_from_final_chunk`
- `tests/test_streaming.py::TestAskGrokChatStream::test_skips_empty_choices_chunks`
- `tests/test_streaming.py::TestAskGrokChatStream::test_skips_none_content_chunks`
- `tests/test_streaming.py::TestAskGrokChatStream::test_yields_nothing_for_empty_stream`
- `tests/test_streaming.py::TestAskGrokChatStream::test_yields_text_chunks`
- `tests/test_streaming.py::TestChatStreamGenerator::test_recommendations_in_done_event`
- `tests/test_streaming.py::TestStreamEndpoint::test_chunk_events_in_order`
- `tests/test_streaming.py::TestStreamEndpoint::test_content_type_is_ndjson`
- `tests/test_streaming.py::TestStreamEndpoint::test_done_event_has_message_id`
- `tests/test_streaming.py::TestStreamEndpoint::test_error_event_propagated`
- `tests/test_streaming.py::TestStreamEndpoint::test_last_event_is_done`
- `tests/test_streaming.py::TestStreamEndpoint::test_missing_message_returns_422`
- `tests/test_streaming.py::TestStreamEndpoint::test_missing_session_id_returns_422`
- `tests/test_streaming.py::TestStreamEndpoint::test_no_cache_header_set`
- `tests/test_streaming.py::TestStreamEndpoint::test_response_is_valid_ndjson`
- `tests/test_streaming.py::TestStreamEndpoint::test_returns_200`
- `tests/test_topic_cluster.py::TestEndpointWiring::test_categories_are_valid_values`
- `tests/test_topic_cluster.py::TestEndpointWiring::test_known_topic_titles_get_correct_category`
- `tests/test_topic_cluster.py::TestEndpointWiring::test_topics_have_category_field`
- `tests/test_topic_expansion.py::TestExpandTopic::test_returns_cached_result_without_calling_grok`
- `tests/test_topic_expansion.py::TestStoreAndRetrieve::test_retrieve_is_case_insensitive`
- `tests/test_topic_expansion.py::TestStoreAndRetrieve::test_retrieve_returns_stored_result`
- `tests/test_topic_expansion.py::TestStoreAndRetrieve::test_retrieve_strips_whitespace`

</details>
