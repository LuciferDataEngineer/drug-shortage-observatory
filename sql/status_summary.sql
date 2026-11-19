SELECT status, COUNT(*) AS listing_rows,
       COUNT(DISTINCT generic_name) AS generic_labels,
       COUNT(DISTINCT company_name) AS company_labels
FROM current_listings
GROUP BY status ORDER BY status;
