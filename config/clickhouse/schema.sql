CREATE DATABASE IF NOT EXISTS teremoqwow;

CREATE TABLE IF NOT EXISTS teremoqwow.telemetry_events
(
    id           UUID,
    namespace    String,
    kind         LowCardinality(String),
    source       LowCardinality(String),
    producer_id  String,
    sequence     UInt64,
    timestamp_pts UInt64    COMMENT 'ms desde epoch',
    payload      String     COMMENT 'JSON del evento',
    inserted_at  DateTime DEFAULT now()
)
ENGINE = MergeTree()
ORDER BY (namespace, timestamp_pts)
PARTITION BY toYYYYMM(toDateTime(timestamp_pts / 1000))
TTL toDateTime(timestamp_pts / 1000) + INTERVAL 90 DAY;
