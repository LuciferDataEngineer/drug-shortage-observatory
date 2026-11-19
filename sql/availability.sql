SELECT status, COALESCE(availability, 'Not reported') AS availability,
       availability IS NOT NULL AS availability_reported,
       COUNT(*) AS listing_rows, COUNT(DISTINCT generic_name) AS generic_labels
FROM current_listings
GROUP BY status, availability ORDER BY status, availability;
