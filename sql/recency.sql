WITH age AS (
  SELECT l.ordinal, l.status,
         CAST(julianday(s.export_date) - julianday(l.update_date) AS INTEGER) AS days
  FROM current_listings l CROSS JOIN current_snapshot s
)
SELECT status,
       CASE WHEN days IS NULL THEN 'Missing date'
            WHEN days < 0 THEN 'After export date'
            WHEN days <= 7 THEN '0-7 days'
            WHEN days <= 30 THEN '8-30 days'
            WHEN days <= 90 THEN '31-90 days'
            ELSE '91+ days' END AS update_age,
       COUNT(*) AS listing_rows
FROM age GROUP BY status, update_age ORDER BY status, update_age;
