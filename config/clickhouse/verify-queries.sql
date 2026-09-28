-- Validation queries for teremoqwow telemetry in ClickHouse

-- Query 1: Count events by namespace in the last 24 hours
-- Monitors event ingestion volume per namespace
--
-- SELECT 
--     namespace,
--     COUNT(*) as event_count,
--     toDateTime(max(timestamp_pts) / 1000) as latest_event
-- FROM teremoqwow.telemetry_events
-- WHERE timestamp_pts >= (now() - INTERVAL 24 HOUR) * 1000
-- GROUP BY namespace
-- ORDER BY event_count DESC;


-- Query 2: PTS latency percentile by event kind in the last 1 hour
-- Identifies latency patterns for different event types
--
-- SELECT 
--     kind,
--     count() as sample_count,
--     quantile(0.5)(timestamp_pts) as p50_ms,
--     quantile(0.95)(timestamp_pts) as p95_ms,
--     quantile(0.99)(timestamp_pts) as p99_ms
-- FROM teremoqwow.telemetry_events
-- WHERE timestamp_pts >= (now() - INTERVAL 1 HOUR) * 1000
-- GROUP BY kind
-- ORDER BY sample_count DESC;


-- Query 3: Last 10 events from a specific broadcast
-- Useful for debugging synchronization issues
--
-- SELECT 
--     id,
--     kind,
--     source,
--     timestamp_pts,
--     toDateTime(timestamp_pts / 1000) as event_time,
--     payload
-- FROM teremoqwow.telemetry_events
-- WHERE namespace = 'anon/live1'
-- ORDER BY timestamp_pts DESC
-- LIMIT 10;
