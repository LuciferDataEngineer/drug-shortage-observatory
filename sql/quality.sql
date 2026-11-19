SELECT 'raw_rows' AS metric, raw_rows AS value FROM current_snapshot
UNION ALL SELECT 'accepted_rows', accepted FROM current_snapshot
UNION ALL SELECT 'quarantined_rows', quarantined FROM current_snapshot
UNION ALL SELECT 'repeated_natural_key_groups', COUNT(*) FROM
 (SELECT natural_key FROM current_listings GROUP BY natural_key HAVING COUNT(*) > 1)
UNION ALL SELECT 'extra_rows_at_repeated_natural_keys', COALESCE(SUM(n - 1), 0) FROM
 (SELECT COUNT(*) n FROM current_listings GROUP BY natural_key HAVING COUNT(*) > 1)
UNION ALL SELECT 'exact_raw_duplicate_extra_rows', COALESCE(SUM(n - 1), 0) FROM
 (SELECT COUNT(*) n FROM (
    SELECT raw_row_sha256 FROM current_listings
    UNION ALL
    SELECT q.raw_row_sha256 FROM quarantine q JOIN current_snapshot s USING(snapshot_id)
  ) GROUP BY raw_row_sha256 HAVING COUNT(*) > 1)
UNION ALL SELECT 'projected_duplicate_extra_rows', COALESCE(SUM(n - 1), 0) FROM
 (SELECT COUNT(*) n FROM current_listings GROUP BY projected_sha256 HAVING COUNT(*) > 1)
UNION ALL SELECT 'generic_labels_with_multiple_statuses', COUNT(*) FROM
 (SELECT generic_name FROM current_listings GROUP BY generic_name HAVING COUNT(DISTINCT status) > 1)
UNION ALL SELECT 'unknown_availability_rows', COUNT(*) FROM current_listings
 WHERE availability IS NOT NULL AND availability NOT IN ('Available','Unavailable','Limited Availability')
UNION ALL SELECT 'missing_dosage_form_rows', COUNT(*) FROM current_listings WHERE dosage_form IS NULL
UNION ALL SELECT 'missing_shortage_reason_rows', COUNT(*) FROM current_listings WHERE shortage_reason IS NULL;
