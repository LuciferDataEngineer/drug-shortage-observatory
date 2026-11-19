SELECT c.category,
       COUNT(DISTINCT l.ordinal) AS current_listing_rows,
       COUNT(DISTINCT l.generic_name) AS current_generic_labels
FROM current_listings l
JOIN categories c USING(snapshot_id, ordinal)
WHERE l.status = 'Current'
GROUP BY c.category
ORDER BY current_listing_rows DESC, c.category;
